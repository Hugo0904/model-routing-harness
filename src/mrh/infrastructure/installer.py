"""Safe, explicit-home installer for the untrusted Codex hook candidate.

The installer only writes ``hooks.json`` under the caller-supplied home. It
never changes trust, model, security, or other Codex configuration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import shlex
import stat
import tempfile
import threading
import tomllib
from typing import Any


_EVENTS = ("PreToolUse", "PostToolUse")
_MATCHER = "^spawn_agent$"
_MANAGED_ENV = "MRH_INSTALLER_ID=org.model-routing-harness.hooks.v1"
_OWNED_MARKER = "org.model-routing-harness.hooks.v1"


class _DuplicateKey(ValueError):
    pass


class _UnsafeConfig(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey
        result[key] = value
    return result


def _hash(data: bytes | None) -> str | None:
    if data is None:
        return None
    return hashlib.sha256(data).hexdigest()


def _read_regular(path: Path, *, missing_ok: bool) -> bytes | None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        if missing_ok:
            return None
        raise _UnsafeConfig("missing_home")
    except OSError:
        raise _UnsafeConfig("read_failed") from None

    if stat.S_ISLNK(info.st_mode):
        raise _UnsafeConfig("symlink_target")
    if not stat.S_ISREG(info.st_mode):
        raise _UnsafeConfig("not_a_regular_file")
    try:
        return path.read_bytes()
    except OSError:
        raise _UnsafeConfig("read_failed") from None


def _parse_hooks(data: bytes | None) -> dict[str, Any]:
    if data is None:
        return {"hooks": {}}
    try:
        parsed = json.loads(data.decode("utf-8"), object_pairs_hook=_object_without_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError, _DuplicateKey):
        raise _UnsafeConfig("invalid_hooks_json") from None
    if not isinstance(parsed, dict):
        raise _UnsafeConfig("invalid_hooks_json")
    hooks = parsed.get("hooks", {})
    if not isinstance(hooks, dict):
        raise _UnsafeConfig("invalid_hooks_shape")
    for event in _EVENTS:
        entries = hooks.get(event, [])
        if not isinstance(entries, list) or any(not isinstance(entry, dict) for entry in entries):
            raise _UnsafeConfig("invalid_hooks_shape")
    parsed["hooks"] = hooks
    return parsed


def _check_toml(data: bytes | None) -> bool:
    if data is None:
        return False
    try:
        parsed = tomllib.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError):
        raise _UnsafeConfig("invalid_config_toml") from None
    # Codex's hooks table is a top-level config key. Other applications may
    # legitimately use a nested key named "hooks" in unrelated settings.
    return "hooks" in parsed


def _hook_command(command: str) -> str:
    return f"{_MANAGED_ENV} {shlex.quote(command)} hook --candidate"


def _managed_entry(event_entry: dict[str, Any]) -> bool:
    """Recognize only our exact event shape and explicit ownership marker."""
    if set(event_entry) != {"matcher", "hooks"} or event_entry.get("matcher") != _MATCHER:
        return False
    hooks = event_entry.get("hooks")
    if not isinstance(hooks, list) or len(hooks) != 1:
        return False
    hook = hooks[0]
    if not isinstance(hook, dict) or set(hook) != {"type", "command"}:
        return False
    if hook.get("type") != "command" or not isinstance(hook.get("command"), str):
        return False
    try:
        tokens = shlex.split(hook["command"])
    except ValueError:
        return False
    return (
        len(tokens) == 4
        and tokens[0] == _MANAGED_ENV
        and tokens[1] not in ("",)
        and all("\x00" not in token for token in tokens)
        and tokens[2:] == ["hook", "--candidate"]
    )


def _has_marker(value: Any) -> bool:
    if isinstance(value, str):
        return _OWNED_MARKER in value
    if isinstance(value, dict):
        return any(_has_marker(key) or _has_marker(item) for key, item in value.items())
    if isinstance(value, list):
        return any(_has_marker(item) for item in value)
    return False


def _scan_owned(hooks: dict[str, Any]) -> dict[str, list[int]]:
    found: dict[str, list[int]] = {event: [] for event in _EVENTS}
    for event in _EVENTS:
        entries = hooks.get(event, [])
        for index, entry in enumerate(entries):
            marker_present = _has_marker(entry)
            if _managed_entry(entry):
                found[event].append(index)
            elif marker_present:
                raise _UnsafeConfig("ambiguous_managed_entry")
        if len(found[event]) > 1:
            raise _UnsafeConfig("ambiguous_managed_entry")
    return found


def _new_entry(command: str) -> dict[str, Any]:
    return {
        "matcher": _MATCHER,
        "hooks": [{"type": "command", "command": command}],
    }


def _updated_document(
    document: dict[str, Any],
    action: str,
    command: str,
) -> tuple[dict[str, Any], bool, str]:
    hooks = document["hooks"]
    owned = _scan_owned(hooks)
    if action == "disable":
        changed = False
        for event in _EVENTS:
            for index in reversed(owned[event]):
                del hooks[event][index]
                changed = True
            if event in hooks and not hooks[event]:
                # Preserve the caller's empty-list choice when it already existed.
                pass
        return document, changed, "disabled" if changed else "not_installed"

    desired = _hook_command(command)
    changed = False
    for event in _EVENTS:
        entries = hooks.setdefault(event, [])
        if owned[event]:
            index = owned[event][0]
            if entries[index] != _new_entry(desired):
                entries[index] = _new_entry(desired)
                changed = True
        else:
            entries.append(_new_entry(desired))
            changed = True
    return document, changed, "installed" if changed else "already_installed"


def _serialize(document: dict[str, Any]) -> bytes:
    return (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


@dataclass(frozen=True)
class Plan:
    """A preview plan bound to exact source bytes observed by ``prepare``."""

    home: Path
    action: str
    status: str
    reason: str | None
    candidate_change: bool
    _command: str = field(repr=False)
    _hooks_hash: str | None = field(repr=False)
    _config_hash: str | None = field(repr=False)

    def public(self) -> dict[str, Any]:
        """Return safe preview metadata without exposing configured commands."""
        result: dict[str, Any] = {
            "action": self.action,
            "target": str(self.home / "hooks.json"),
            "status": self.status,
            "candidate_change": self.candidate_change,
            "will_write": False,
            "mutation_supported": False,
            "mutation_scope": "private_synthetic_fixture_only",
            "mutation_reason": "exclusive_target_unverified",
            "managed_events": list(_EVENTS),
            "trust_changes": False,
            "main_model_changes": False,
        }
        if self.reason is not None:
            result["reason"] = self.reason
        return result


def prepare(home: str | os.PathLike[str], command: str, action: str = "apply") -> Plan:
    """Build a no-write plan for one explicit home directory."""
    try:
        home_path = Path(home)
    except (TypeError, ValueError):
        home_path = Path(".")
        return Plan(home_path, action, "refused", "invalid_home", False, "", None, None)

    candidate_command = command if isinstance(command, str) else ""
    if action not in ("apply", "disable"):
        return Plan(home_path, action, "refused", "invalid_action", False, candidate_command, None, None)
    if not home_path.is_absolute():
        return Plan(home_path, action, "refused", "home_must_be_absolute", False, candidate_command, None, None)
    if action == "apply" and (not candidate_command.strip() or "\x00" in candidate_command):
        return Plan(home_path, action, "refused", "invalid_command", False, candidate_command, None, None)

    try:
        home_info = home_path.lstat()
    except FileNotFoundError:
        return Plan(home_path, action, "refused", "missing_home", False, candidate_command, None, None)
    except OSError:
        return Plan(home_path, action, "refused", "read_failed", False, candidate_command, None, None)
    if stat.S_ISLNK(home_info.st_mode):
        return Plan(home_path, action, "refused", "symlink_home", False, candidate_command, None, None)
    if not stat.S_ISDIR(home_info.st_mode):
        return Plan(home_path, action, "refused", "invalid_home", False, candidate_command, None, None)

    hooks_path = home_path / "hooks.json"
    config_path = home_path / "config.toml"
    try:
        hooks_data = _read_regular(hooks_path, missing_ok=True)
        config_data = _read_regular(config_path, missing_ok=True)
        toml_hooks = _check_toml(config_data)
        if toml_hooks:
            raise _UnsafeConfig("toml_hooks_present")
        document = _parse_hooks(hooks_data)
        _, changed, _ = _updated_document(document, action, candidate_command)
    except _UnsafeConfig as exc:
        return Plan(
            home_path, action, "refused", exc.reason, False, candidate_command,
            _hash(hooks_data) if "hooks_data" in locals() else None,
            _hash(config_data) if "config_data" in locals() else None,
        )

    return Plan(
        home=home_path,
        action=action,
        status="ready" if changed else "no_change",
        reason=None,
        candidate_change=changed,
        _command=candidate_command,
        _hooks_hash=_hash(hooks_data),
        _config_hash=_hash(config_data),
    )


def _write_atomically(path: Path, data: bytes, mode: int | None) -> None:
    fd = -1
    temporary: str | None = None
    try:
        fd, temporary = tempfile.mkstemp(prefix=".hooks.json.mrh-", dir=path.parent)
        if mode is not None:
            os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as stream:
            fd = -1
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
        except OSError:
            directory_fd = -1
        if directory_fd >= 0:
            try:
                os.fsync(directory_fd)
            except OSError:
                # The replacement is already atomic and visible. A directory
                # fsync failure must not be reported as though nothing changed.
                pass
            finally:
                try:
                    os.close(directory_fd)
                except OSError:
                    pass
    finally:
        if fd >= 0:
            os.close(fd)
        if temporary is not None:
            try:
                os.unlink(temporary)
            except OSError:
                pass


def _apply_fixture_plan(plan: Plan, expected_home: Path) -> dict[str, Any]:
    """Mutate one owned fixture while its SyntheticHome lock is held."""
    if not isinstance(plan, Plan):
        return {"ok": False, "status": "refused", "reason": "invalid_plan"}
    if plan.home != expected_home:
        return {"ok": False, "status": "refused", "reason": "fixture_target_mismatch"}
    if plan.status == "refused":
        return {"ok": False, "status": "refused", "reason": plan.reason or "invalid_plan"}
    if plan.status not in ("ready", "no_change") or plan.action not in ("apply", "disable") or not plan.home.is_absolute():
        return {"ok": False, "status": "refused", "reason": "invalid_plan"}

    hooks_path = plan.home / "hooks.json"
    config_path = plan.home / "config.toml"
    try:
        home_info = plan.home.lstat()
        if stat.S_ISLNK(home_info.st_mode) or not stat.S_ISDIR(home_info.st_mode):
            raise _UnsafeConfig("invalid_home")
        hooks_data = _read_regular(hooks_path, missing_ok=True)
        config_data = _read_regular(config_path, missing_ok=True)
        if _hash(hooks_data) != plan._hooks_hash or _hash(config_data) != plan._config_hash:
            raise _UnsafeConfig("source_changed")
        if _check_toml(config_data):
            raise _UnsafeConfig("toml_hooks_present")
        document = _parse_hooks(hooks_data)
        document, changed, result_status = _updated_document(document, plan.action, plan._command)
        if not changed:
            return {"ok": True, "status": result_status, "target": str(hooks_path), "changed": False}

        updated = _serialize(document)
        # This detects changes since preview. The fixture lock coordinates only
        # cooperating SyntheticHome writers; external editors have no portable
        # compare-and-swap guarantee here.
        latest_hooks = _read_regular(hooks_path, missing_ok=True)
        latest_config = _read_regular(config_path, missing_ok=True)
        if _hash(latest_hooks) != plan._hooks_hash or _hash(latest_config) != plan._config_hash:
            raise _UnsafeConfig("source_changed")
        if _check_toml(latest_config):
            raise _UnsafeConfig("toml_hooks_present")
        mode = stat.S_IMODE(hooks_path.stat().st_mode) if latest_hooks is not None else 0o600
        _write_atomically(hooks_path, updated, mode)
        return {"ok": True, "status": result_status, "target": str(hooks_path), "changed": True}
    except _UnsafeConfig as exc:
        return {"ok": False, "status": "refused", "reason": exc.reason}
    except OSError:
        return {"ok": False, "status": "refused", "reason": "write_failed"}


def apply(plan: Plan) -> dict[str, Any]:
    """Refuse real-home mutation until an exclusive host protocol is verified."""
    return {
        "ok": False,
        "status": "refused",
        "reason": "exclusive_target_unverified",
        "changed": False,
    }


class SyntheticHome:
    """Owned temporary home for isolated installer candidate tests only.

    The private directory is created internally. Calls to ``apply`` serialize
    cooperating writers for the complete read/validate/merge/replace operation;
    non-cooperating filesystem editors remain outside that guarantee.
    """

    def __init__(self) -> None:
        self._temporary = tempfile.TemporaryDirectory(prefix="mrh-installer-")
        self._home = Path(self._temporary.name) / "home"
        self._home.mkdir(mode=0o700)
        self._lock = threading.RLock()
        self._active = True

    @property
    def home(self) -> Path:
        return self._home

    def __enter__(self) -> SyntheticHome:
        with self._lock:
            if not self._active:
                raise RuntimeError("synthetic home is closed")
            return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool:
        self.close()
        return False

    def close(self) -> None:
        with self._lock:
            if self._active:
                self._active = False
                self._temporary.cleanup()

    def apply(self, plan: Plan) -> dict[str, Any]:
        """Apply only a plan for this exact, active fixture home."""
        with self._lock:
            if not self._active:
                return {"ok": False, "status": "refused", "reason": "fixture_inactive", "changed": False}
            if not isinstance(plan, Plan) or plan.home != self._home:
                return {"ok": False, "status": "refused", "reason": "fixture_target_mismatch", "changed": False}
            return _apply_fixture_plan(plan, expected_home=self._home)
