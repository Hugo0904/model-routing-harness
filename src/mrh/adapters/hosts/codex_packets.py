"""Codex-only, opt-in full-task packets. Native dispatch and queries stay distinct.

The caller obtains session/turn from native host metadata. CLI arguments declare
that scope; the hook verifies it against its actual native event, never treating
the random packet identifier as a native request identifier.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import threading
import time
import uuid

from mrh.advisory import engine
from mrh.advisory.request import AdvisoryRequest
from mrh.advisory.store import AdviceStore
from mrh.infrastructure import owned, settings_v2 as v2
from mrh.routing.types import safe_id, safe_model_id

PREFIXES = {"query": "mrh_packet_", "release": "mrh_release_"}
IDENTIFIER = re.compile(r"[0-9a-f]{32}")
MAX_TASK_BYTES = 16_384
TTL_SECONDS = 600
STATES = {"prepared", "classifying", "classified", "failed", "released", "completed", "expired", "cancelled"}


class PacketError(ValueError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


def _hash(value):
    return hashlib.sha256(value).hexdigest()


def marked(event):
    data = event.get("tool_input") if isinstance(event, dict) else None
    return (event.get("tool_name") in ("spawn_agent", "collaborationspawn_agent")
            and isinstance(data, dict) and isinstance(data.get("task_name"), str)
            and any(data["task_name"].startswith(p) for p in PREFIXES.values())) if isinstance(event, dict) else False


def _marker(event):
    name = event["tool_input"]["task_name"]
    for phase, prefix in PREFIXES.items():
        if name.startswith(prefix) and IDENTIFIER.fullmatch(name[len(prefix):]):
            return phase, name[len(prefix):]
    raise PacketError("packet_marker_invalid")


def _private(path, directory=False):
    info = path.lstat()
    kind = stat.S_ISDIR if directory else stat.S_ISREG
    if not kind(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or (not directory and info.st_nlink != 1):
        raise PacketError("packet_unsafe_file")


def root_for(settings_path):
    settings = owned.canonical_path(settings_path)
    return settings.parent.with_name(settings.parent.name + "-codex-packets")


def _directory(settings_path, identifier, create=False):
    if not isinstance(identifier, str) or not IDENTIFIER.fullmatch(identifier):
        raise PacketError("packet_id_invalid")
    root = root_for(settings_path)
    if create:
        owned.initialize(root, "codex_packets")
    owned.verify(root, "codex_packets")
    _private(root, True)
    target = root / identifier
    if create:
        target.mkdir(mode=0o700)  # O_EXCL-like creation: never reuse a packet ID
        owned.initialize(target, "codex_packet")
    owned.verify(target, "codex_packet")
    _private(target, True)
    return target


def _read(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1 or info.st_mode & 0o077:
            raise PacketError("packet_unsafe_file")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            data = stream.read(65537)
        if len(data) > 65536:
            raise PacketError("packet_file_oversized")
        return json.loads(data, object_pairs_hook=owned._unique)
    finally:
        os.close(fd)


def _write(path, value):
    if path.exists() or path.is_symlink():
        _private(path)
    owned.replace_owned(path, (json.dumps(value, sort_keys=True, allow_nan=False) + "\n").encode())


@contextmanager
def _lock(directory):
    path = directory / ".packet.lock"
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1 or info.st_mode & 0o077:
            raise PacketError("packet_unsafe_lock")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise PacketError("packet_classification_in_progress") from None
        yield
    finally:
        os.close(fd)


def prepare(settings_path, task, session, turn, workspace, *, user_model=None, user_effort=None, clock=time.time):
    settings = v2.read(settings_path)
    if not settings["enabled"] or not settings["task_export_permitted"]:
        raise PacketError("packet_export_not_permitted")
    workspace = str(owned.canonical_path(workspace))
    if not v2.workspace_allowed(settings, workspace):
        raise PacketError("packet_workspace_denied")
    # Native identity must come from supported host metadata, not task text or a
    # generated identifier. Strict UUID syntax is necessary but not authenticity.
    try:
        if str(uuid.UUID(session)) != session or str(uuid.UUID(turn)) != turn:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise PacketError("packet_native_scope_required") from None
    if (not isinstance(task, str) or not task.strip() or len(task.encode()) > MAX_TASK_BYTES
            or any(ord(c) < 32 and c not in "\n\r\t" for c in task)):
        raise PacketError("packet_task_invalid")
    if user_model is not None and not safe_model_id(user_model) or user_effort is not None and not safe_id(user_effort):
        raise PacketError("packet_user_profile_invalid")
    identifier, now = uuid.uuid4().hex, clock()
    directory = _directory(settings_path, identifier, create=True)
    scope = {"session": session, "turn": turn, "workspace": workspace, "revision": settings["revision"]}
    packet = {"version": 1, "id": identifier, "scope": scope, "sha256": _hash(task.encode()),
              "length": len(task.encode()), "expires": now + TTL_SECONDS, "task": task,
              "user_profile": {"model": user_model, "effort": user_effort}}
    _write(directory / "packet.json", packet)
    os.chmod(directory / "packet.json", 0o400)
    receipt = {k: packet[k] for k in ("version", "id", "scope", "sha256", "length", "expires", "user_profile")}
    receipt.update(state="prepared", created=now)
    _write(directory / "receipt.json", receipt)
    return {"packet_id": identifier, "sha256": packet["sha256"], "length": packet["length"],
            "query_task_name": PREFIXES["query"] + identifier, "release_task_name": PREFIXES["release"] + identifier,
            "body_path": str(directory / "packet.json"), "expires": packet["expires"]}


def _receipt(directory, identifier):
    row = _read(directory / "receipt.json")
    if (row.get("version") != 1 or row.get("id") != identifier or row.get("state") not in STATES
            or not isinstance(row.get("scope"), dict) or not isinstance(row.get("expires"), (float, int))):
        raise PacketError("packet_receipt_invalid")
    return row


def _packet(directory, row, event, settings, now):
    if (directory / "packet.json").lstat().st_mode & 0o222:
        raise PacketError("packet_not_immutable")
    packet = _read(directory / "packet.json")
    fields = {"version", "id", "scope", "sha256", "length", "expires", "task", "user_profile"}
    if set(packet) != fields or any(packet[k] != row.get(k) for k in fields - {"task"}):
        raise PacketError("packet_format_invalid")
    task = packet["task"]
    if (not isinstance(task, str) or not task.strip() or len(task.encode()) > MAX_TASK_BYTES
            or _hash(task.encode()) != row["sha256"] or len(task.encode()) != row["length"]):
        raise PacketError("packet_hash_invalid")
    scope = row["scope"]
    if (scope != {"session": event.get("session_id"), "turn": event.get("turn_id"),
                  "workspace": str(owned.canonical_path(event.get("cwd"))), "revision": settings["revision"]}
            or not safe_id(event.get("tool_use_id"))):
        raise PacketError("packet_scope_invalid")
    if not now < row["expires"] <= row["created"] + TTL_SECONDS:
        row.update(state="expired")
        _write(directory / "receipt.json", row)
        (directory / "packet.json").unlink()
        raise PacketError("packet_expired")
    return task


def _deny(reason):
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": "MRH Codex packet: " + reason}}


def _advice(row):
    return _deny("classification ready " + json.dumps({"packet_id": row["id"], "sha256": row["sha256"],
                 **row["classification"]}, sort_keys=True) + ". Compare the complete profiles with current skill/role/catalog constraints. "
                 "For an eligible dispatch, use the SAME message and task_name=" + PREFIXES["release"] + row["id"]
                 + "; Top Main continues in the parent unless a recorded user profile takes precedence. Do not repeat the query.")


@contextmanager
def _observe_http(observation):
    """Read-only audit/return observations; never replace transport or log headers."""
    active = [True]
    def audit(name, args):
        if not active[0] or name != "http.client.send" or len(args) < 2 or not isinstance(args[1], bytes):
            return
        raw = args[1]
        if len(raw) > 65536 or not raw.startswith(b"{"):
            return
        try:
            task = json.loads(raw).get("state", {}).get("task")
            if isinstance(task, str):
                observation["outbound"] = {"task_sha256": _hash(task.encode()), "task_length": len(task.encode()),
                                           "wire_body_sha256": _hash(raw), "wire_body_length": len(raw)}
        except (ValueError, AttributeError):
            pass
    def profile(frame, event, value):
        if (active[0] and event == "return" and frame.f_globals.get("__name__") == "mrh.adapters.providers.typesafe"
                and frame.f_code.co_name == "request" and type(frame.f_locals.get("self")).__name__ == "HttpTransport"
                and hasattr(value, "status") and isinstance(getattr(value, "body", None), bytes)):
            observation["response"] = {"status": value.status, "body_sha256": _hash(value.body), "body_length": len(value.body)}
    old_sys, old_thread = sys.getprofile(), threading.getprofile()
    sys.addaudithook(audit)
    sys.setprofile(profile)
    threading.setprofile(profile)
    try:
        yield
    finally:
        active[0] = False
        sys.setprofile(old_sys)
        threading.setprofile(old_thread)


def handle(event, settings_path, settings, host, factory, clock=time.time):
    """Called only by platform-guarded wiring after export/workspace gates."""
    try:
        phase, identifier = _marker(event)
        directory = _directory(settings_path, identifier)
        with _lock(directory):
            row = _receipt(directory, identifier)
            if event.get("hook_event_name") == "PostToolUse":
                child = host.child(event)
                if (phase != "release" or row["state"] != "released" or child is None or child.agent_id is None
                        or row.get("release_call") != event.get("tool_use_id")
                        or row["scope"]["session"] != event.get("session_id")
                        or row["scope"]["turn"] != event.get("turn_id")):
                    return {}  # unknown spawn result remains released/unknown, not a retry
                row.update(state="completed", completion="native_spawn_result_observed", child_id=child.agent_id,
                           requested_model=child.requested_model, requested_effort=child.requested_effort,
                           observed_model=child.resolved_model, completed=clock())
                _write(directory / "receipt.json", row)
                # The message contains the entire task; this mode never requires
                # a child to read the packet after its native spawn acknowledges.
                _private(directory / "packet.json")
                (directory / "packet.json").unlink()
                AdviceStore(Path(settings_path).parent / "advice.sqlite3").record_child(child, clock())
                return {}
            if event.get("hook_event_name") != "PreToolUse":
                return {}
            if row["state"] in {"released", "completed"}:
                return _deny("packet_spawn_outcome_unknown" if row["state"] == "released" else "packet_already_completed")
            task = _packet(directory, row, event, settings, clock())
            actual = host.request(event)
            if actual is None:
                raise PacketError("packet_native_event_invalid")
            from mrh.adapters.hosts.advisory_hosts import _CIPHERTEXT
            message = event["tool_input"].get("message")
            if not isinstance(message, str) or not message.strip():
                raise PacketError("packet_message_required")
            opaque = bool(_CIPHERTEXT.fullmatch(message.strip()))
            if not opaque and message != task:
                raise PacketError("packet_message_mismatch")
            actual = replace(actual, task=task)  # keep every protected execution field
            if phase == "query":
                if row["state"] == "classified":
                    return _advice(row)
                if row["state"] != "prepared":
                    return _deny("packet_" + row["state"] + "; do not retry classification")
                row.update(state="classifying", query_call="packet_query_" + identifier, message_visibility="opaque" if opaque else "plaintext_matched")
                _write(directory / "receipt.json", row)
                db = directory / "query.sqlite3"
                if db.exists() or db.is_symlink():
                    _private(db)
                    owned.read_regular(db, 4_000_000)
                query = AdvisoryRequest("codex", actual.session_id, actual.turn_id, row["query_call"], task, cwd=actual.cwd)
                observation = {}
                # Only an OS file lock spans the network; engine opens/closes its
                # ordinary DB operations without an enclosing SQL transaction.
                with _observe_http(observation):
                    advice = engine.decide(query, settings, AdviceStore(db), factory, clock)
                row["transport_observation"] = observation
                row["classification"] = {"action": advice.action, "reason": advice.reason, "tier": advice.tier,
                                          "confidence": advice.confidence, "candidates": list(advice.candidates),
                                          "query_request_id": advice.request_id}
                row["state"] = "classified" if advice.reason in {"advice_given", "top_main_requested", "low_confidence", "no_candidates_for_platform"} else "failed"
                _write(directory / "receipt.json", row)
                return _advice(row) if row["state"] == "classified" else _deny("packet_classification_failed: " + advice.reason)
            if row["state"] != "classified":
                return _deny("packet_not_classified")
            user = row["user_profile"]
            if any(user.get(k) is not None and user[k] != getattr(actual, "explicit_" + k) for k in ("model", "effort")):
                return _deny("packet_user_profile_must_be_preserved")
            if row["classification"]["action"] == "continue_main" and not any(user.values()):
                return _deny("packet_top_main_continue_in_parent")
            if actual.explicit_model is None:
                return _deny("packet_selected_model_required")
            # Preserve real worker/profile protection and ordinary real-spawn
            # statistics; the independently classified query stays elsewhere.
            engine.decide(actual, settings, AdviceStore(Path(settings_path).parent / "advice.sqlite3"), factory, clock)
            row.update(state="released", release_call=actual.call_id, released=clock(),
                       requested_model=actual.explicit_model, requested_effort=actual.explicit_effort, role=actual.role)
            _write(directory / "receipt.json", row)
            return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow",
                                           "permissionDecisionReason": "MRH Codex packet released: " + identifier}}
    except (PacketError, owned.OwnedError) as exc:
        return _deny(getattr(exc, "reason", "packet_invalid"))
    except Exception:
        return _deny("packet_invalid_or_processing_unknown; do not retry")


def status(settings_path, identifier, *, finish=False, clock=time.time):
    directory = _directory(settings_path, identifier)
    with _lock(directory):
        row = _receipt(directory, identifier)
        if finish or clock() >= row["expires"]:
            if row["state"] == "released" and clock() < row["expires"]:
                raise PacketError("packet_spawn_outcome_unknown")
            packet = directory / "packet.json"
            if packet.exists() or packet.is_symlink():
                _private(packet)
                packet.unlink()
            if row["state"] != "completed":
                row["state"] = "expired" if clock() >= row["expires"] else "cancelled"
                _write(directory / "receipt.json", row)
        return row
