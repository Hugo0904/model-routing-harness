"""Private, site-free native CPython snapshot from an explicit local install.

No downloads, pip, user site packages, WSL, junctions or copied credentials.
The installed standard library and third-party DLL notices stay with the copy.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

from mrh.infrastructure import owned
from mrh.adapters.platforms.windows import assert_safe, protect

def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''): h.update(chunk)
    return h.hexdigest()

def snapshot_python(source, store):
    source = Path(source).resolve()
    result = subprocess.run([str(source), '-I', '-S', '-B', '-c',
        'import sys,os,platform,json;print(json.dumps({"base":sys.base_prefix,"version":list(sys.version_info[:3]),"os":os.name,"machine":platform.machine()}))'],
        capture_output=True, text=True, timeout=10, check=True)
    info = json.loads(result.stdout)
    if info['os'] != 'nt' or tuple(info['version']) < (3, 11) or info['machine'].lower() not in ('amd64', 'x86_64'):
        raise ValueError('windows_python_unsupported')
    base = Path(info['base']).resolve(); version = ''.join(str(n) for n in info['version'][:2])
    files = {p.name: p for p in base.iterdir() if p.is_file() and
             (p.name.lower() in ('python.exe', 'pythonw.exe', 'license.txt') or p.suffix.lower() == '.dll')}
    if not {'python.exe', 'LICENSE.txt', 'python'+version+'.dll'}.issubset(files):
        raise ValueError('windows_python_distribution_incomplete')
    for name in ('Lib', 'DLLs'):
        for directory, children, names in os.walk(base/name, followlinks=False):
            parent = Path(directory)
            children[:] = [n for n in children if n not in ('site-packages', '__pycache__')]
            for child in children:
                if (parent/child).lstat().st_file_attributes & 0x400: raise ValueError('windows_runtime_reparse_point')
            for filename in names:
                p = parent/filename
                if p.suffix == '.pyc': continue
                if p.lstat().st_file_attributes & 0x400: raise ValueError('windows_runtime_reparse_point')
                files[p.relative_to(base).as_posix()] = p
    hashes = {n: digest(p) for n, p in sorted(files.items())}
    identity = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    store = owned.initialize(Path(store), 'python_runtimes')
    target = store/identity[:24]
    with owned.locked(store, 'python_runtimes'):
        if target.exists():
            verify(target)
            return target/'python.exe'
        # The target is not referenced until complete. A failed copy stays
        # named as incomplete and is never silently accepted on a rerun.
        root = owned.initialize(target, 'python_runtime')
        for name, src in sorted(files.items()):
            destination = root/name
            destination.parent.mkdir(parents=True, exist_ok=True)
            data = src.read_bytes()
            if hashlib.sha256(data).hexdigest() != hashes[name]: raise ValueError('windows_runtime_source_changed')
            destination.write_bytes(data)
        for name, src in files.items():
            if digest(src) != hashes[name]: raise ValueError('windows_runtime_source_changed')
        pth = 'python'+version+'._pth'
        (root/pth).write_text('Lib\nDLLs\n.\n', encoding='ascii')
        hashes[pth] = digest(root/pth)
        owned.replace_owned(root/'runtime-manifest.json', (json.dumps({'schema_version':1,'source_version':info['version'],
            'source_fingerprint':identity,'files':hashes}, sort_keys=True)+'\n').encode(), limit=2_000_000)
        verify(root)
    return target/'python.exe'

def verify(root):
    root = owned.verify(Path(root), 'python_runtime')
    manifest = json.loads(owned.read_regular(root/'runtime-manifest.json', 2_000_000))
    expected = manifest['files']
    actual = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
    if actual != set(expected) | {owned.MARKER, 'runtime-manifest.json'}:
        raise ValueError('windows_runtime_contents_changed')
    for path in root.rglob('*'):
        assert_safe(path, path.is_dir(), private=True)
    if any(digest(root/name) != value for name, value in expected.items()):
        raise ValueError('windows_runtime_integrity_failed')
    return manifest
