"""Exact-version, offline public ACP defaults; no prompt, login or real key."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import selectors
import shutil
import signal
import subprocess
import tempfile
import time

from .catalog import Catalog, CatalogError, Model, executable_hash
from .claude_catalog import isolation_profile
from .types import safe_model_id

TESTED_VERSION = '0.63.0'
PLACEHOLDER = 'mrh-invalid-offline-placeholder'
MAX_RESPONSE = 262144


def installation(executable):
    """Pin npm payload and its existing Node, rather than only a tiny stub."""
    entry = Path(executable)
    executable_hash(entry)  # Existing ownership/permission/absolute-file gate.
    package = entry.parent.parent
    try:
        metadata = json.loads((package / 'package.json').read_text())
        if metadata['name'] != '@google/gemini-cli' or metadata['bin'] != {'gemini': 'bundle/gemini.js'} or entry != package / 'bundle/gemini.js':
            raise CatalogError('gemini_installation_unsupported')
        if metadata['version'] != TESTED_VERSION:
            raise CatalogError('gemini_catalog_version_unsupported')
        node = (package.parents[3] / 'bin/node').resolve()
        node_hash = executable_hash(node)
        digest = hashlib.sha256(); files = {}; total = 0
        for path in sorted(package.rglob('*')):
            name = path.relative_to(package).as_posix()
            if path.is_symlink():
                if not path.resolve().is_relative_to(package):
                    raise CatalogError('gemini_installation_unsupported')
                value = 'link:' + os.readlink(path)
            elif path.is_file():
                total += path.stat().st_size
                if total > 256_000_000 or path.stat().st_mode & 0o022:
                    raise CatalogError('gemini_installation_unsupported')
                value = hashlib.sha256(path.read_bytes()).hexdigest()
            else:
                continue
            files[name] = value; digest.update((name + '\0' + value + '\n').encode())
        digest.update(('node\0' + node_hash).encode())
        return {'entry': entry, 'package': package, 'node': node, 'node_sha256': node_hash,
                'version': metadata['version'], 'sha256': digest.hexdigest(), 'files': files}
    except CatalogError:
        raise
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        raise CatalogError('gemini_installation_unsupported') from None


def parse_initialize(frame, identity=1):
    try:
        if type(frame) is not dict or frame['jsonrpc'] != '2.0' or type(frame['id']) is not int or frame['id'] != identity or 'error' in frame:
            raise ValueError()
        result = frame['result']
        if result['protocolVersion'] != 1 or result['agentInfo']['name'] != 'gemini-cli' or result['agentInfo']['version'] != TESTED_VERSION:
            raise ValueError()
    except (KeyError, TypeError, ValueError):
        raise CatalogError('gemini_catalog_protocol_incompatible') from None


def parse_session(frame, identity=2):
    try:
        if type(frame) is not dict or frame['jsonrpc'] != '2.0' or type(frame['id']) is not int or frame['id'] != identity:
            raise ValueError()
        if 'error' in frame:
            raise CatalogError('gemini_catalog_initialize_failed')
        result = frame['result']; models = result['models']; rows = models['availableModels']
        if (not isinstance(result['sessionId'], str) or not result['sessionId'] or
                type(rows) is not list or not 0 < len(rows) <= 1024 or not safe_model_id(models['currentModelId'])):
            raise ValueError()
        output = []; seen = set()
        for row in rows:
            if (type(row) is not dict or set(row) - {'modelId', 'name', 'description'} or
                    not safe_model_id(row['modelId']) or row['modelId'] in seen or
                    not isinstance(row['name'], str) or not 0 < len(row['name']) <= 256):
                raise ValueError()
            seen.add(row['modelId'])
            # ACP approval modes/thinking budgets are not reasoning efforts.
            # Exact modelId includes aliases such as auto; names are labels.
            output.append(Model(row['modelId'], row['name'], ()))
        if models['currentModelId'] not in seen:
            raise ValueError()
        return tuple(output)
    except CatalogError:
        raise
    except (KeyError, TypeError, ValueError):
        raise CatalogError('gemini_catalog_protocol_incompatible') from None


@contextmanager
def isolated_install(info):
    if os.uname().sysname != 'Darwin' or not Path('/usr/bin/sandbox-exec').is_file():
        raise CatalogError('gemini_catalog_isolation_unavailable')
    tmp = tempfile.mkdtemp(prefix='mrh-gemini-', dir='/private/tmp')
    cleanup = True
    try:
        root = Path(tmp).resolve(); package = root / 'public-cli'
        # The package was checked for external links. The copied public payload
        # can be read under deny-/Users without permitting its real home.
        shutil.copytree(info['package'], package, symlinks=True)
        node = root / 'node'; shutil.copy2(info['node'], node)
        for relative, digest in info['files'].items():
            copied = package / relative
            actual = 'link:' + os.readlink(copied) if copied.is_symlink() else hashlib.sha256(copied.read_bytes()).hexdigest()
            if actual != digest:
                raise CatalogError('tool_changed_rebind_required')
        if hashlib.sha256(node.read_bytes()).hexdigest() != info['node_sha256']:
            raise CatalogError('tool_changed_rebind_required')
        home = root / 'home'; home.mkdir(); work = root / 'work'; work.mkdir(); config = home / '.gemini'; config.mkdir()
        settings = {'security': {'auth': {'selectedType': 'gemini-api-key'}},
                    'general': {'enableAutoUpdate': False, 'enableAutoUpdateNotification': False},
                    'advanced': {'autoConfigureMemory': False}, 'telemetry': {'enabled': False},
                    'experimental': {'autoMemory': False}, 'hooksConfig': {'enabled': False}, 'hooks': {}, 'mcpServers': {}}
        (config / 'settings.json').write_text(json.dumps(settings))
        conf = root / 'openssl.cnf'; conf.write_text('')
        profile = root / 'isolation.sb'; profile.write_text(isolation_profile(root, node))
        env = {'PATH': '/usr/bin:/bin', 'HOME': str(home), 'TMPDIR': str(root), 'OPENSSL_CONF': str(conf),
               'LANG': 'en_US.UTF-8', 'NO_COLOR': '1', 'GEMINI_API_KEY': PLACEHOLDER}
        prefix = ['/usr/bin/sandbox-exec', '-f', str(profile), str(node)]
        yield root, work, env, prefix, package / 'bundle/gemini.js'
    except CatalogError as error:
        if str(error) == 'gemini_catalog_cleanup_failed':
            cleanup = False  # Preserve owned files while a child might remain.
        raise
    finally:
        if cleanup:
            shutil.rmtree(tmp)


def _stop(process):
    try: process.stdin.close()
    except OSError: pass
    try: process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        if os.getpgid(process.pid) != process.pid:
            raise CatalogError('gemini_catalog_cleanup_failed')
        os.killpg(process.pid, signal.SIGTERM)
        try: process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL); process.wait(timeout=2)
    # Reap the leader and ensure its fresh group (including relaunch children)
    # is gone before deleting the owned files. No unrelated group is targeted.
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try: os.killpg(process.pid, sig)
        except ProcessLookupError: return
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            try: os.killpg(process.pid, 0)
            except ProcessLookupError: return
            time.sleep(.01)
    raise CatalogError('gemini_catalog_cleanup_failed')


def acquire(info):
    with isolated_install(info) as (root, work, env, prefix, entry):
        version = subprocess.run(prefix + [str(entry), '--version'], cwd=work, env=env,
                                 capture_output=True, text=True, timeout=5)
        if version.returncode or version.stdout.strip() != TESTED_VERSION:
            raise CatalogError('gemini_catalog_version_unsupported')
        process = subprocess.Popen(prefix + [str(entry), '--acp'], cwd=work, env=env,
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                   start_new_session=True)
        selector = selectors.DefaultSelector(); selector.register(process.stdout, selectors.EVENT_READ)
        buffer = bytearray(); deadline = time.monotonic() + 12
        def rpc(identity, method, params):
            process.stdin.write((json.dumps({'jsonrpc': '2.0', 'id': identity, 'method': method, 'params': params}) + '\n').encode()); process.stdin.flush()
            while time.monotonic() < deadline:
                while b'\n' in buffer:
                    line, _, rest = buffer.partition(b'\n'); buffer[:] = rest
                    frame = json.loads(line, object_pairs_hook=_unique)
                    if not isinstance(frame, dict) or 'method' in frame and 'id' in frame:
                        raise CatalogError('gemini_catalog_unexpected_callback')
                    if frame.get('id') == identity: return frame
                ready = selector.select(max(0, deadline - time.monotonic()))
                if not ready: raise CatalogError('gemini_catalog_timeout')
                chunk = os.read(process.stdout.fileno(), MAX_RESPONSE + 1)
                if not chunk: raise CatalogError('gemini_catalog_unavailable')
                buffer.extend(chunk)
                if len(buffer) > MAX_RESPONSE: raise CatalogError('gemini_catalog_oversized')
            raise CatalogError('gemini_catalog_timeout')
        try:
            parse_initialize(rpc(1, 'initialize', {'protocolVersion': 1, 'clientCapabilities': {}}))
            return parse_session(rpc(2, 'session/new', {'cwd': str(work), 'mcpServers': []}))
        finally:
            _stop(process); selector.close(); process.stdout.close()


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result: raise ValueError('duplicate_field')
        result[key] = value
    return result


class GeminiCatalog:
    def describe(self, candidate):
        info = installation(candidate['executable'])
        return {**candidate, 'version': TESTED_VERSION, 'executable_sha256': info['sha256']}

    def refresh(self, binding):
        try:
            if binding['tool'] != 'gemini' or binding['version'] != TESTED_VERSION:
                raise CatalogError('gemini_catalog_version_unsupported')
            info = installation(binding['executable'])
            if info['sha256'] != binding['executable_sha256']:
                raise CatalogError('tool_changed_rebind_required')
            models = acquire(info)
            if installation(binding['executable'])['sha256'] != info['sha256']:
                raise CatalogError('tool_changed_rebind_required')
            return Catalog(binding['id'], 'gemini', info['sha256'], TESTED_VERSION,
                           'gemini:acp-session-new:isolated-defaults', time.time(), models).validate()
        except CatalogError:
            raise
        except (OSError, subprocess.SubprocessError, ValueError, TypeError, KeyError):
            raise CatalogError('gemini_catalog_refresh_failed') from None
