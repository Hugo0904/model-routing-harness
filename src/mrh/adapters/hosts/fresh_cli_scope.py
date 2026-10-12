"""Pinned fresh root CLI configuration assurance, never resolver observation.

Only native SessionStart can establish a record. Every use rechecks the live
process and launch-aged configuration sources; task JSON cannot establish it.
"""
import ctypes
import json
import os
from pathlib import Path
import stat
import subprocess

from mrh.infrastructure import owned
from mrh.adapters.hosts import codex_scope as pinned
from mrh.adapters.hosts.codex_defaults import DEFAULT_MODELS
from mrh.adapters.catalogs.catalog import executable_hash
from mrh.routing.facts import CallScope, Fact, HostSnapshot, TargetFacts
from mrh.routing.types import safe_id, safe_model_id

CONTRACT = 'official-0.159.3-fresh-root-cli-v1'
KIND = 'fresh-cli-sessions'
SYSTEM_SOURCES = tuple(path.resolve() for path in (Path('/etc/codex/config.toml'), Path('/etc/codex/requirements.toml'),
    Path('/Library/Managed Preferences/com.openai.codex.plist'),
    Path('/Library/Preferences/com.openai.codex.plist')))


def _fail(reason='scope_fresh_sources_changed'):
    raise pinned.ScopeError(reason)


def _layers(home, workspaces):
    paths = {home / 'config.toml'}
    folders = {home / 'agents'}
    excluded = set(SYSTEM_SOURCES) | {home / 'requirements.toml', home / 'managed_config.toml'}
    for workspace in workspaces:
        for parent in (workspace, *workspace.parents):
            if parent / '.codex' != home:
                paths.add(parent / '.codex/config.toml')
                folders.add(parent / '.codex/agents')
    return sorted(paths), sorted(folders), sorted(excluded)


def _inspect_config(path, *, home=False):
    config = pinned._toml(path)
    # Project layers are deliberately finite: MCP and project trust are known
    # unrelated to the derived child-default/role contract. Unknown keys fail.
    if not home and set(config) - {'mcp_servers', 'projects'}:
        _fail('scope_unsupported')
    if config.get('profile') or config.get('profiles') or config.get('config'):
        _fail('scope_unsupported')
    if config.get('model_provider') not in (None, 'openai') or config.get('model_catalog_json') is not None:
        _fail('scope_unsupported')
    providers = config.get('model_providers', {})
    if type(providers) is not dict or 'openai' in providers: _fail('scope_unsupported')
    agents = config.get('agents', {})
    if (type(agents) is not dict or agents.get('enabled', True) is not True or 'default' in agents
            or any(key in agents or key in config for key in
                   ('default_subagent_model', 'default_subagent_reasoning_effort'))):
        _fail('scope_unsupported')
    features = config.get('features', {})
    if type(features) is not dict or features.get('hooks') is False or features.get('codex_hooks') is False:
        _fail('scope_unsupported')
    references=[]
    for role in agents.values():
        if isinstance(role,dict) and 'config_file' in role:
            reference=role['config_file']
            if not isinstance(reference,str) or not reference: _fail('scope_unsupported')
            target=Path(reference)
            references.append(owned.canonical_path(target if target.is_absolute() else path.parent/target))
    return references


def _components(path, birth_ns=None):
    """No symlink traversal; directory identity detects ancestor replacement."""
    result = []
    for parent in reversed((path, *path.parents)):
        try: info = parent.lstat()
        except FileNotFoundError: break
        if stat.S_ISLNK(info.st_mode): _fail('scope_unsupported')
        if birth_ns is not None and info.st_ctime_ns >= birth_ns: _fail('scope_fresh_sources_not_predated')
        # Every check proves ancestor ctime < the same immutable birth. Its
        # identity is persisted; post-birth edits fail even after byte restore.
        result.append([str(parent), info.st_dev, info.st_ino])
    return result


def _stamp(path, birth_ns=None, *, directory=False):
    components = _components(path, birth_ns)
    try: info = path.lstat()
    except FileNotFoundError:
        ancestor = path.parent
        while not ancestor.exists(): ancestor = ancestor.parent
        info = ancestor.lstat()
        if not stat.S_ISDIR(info.st_mode): _fail('scope_unsupported')
        if birth_ns is not None and info.st_ctime_ns >= birth_ns: _fail('scope_fresh_sources_not_predated')
        return {'missing': True, 'components': components,
                'anchor': [str(ancestor), info.st_dev, info.st_ino, info.st_ctime_ns]}
    if birth_ns is not None and info.st_ctime_ns >= birth_ns: _fail('scope_fresh_sources_not_predated')
    value = {'components': components, 'stat': [info.st_dev, info.st_ino, info.st_ctime_ns]}
    if directory:
        if not stat.S_ISDIR(info.st_mode): _fail('scope_unsupported')
        value['members'] = sorted(p.name for p in path.iterdir())
    else:
        if not stat.S_ISREG(info.st_mode): _fail('scope_unsupported')
        value['sha256'] = pinned._hash(owned.read_regular(path, 1048576).hex())
    # Bound races during reads/listing, not merely mtime/content equality.
    after = path.lstat()
    if (after.st_dev, after.st_ino, after.st_ctime_ns) != tuple(value['stat']): _fail()
    return value


def configuration(home, workspaces, birth_ns=None):
    home = owned.canonical_path(home)
    workspaces = [owned.canonical_path(p) for p in workspaces]
    paths, folders, excluded = _layers(home, workspaces)
    sources = {}
    references=[]
    for path in excluded:
        if path.exists() or path.is_symlink(): _fail('scope_unsupported')
        sources[str(path)] = _stamp(path, birth_ns)
    for path in paths:
        sources[str(path)] = _stamp(path, birth_ns)
        references += _inspect_config(path, home=path == home / 'config.toml')
    def role_file(path):
        sources[str(path)] = _stamp(path,birth_ns)
        if not path.is_file(): _fail('scope_unsupported')
        name=pinned._toml(path).get('name')
        if path.stem == 'default' or (isinstance(name,str) and name.strip() == 'default'):
            _fail('scope_unsupported')
        if name is not None and not isinstance(name,str): _fail('scope_unsupported')
    for path in references: role_file(path)
    for folder in folders:
        pending=[folder]
        while pending:
            directory=pending.pop()
            if len(sources)>2048: _fail('scope_unsupported')
            sources[str(directory)] = _stamp(directory, birth_ns, directory=True)
            if directory.is_dir():
                for path in sorted(directory.iterdir()):
                    if path.is_symlink(): _fail('scope_unsupported')
                    if path.is_dir(): pending.append(path)
                    elif path.suffix == '.toml': role_file(path)
    # Recheck the complete finite set, including missing paths and directory
    # membership, after parsing. Unrelated volatile file contents stay out.
    for name, stamp in sources.items():
        if _stamp(Path(name), birth_ns, directory='members' in stamp) != stamp: _fail()
    return sources


def _process(pid):
    """Darwin kernel image/birth/argv and only the home-related environment."""
    lib = ctypes.CDLL('/usr/lib/libproc.dylib', use_errno=True)
    lib.proc_pidpath.argtypes = (ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32)
    lib.proc_pidinfo.argtypes = (ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int)
    buffer = ctypes.create_string_buffer(4096)
    size = lib.proc_pidpath(pid, buffer, len(buffer))
    if size <= 0: _fail('scope_host_unverified')
    image = buffer.value.decode()
    # proc_bsdinfo: 12 uint32, comm[16], name[32], 6 uint32, 2 uint64.
    bsd = ctypes.create_string_buffer(136)
    if lib.proc_pidinfo(pid, 3, 0, bsd, len(bsd)) != len(bsd): _fail('scope_host_unverified')
    raw = bsd.raw
    parent = int.from_bytes(raw[16:20], 'little')
    birth = int.from_bytes(raw[120:128], 'little') * 10**9 + int.from_bytes(raw[128:136], 'little') * 1000
    if birth <= 0: _fail('scope_host_unverified')
    libc = ctypes.CDLL(None, use_errno=True)
    libc.sysctl.argtypes = (ctypes.POINTER(ctypes.c_int), ctypes.c_uint, ctypes.c_void_p,
                           ctypes.POINTER(ctypes.c_size_t), ctypes.c_void_p, ctypes.c_size_t)
    mib = (ctypes.c_int * 3)(1, 49, pid)  # CTL_KERN / KERN_PROCARGS2
    capacity = ctypes.c_size_t(0)
    if libc.sysctl(mib, 3, None, ctypes.byref(capacity), None, 0) or not 0 < capacity.value <= 2097152:
        _fail('scope_host_unverified')
    data = ctypes.create_string_buffer(capacity.value)
    if libc.sysctl(mib, 3, data, ctypes.byref(capacity), None, 0): _fail('scope_host_unverified')
    data = data.raw[:capacity.value]
    argc = int.from_bytes(data[:4], 'little', signed=True)
    if not 0 < argc <= 256: _fail('scope_host_unverified')
    offset = data.index(b'\0', 4) + 1
    while offset < len(data) and data[offset] == 0: offset += 1
    parts = data[offset:].split(b'\0')
    argv = [part.decode() for part in parts[:argc]]
    env = {}
    for part in parts[argc:]:
        key, sep, value = part.partition(b'=')
        if sep and key in (b'CODEX_HOME', b'HOME'): env[key.decode()] = value.decode()
    return {'pid': pid, 'birth_ns': birth, 'image': image, 'parent': parent, 'argv': argv, 'home_env': env}


def _startup(argv):
    if not pinned.supported_startup(argv) or 'app-server' in argv or '--no-daemon' not in argv: _fail('scope_host_unverified')
    cd = None
    for index, arg in enumerate(argv[1:], 1):
        if arg in ('-C', '--cd'): cd = argv[index + 1]
        elif arg.startswith('--cd='): cd = arg[5:]
        elif arg.startswith('-C') and arg != '-C': cd = arg[2:]
    if cd is not None: return str(owned.canonical_path(cd))
    return None


def native_identity(scope, binding):
    pid = os.getppid()
    launcher = str(Path(binding).parent / 'launcher.py')
    launcher_seen = False
    for _ in range(8):
        if pid <= 1: break
        row = _process(pid)
        if row['image'] == scope['binary']:
            if not launcher_seen: _fail('scope_host_unverified')
            cd = _startup(row['argv'])
            run = subprocess.run(['/usr/sbin/lsof', '-a', '-p', str(pid), '-d', 'cwd', '-Fn'],
                                 capture_output=True, text=True, timeout=3)
            cwd = [line[1:] for line in run.stdout.splitlines() if line.startswith('n')]
            if run.returncode or len(cwd) != 1: _fail('scope_host_unverified')
            cwd = str(owned.canonical_path(cwd[0]))
            home = row['home_env'].get('CODEX_HOME')
            if home is None:
                base = row['home_env'].get('HOME')
                if not base: _fail('scope_host_unverified')
                home = str(Path(base) / '.codex')
            if str(owned.canonical_path(home)) != scope['codex_home']: _fail('scope_host_unverified')
            return {'pid': pid, 'birth_ns': row['birth_ns'], 'binary': row['image'],
                    'startup_cwd': cd or cwd, 'codex_home': home}
        # Tool-execution servers or arbitrary intermediaries never establish a
        # native Hook chain. The supervisor must be in this direct ancestry.
        if row['image'] not in (scope['python'], '/bin/sh', '/bin/bash', '/bin/zsh'): _fail('scope_host_unverified')
        if launcher in row['argv']: launcher_seen = True
        pid = row['parent']
    _fail('scope_host_unverified')


def prepare(binary, home, workspace, sessions, python):
    binary = owned.canonical_path(binary)
    if executable_hash(binary) != pinned.BINARY_SHA256: _fail('scope_unsupported')
    home = owned.canonical_path(home); workspace = owned.canonical_path(workspace)
    configuration(home, [workspace])
    return {'contract': CONTRACT, 'binary': str(binary), 'binary_sha256': pinned.BINARY_SHA256,
            'version': pinned.VERSION, 'codex_home': str(home), 'workspace': str(workspace),
            'sessions': str(owned.canonical_path(sessions)), 'python': str(owned.canonical_path(python)),
            'models': DEFAULT_MODELS, 'assurance': 'fresh-root-cli-configuration'}


def _static(scope):
    if (scope.get('contract') != CONTRACT or scope.get('binary_sha256') != pinned.BINARY_SHA256
            or executable_hash(scope['binary']) != pinned.BINARY_SHA256 or scope.get('models') != DEFAULT_MODELS): _fail('scope_unsupported')
    configuration(scope['codex_home'], [scope['workspace']])


def _record_path(scope, session):
    if not safe_id(session): _fail('scope_fresh_start_missing')
    root = owned.initialize(owned.canonical_path(scope['sessions']), KIND)
    return root, root / (pinned._hash(session) + '.json')


def session_start(scope, event, binding):
    _static(scope)
    root, path = _record_path(scope, event.get('session_id'))
    with owned.locked(root, KIND):
        old = json.loads(owned.read_regular(path, 1048576), object_pairs_hook=owned._unique) if path.exists() else None
        try:
            identity = native_identity(scope, binding)
            if event.get('source') != 'startup' or event.get('hook_event_name') != 'SessionStart': _fail('scope_fresh_lifecycle')
            if str(owned.canonical_path(event.get('cwd'))) != identity['startup_cwd']: _fail('scope_host_unverified')
            sources = configuration(scope['codex_home'], [identity['startup_cwd']], identity['birth_ns'])
            value = {'session_id': event['session_id'], 'status': 'valid', 'identity': identity, 'sources': sources}
            if old is not None and old != value: _fail('scope_fresh_lifecycle')
            if old is None: owned.replace_owned(path, (json.dumps(value, sort_keys=True) + '\n').encode(), limit=1048576)
        except (pinned.ScopeError, OSError, ValueError) as exc:
            reason = str(exc) if isinstance(exc, pinned.ScopeError) else 'scope_host_unverified'
            value = {'session_id': event['session_id'], 'status': 'invalid', 'reason': reason}
            owned.replace_owned(path, (json.dumps(value, sort_keys=True) + '\n').encode(), limit=1048576)
            raise pinned.ScopeError(reason) from None
    return {}


def check(scope, event=None, *, binding=None, synthetic=False):
    _static(scope)
    if event is None:
        return {'contract': CONTRACT, 'workspace': scope['workspace'], 'assurance': 'fresh-root-cli-configuration',
                'active_session': 'unverified; requires native SessionStart', 'native_invocation': 'unverified'}
    if binding is None: _fail('scope_host_unverified')
    root, path = _record_path(scope, event.get('session_id'))
    with owned.locked(root, KIND):
        if not path.exists(): _fail('scope_fresh_start_missing')
        value = json.loads(owned.read_regular(path, 1048576), object_pairs_hook=owned._unique)
        if value.get('status') != 'valid' or value.get('session_id') != event['session_id']: _fail('scope_fresh_lifecycle')
        identity = native_identity(scope, binding)
        if identity != value['identity']: _fail('scope_host_unverified')
        cwd = str(owned.canonical_path(event.get('cwd')))
        sources = configuration(scope['codex_home'], [identity['startup_cwd'], cwd], identity['birth_ns'])
        if any(sources.get(name) != stamp for name, stamp in value['sources'].items()): _fail()
    observed = event.get('model')
    if not safe_model_id(observed): _fail('scope_host_unverified')
    call = CallScope.for_hook(event)
    known = lambda value: Fact.configured(call, value, 'fresh-root-cli-configuration')
    facts = HostSnapshot(call, synthetic,
        parent_model=Fact.observed(call, observed, 'canonical-hook-model'),
        workspace=Fact.observed(call, cwd, 'canonical-hook-cwd'), role_protection=known('unprotected'),
        deny_supported=known(True), rewrite_supported=known(True), original_model=known(observed),
        targets=tuple(TargetFacts(name, known(True), known(tuple(model['efforts'])), Fact())
                      for name, model in scope['models'].items()))
    # Rechecking uses this actual Hook's identity/cwd/model, not caller policy.
    return pinned.ConfigurationScope(facts, pinned._hash(sources), assurance='fresh-root-cli-configuration',
        descriptor={**scope, '_binding': str(binding)}, recheck_event={key: event[key] for key in
            ('session_id', 'turn_id', 'tool_use_id', 'hook_event_name', 'tool_name', 'cwd', 'model') if key in event})
