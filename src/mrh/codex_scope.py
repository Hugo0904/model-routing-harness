"""Finite official-host scope assurance, distinct from same-call observations.

Only package code inspects this scope. No tool/task JSON can declare it valid.
Per-turn/session config overrides that the Hook cannot observe are excluded
from this contract; they are never asserted to have been observed.
"""
from dataclasses import dataclass
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import tomllib

from . import owned
from .catalog import executable_hash
from .facts import CallScope, Fact, HostSnapshot, TargetFacts
from .types import safe_id, safe_model_id
from .codex_defaults import DEFAULT_MODELS

VERSION = 'codex-cli 0.159.3'
BINARY_SHA256 = '4d210f7c5a18fd0386434df23b5bdbb8c0e7257d3e8a2b30b0769c8bbe99a878'
CONTRACT = 'official-0.159.3-local-stdio-config-pinned'


class ScopeError(ValueError):
    pass


@dataclass(frozen=True)
class ConfigurationScope:
    facts: HostSnapshot
    fingerprint: str | None = None
    error: str | None = None
    assurance: str = 'inspected-configuration'
    descriptor: dict | None = None

    def __getattr__(self, name):return getattr(self.facts, name)

    def validation_reason(self, proposal):
        if self.descriptor is not None:
            try:check(self.descriptor)
            except (ScopeError,OSError,ValueError):return 'scope_changed'
        return self.error or self.facts.validation_reason(proposal, configuration=True)


def _hash(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def _toml(path):
    if not path.exists():return {}
    try:return tomllib.loads(owned.read_regular(path,1048576).decode())
    except (OSError,ValueError):raise ScopeError('scope_unsupported') from None


def _configuration(home, workspace):
    # This finite initial contract rejects additional/managed layers instead of
    # attempting to guess their precedence. It never reads auth/state/transcript.
    excluded=[Path('/etc/codex/config.toml'),Path('/etc/codex/requirements.toml'),
              Path('/Library/Managed Preferences/com.openai.codex.plist'),
              Path('/Library/Preferences/com.openai.codex.plist'),
              home/'requirements.toml',home/'managed_config.toml']
    ancestors=[workspace,*workspace.parents]
    excluded += [p/'.codex/config.toml' for p in ancestors if p/'.codex' != home]
    if any(p.exists() or p.is_symlink() for p in excluded):raise ScopeError('scope_unsupported')
    config=_toml(home/'config.toml')
    if config.get('profile') or config.get('profiles') or config.get('config'):
        raise ScopeError('scope_unsupported')
    agents=config.get('agents',{})
    if type(agents) is not dict or agents.get('enabled',True) is not True or 'default' in agents:
        raise ScopeError('scope_unsupported')
    # Standalone files can override the built-in fallback by declared name.
    for folder in [home/'agents',*[p/'.codex/agents' for p in ancestors]]:
        if folder.is_symlink():raise ScopeError('scope_unsupported')
        if folder.is_dir():
            for file in folder.glob('*.toml'):
                if file.stem=='default' or _toml(file).get('name')=='default':
                    raise ScopeError('scope_unsupported')
    fields={k:config.get(k) for k in ('model','model_reasoning_effort','model_provider','model_catalog_json')}
    fields['agents']={k:agents.get(k) for k in ('default_subagent_model','default_subagent_reasoning_effort')}
    provider=config.get('model_providers',{}).get(config.get('model_provider'),{})
    fields['provider_fingerprint']=_hash({k:provider.get(k) for k in ('name','base_url','wire_api','requires_openai_auth','env_key')})
    fields['features']={k:config.get('features',{}).get(k) for k in ('hooks','codex_hooks','multi_agent','code_mode')}
    if fields['features']['hooks'] is False or fields['features']['codex_hooks'] is False:
        raise ScopeError('scope_unsupported')
    return fields


def _catalog_file(path):
    try:
        data=owned.read_regular(owned.canonical_path(path),1048576)
        rows=json.loads(data,object_pairs_hook=owned._unique)['models']
        if type(rows) is not list or not 0<len(rows)<=1024:raise ValueError()
        models={}
        for row in rows:
            name=row['slug'];efforts=tuple(x['effort'] for x in row['supported_reasoning_levels'])
            default=row['default_reasoning_level']
            if not safe_model_id(name) or name in models or not all(safe_id(e) for e in efforts) or default not in efforts:raise ValueError()
            models[name]={'efforts':list(efforts),'default_effort':default}
        return models,hashlib.sha256(data).hexdigest()
    except (OSError,ValueError,KeyError,TypeError):raise ScopeError('scope_unsupported') from None


def prepare(binary, home, workspace):
    binary=owned.canonical_path(binary);home=owned.canonical_path(home);workspace=owned.canonical_path(workspace)
    if executable_hash(binary)!=BINARY_SHA256:raise ScopeError('scope_unsupported')
    with tempfile.TemporaryDirectory(prefix='mrh-scope-version-') as tmp:
        version=subprocess.run([str(binary),'--version'],cwd=tmp,env={'HOME':tmp,'CODEX_HOME':tmp,'PATH':os.defpath},
                               capture_output=True,text=True,timeout=5)
    if version.returncode or version.stdout.strip()!=VERSION:raise ScopeError('scope_unsupported')
    fields=_configuration(home,workspace);path=fields['model_catalog_json']
    if path is not None:
        models,catalog_hash=_catalog_file(path)
    else:
        models=DEFAULT_MODELS
        catalog_hash=None
    return {'contract':CONTRACT,'binary':str(binary),'binary_sha256':BINARY_SHA256,'version':VERSION,
            'mode':'local-cli-or-app-server-stdio','codex_home':str(home),'workspace':str(workspace),
            'configuration':fields,'configuration_fingerprint':_hash(fields),'catalog_sha256':catalog_hash,'models':models,
            'excluded_overrides':'session/turn model-effort-config and dynamic role overrides; not observed by Hook'}


def _native_parent(scope):
    pid=os.getppid()
    for _ in range(8):
        if pid<=1:break
        try:
            run=subprocess.run(['/bin/ps','-p',str(pid),'-o','ppid=','-o','comm=','-o','args='],
                               capture_output=True,text=True,timeout=2)
            fields=run.stdout.strip().split(None,2)
            if run.returncode or len(fields)!=3:break
            parent=int(fields[0]);argv=shlex.split(fields[2])
            # macOS ps comm can be a basename/title, not the executable path.
            # Use the public kernel process-image API for exact identity.
            buffer=ctypes.create_string_buffer(4096)
            lib=ctypes.CDLL('/usr/lib/libproc.dylib')
            lib.proc_pidpath.argtypes=(ctypes.c_int,ctypes.c_void_p,ctypes.c_uint32)
            lib.proc_pidpath.restype=ctypes.c_int
            size=lib.proc_pidpath(pid,buffer,len(buffer))
            command=buffer.value.decode() if size>0 else None
            if command==scope['binary']:
                if (not argv or any(x in argv for x in ('-c','--config','-p','--profile','-m','--model','--enable','--disable',
                                                      'resume','fork','cloud','--dangerously-bypass-hook-trust'))):
                    raise ScopeError('scope_host_unverified')
                if 'app-server' in argv and ('--listen' not in argv or argv[argv.index('--listen')+1]!='stdio://'):
                    raise ScopeError('scope_host_unverified')
                return
            pid=parent
        except (OSError,ValueError,IndexError,subprocess.SubprocessError):break
    raise ScopeError('scope_host_unverified')


def check(scope, event=None, *, native=True, synthetic=False):
    if not isinstance(scope,dict) or scope.get('contract')!=CONTRACT:raise ScopeError('scope_unsupported')
    if scope.get('binary_sha256')!=BINARY_SHA256 or executable_hash(scope['binary'])!=BINARY_SHA256:
        raise ScopeError('scope_changed')
    home=owned.canonical_path(scope['codex_home']);workspace=owned.canonical_path(scope['workspace'])
    fields=_configuration(home,workspace)
    if _hash(fields)!=scope['configuration_fingerprint']:raise ScopeError('scope_changed')
    if fields['model_catalog_json'] is not None:
        models,digest=_catalog_file(fields['model_catalog_json'])
        if digest!=scope['catalog_sha256'] or models!=scope['models']:raise ScopeError('scope_changed')
    elif scope['models']!=DEFAULT_MODELS:raise ScopeError('scope_changed')
    if event is None:return {'contract':CONTRACT,'configuration_fingerprint':scope['configuration_fingerprint'],
                            'workspace':str(workspace),'assurance':'inspected-configuration','native_invocation':'unverified until Hook execution'}
    actual_home=Path(os.environ.get('CODEX_HOME',Path.home()/'.codex')).resolve()
    if actual_home!=home or owned.canonical_path(event.get('cwd'))!=workspace:raise ScopeError('scope_changed')
    if native:_native_parent(scope)
    parent=fields['model'];observed=event.get('model')
    if parent and observed!=parent:raise ScopeError('scope_changed')
    call=CallScope.for_hook(event);known=lambda v:Fact.configured(call,v,'official-scoped-configuration')
    baseline=fields['agents']['default_subagent_model'] or parent
    effort=fields['agents']['default_subagent_reasoning_effort']
    if effort is None:
        effort=(scope['models'].get(baseline,{}).get('default_effort') if fields['agents']['default_subagent_model']
                else fields['model_reasoning_effort'])
    targets=tuple(TargetFacts(name,known(True),known(tuple(m['efforts'])),Fact()) for name,m in scope['models'].items())
    # available=True here means legal advertised request, not account/provider
    # availability. Configuration basis remains explicit in every such field.
    facts=HostSnapshot(call,synthetic,
        parent_model=Fact.observed(call,observed,'canonical-hook-model') if safe_model_id(observed) else Fact(),
        workspace=Fact.observed(call,str(workspace),'canonical-hook-cwd'),role_protection=known('unprotected'),
        deny_supported=known(True),rewrite_supported=known(True),
        original_model=known(baseline) if safe_model_id(baseline) else Fact(),
        original_effort=known(effort) if safe_id(effort) else Fact(),targets=targets)
    return ConfigurationScope(facts,scope['configuration_fingerprint'],descriptor=scope)


def rejected(event, reason, synthetic=False):
    return ConfigurationScope(HostSnapshot(CallScope.for_hook(event),synthetic),error=reason)
