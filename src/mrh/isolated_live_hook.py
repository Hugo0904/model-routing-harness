"""Private live Hook experiment: trusted owned launch/registration, synthetic policy.

No production factory or settings selector imports this module. Native stdin is
trusted only inside the reviewed owned producer/registered-command experiment.
Same-owner hostile execution/writes are outside this local trust assumption.
"""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import time
import uuid

from .facts import CallScope
from .isolated_host_export import ExportError, _snapshot


def _regular(path, root):
    path = Path(path)
    info = path.lstat()
    if (not path.is_absolute() or path.is_symlink() or not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid() or info.st_mode & 0o022
            or not path.resolve().is_relative_to(root)):
        raise ExportError("unverified_live_registration")
    return path


def routing_binding(event):
    original = event.get("tool_input")
    if type(original) is not dict:
        raise ExportError("invalid_live_input")
    return {key: original.get(key) for key in ("agent_type", "model", "reasoning_effort", "fork_context")}


class OwnedRegistration:
    """Code-level bootstrap dependency; its context is never read from stdin."""
    def __init__(self, context_path):
        path = Path(context_path)
        if not path.is_absolute():
            raise ExportError("unverified_live_registration")
        self.root = path.parent.resolve(strict=True)
        if json.loads((self.root/"OWNED.json").read_text()).get("owner") != "MRH-001-E8":
            raise ExportError("unverified_live_registration")
        self.context = json.loads(_regular(path, self.root).read_text())
        for field in ("producer", "bootstrap"):
            entry = self.context[field]
            artifact = _regular(entry["path"], self.root)
            if hashlib.sha256(artifact.read_bytes()).hexdigest() != entry["sha256"]:
                raise ExportError("unverified_live_registration")
        self.launch_lock = _regular(self.root/"launch.lock", self.root)

    def launch_alive(self):
        with self.launch_lock.open("r+") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            fcntl.flock(lock, fcntl.LOCK_UN)
            return False

    def exchange(self, event):
        return LiveExchange(self, event)


class LiveExchange:
    synthetic = True

    def __init__(self, registration, event):
        if type(registration) is not OwnedRegistration:
            raise ExportError("unverified_live_registration")
        self.registration = registration
        self.scope = CallScope.for_hook(event)
        self.binding = routing_binding(event)
        self._active = True
        self._packet = event.get("pending_delegation")
        try:
            nonce = self._packet["validity"]["nonce"]
            if str(uuid.UUID(nonce)) != nonce:
                raise ValueError()
        except (TypeError, KeyError, ValueError, AttributeError):
            raise ExportError("unavailable_live_export") from None
        self._file = _regular(registration.root/"leases"/(nonce+".json"), registration.root).open("r+")
        try:
            fcntl.flock(self._file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self._active = False
            self._file.close()
            raise ExportError("busy_live_exchange") from None
        try:
            self._lease = json.load(self._file)
            self.check(event)
            if self._lease.get("admitted") is not False:
                raise ExportError("replayed_live_exchange")
            self._lease["admitted"] = True
            self._write()
        except BaseException:
            self.close()
            raise

    def _write(self):
        self._file.seek(0); self._file.truncate()
        json.dump(self._lease, self._file); self._file.flush()

    def check(self, event=None):
        if not self._active or not self.registration.launch_alive():
            raise ExportError("expired_live_exchange")
        self._file.seek(0); current = json.load(self._file)
        if (current.get("phase") != "active" or type(current.get("expires_at")) not in (float, int)
                or not time.time() < current["expires_at"] <= time.time()+60
                or current.get("registration_id") != self.registration.context["registration_id"]
                or current.get("scope") != self.scope.__dict__ or current.get("routing") != self.binding
                or type(self._packet) is not dict
                or current.get("export_nonce") != self._packet.get("validity", {}).get("nonce")):
            raise ExportError("expired_or_foreign_live_exchange")
        if event is not None and (CallScope.for_hook(event) != self.scope or routing_binding(event) != self.binding):
            raise ExportError("changed_live_input")

    def resolve(self, event):
        self.check(event)
        return _snapshot(json.dumps(self._packet, allow_nan=False).encode(), self.scope)

    def close(self):
        if getattr(self, "_active", False):
            self._active = False
            if hasattr(self, "_file"):
                self._lease = getattr(self, "_lease", {})
                self._lease["phase"] = "closed"
                self._write()
                fcntl.flock(self._file, fcntl.LOCK_UN)
                self._file.close()
