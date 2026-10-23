"""One hook's monotonic deadline and shared SQLite wait allowance; CLI callers opt out."""
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import json
from pathlib import Path
import sys
import threading
import time

CURRENT = ContextVar('mrh_hook_budget', default=None)

# Windows process creation plus runtime import takes 0.4-1.1 s, so there a local-only PreToolUse
# decision gets the Jev window and PostToolUse gets 2.0 s. Other platforms keep 1.0 s unchanged.
LOCAL_SECONDS = 2.5 if sys.platform == 'win32' else 1.0
POST_SECONDS = 2.0 if sys.platform == 'win32' else 1.0


def settings_digest(settings):
    return hashlib.sha256(json.dumps(settings, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def launch_seconds(event, platform, settings):
    """Use the same validated settings/host contracts as runtime, never a binding cache."""
    from mrh.infrastructure import settings_v2 as v2
    provider = settings['classifier']['provider']
    if provider not in v2.PROVIDERS:
        raise ValueError('invalid_hook_provider')
    if not isinstance(event, dict) or event.get('hook_event_name') != 'PreToolUse':
        return POST_SECONDS if isinstance(event, dict) and event.get('hook_event_name') == 'PostToolUse' else 1.0
    data = event.get('tool_input')
    packet_query = (platform == 'codex' and isinstance(data, dict)
                    and event.get('tool_name') in ('spawn_agent', 'collaborationspawn_agent')
                    and isinstance(data.get('task_name'), str) and data['task_name'].startswith('mrh_packet_'))
    # These fields can only shorten the wait; the child still validates the
    # complete native event. Long waits always require the registered host.
    if isinstance(data, dict) and not packet_query:
        from mrh.routing.types import safe_id
        effort = data.get('reasoning_effort') if platform == 'codex' else data.get('effort')
        if data.get('model') is not None or (effort is not None and (platform == 'codex' or safe_id(effort))):
            return LOCAL_SECONDS
    from mrh.adapters.hosts.registry import HOSTS
    host = HOSTS.get(platform)
    if host is None:
        return LOCAL_SECONDS
    pre = host.request(event)
    if pre is None or not settings['enabled'] or not settings['task_export_permitted']:
        return LOCAL_SECONDS
    cwd = event.get('cwd')
    if not isinstance(cwd, str) or not Path(cwd).is_absolute() or not v2.workspace_allowed(settings, str(Path(cwd).resolve())):
        return LOCAL_SECONDS
    if not packet_query and (pre.explicit_model is not None or pre.explicit_effort is not None
            or pre.role is not None and pre.role not in v2.generic_roles(settings['policy'], pre.platform)):
        return LOCAL_SECONDS
    return 2.5 if provider == 'jev' else 48.0


class HookExpired(TimeoutError):
    pass


class HookStoreBusy(RuntimeError):
    pass


class HookBudget:
    def __init__(self, started=None, *, clock=None, notify=None):
        self.clock = clock or time.monotonic
        self.started = self.clock() if started is None else started
        self.deadline = self.started + 48.0  # non-Jev compatibility path
        self.sqlite_left = .100
        self.store_busy = False
        self.lock = threading.Lock()
        self.notify = notify

    def establish(self, seconds):
        self.deadline = min(self.deadline, self.started + seconds)
        self.check()
        if self.notify is not None:
            self.notify(seconds)

    def remaining(self):
        return max(0.0, self.deadline - self.clock())

    def check(self):
        if self.store_busy:
            raise HookStoreBusy()
        if self.remaining() <= 0:
            raise HookExpired()

    def local(self):
        self.establish(LOCAL_SECONDS)

    def provider(self, provider):
        if provider == 'jev':
            self.deadline = min(self.deadline, self.started + 2.5)
        self.check()

    def classification_timeout(self, seconds, provider):
        self.check()
        value = min(seconds, self.remaining() - .15)
        if provider == 'jev':
            value = min(value, 1.5)
        if value <= 0:
            raise HookExpired()
        return value

    @contextmanager
    def sql(self):
        # Reserve before entering SQLite, so concurrent telemetry cannot spend
        # the same wait allowance. CPU time is conservatively charged as well.
        self.check()
        with self.lock:
            reserved = min(self.sqlite_left, self.remaining())
            self.sqlite_left -= reserved
        started = self.clock()
        try:
            yield int(reserved * 1000)
        finally:
            spent = max(0.0, self.clock() - started)
            with self.lock:
                self.sqlite_left += max(0.0, reserved - spent)


def hook_connection(*args, budget, **kwargs):
    import sqlite3
    class HookConnection(sqlite3.Connection):
        def __init__(self, *args, budget, **kwargs):
            super().__init__(*args, **kwargs)
            self.budget = budget

        def _bounded(self, operation, *args, **kwargs):
            with self.budget.sql() as milliseconds:
                super().execute('PRAGMA busy_timeout=' + str(milliseconds))
                try:
                    return operation(*args, **kwargs)
                except sqlite3.OperationalError as exc:
                    if (getattr(exc, 'sqlite_errorcode', 0) & 255) in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                        self.budget.store_busy = True
                    raise

        def execute(self, *args, **kwargs):
            return self._bounded(super().execute, *args, **kwargs)

        def executemany(self, *args, **kwargs):
            sql, parameters = args
            cursor = None
            for row in parameters:
                cursor = self.execute(sql, row, **kwargs)
            return cursor

        def executescript(self, script):
            # SQLite's built-in executescript resets busy timeout per statement.
            # Schema setup must use the same aggregate allowance as later queries.
            statement = ''
            cursor = None
            for char in script:
                statement += char
                if char == ';' and sqlite3.complete_statement(statement):
                    cursor = self.execute(statement)
                    statement = ''
            if statement.strip():
                cursor = self.execute(statement)
            return cursor

        def commit(self):
            return self._bounded(super().commit)

        def rollback(self):
            # Releasing a failed/expired transaction must not acquire another wait.
            super().execute('PRAGMA busy_timeout=0')
            return super().rollback()

        def __exit__(self, kind, value, traceback):
            if kind is not None:
                self.rollback()
            else:
                try:
                    self.commit()
                except BaseException:
                    self.rollback()
                    raise
            return False
    return HookConnection(*args, budget=budget, **kwargs)
