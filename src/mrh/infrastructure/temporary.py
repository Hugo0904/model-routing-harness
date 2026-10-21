"""Disposable project scratch/cache only. No backup, statistics or recovery ledger."""
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
import time

from mrh.infrastructure import owned


def project_root():
    # An installed generation wins over caller environment. Source / standalone
    # callers may explicitly bind a test or user project, never their cwd.
    root = None
    source = None
    for parent in Path(__file__).absolute().parents:
        if (parent / 'generation.json').is_file():
            meta = json.loads(owned.read_regular(parent / 'generation.json'))
            if meta.get('project_root'):
                root = owned.canonical_path(meta['project_root']); break
        if (parent / 'pyproject.toml').is_file() and (parent / 'src/mrh').is_dir():
            source = parent
            break
    if root is None:
        explicit = os.environ.get('MRH_PROJECT_ROOT')
        root = owned.canonical_path(explicit) if explicit else source
    if root is None or not root.is_dir():
        raise owned.OwnedError('project_runtime_unavailable:請指定有效的 MRH_PROJECT_ROOT')
    return owned.canonical_path(root)


def area(kind='tmp', *, create=True):
    if kind not in ('tmp', 'cache'):
        raise ValueError('invalid_disposable_area')
    root = owned.canonical_path(project_root() / 'runtime' / kind / 'mrh')
    if create:
        root.parent.mkdir(parents=True, exist_ok=True)
        return owned.initialize(root, 'disposable_' + kind)
    return owned.canonical_path(root)


def mkstemp(*, prefix='.mrh-', **kwargs):
    root = area()
    with owned.locked(root, 'disposable_tmp'):
        return tempfile.mkstemp(prefix=prefix, dir=root, **kwargs)


def directory(*, prefix='mrh-', dir=None):
    root = area()
    if dir is not None and owned.canonical_path(dir) != root:raise ValueError('temporary_root_override_denied')
    with owned.locked(root, 'disposable_tmp'):
        result = tempfile.TemporaryDirectory(prefix=prefix, dir=root)
        if os.name == 'nt':
            from mrh.adapters.platforms.windows import protect
            protect(Path(result.name))
        return result


def mkdtemp(*, prefix='mrh-'):
    root = area()
    with owned.locked(root, 'disposable_tmp'):
        result = tempfile.mkdtemp(prefix=prefix, dir=root)
        if os.name == 'nt':
            from mrh.adapters.platforms.windows import protect
            protect(Path(result))
        return result


def _inventory(path):
    info = path.lstat()
    if path.is_symlink() or getattr(info, 'st_file_attributes', 0) & 0x400:
        raise ValueError('link_or_reparse_point')
    if stat.S_ISREG(info.st_mode):
        if info.st_nlink != 1:raise ValueError('hardlink')
        return 1, info.st_size
    if stat.S_ISDIR(info.st_mode):
        rows = [_inventory(child) for child in path.iterdir()]
        return sum(r[0] for r in rows), sum(r[1] for r in rows)
    raise ValueError('unsupported_file_type')


def cleanup(*, apply=False):
    result = {'applied': apply, 'files': 0, 'bytes': 0, 'count_scope': 'complete_entries', 'skipped': [], 'roots': []}
    cutoff = time.time_ns()
    for kind in ('tmp', 'cache'):
        root = area(kind, create=False)
        result['roots'].append(str(root))
        if not root.exists():continue
        owned.verify(root, 'disposable_' + kind)
        try:
            with owned.locked(root, 'disposable_' + kind, blocking=False):
                for path in list(root.iterdir()):
                    if path.name in (owned.MARKER, '.mrh.lock'):continue
                    try:
                        before = path.lstat()
                        if before.st_ctime_ns > cutoff:raise ValueError('created_or_changed_during_reset')
                        files, size = _inventory(path)
                        after = path.lstat()
                        if (after.st_ino, after.st_ctime_ns) != (before.st_ino, before.st_ctime_ns):
                            raise ValueError('changed_during_reset')
                        if apply:
                            if path.is_dir():shutil.rmtree(path)
                            else:path.unlink()
                        result['files'] += files
                        result['bytes'] += size
                    except (OSError, ValueError) as exc:
                        result['skipped'].append({'name': path.name, 'reason': str(exc) if isinstance(exc, ValueError) else type(exc).__name__})
        except (BlockingIOError, owned.OwnedError) as exc:
            if isinstance(exc, owned.OwnedError) and str(exc) != 'owned_lock_busy':raise
            result['skipped'].append({'name': kind, 'reason': 'in_use'})
    return result
