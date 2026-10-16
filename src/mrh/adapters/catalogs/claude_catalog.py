"""CLI-only, version-scoped advertised catalog; no SDK, account or task API.

The initialize envelope was checked against official SDK 0.3.296's published
types/implementation and native Claude Code 2.1.267, and re-run against 2.1.296 (isolated initialize, 5 models
parsed, no model call). It is a compatibility
contract over the public stream-json entry, not a stable model-list API.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import tempfile
import time
import uuid

from mrh.adapters.catalogs.catalog import Catalog, CatalogError, Model, executable_hash
from mrh.routing.types import safe_model_id
from mrh.adapters.catalogs.isolation import isolation_profile

TESTED_VERSION = '2.1.296 (Claude Code)'
EFFORTS = frozenset({'low','medium','high','xhigh','max'})
MAX_RESPONSE = 262144


def parse_initialize(frame, request_id):
    """Only the matching metadata response; returned request IDs stay exact."""
    incompatible = 'claude_catalog_protocol_incompatible'
    try:
        if type(frame) is not dict or frame.get('type') != 'control_response':
            raise CatalogError(incompatible)
        response=frame.get('response')
        if type(response) is not dict or response.get('request_id') != request_id:
            raise CatalogError(incompatible)
        if response.get('subtype') == 'error':
            raise CatalogError('claude_catalog_initialize_failed')
        if response.get('subtype') != 'success' or type(response.get('response')) is not dict:
            raise CatalogError(incompatible)
        rows=response['response'].get('models')
        if type(rows) is not list or len(rows)>1024:
            raise CatalogError(incompatible)
        models=[];seen=set()
        for row in rows:
            if type(row) is not dict or not safe_model_id(row.get('value')):
                raise CatalogError(incompatible)
            label=row.get('displayName');resolved=row.get('resolvedModel')
            if not isinstance(label,str) or not 0<len(label)<=256 or row['value'] in seen:
                raise CatalogError(incompatible)
            if resolved is not None and not safe_model_id(resolved):
                raise CatalogError(incompatible)
            if 'supportsEffort' in row and type(row['supportsEffort']) is not bool:
                raise CatalogError(incompatible)
            levels=row.get('supportedEffortLevels',[])
            if (type(levels) is not list or not all(type(e) is str and e in EFFORTS for e in levels)
                    or len(set(levels))!=len(levels) or (row.get('supportsEffort') is False and levels)):
                raise CatalogError(incompatible)
            seen.add(row['value'])
            models.append(Model(row['value'],label,tuple(levels),resolved_model=resolved))
        return tuple(models)
    except (KeyError,TypeError,ValueError) as exc:
        if isinstance(exc,CatalogError):raise
        raise CatalogError(incompatible) from None





@contextmanager
def isolated_cli(executable):
    if sys.platform!='darwin' or not Path('/usr/bin/sandbox-exec').is_file():
        raise CatalogError('claude_catalog_isolation_unavailable')
    with tempfile.TemporaryDirectory(prefix='mrh-claude-',dir='/private/tmp') as tmp:
        root=Path(tmp).resolve()/'runtime';root.mkdir(mode=0o700)
        for name in ('config','cache','tmp'):(root/name).mkdir(mode=0o700)
        conf=root/'config/openssl.cnf';conf.write_text('')
        settings=root/'config/settings.json';settings.write_text('{}')
        mcp=root/'config/mcp.json';mcp.write_text('{"mcpServers":{}}')
        profile=root/'isolation.sb';profile.write_text(isolation_profile(root,executable))
        env={'PATH':'/usr/bin:/bin','HOME':str(root),'TMPDIR':str(root/'tmp'),
             'CLAUDE_CODE_TMPDIR':str(root/'tmp'),'CLAUDE_CONFIG_DIR':str(root/'config'),
             'XDG_CONFIG_HOME':str(root/'config'),'XDG_CACHE_HOME':str(root/'cache'),
             'OPENSSL_CONF':str(conf),'DISABLE_TELEMETRY':'1',
             'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC':'1','NO_COLOR':'1'}
        command=['/usr/bin/sandbox-exec','-f',str(profile),executable]
        yield root,env,command,settings,mcp


def _unique(pairs):
    value={}
    for key,item in pairs:
        if key in value:raise ValueError('duplicate key')
        value[key]=item
    return value


def _stop(proc):
    try:proc.stdin.close()
    except OSError:pass
    try:proc.wait(timeout=1)
    except subprocess.TimeoutExpired:
        for sig in (signal.SIGTERM,signal.SIGKILL):
            try:os.killpg(proc.pid,sig)
            except ProcessLookupError:break
            except PermissionError:
                # Target only the owned child if a launcher forbids group signals.
                try:proc.send_signal(sig)
                except ProcessLookupError:break
                except PermissionError:raise CatalogError('claude_catalog_cleanup_failed') from None
            try:proc.wait(timeout=1);break
            except subprocess.TimeoutExpired:continue
    proc.stdout.close()
    if proc.poll() is None:raise CatalogError('claude_catalog_cleanup_failed')
    # No descendant may outlive a completed metadata lifecycle.
    try:os.killpg(proc.pid,0)
    except ProcessLookupError:return
    except PermissionError:raise CatalogError('claude_catalog_cleanup_failed') from None
    try:os.killpg(proc.pid,signal.SIGKILL)
    except ProcessLookupError:return
    except PermissionError:raise CatalogError('claude_catalog_cleanup_failed') from None


def _models(command,root,env,settings,mcp):
    args=['-p','--bare','--verbose','--output-format','stream-json','--input-format','stream-json',
          '--setting-sources','','--settings',str(settings),'--tools','','--strict-mcp-config',
          '--mcp-config',str(mcp),'--permission-mode','dontAsk','--disable-slash-commands',
          '--no-session-persistence']
    proc=subprocess.Popen([*command,*args],cwd=root,env=env,stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,start_new_session=True)
    selector=selectors.DefaultSelector();selector.register(proc.stdout,selectors.EVENT_READ)
    request_id='mrh_'+uuid.uuid4().hex
    request={'type':'control_request','request_id':request_id,
             'request':{'subtype':'initialize','hooks':{},'sdkMcpServers':[],'agents':{},'plugins':[]}}
    try:
        proc.stdin.write((json.dumps(request)+'\n').encode());proc.stdin.flush()
        deadline=time.monotonic()+15;buffer=b'';received=0
        while time.monotonic()<deadline:
            if not selector.select(max(0,deadline-time.monotonic())):break
            data=os.read(proc.stdout.fileno(),16384)
            if not data:raise CatalogError('claude_catalog_initialize_failed')
            received+=len(data);buffer+=data
            if received>MAX_RESPONSE:raise CatalogError('claude_catalog_protocol_incompatible')
            while b'\n' in buffer:
                line,buffer=buffer.split(b'\n',1)
                frame=json.loads(line,object_pairs_hook=_unique)
                if type(frame) is not dict:raise CatalogError('claude_catalog_protocol_incompatible')
                if frame.get('type')=='control_response':
                    if type(frame.get('response')) is not dict:
                        raise CatalogError('claude_catalog_protocol_incompatible')
                    if frame['response'].get('request_id')==request_id:
                        return parse_initialize(frame,request_id)
                elif frame.get('type') not in ('system','keep_alive'):
                    raise CatalogError('claude_catalog_protocol_incompatible')
        raise CatalogError('claude_catalog_timeout')
    except CatalogError:
        raise
    except (ValueError,UnicodeError):
        raise CatalogError('claude_catalog_protocol_incompatible') from None
    finally:
        selector.close();_stop(proc)


class ClaudeCatalog:
    def describe(self,candidate):
        digest=executable_hash(candidate['executable'])
        try:
            with isolated_cli(candidate['executable']) as (root,env,command,_,_):
                result=subprocess.run([*command,'--version'],cwd=root,env=env,capture_output=True,
                                      text=True,timeout=5,start_new_session=True)
            if result.returncode:raise CatalogError('tool_unavailable')
            if result.stdout.strip()!=TESTED_VERSION:raise CatalogError('claude_catalog_version_unsupported')
            return {**candidate,'version':result.stdout.strip(),'executable_sha256':digest}
        except (OSError,subprocess.SubprocessError):
            raise CatalogError('claude_catalog_isolation_unavailable') from None

    def refresh(self,binding):
        if binding['tool']!='claude':raise CatalogError('tool_catalog_unsupported')
        if binding['version']!=TESTED_VERSION:raise CatalogError('claude_catalog_version_unsupported')
        if executable_hash(binding['executable'])!=binding['executable_sha256']:
            raise CatalogError('tool_changed_rebind_required')
        try:
            current=self.describe(binding)
            if current['version']!=binding['version']:
                raise CatalogError('tool_changed_rebind_required')
            with isolated_cli(binding['executable']) as (root,env,command,settings,mcp):
                models=_models(command,root,env,settings,mcp)
            if executable_hash(binding['executable'])!=binding['executable_sha256']:
                raise CatalogError('tool_changed_rebind_required')
            return Catalog(binding['id'],'claude',binding['executable_sha256'],binding['version'],
                           'claude:stream-json-initialize:isolated-defaults',time.time(),models).validate()
        except CatalogError:raise
        except (OSError,subprocess.SubprocessError):
            raise CatalogError('claude_catalog_initialize_failed') from None
