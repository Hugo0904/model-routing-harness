"""Small owned-directory boundary. Locks serialize cooperating MRH writers."""
from contextlib import contextmanager
if __import__('os').name != 'nt':
    import fcntl
import json
import os
from pathlib import Path
import stat
import tempfile
import time

OWNER = "org.model-routing-harness"
MARKER = ".mrh-owner.json"


class OwnedError(ValueError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


def canonical_path(value):
    path = Path(value)
    if not path.is_absolute() or path != path.resolve() or any(ord(c) < 32 for c in str(path)):
        raise OwnedError("unsafe_path")
    return path


def read_regular(path, limit=65536):
    # Reject FIFOs via fstat without blocking before cancellation can proceed.
    if os.name == 'nt':
        from mrh.adapters.platforms.windows import open_regular
        fd = open_regular(path)
    else:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or (os.name != 'nt' and info.st_uid != os.getuid()):
            raise OwnedError("unsafe_owned_file")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            data = stream.read(limit + 1)
        if len(data) > limit:
            raise OwnedError("owned_file_oversized")
        return data
    finally:
        os.close(fd)


def _marker(kind):
    return {"schema_version": 1, "owner": OWNER, "kind": kind}


def _unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise OwnedError("unowned_target")
        value[key] = item
    return value


def verify(root, kind, allowed=None):
    root = canonical_path(root)
    info = root.lstat()
    if os.name == 'nt':
        from mrh.adapters.platforms.windows import assert_safe
        assert_safe(root, directory=True, private=True)
    elif not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
        raise OwnedError("unowned_target")
    try:
        marker = json.loads(read_regular(root / MARKER), object_pairs_hook=_unique)
    except (ValueError, OSError):
        raise OwnedError("unowned_target") from None
    if marker != _marker(kind):
        raise OwnedError("unowned_target")
    if allowed is not None:
        for path in root.iterdir():
            if path.name not in set(allowed) | {MARKER, ".mrh.lock"}:
                raise OwnedError("unknown_owned_contents")
            try:
                info = path.lstat()
                if os.name == 'nt':
                    assert_safe(path, private=True)
                elif not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid():
                    raise OwnedError("unsafe_owned_file")
            except FileNotFoundError:
                # Concurrent Hook processes open and close the SQLite store, which deletes its -wal/-shm
                # sidecars between this listing and the check. A vanished sidecar is not an ownership
                # problem; any other allowed file that disappears still fails. Windows only so far:
                # the same race exists on POSIX and is left for that platform's own verification.
                if not (os.name == 'nt' and path.name.endswith(("-wal", "-shm"))):
                    raise
    return root


def initialize(root, kind, allowed=None):
    root = canonical_path(root)
    if root.exists():
        info = root.lstat()
        if os.name == 'nt':
            from mrh.adapters.platforms.windows import assert_safe
            assert_safe(root, directory=True)
        elif not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
            raise OwnedError("unowned_target")
        if (root / MARKER).exists():
            return verify(root, kind, allowed)
        if not root.is_dir() or any(root.iterdir()):
            raise OwnedError("unowned_target")
    else:
        root.mkdir(mode=0o700)
    if os.name == 'nt':
        from mrh.adapters.platforms.windows import protect
        protect(root)
    # O_EXCL never overwrites another file, including a racing creator.
    if os.name == 'nt':
        from mrh.adapters.platforms.windows import open_regular
        fd = open_regular(root / MARKER, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    else:
        fd = os.open(root / MARKER, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(_marker(kind), stream, sort_keys=True)
        stream.write("\n")
    return verify(root, kind, allowed)


@contextmanager
def locked(root, kind, allowed=None, *, recorder=None, blocking=True):
    root = verify(root, kind)
    if os.name == 'nt':
        from mrh.adapters.platforms.windows import open_regular, lock_fd
        fd = open_regular(root / '.mrh.lock', os.O_RDWR | os.O_CREAT)
    else:
        fd = os.open(root / ".mrh.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or (os.name != 'nt' and info.st_uid != os.getuid()):
            raise OwnedError("unsafe_owned_file")
        if os.name == 'nt':
            deadline = time.monotonic() + 10
            while True:
                if recorder is not None: recorder.check()
                try:
                    lock_fd(fd)
                    break
                except BlockingIOError:
                    if not blocking:raise OwnedError('owned_lock_busy') from None
                    if time.monotonic() >= deadline: raise OwnedError('owned_lock_busy') from None
                    time.sleep(.02 if recorder is None else min(.02, recorder.remaining()))
            if recorder is not None: recorder.check()
        elif recorder is None:
            fcntl.flock(fd, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        else:
            while True:
                recorder.check()
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    time.sleep(min(.02, recorder.remaining()))
            recorder.check()
        verify(root, kind, allowed)
        yield root
    finally:
        os.close(fd)


def replace_owned(path, data, *, limit=65536, mode=0o600):
    """Caller holds an owned-directory lock; no external-writer CAS claim."""
    if path.exists() or path.is_symlink():
        read_regular(path, limit)
    fd, name = tempfile.mkstemp(prefix=".mrh-write-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            if os.name != 'nt':os.fchmod(stream.fileno(), mode)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if os.name == 'nt':
            from mrh.adapters.platforms.windows import protect
            protect(name)
        if os.name == 'nt':
            # Antivirus/readers can temporarily hold a rename lease. A bounded
            # retry keeps the old file intact; never truncate it as a fallback.
            for attempt in range(6):
                try:
                    os.replace(name, path)
                    break
                except PermissionError:
                    if attempt == 5: raise OwnedError('owned_file_busy') from None
                    time.sleep(.02)
        else:
            os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)
