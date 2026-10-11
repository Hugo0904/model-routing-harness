"""Catalog acquisition, never policy mutation or same-call capability evidence.

The Codex adapter queries a fresh credential-free public app-server. Its scope
is the installed tool's advertised picker, not a signed-in account. There is no
public unique account/workspace binding in the inspected account/read contract.
"""
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import queue
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time

from mrh.routing.types import safe_id, safe_model_id


class CatalogError(ValueError):
    pass


@dataclass(frozen=True)
class Model:
    id: str
    label: str
    efforts: tuple = ()
    state: str = "available"
    retirement_ref: str | None = None
    resolved_model: str | None = None


@dataclass(frozen=True)
class Catalog:
    binding_id: str
    tool: str
    scope: str
    version: str
    source: str
    fetched_at: float
    models: tuple
    assurance: str = "tool-advertised"
    complete: bool = True

    def validate(self):
        if not all(safe_id(v, 256) for v in (self.binding_id, self.tool, self.scope, self.source)):
            raise CatalogError("catalog_invalid")
        if not isinstance(self.version, str) or not 0 < len(self.version) <= 128:
            raise CatalogError("catalog_invalid")
        if type(self.fetched_at) not in (float, int) or not 0 < self.fetched_at < float('inf'):
            raise CatalogError("catalog_invalid")
        if self.assurance not in ("tool-advertised", "account-confirmed", "synthetic") or self.complete is not True:
            raise CatalogError("catalog_partial")
        if type(self.models) is not tuple or len(self.models) > 1024:
            raise CatalogError("catalog_invalid")
        names = set()
        for m in self.models:
            if type(m) is not Model or not safe_model_id(m.id) or m.id in names or not isinstance(m.label, str) or len(m.label) > 256:
                raise CatalogError("catalog_invalid")
            if m.resolved_model is not None and not safe_model_id(m.resolved_model):
                raise CatalogError("catalog_invalid")
            names.add(m.id)
            if type(m.efforts) is not tuple or len(m.efforts) > 32 or len(set(m.efforts)) != len(m.efforts) or not all(safe_id(e) for e in m.efforts):
                raise CatalogError("catalog_invalid")
            if m.state not in ("available", "unavailable", "retired") or (m.state == "retired" and not safe_id(m.retirement_ref, 256)):
                raise CatalogError("catalog_invalid")
        return self

    def public(self):
        return json.loads(json.dumps(asdict(self.validate()), allow_nan=False))

    @classmethod
    def from_dict(cls, value):
        try:
            copied = dict(value)
            copied['models'] = tuple(Model(**{**m, 'efforts': tuple(m['efforts'])}) for m in copied['models'])
            return cls(**copied).validate()
        except (KeyError, TypeError, ValueError):
            raise CatalogError("catalog_invalid") from None

    def option(self, model, effort=None):
        return next((m for m in self.models if m.id == model and m.state == 'available'
                     and (effort is None or effort in m.efforts)), None)


def executable_hash(path):
    p = Path(path)
    info = p.stat()
    if not p.is_absolute() or p != p.resolve() or not stat.S_ISREG(info.st_mode) or info.st_mode & 0o022 or not os.access(p, os.X_OK):
        raise CatalogError('tool_untrusted')
    return hashlib.sha256(p.read_bytes()).hexdigest()


def installation_hash(tool, path):
    if tool == 'gemini':
        from mrh.adapters.catalogs.gemini_catalog import installation
        return installation(path)['sha256']
    return executable_hash(path)


def discover():
    """Only named tools in installation locations; no workspace traversal."""
    candidates = []
    trusted = [Path('/usr'), Path('/opt/homebrew'), Path('/Applications'),
               Path.home()/'.nvm', Path.home()/'.local/share']
    for tool in ('codex', 'claude', 'gemini'):
        found = shutil.which(tool)
        if not found:
            continue
        p = Path(found).resolve()
        if not any(p.is_relative_to(root) for root in trusted):
            continue
        if tool == 'codex' and p.name == 'codex.js':
            # The public npm package locates the native executable this way.
            package = p.parent.parent
            try:
                if json.loads((package/'package.json').read_text())['name'] != '@openai/codex':
                    continue
                native = list(package.glob('node_modules/@openai/codex-*/vendor/*/bin/codex'))
                if len(native) != 1:
                    continue
                p = native[0].resolve()
            except (OSError, ValueError, KeyError):
                continue
        candidates.append({'tool': tool, 'executable': str(p), 'label': tool.title(),
                           'supported': tool == 'codex' or (tool in ('claude', 'gemini') and sys.platform == 'darwin')})
    if os.name == 'posix':
        p = Path('/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex')
        if p.is_file() and not any(x['executable'] == str(p.resolve()) for x in candidates):
            candidates.append({'tool': 'codex', 'executable': str(p.resolve()),
                               'label': 'Codex Desktop bundled CLI', 'supported': True})
    return candidates


class CodexCatalog:
    """Supported public RPC, no login, real home, credentials or model request."""
    def refresh(self, binding):
        try:
            return self._refresh(binding)
        except CatalogError:
            raise
        except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
            raise CatalogError('catalog_refresh_failed') from None

    def _refresh(self, binding):
        if binding['tool'] != 'codex':
            raise CatalogError('tool_catalog_unsupported')
        if executable_hash(binding['executable']) != binding['executable_sha256']:
            raise CatalogError('tool_changed_rebind_required')
        with tempfile.TemporaryDirectory(prefix='mrh-catalog-') as tmp:
            root = Path(tmp).resolve(); home = root/'home'; home.mkdir()
            env = {'PATH': os.defpath, 'HOME': str(home), 'CODEX_HOME': str(home),
                   'TMPDIR': str(root), 'LANG': 'en_US.UTF-8',
                   'HTTP_PROXY': 'http://127.0.0.1:9', 'HTTPS_PROXY': 'http://127.0.0.1:9',
                   'ALL_PROXY': 'http://127.0.0.1:9', 'NO_PROXY': ''}
            version = subprocess.run([binding['executable'], '--version'], cwd=root, env=env,
                                     capture_output=True, text=True, timeout=5)
            if version.returncode or version.stdout.strip() != binding['version']:
                raise CatalogError('tool_changed_rebind_required')
            proc = subprocess.Popen([binding['executable'], 'app-server', '--listen', 'stdio://'],
                                    cwd=root, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL)
            inbox = queue.Queue(); deadline = time.monotonic()+10
            def collect():
                for line in iter(lambda: proc.stdout.readline(262145), b''):
                    try:
                        if len(line) > 262144:
                            raise ValueError()
                        inbox.put(json.loads(line))
                    except (ValueError, UnicodeError):
                        inbox.put({'error': True})
            threading.Thread(target=collect, daemon=True).start()
            serial = 0
            def rpc(method, params):
                nonlocal serial
                serial += 1
                proc.stdin.write((json.dumps({'id': serial, 'method': method, 'params': params})+'\n').encode());proc.stdin.flush()
                while time.monotonic() < deadline:
                    item = inbox.get(timeout=max(.01, deadline-time.monotonic()))
                    if item.get('id') == serial:
                        if 'error' in item or not isinstance(item.get('result'), dict):
                            raise CatalogError('catalog_refresh_failed')
                        return item['result']
                raise CatalogError('catalog_refresh_failed')
            try:
                rpc('initialize', {'clientInfo': {'name': 'mrh_model_picker', 'version': '1'}})
                proc.stdin.write(b'{"method":"initialized"}\n');proc.stdin.flush()
                account = rpc('account/read', {'refreshToken': False})
                if account.get('account') is not None:
                    raise CatalogError('isolated_account_unexpected')
                models = []; cursor = None; cursors = set()
                for _ in range(64):
                    params = {'limit': 100, 'includeHidden': False}
                    if cursor is not None: params['cursor'] = cursor
                    page = rpc('model/list', params)
                    if type(page.get('data')) is not list or 'nextCursor' not in page:
                        raise CatalogError('catalog_partial')
                    for row in page['data']:
                        # `model`, not the opaque picker `id`, is the request ID.
                        efforts = tuple(e['reasoningEffort'] for e in row['supportedReasoningEfforts'])
                        models.append(Model(row['model'], row['displayName'], efforts))
                    cursor = page['nextCursor']
                    if cursor is None: break
                    if not isinstance(cursor, str) or cursor in cursors or len(cursor) > 1024:
                        raise CatalogError('catalog_partial')
                    cursors.add(cursor)
                else: raise CatalogError('catalog_partial')
                return Catalog(binding['id'], 'codex', binding['executable_sha256'], binding['version'],
                               'codex:model-list:isolated-defaults', time.time(), tuple(models)).validate()
            except CatalogError:
                raise
            except (OSError, queue.Empty, KeyError, TypeError, ValueError):
                raise CatalogError('catalog_refresh_failed') from None
            finally:
                try: proc.stdin.close()
                except OSError: pass
                try: proc.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    proc.kill();proc.wait(timeout=2)
                proc.stdout.close()


def describe_tool(candidate):
    if candidate['tool'] == 'gemini':
        from mrh.adapters.catalogs.gemini_catalog import GeminiCatalog
        return GeminiCatalog().describe(candidate)
    if candidate['tool'] == 'claude':
        from mrh.adapters.catalogs.claude_catalog import ClaudeCatalog
        return ClaudeCatalog().describe(candidate)
    if candidate['tool'] != 'codex':
        raise CatalogError('tool_catalog_unsupported')
    digest = executable_hash(candidate['executable'])
    with tempfile.TemporaryDirectory(prefix='mrh-tool-version-') as tmp:
        env = {'PATH': os.defpath, 'HOME': tmp, 'CODEX_HOME': tmp, 'TMPDIR': tmp, 'LANG': 'en_US.UTF-8'}
        result = subprocess.run([candidate['executable'], '--version'], capture_output=True, text=True,
                                cwd=tmp, env=env, timeout=5)
    if result.returncode or not result.stdout.strip().startswith('codex-cli '):
        raise CatalogError('tool_unavailable')
    return {**candidate, 'version': result.stdout.strip(), 'executable_sha256': digest}


class ToolCatalog:
    """Tool dispatch only; consumers and core do not know provider transports."""
    def refresh(self, binding):
        if binding['tool'] == 'gemini':
            from mrh.adapters.catalogs.gemini_catalog import GeminiCatalog
            return GeminiCatalog().refresh(binding)
        if binding['tool'] == 'codex':
            return CodexCatalog().refresh(binding)
        if binding['tool'] == 'claude':
            from mrh.adapters.catalogs.claude_catalog import ClaudeCatalog
            return ClaudeCatalog().refresh(binding)
        raise CatalogError('tool_catalog_unsupported')
