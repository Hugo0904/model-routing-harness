"""Workspace scope is export permission, never host filesystem authority."""
from pathlib import Path, PureWindowsPath
import unicodedata

ALL = '*'

def path(value, *, resolve_local=False):
    if not isinstance(value, str) or not value or any(unicodedata.category(c) == 'Cc' for c in value):
        raise ValueError('workspace_invalid')
    p = PureWindowsPath(value)
    if any(c in value for c in '<>"|?*') or ':' in p.drive.removesuffix(':'):
        raise ValueError('workspace_invalid')
    if (not p.is_absolute() or value.startswith(('\\\\?\\', '\\\\.\\')) or '..' in p.parts
            or any(':' in part or part.endswith((' ', '.')) for part in p.parts[1:])):
        raise ValueError('workspace_invalid')
    if resolve_local and not p.drive.startswith('\\\\'):
        p = PureWindowsPath(str(Path(value).resolve()))
    return p

def allowed(roots, cwd):
    try:
        candidate = path(cwd, resolve_local=True)
        # Explicit Windows sentinel persists across new drives/shares. It is
        # not the current-drive '/' alias and never grants relative/device paths.
        if ALL in roots: return True
        return any(candidate == path(root, resolve_local=True) or path(root, resolve_local=True) in candidate.parents for root in roots)
    except (OSError, ValueError, RuntimeError): return False
