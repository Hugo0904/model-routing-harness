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


def handle(event, platform, settings_path, *, classifier_factory=None, clock=None, stderr=None, codex_packets=False):
    """Return the hook JSON object for one event. Never raises."""
    stderr = stderr or sys.stderr
    host = HOSTS.get(platform)
    from mrh.adapters.hosts import codex_packets as packets
    opt_in = platform == "codex" and packets.marked(event)
    try:
        if host is None or not isinstance(event, dict):
            return {}
        pre, post = host.request(event), host.child(event)
        if pre is None and post is None and not opt_in:
            return {}                                 # not a delegation: no settings, DB or key touched
        settings = v2.read(settings_path)
        if not settings["enabled"] or not settings["task_export_permitted"]:
            return packets._deny("packet_export_not_permitted") if opt_in and event.get("hook_event_name") == "PreToolUse" else {}
        if not v2.workspace_allowed(settings, _real(event.get("cwd"))):
            return packets._deny("packet_workspace_denied") if opt_in and event.get("hook_event_name") == "PreToolUse" else {}
        if opt_in:
            if not codex_packets:
                return packets._deny("packet_opt_in_not_enabled") if event.get("hook_event_name") == "PreToolUse" else {}
            import time
            factory = classifier_factory or (lambda: build(settings))
            return packets.handle(event, settings_path, settings, host, factory, clock or time.time)
        store = AdviceStore(Path(settings_path).parent / "advice.sqlite3")
        import time
        now = clock or time.time
        if post is not None:
            store.record_child(post, now())
            store.maintain(v2.retention_days(settings), now())      # at most once a day
            return {}
        factory = classifier_factory or (lambda: build(settings))
        advice = engine.decide(pre, settings, store, factory, now)
        return host.output(advice)
    except SettingsError as exc:
        stderr.write("mrh: " + exc.reason + "\n")
    except Exception:
        stderr.write("mrh: advisory_hook_error\n")
    if opt_in and event.get("hook_event_name") == "PreToolUse":
        return packets._deny("packet_settings_or_runtime_invalid")
    return {}


def run(platform, settings_path, stdin, stdout, stderr, *, codex_packets=False):
    try:
        payload = stdin.read(MAX_EVENT_BYTES + 1)
        if len(payload) > MAX_EVENT_BYTES:
            raise ValueError()
        response = handle(json.loads(payload), platform, settings_path, stderr=stderr, codex_packets=codex_packets)
    except Exception:
        stderr.write("mrh: advisory_hook_error\n")
        response = {}
    stdout.write(json.dumps(response, separators=(",", ":"), allow_nan=False) + "\n")
    return 0
