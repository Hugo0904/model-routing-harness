"""Hook entry: stdin event -> gates -> engine -> stdout. Any failure keeps the original call."""
from __future__ import annotations

import json
import sys
import sqlite3
import os
from pathlib import Path

from mrh.adapters.hosts.registry import HOSTS
from mrh.adapters.hosts.advisory_hosts import codex_packet_marked
from mrh.advisory import advice_text
from mrh.advisory.hook_budget import CURRENT, HookBudget, HookExpired, HookStoreBusy, settings_digest, launch_seconds
from mrh.advisory.store import AdviceStore
from mrh.infrastructure import settings_v2 as v2
from mrh.infrastructure.settings_schema import SettingsError

MAX_EVENT_BYTES = 2_000_000


def build(settings):
    # Explicit/local hooks must not load HTTP/CLI transports they never use.
    from mrh.adapters.providers.registry import build as provider_build
    return provider_build(settings)


def _real(cwd):
    """Hosts may report a symlinked cwd (e.g. /tmp); the allowlist compares resolved paths."""
    try:
        if os.name == 'nt':
            from mrh.adapters.platforms.windows_workspace import path
            return str(path(cwd, resolve_local=True))
        return str(Path(cwd).resolve()) if isinstance(cwd, str) and Path(cwd).is_absolute() else None
    except (OSError, RuntimeError, ValueError):
        return None


def _handle(event, platform, settings_path, *, classifier_factory=None, clock=None, stderr=None, codex_packets=False, hook_budget, expected_settings=None):
    """Return the hook JSON object for one event. Never raises."""
    stderr = stderr or sys.stderr
    host = HOSTS.get(platform)
    opt_in = platform == "codex" and codex_packet_marked(event)
    if opt_in:
        from mrh.adapters.hosts import codex_packets as packets
    try:
        if host is None or not isinstance(event, dict):
            return {}
        pre, post = host.request(event), host.child(event)
        if pre is None and post is None and not opt_in:
            return {}                                 # not a delegation: no settings, DB or key touched
        hook_budget.check()
        settings = v2.read(settings_path)
        if expected_settings is not None and settings_digest(settings) != expected_settings:
            raise SettingsError('hook_settings_changed')
        if settings_digest(v2.read(settings_path)) != settings_digest(settings):
            raise SettingsError('hook_settings_changed')
        hook_budget.establish(launch_seconds(event, platform, settings))
        hook_budget.provider(settings["classifier"]["provider"])
        if not settings["enabled"] or not settings["task_export_permitted"]:
            return packets._deny("packet_export_not_permitted") if opt_in and event.get("hook_event_name") == "PreToolUse" else {}
        if not v2.workspace_allowed(settings, _real(event.get("cwd"))):
            return packets._deny("packet_workspace_denied") if opt_in and event.get("hook_event_name") == "PreToolUse" else {}
        if opt_in:
            if not codex_packets:
                return packets._deny("packet_opt_in_not_enabled") if event.get("hook_event_name") == "PreToolUse" else {}
            import time
            factory = classifier_factory or (lambda: build(settings))
            output = packets.handle(event, settings_path, settings, host, factory, clock or time.time)
            # A Post failure cannot retroactively deny/reissue the successful
            # native tool. Keep packet state intact and surface only context.
            if event.get("hook_event_name") == "PostToolUse" and output.get("hookSpecificOutput", {}).get("permissionDecision"):
                return advice_text.fault_output(event)
            return output
        store = AdviceStore(Path(settings_path).parent / "advice.sqlite3")
        import time
        now = clock or time.time
        if post is not None:
            store.record_child(post, now())
            store.maintain(v2.retention_days(settings), now())      # at most once a day
            return {}
        factory = classifier_factory or (lambda: build(settings))
        from mrh.advisory import engine
        advice = engine.decide(pre, settings, store, factory, now)
        return host.output(advice)
    except SettingsError:
        reason = "settings_unavailable"
    except HookExpired:
        reason = "hook_deadline"
    except HookStoreBusy:
        reason = "sqlite_busy"
    except sqlite3.OperationalError as exc:
        reason = "sqlite_busy" if getattr(exc, "sqlite_errorcode", 0) & 255 in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED) else "runtime_unavailable"
    except Exception:
        reason = "runtime_unavailable"
    stderr.write("mrh: " + reason + "\n")
    if opt_in and event.get("hook_event_name") == "PreToolUse":
        return packets._deny("packet_settings_or_runtime_invalid")
    return advice_text.fault_output(event, reason)


def handle(event, platform, settings_path, *, classifier_factory=None, clock=None, stderr=None, codex_packets=False, hook_budget=None, expected_settings=None):
    budget = hook_budget or HookBudget()
    token = CURRENT.set(budget)
    try:
        return _handle(event, platform, settings_path, classifier_factory=classifier_factory, clock=clock,
                       stderr=stderr, codex_packets=codex_packets, hook_budget=budget, expected_settings=expected_settings)
    finally:
        CURRENT.reset(token)


def run(platform, settings_path, stdin, stdout, stderr, *, codex_packets=False, started=None, expected_settings=None, control_fd=None):
    if control_fd is not None:
        os.set_inheritable(control_fd, False)
    def notify(seconds):
        if control_fd is not None:
            try:
                os.write(control_fd, (json.dumps({"seconds": seconds}) + "\n").encode())
            except OSError:
                pass
    budget = HookBudget(started, notify=notify)
    event = None
    try:
        payload = stdin.read(MAX_EVENT_BYTES + 1)
        if len(payload) > MAX_EVENT_BYTES:
            raise ValueError()
        event = json.loads(payload)
        response = handle(event, platform, settings_path, stderr=stderr, codex_packets=codex_packets, hook_budget=budget, expected_settings=expected_settings)
    except Exception:
        stderr.write("mrh: advisory_hook_error\n")
        response = advice_text.fault_output(event)
    if control_fd is not None:
        try:
            os.close(control_fd)
        except OSError:
            pass
    stdout.write(json.dumps(response, separators=(",", ":"), allow_nan=False) + "\n")
    return 0
