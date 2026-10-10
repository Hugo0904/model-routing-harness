"""Small owned-directory boundary. Locks serialize cooperating MRH writers."""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import stat
import tempfile

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
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid():
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
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
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
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid():
                raise OwnedError("unsafe_owned_file")
    return root


def initialize(root, kind, allowed=None):
    root = canonical_path(root)
    if root.exists():
        info = root.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
            raise OwnedError("unowned_target")
        if (root / MARKER).exists():
            return verify(root, kind, allowed)
        if not root.is_dir() or any(root.iterdir()):
            raise OwnedError("unowned_target")
    else:
        root.mkdir(mode=0o700)
    # O_EXCL never overwrites another file, including a racing creator.
    fd = os.open(root / MARKER, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(_marker(kind), stream, sort_keys=True)
        stream.write("\n")
    return verify(root, kind, allowed)


@contextmanager
def locked(root, kind, allowed=None):
    root = verify(root, kind)
    fd = os.open(root / ".mrh.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid():
            raise OwnedError("unsafe_owned_file")
        fcntl.flock(fd, fcntl.LOCK_EX)
        verify(root, kind, allowed)
        yield root
    finally:
        os.close(fd)


def replace_owned(path, data):
    """Caller holds an owned-directory lock; no external-writer CAS claim."""
    if path.exists() or path.is_symlink():
        read_regular(path)
    fd, name = tempfile.mkstemp(prefix=".mrh-write-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)
