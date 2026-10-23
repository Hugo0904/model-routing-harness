"""Managed installed/editable execution; no user-site or cwd-based discovery.

The managed Windows interpreter deliberately disables site initialization. Its
editable link is the same plain-path PEP 660 wheel link used by normal Python
frontends, resolved explicitly rather than executing arbitrary .pth code.
"""
import json
import os
from pathlib import Path
import sys
from contextlib import contextmanager, ExitStack

from mrh.infrastructure import owned

DESCRIPTOR = 'model_routing_harness-editable.json'
PTH = 'model_routing_harness-editable.pth'


def editable_source(directory, expected=None):
    directory = owned.canonical_path(Path(directory))
    value = json.loads(owned.read_regular(directory / DESCRIPTOR))
    if set(value) != {'schema_version', 'source_root', 'source_path'} or value['schema_version'] != 1:
        raise owned.OwnedError('editable_link_invalid')
    root = owned.canonical_path(Path(value['source_root']))
    source = owned.canonical_path(Path(value['source_path']))
    if source != root / 'src' or expected is not None and root != Path(expected):
        raise owned.OwnedError('editable_link_invalid')
    if owned.read_regular(directory / PTH).decode('utf-8') != str(source) + '\n':
        raise owned.OwnedError('editable_link_invalid')
    return legacy_source(root)


def legacy_source(root):
    """Validate mutable source without inventing editable links for old generations."""
    root = owned.canonical_path(Path(root))
    source = owned.canonical_path(root / 'src')
    if not (source / 'mrh/__init__.py').is_file():
        raise owned.OwnedError('editable_source_unavailable')
    # Mutable source is explicitly trusted only in development mode. The
    # ownership check remains separate from published artifact integrity.
    for path in (root, source, source / 'mrh'):
        if os.name == 'nt':
            from mrh.adapters.platforms.windows import assert_safe
            assert_safe(path, directory=True)
        else:
            info = path.stat()
            if info.st_uid != os.getuid() or info.st_mode & 0o022:
                raise owned.OwnedError('editable_source_unsafe')
    return source


def generation_root():
    for parent in Path(__file__).absolute().parents:
        if (parent / 'generation.json').is_file():
            return parent
    return None


def activate_editable(directory, expected):
    source = editable_source(directory, expected)
    os.environ['MRH_EXECUTION_MODE'] = 'development'
    os.environ['MRH_SOURCE_ROOT'] = str(source.parent)
    for name in list(sys.modules):
        if name == 'mrh' or name.startswith('mrh.'):
            del sys.modules[name]
    sys.path.insert(0, str(source))


def main():
    root = generation_root()
    if root is not None:
        meta = json.loads(owned.read_regular(root / 'generation.json'))
        if 'runtime_root' in meta:
            os.environ.pop('MRH_PROJECT_ROOT', None)
            os.environ['MRH_RUNTIME_ROOT'] = str(owned.canonical_path(Path(meta['runtime_root'])))
        dev = meta.get('dev_source')
        if dev is not None:
            activate_editable(root / 'app/editable', dev)
        else:
            os.environ['MRH_EXECUTION_MODE'] = 'installed'
            os.environ.pop('MRH_SOURCE_ROOT', None)
    from mrh.cli import main as cli_main
    return cli_main()


def assert_idle_packets(settings_paths):
    """Read only: refuse a mode change while an unexpired packet is in flight."""
    import time
    from mrh.adapters.hosts import codex_packets as packets
    terminal = {'completed', 'failed', 'expired', 'cancelled'}
    now = time.time()
    for settings in dict.fromkeys(Path(p) for p in settings_paths):
        root = packets.root_for(settings)
        if not root.exists():
            continue
        owned.verify(root, 'codex_packets')
        for directory in root.iterdir():
            if not directory.is_dir():
                continue
            identifier = directory.name
            directory = packets._directory(settings, identifier)
            with packets._lock(directory):
                receipt = packets._receipt(directory, identifier)
                if receipt['state'] not in terminal and (receipt['state'] == 'released' or receipt['expires'] > now):
                    raise owned.OwnedError('mode_change_packet_in_progress')


def runtime_binding(metadata):
    runtime = metadata.get('runtime_root')
    if runtime is None and metadata.get('project_root'):
        runtime = str(Path(metadata['project_root']) / 'runtime')
    return runtime, metadata.get('dev_source')


@contextmanager
def packet_mode_transition(settings_paths):
    """Keep packet admission closed from the idle check through the managed switch."""
    from mrh.adapters.hosts import codex_packets as packets
    paths = sorted({owned.canonical_path(Path(path)) for path in settings_paths}, key=str)
    with ExitStack() as stack:
        for settings in paths:
            root = packets.root_for(settings)
            owned.initialize(root, 'codex_packets')
            try:
                stack.enter_context(owned.locked(root, 'codex_packets', blocking=False))
            except (BlockingIOError, owned.OwnedError) as exc:
                if isinstance(exc, BlockingIOError) or str(exc) == 'owned_lock_busy':
                    raise owned.OwnedError('mode_change_packet_in_progress') from None
                raise
        try:
            assert_idle_packets(paths)
        except packets.PacketError as exc:
            if exc.reason == 'packet_classification_in_progress':
                raise owned.OwnedError('mode_change_packet_in_progress') from None
            raise
        yield
