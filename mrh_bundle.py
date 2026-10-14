"""Build-time macOS arm64 directory bundle; no downloader in the application."""
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import shutil
import stat
import subprocess
import tarfile
import tempfile
from urllib.parse import unquote
import zipfile

import mrh_build

ROOT = Path(__file__).resolve().parent
LOCK = ROOT / 'packaging/macos-arm64/runtime-lock.json'
CACHE_MARKER = '.mrh-e15-public-assets'
CACHE_CONTENT = 'MRH E15 fixed official runtime/notices build inputs\n'
MAX_UNPACKED = 512_000_000

ENTRY = b'''#!/bin/sh
set -eu
if [ "$(/usr/bin/uname -s)" != Darwin ] || [ "$(/usr/bin/uname -m)" != arm64 ]; then
    echo "MRH: this candidate requires macOS arm64." >&2
    exit 1
fi
mrh_entry=$0
case "$mrh_entry" in */*) ;; *) mrh_entry=$(command -v "$mrh_entry");; esac
mrh_hops=0
while [ -L "$mrh_entry" ]; do
    mrh_hops=$((mrh_hops + 1))
    if [ "$mrh_hops" -gt 16 ]; then echo "MRH: entry symlink loop." >&2; exit 1; fi
    mrh_dir=$(CDPATH= cd -P "$(/usr/bin/dirname "$mrh_entry")" && pwd)
    mrh_link=$(/usr/bin/readlink "$mrh_entry")
    case "$mrh_link" in /*) mrh_entry=$mrh_link;; *) mrh_entry=$mrh_dir/$mrh_link;; esac
done
mrh_dir=$(CDPATH= cd -P "$(/usr/bin/dirname "$mrh_entry")" && pwd)
exec "$mrh_dir/runtime/bin/python3.11" -I -B "$mrh_dir/app/mrh.pyz" "$@"
'''

README = """MRH macOS arm64 code asset

Normally installed and retained by the checkout's ./setup --host command.
The private runtime and its complete notices are included. No vendor CLI,
credentials, profile or statistics are embedded in this directory.
Do not replace a shared interpreter or move an active managed generation.
Settings and statistics live at the separately selected persistent profile.
Native installation and trust are separate; preparing or checking these files
makes no model/classifier call and grants no permission to export a task.

This is an unsigned local candidate, not a notarized public multi-platform
release. manifest.json records source/runtime provenance and file hashes;
notices/runtime retains the runtime metadata and required notices.
No additional publication license is asserted by this build.
"""


class BundleError(ValueError):
    pass


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def read_lock(path=LOCK):
    value = json.loads(Path(path).read_text())
    if (value.get('schema_version') != 1 or value.get('provider') != 'astral-sh/python-build-standalone' or
            value.get('target') != 'aarch64-apple-darwin' or not value.get('python_version', '').startswith('3.11.')):
        raise BundleError('runtime_lock_invalid')
    for key in ('runtime', 'licensing_source'):
        a = value[key]
        prefix = 'https://github.com/astral-sh/python-build-standalone/releases/download/' + value['release'] + '/'
        expected = 'cpython-' + value['python_version'] + '+' + value['release'] + '-' + value['target']
        suffix = '-install_only.tar.gz' if key == 'runtime' else '-pgo+lto-full.tar.zst'
        if (a['name'] != expected + suffix or not a['url'].startswith(prefix) or
                unquote(a['url'].removeprefix(prefix)) != a['name'] or '/' in a['name'] or '..' in a['name'] or
                type(a['size']) is not int or not 0 < a['size'] < MAX_UNPACKED or
                len(a['sha256']) != 64 or any(c not in '0123456789abcdef' for c in a['sha256'])):
            raise BundleError('runtime_lock_invalid')
    snapshot = value.get('licensing_snapshot_sha256')
    if snapshot is not None and (not isinstance(snapshot,str) or len(snapshot)!=64 or any(c not in '0123456789abcdef' for c in snapshot)):
        raise BundleError('runtime_lock_invalid')
    return value


def asset_cache(cache, lock):
    cache = Path(cache).absolute()
    if cache.is_symlink():
        raise BundleError('cache_unowned')
    if not cache.exists():
        cache.mkdir(parents=True)
        (cache / CACHE_MARKER).write_text(CACHE_CONTENT)
    marker = cache / CACHE_MARKER
    if marker.is_symlink() or not marker.is_file() or marker.stat().st_size > 1024 or marker.read_text() != CACHE_CONTENT:
        raise BundleError('cache_unowned')
    allowed = {CACHE_MARKER} | {lock[k]['name'] for k in ('runtime', 'licensing_source')}
    if any(p.name not in allowed or p.is_symlink() for p in cache.iterdir()):
        raise BundleError('cache_unowned')
    return cache


def fixed_assets(cache, lock, *, download=False):
    cache = asset_cache(cache, lock)
    result = {}
    for key in ('runtime', 'licensing_source'):
        asset = lock[key]; path = cache / asset['name']
        if not path.exists():
            if not download:
                raise BundleError('fixed_asset_missing')
            with tempfile.TemporaryDirectory(prefix='mrh-runtime-download-', dir=cache.parent) as tmp:
                staged = Path(tmp) / asset['name']
                subprocess.run(['/usr/bin/curl', '--disable', '--fail', '--silent', '--show-error', '--location', '--proto', '=https', '--proto-redir', '=https',
                                '--max-time', '120', asset['url'], '-o', str(staged)], check=True,
                               env={'PATH': '/usr/bin:/bin', 'TMPDIR': tmp})
                if staged.stat().st_size != asset['size'] or sha256(staged) != asset['sha256']:
                    raise BundleError('fixed_asset_hash_mismatch')
                staged.replace(path)
        if not path.is_file() or path.stat().st_size != asset['size'] or sha256(path) != asset['sha256']:
            raise BundleError('fixed_asset_hash_mismatch')
        result[key] = path
    return result


def _relative(name, prefix='python'):
    p = PurePosixPath(name)
    if (p.is_absolute() or not p.parts or p.parts[0] != prefix or
            '..' in p.parts or '\\' in name or '\x00' in name):
        raise BundleError('unsafe_archive_path')
    return Path(*p.parts[1:])


def extract_runtime(archive, destination, *, prefix='python'):
    """Validate every name/type/link before writes; links are created last."""
    destination = Path(destination)
    if destination.exists():
        raise BundleError('output_exists')
    with tarfile.open(archive, 'r:gz') as tf:
        members = tf.getmembers(); seen = set(); total = 0
        for member in members:
            relative = _relative(member.name, prefix); key = relative.as_posix().casefold()
            if key in seen:
                raise BundleError('duplicate_archive_path')
            seen.add(key); total += member.size
            if total > MAX_UNPACKED or len(members) > 100_000 or member.mode & 0o6000:
                raise BundleError('unsafe_archive_size_or_mode')
            if not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
                raise BundleError('unsafe_archive_type')
            if member.issym():
                if PurePosixPath(member.linkname).is_absolute() or '\\' in member.linkname:
                    raise BundleError('unsafe_archive_link')
                _relative(posixpath.normpath(posixpath.join(posixpath.dirname(member.name), member.linkname)), prefix)
            elif member.islnk():
                _relative(member.linkname, prefix)
        # No regular member is written through a symlink. Existing contents are
        # never reused; caller owns this fresh staging directory.
        destination.mkdir()
        for member in members:
            path = destination / _relative(member.name, prefix)
            if member.isdir():
                path.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                path.parent.mkdir(parents=True, exist_ok=True)
                with tf.extractfile(member) as source, path.open('xb') as target:
                    shutil.copyfileobj(source, target)
                path.chmod(0o755 if member.mode & 0o111 else 0o644)
                os.utime(path, (member.mtime, member.mtime))
        for member in members:
            path = destination / _relative(member.name, prefix)
            if member.islnk():
                path.parent.mkdir(parents=True, exist_ok=True)
                target = destination / _relative(member.linkname, prefix)
                if not target.is_file() or target.is_symlink():
                    raise BundleError('unsafe_archive_link')
                os.link(target, path)
            elif member.issym():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.symlink_to(member.linkname)
        for path in destination.rglob('*'):
            if path.is_symlink() and (not path.exists() or not path.resolve().is_relative_to(destination.resolve())):
                raise BundleError('unsafe_archive_link')


def licensing_snapshot(destination, lock, runtime):
    """Ship reviewed public notices without an undeclared tar/zstd/otool dependency."""
    source=ROOT/'packaging/macos-arm64/license-snapshot'
    try:
        if source.is_symlink() or sha256(source/'snapshot.json')!=lock['licensing_snapshot_sha256']:
            raise ValueError()
        value=json.loads((source/'snapshot.json').read_bytes())
        if value['schema_version']!=1 or value['source']!={'provider':lock['provider'],'release':lock['release'],
                'runtime_sha256':lock['runtime']['sha256'],'licensing_sha256':lock['licensing_source']['sha256']}:
            raise ValueError()
        files=value['files']
        actual={p.relative_to(source).as_posix() for p in source.rglob('*') if p.is_file()}
        if actual!=set(files)|{'snapshot.json'} or any(p.is_symlink() for p in source.rglob('*')):
            raise ValueError()
        for name,info in files.items():
            relative=_relative('python/'+name)
            p=source/relative
            if p.stat().st_size!=info['size'] or sha256(p)!=info['sha256']:
                raise ValueError()
        metadata=json.loads((source/'PYTHON.json').read_bytes());summary=value['summary']
        if metadata['python_version']!=lock['python_version'] or metadata['target_triple']!=lock['target']:
            raise ValueError()
        if summary['metadata_sha256']!=files['PYTHON.json']['sha256'] or summary['metadata_source']!=lock['licensing_source']:
            raise ValueError()
        if summary['copied_notices']!={n:info['sha256'] for n,info in files.items() if n!='PYTHON.json'}:
            raise ValueError()
        binary=value['runtime_binary'];binary_path=Path(runtime)/_relative('python/'+binary['path'])
        if sha256(binary_path)!=binary['sha256']:
            raise ValueError()
        missing=set(summary['required_license_paths'])-set(summary['copied_notices'])
        if missing!=set(summary['missing_nonredistributed_alternative']) or missing-{'licenses/LICENSE.zlib-ng.txt'}:
            raise ValueError()
        if missing and '/usr/lib/libz.1.dylib' not in binary['verified_system_libraries']:
            raise ValueError()
    except (KeyError,TypeError,ValueError,OSError):
        raise BundleError('licensing_snapshot_invalid') from None
    destination=Path(destination)
    if destination.exists():raise BundleError('output_exists')
    destination.mkdir(parents=True)
    for name in files:
        p=destination/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes((source/name).read_bytes())
    return {**summary,'snapshot_verification':{'sha256':lock['licensing_snapshot_sha256'],
            'runtime_binary_sha256':binary['sha256'],'source':'locked public notice snapshot; exact pinned runtime binary'}}


def licensing(full_archive, destination, lock, runtime):
    if lock.get('licensing_snapshot_sha256'):
        return licensing_snapshot(destination,lock,runtime)
    # Compatibility for old lock files. The maintainer path may require zstd;
    # current consumer builds use the locked public notice snapshot above.
    listing = subprocess.run(['/usr/bin/tar', '-tf', str(full_archive)], capture_output=True, text=True, check=True).stdout.splitlines()
    read = lambda name: subprocess.run(['/usr/bin/tar', '-xOf', str(full_archive), name], capture_output=True, check=True).stdout
    metadata_bytes = read('python/PYTHON.json'); metadata = json.loads(metadata_bytes)
    if metadata['python_version'] != lock['python_version'] or metadata['target_triple'] != lock['target']:
        raise BundleError('licensing_metadata_mismatch')
    required = {metadata['license_path']}; contexts = {}
    for module, candidates in metadata['build_info']['extensions'].items():
        for candidate in candidates:
            required.update(candidate.get('license_paths', []))
            for path in candidate.get('license_paths', []):
                contexts.setdefault(path, []).append({'module': module, 'links': candidate.get('links', [])})
            if candidate.get('licenses') and not candidate.get('license_paths'):
                raise BundleError('licensing_metadata_incomplete')
    names = sorted(n for n in listing if n.startswith('python/licenses/') and not n.endswith('/'))
    available = {n.removeprefix('python/') for n in names}
    missing = required - available; system_notices = {}
    for path in missing:
        # The exact Darwin metadata names both zlib variants while its module
        # links only Apple's system libz. Do not invent a missing shipped notice:
        # retain the original metadata and prove this dependency isn't bundled.
        uses = contexts.get(path, [])
        if (path != 'licenses/LICENSE.zlib-ng.txt' or not uses or
                any(x['module'] != 'zlib' or x['links'] != [{'name': 'z', 'system': True}] for x in uses)):
            raise BundleError('license_text_missing')
        binaries = list((Path(runtime) / 'lib/python3.11/lib-dynload').glob('zlib*.so'))
        if not binaries:
            # This standalone distribution compiles extensions into its Python
            # executable rather than emitting a separate zlib shared object.
            binary = Path(runtime) / _relative('python/' + metadata['python_exe'].removeprefix('install/'))
            binaries = [binary] if binary.is_file() else []
        if len(binaries) != 1:
            raise BundleError('system_dependency_unverified')
        linked = subprocess.run(['/usr/bin/otool', '-L', str(binaries[0])], capture_output=True, text=True, check=True).stdout
        if '/usr/lib/libz.1.dylib' not in linked or any('zlib-ng' in p.name.lower() for p in Path(runtime).rglob('*')):
            raise BundleError('system_dependency_unverified')
        system_notices[path] = {'reason': 'metadata alternative; zlib-ng not redistributed',
                                'metadata': uses, 'actual_system_library': '/usr/lib/libz.1.dylib'}
    destination.mkdir(parents=True)
    (destination / 'PYTHON.json').write_bytes(metadata_bytes)
    paths = {}
    for name in names:
        relative = _relative(name); data = read(name)
        if len(data) > 1_000_000 or not data:
            raise BundleError('license_text_invalid')
        path = destination / relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)
        paths[relative.as_posix()] = hashlib.sha256(data).hexdigest()
    return {'metadata_source': lock['licensing_source'], 'metadata_sha256': hashlib.sha256(metadata_bytes).hexdigest(),
            'required_license_paths': sorted(required), 'copied_notices': paths,
            'missing_nonredistributed_alternative': system_notices,
            'deployment_target': metadata.get('apple_sdk_deployment_target'), 'build_options': metadata.get('build_options')}


def application_archive(path):
    _, _, _, files = mrh_build.metadata()
    files.update(mrh_build.package_files())
    files['__main__.py'] = b'from mrh.cli import main\nraise SystemExit(main())\n'
    path.parent.mkdir()
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, data in sorted(files.items()):
            entry = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0)); entry.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(entry, data)
    return {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}


def file_manifest(root):
    result = {}
    for p in sorted(root.rglob('*')):
        name = p.relative_to(root).as_posix()
        if p.is_symlink():
            result[name] = {'symlink': os.readlink(p)}
        elif p.is_file() and name != 'manifest.json':
            result[name] = {'sha256': sha256(p), 'size': p.stat().st_size, 'mode': stat.S_IMODE(p.stat().st_mode)}
    return result


def build(cache, output, archive, *, download=False):
    lock = read_lock(); assets = fixed_assets(cache, lock, download=download)
    output, archive = Path(output).absolute(), Path(archive).absolute()
    if output.exists() or output.is_symlink() or archive.exists() or archive.is_symlink():
        raise BundleError('output_exists')
    output.parent.mkdir(parents=True, exist_ok=True); archive.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.mrh-bundle-stage-', dir=output.parent) as tmp:
        staged = Path(tmp) / output.name; staged.mkdir()
        extract_runtime(assets['runtime'], staged / 'runtime')
        notices = licensing(assets['licensing_source'], staged / 'notices/runtime', lock, staged / 'runtime')
        source = application_archive(staged / 'app/mrh.pyz')
        (staged / 'mrh').write_bytes(ENTRY); (staged / 'mrh').chmod(0o755)
        (staged / 'README.txt').write_text(README)
        manifest = {'schema_version': 1, 'kind': 'local_macos_arm64_standalone_candidate',
                    'runtime': lock, 'runtime_notices': notices, 'application_files': source,
                    'entry': 'mrh', 'private_interpreter': 'runtime/bin/python3.11',
                    'source_commit': subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip(),
                    'builder_files': {str(p.relative_to(ROOT)): sha256(p) for p in
                                      (ROOT / 'mrh_bundle.py', ROOT / 'mrh_build.py', ROOT / 'scripts/packaging/build_standalone.py', LOCK)},
                    'files': file_manifest(staged), 'signed_or_notarized_release': False, 'runtime_download_on_use': False}
        (staged / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        # Relocation changes only container paths; runtime and source bytes stay
        # intact. Preserve runtime mtime for its distributed stdlib bytecode.
        staged.rename(output)
    with archive.open('xb') as f, gzip.GzipFile(filename='', fileobj=f, mode='wb', mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode='w') as tf:
            tf.add(output, arcname=output.name, recursive=True)
    return {'directory': str(output), 'archive': str(archive), 'archive_sha256': sha256(archive),
            'archive_bytes': archive.stat().st_size, 'manifest_sha256': sha256(output / 'manifest.json'),
            'runtime_version': lock['python_version'], 'runtime_asset_sha256': lock['runtime']['sha256'],
            'notices': len(notices['copied_notices']), 'runtime_files': len(manifest['files'])}
