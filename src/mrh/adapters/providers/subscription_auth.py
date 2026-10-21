"""Metadata-only File-auth reference; the official CLI alone reads credentials."""
from contextlib import contextmanager, ExitStack
from dataclasses import dataclass
import json
import os
import pwd
from pathlib import Path
import stat
import tempfile
from mrh.infrastructure import temporary as project_temporary
import threading

from mrh.infrastructure import owned
from mrh.routing.core import ClassifierFailure


def fail(reason):
    raise ClassifierFailure('codex_subscription_' + reason) from None


@dataclass(frozen=True)
class FileAuthSource:
    home: Path
    workspace: Path

    @classmethod
    def resolve(cls, home, workspace):
        try:
            value = cls(owned.canonical_path(home), owned.canonical_path(workspace))
            value.verify()
            return value
        except ClassifierFailure:
            raise
        except (OSError, ValueError, TypeError):
            fail('auth_source_unconfirmed')

    @property
    def path(self):
        return self.home / 'auth.json'

    def verify(self):
        try:
            import tomllib
            owned.canonical_path(self.home)
            config = self.home / 'config.toml'
            if config.exists():
                if not stat.S_ISREG(config.lstat().st_mode):
                    fail('auth_source_invalid')
                raw = owned.read_regular(config)
                if tomllib.loads(raw.decode('utf-8')).get('cli_auth_credentials_store', 'file') != 'file':
                    fail('auth_source_unconfirmed')
            info = self.path.lstat()
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or info.st_nlink != 1 or info.st_mode & 0o077):
                fail('auth_source_invalid')
        except ClassifierFailure:
            raise
        except (OSError, ValueError, TypeError):
            fail('auth_source_invalid')


@dataclass(frozen=True)
class HomeAuthSource(FileAuthSource):
    """Standalone mode: an official CLI home with a file-stored login, no MRH scope binding.

    Only metadata is checked; no credential file is opened. Hook-time safety comes from
    the isolated execution home, the disabled-feature flags and strict output parsing.
    """

    def verify(self):
        try:
            import tomllib
            owned.canonical_path(self.home)
            config = self.home / 'config.toml'
            if config.exists():
                if not stat.S_ISREG(config.lstat().st_mode):
                    fail('auth_source_invalid')
                raw = owned.read_regular(config)
                if tomllib.loads(raw.decode('utf-8')).get('cli_auth_credentials_store', 'file') != 'file':
                    fail('auth_source_unconfirmed')
            info = self.path.lstat()
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or info.st_nlink != 1 or info.st_mode & 0o077):
                fail('auth_source_invalid')
        except ClassifierFailure:
            raise
        except (OSError, ValueError, TypeError):
            fail('auth_source_invalid')


def source_for_home(home=None):
    base = Path(home) if home else Path(os.environ.get('CODEX_HOME') or Path(pwd.getpwuid(os.getuid()).pw_dir) / '.codex')
    try:
        value = HomeAuthSource(owned.canonical_path(base), Path('/'))
    except (OSError, ValueError, TypeError):
        fail('auth_source_unconfirmed')
    value.verify()
    return value




@contextmanager
def source_lock(source, recorder, root=None):
    # One stable owned lock serializes MRH classifiers, including equal auth
    # sources in different profiles. It does not coordinate stock CLI writers.
    # HOME can differ between Codex profiles. Use the OS user's stable state
    # root so equal auth sources cannot accidentally acquire different locks.
    root = root or Path(pwd.getpwuid(os.getuid()).pw_dir) / '.local/state/model-routing-harness/subscription-auth'
    try:
        root = owned.canonical_path(root)
        root.parent.mkdir(parents=True, exist_ok=True)
        owned.initialize(root, 'subscription-auth', set())
    except (owned.OwnedError, OSError):
        fail('auth_lock_unavailable')
    with ExitStack() as stack:
        try:
            stack.enter_context(owned.locked(root, 'subscription-auth', set(), recorder=recorder))
        except TimeoutError:
            raise
        except (owned.OwnedError, OSError):
            fail('auth_lock_unavailable')
        recorder.check()
        source.verify()
        yield


class ReferenceHome:
    """Cancellation kills registered processes before removing owned scratch."""
    def __init__(self, source, recorder):
        self.source = source
        self.parent = recorder
        self.lock = threading.RLock()
        self.closed = False
        self.done = threading.Event()
        self.cleanups = []
        self.temp = project_temporary.directory(prefix='mrh-classifier-')
        self.root = Path(self.temp.name).resolve()
        self.home = self.root / 'home'
        self.work = self.root / 'work'
        try:
            self.home.mkdir(mode=0o700)
            self.work.mkdir(mode=0o700)
            source.verify()
            (self.home / 'auth.json').symlink_to(source.path)
            recorder.add_cleanup(self.close)
            self.verify_reference()
        except BaseException:
            self.close()
            raise

    def check(self):
        self.parent.check()
        with self.lock:
            if self.closed or not self.root.is_dir():
                raise TimeoutError()

    def verify_reference(self):
        self.check()
        with self.lock:
            self.source.verify()
            reference = self.home / 'auth.json'
            if not reference.is_symlink() or os.readlink(reference) != str(self.source.path):
                fail('auth_reference_invalid')
            if any(os.path.lexists(self.home / name) for name in ('AGENTS.md', 'AGENTS.override.md')):
                fail('home_instructions')

    def add_cleanup(self, callback):
        with self.lock:
            closed = self.closed
            if not closed:
                self.cleanups.append(callback)
        if closed:
            callback()
            raise TimeoutError()

    def close(self):
        with self.lock:
            first = not self.closed
            if first:
                self.closed = True
                cleanups = list(reversed(self.cleanups))
        if not first:
            self.done.wait()
            return
        try:
            for callback in cleanups:
                callback()
        finally:
            # TemporaryDirectory unlinks symlinks; it never follows them.
            try:
                self.temp.cleanup()
            finally:
                self.done.set()

    def remaining(self):
        return self.parent.remaining()


@contextmanager
def execution_home(source, recorder, lock_root=None):
    with source_lock(source, recorder, lock_root):
        reference = ReferenceHome(source, recorder)
        try:
            yield reference
        finally:
            reference.close()
