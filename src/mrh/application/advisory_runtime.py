"""Hook entry: stdin event -> gates -> engine -> stdout. Any failure keeps the original call."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from mrh.adapters.hosts.advisory_hosts import HOSTS
from mrh.adapters.providers.registry import build
from mrh.advisory import engine
from mrh.advisory.store import AdviceStore
from mrh.infrastructure import settings_v2 as v2
from mrh.infrastructure.settings_schema import SettingsError

MAX_EVENT_BYTES = 2_000_000


def _real(cwd):
    """Hosts may report a symlinked cwd (e.g. /tmp); the allowlist compares resolved paths."""
    try:
        return str(Path(cwd).resolve()) if isinstance(cwd, str) and Path(cwd).is_absolute() else None
    except (OSError, RuntimeError, ValueError):
        return None


def handle(event, platform, settings_path, *, classifier_factory=None, clock=None, stderr=None):
    """Return the hook JSON object for one event. Never raises."""
    stderr = stderr or sys.stderr
    host = HOSTS.get(platform)
    try:
        if host is None or not isinstance(event, dict):
            return {}
        pre, post = host.request(event), host.child(event)
        if pre is None and post is None:
            return {}                                 # not a delegation: no settings, DB or key touched
        settings = v2.read(settings_path)
        if not settings["enabled"] or not settings["task_export_permitted"]:
            return {}
        if not v2.workspace_allowed(settings, _real(event.get("cwd"))):
            return {}
        store = AdviceStore(Path(settings_path).parent / "advice.sqlite3")
        import time
        now = clock or time.time
        if post is not None:
            store.record_child(post, now())
            return {}
        factory = classifier_factory or (lambda: build(settings))
        advice = engine.decide(pre, settings, store, factory, now)
        return host.output(advice)
    except SettingsError as exc:
        stderr.write("mrh: " + exc.reason + "\n")
    except Exception:
        stderr.write("mrh: advisory_hook_error\n")
    return {}


def run(platform, settings_path, stdin, stdout, stderr):
    try:
        payload = stdin.read(MAX_EVENT_BYTES + 1)
        if len(payload) > MAX_EVENT_BYTES:
            raise ValueError()
        response = handle(json.loads(payload), platform, settings_path, stderr=stderr)
    except Exception:
        stderr.write("mrh: advisory_hook_error\n")
        response = {}
    stdout.write(json.dumps(response, separators=(",", ":"), allow_nan=False) + "\n")
    return 0
