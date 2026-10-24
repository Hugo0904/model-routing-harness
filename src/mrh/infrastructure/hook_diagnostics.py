"""Best-effort direct Hook records; no receiver, network or login startup."""
import ast
import json
import os
from pathlib import Path
import stat
import sys
import time
from mrh.infrastructure import owned, locations

CONFIG_KIND = 'hook-diagnostics'
LOG_KIND = 'hook-observation'
RECORD_BYTES = 512
RECORD_FILES = {'codex': 'latest-codex.json', 'claude': 'latest-claude.json'}


MAX_FRAME = 192

STAGES = frozenset(('self_check', 'input', 'binding', 'integrity', 'spawn', 'control',
                    'deadline', 'cleanup', 'result', 'child_gate', 'child_setup',
                    'child_import', 'child_activate', 'child_runtime_import', 'child_run'))

EXCEPTIONS = frozenset(('', 'Exception', 'BaseException', 'ImportError',
                        'ModuleNotFoundError', 'RuntimeError', 'ValueError',
                        'TypeError', 'KeyError', 'OSError', 'PermissionError',
                        'FileNotFoundError', 'TimeoutError', 'SystemExit',
                        'KeyboardInterrupt', 'AssertionError'))

COMMON = '''
import os,sys,json,time,builtins
_diag_fd=2
_diag_sent=False
_diag_epoch=time.monotonic()
_diag_stage="input"
class _DiagQuiet:
    encoding="utf-8"
    errors="replace"
    closed=False
    @property
    def buffer(self):return self
    def write(self,value):return len(value)
    def flush(self):pass
    def fileno(self):return 2
    def isatty(self):return False
    def writable(self):return True
    def close(self):pass
sys.stderr=_DiagQuiet()
sys.__stderr__=sys.stderr
def _diag_emit(stage,error=None,rc=None):
    global _diag_sent
    if _diag_sent:return
    _diag_sent=True
    try:
        names=DIAG_EXCEPTION_NAMES
        kind=type(error)
        name=kind.__name__ if any(kind is getattr(builtins,n,None) for n in names if n) else ("Exception" if error is not None else "")
        winerror=getattr(error,"winerror",None) if name in ("OSError","PermissionError","FileNotFoundError") else None
        winerror=winerror if type(winerror) is int and -2147483648<=winerror<=2147483647 else None
        rc=rc if type(rc) is int and -2147483648<=rc<=2147483647 else None
        elapsed=min(99999999,max(0,int((time.monotonic()-globals().get("started",_diag_epoch))*1000)))
        value={"stage":stage if stage in DIAG_STAGE_NAMES else "result","exception":name,"winerror":winerror,"child_rc":rc,"elapsed_ms":elapsed}
        frame=(json.dumps(value,separators=(",",":"),ensure_ascii=True)+"\\n").encode("ascii")
        if len(frame)<=192:_diag_send(value)
    except BaseException:pass
'''.replace('DIAG_EXCEPTION_NAMES', repr(tuple(sorted(EXCEPTIONS)))).replace(
    'DIAG_STAGE_NAMES', repr(tuple(sorted(STAGES))))

CHILD_SETUP = '''
_diag_stage="child_setup"
try:
    _diag_fd=os.dup(2)
    _diag_null=os.open(os.devnull,os.O_WRONLY)
    try:os.dup2(_diag_null,2)
    finally:os.close(_diag_null)
except BaseException as _diag_error:
    _diag_emit(_diag_stage,_diag_error)
    raise
'''

def _windows_reader():
    # Embed the existing native ownership/no-follow reader, not an MRH import.
    # It is loaded lazily only for a direct-file attempt on Windows.
    from importlib import resources
    text = resources.files('mrh').joinpath('adapters/platforms/windows.py').read_text()
    tree = ast.parse(text)
    definitions = {'api', 'checked', 'sid_text', 'current_sid', 'ACL', 'assert_safe', 'open_regular'}
    imports = 'import ctypes as c\nfrom ctypes import wintypes as w\nimport msvcrt,os,stat\nfrom pathlib import Path\n'
    nodes = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in definitions:
            nodes.append(ast.get_source_segment(text, node))
        elif isinstance(node, ast.Assign) and node.lineno < next(n.lineno for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'checked'):
            nodes.append(ast.get_source_segment(text, node))
    return imports + '\n\n'.join(nodes)

def _once(source, old, new):
    if source.count(old) != 1:
        raise ValueError('isolated_template_mismatch')
    return source.replace(old, new, 1)

def _guard(body, *, finalize=False):
    source = 'try:\n' + ''.join('    ' + line + '\n' for line in body.splitlines())
    source += '''except SystemExit as _diag_error:
    if _diag_error.code is not None and not (type(_diag_error.code) is int and _diag_error.code==0):
        _diag_emit(_diag_stage,_diag_error,_diag_error.code)
    raise
except BaseException as _diag_error:
    _diag_emit(_diag_stage,_diag_error)
    raise
'''
    if finalize:
        source += '''finally:
    if _diag_fd!=2:
        try:os.close(_diag_fd)
        except OSError:pass
'''
    return source

def launcher(original, endpoint, *, windows=False):
    common = producer(endpoint, windows=windows)
    child_common = producer(endpoint, child=True, windows=windows)
    source = original.decode()
    # The Windows gate and application run in the same Python process. Install
    # the restricted sink before its existing one-byte Job-release read as well.
    if windows:
        tree = ast.parse(source)
        node = next(n for n in tree.body if isinstance(n, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == '_PYTHON_GATE' for t in n.targets))
        gate = ast.literal_eval(node.value)
        guarded = child_common + CHILD_SETUP + '_diag_stage="child_gate"\n' + _guard(gate)
        segment = ast.get_source_segment(source, node)
        source = _once(source, segment, '_PYTHON_GATE = ' + repr(guarded))
    # Install only Python-level suppression in the supervisor. Its fd2 remains
    # the original outer-runner pipe, also inherited by the child. Managed child
    # fd2 is redirected to the OS null device before importing runtime code;
    # its private non-inheritable duplicate emits only the bounded safe record.
    marker = 'from pathlib import Path\nevent=None'
    source = _once(source, marker, 'from pathlib import Path\n' + common + '\nevent=None')
    tree = ast.parse(source)
    assignment = next(n for n in ast.walk(tree) if isinstance(n, ast.Assign)
                      and any(isinstance(t, ast.Name) and t.id == 'code' for t in n.targets))
    code = ast.literal_eval(assignment.value).replace(';', '\n')
    for text, stage in (
        ('from mrh.infrastructure.execution import activate_editable', 'child_import'),
        ('activate_editable(sys.argv[7],sys.argv[8]) if sys.argv[8] else None', 'child_activate'),
        ('from mrh.application.advisory_runtime import run', 'child_runtime_import'),
        ('raise SystemExit(run(', 'child_run'),
    ):
        code = _once(code, text, '_diag_stage=' + repr(stage) + '\n' + text)
    child = ('' if windows else child_common + CHILD_SETUP) + _guard('started=float(sys.argv[4])\n' + code, finalize=True)
    segment = ast.get_source_segment(source, assignment)
    source = _once(source, segment, 'code=' + repr(child))
    source = _once(source, 'stderr=subprocess.DEVNULL,', 'stderr=None,')
    for old, new in (
        ('    data=sys.stdin.buffer.read(1048577)', '    _diag_stage="input"\n    data=sys.stdin.buffer.read(1048577)'),
        ('    binding=json.loads(', '    _diag_stage="binding"\n    binding=json.loads('),
        ('    reason="runtime_integrity"', '    _diag_stage="integrity"\n    reason="runtime_integrity"'),
        ('        process=None\n', '        process=None\n        _diag_stage="spawn"\n'),
        ('            pending=data;', '            _diag_stage="control"\n            pending=data;'),
        ('        reason="runtime_load"', '        _diag_stage="result"\n        reason="runtime_load"'),
        ('except Exception:\n    print(json.dumps(failed()',
         'except Exception as _diag_error:\n    _diag_emit("deadline" if type(_diag_error) is TimeoutError else _diag_stage,_diag_error,getattr(locals().get("process"),"returncode",None))\n    print(json.dumps(failed()'),
    ):
        source = _once(source, old, new)
    # A successful finally must not replace the original spawn/control stage.
    # Keep cleanup errors dominant, exactly as in the original finally: observe
    # them and re-raise unchanged; restore the previous stage only on success.
    tree = ast.parse(source)
    owner = next(n for n in ast.walk(tree) if isinstance(n, ast.Try)
                 and any(isinstance(v, ast.Assign)
                         and any(isinstance(t, ast.Name) and t.id == 'args' for t in v.targets)
                         for v in n.body))
    first, last = owner.finalbody[0].lineno, owner.finalbody[-1].end_lineno
    lines = source.splitlines(keepends=True)
    cleanup = ''.join('    ' + line for line in lines[first-1:last])
    observed = ('            _diag_previous_stage=_diag_stage\n'
                '            _diag_stage="cleanup"\n'
                '            try:\n' + cleanup +
                '            except BaseException:\n'
                '                raise\n'
                '            else:\n'
                '                _diag_stage=_diag_previous_stage\n')
    source = ''.join(lines[:first-1]) + observed + ''.join(lines[last:])
    compile(source, '<isolated-diagnostic-launcher>', 'exec')
    return source.encode()

def parse_frames(raw):
    """Runner accepts only the same exact, bounded vocabulary; never logs raw."""
    if len(raw) > 2 * MAX_FRAME:
        raise ValueError('diagnostic_wire_size')
    records = []
    for line in raw.splitlines(keepends=True):
        if len(line) > MAX_FRAME or not line.endswith(b'\n'):
            raise ValueError('diagnostic_frame_size')
        value = json.loads(line)
        if not isinstance(value, dict) or set(value) != {'stage', 'exception', 'winerror', 'child_rc', 'elapsed_ms'}:
            raise ValueError('diagnostic_fields')
        if value['stage'] not in STAGES or value['exception'] not in EXCEPTIONS:
            raise ValueError('diagnostic_enum')
        if type(value['elapsed_ms']) is not int or not 0 <= value['elapsed_ms'] <= 99999999:
            raise ValueError('diagnostic_elapsed')
        for field in ('winerror', 'child_rc'):
            if value[field] is not None and (type(value[field]) is not int or not -2147483648 <= value[field] <= 2147483647):
                raise ValueError('diagnostic_integer')
        records.append(value)
    child = [v for v in records if v['stage'].startswith('child_')]
    if len(child) > 1 or len(records) - len(child) > 1:
        raise ValueError('diagnostic_emitter_count')
    return records

def config_root():
    return locations.default_config_root() / 'hook-diagnostics'

def log_root(runtime=None):
    return owned.canonical_path(runtime or locations.runtime_root()) / 'diagnostics/hook-observation'

def _json(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode()

def _initialize(path, kind):
    path = owned.canonical_path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    return owned.initialize(path, kind)

def _service(root):
    if sys.platform == 'darwin':
        from mrh.adapters.platforms.macos_diagnostics import Service
    elif sys.platform == 'win32':
        from mrh.adapters.platforms.windows_diagnostics import Service
    else:
        raise owned.OwnedError('diagnostics_login_platform_unsupported')
    return Service(root)

def _remove_endpoint(root):
    path = root / 'endpoint.json'
    if path.exists() or path.is_symlink():
        owned.read_regular(path, 2048)
        path.unlink()


def _sink(config_path, *, child=False, windows=False):
    """At most one regular-file overwrite attempt; no create/lock/retry."""
    config_path = owned.canonical_path(config_path)
    source = '''
_diag_native=None
_diag_platform=sys.argv[DIAG_INDEX] if len(sys.argv)>DIAG_INDEX else 'codex'
def _diag_open(path,writing=False):
    global _diag_native
    import stat
    parent=path.parent
    if parent.resolve()!=parent or path.is_symlink():raise ValueError()
    if os.name=='nt':
        if _diag_native is None:
            _diag_native={}
            exec(DIAG_NATIVE,_diag_native)
        _diag_native['assert_safe'](parent,directory=True,private=True)
        _diag_native['assert_safe'](path,private=True)
        fd=_diag_native['open_regular'](path,os.O_WRONLY if writing else os.O_RDONLY)
    else:
        info=parent.stat()
        if info.st_uid!=os.getuid() or info.st_mode&0o077:raise ValueError()
        fd=os.open(path,(os.O_WRONLY if writing else os.O_RDONLY)|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1:raise ValueError()
        if os.name!='nt' and (info.st_uid!=os.getuid() or info.st_mode&0o077 or (writing and not info.st_mode&0o200)):raise ValueError()
        if writing and info.st_size!=512:raise ValueError()
        return fd
    except BaseException:
        os.close(fd)
        raise
def _diag_read(path,limit):
    fd=_diag_open(path)
    try:data=os.read(fd,limit+1)
    finally:os.close(fd)
    if len(data)>limit:raise ValueError()
    return json.loads(data)
def _diag_send(frame):
    try:
        from pathlib import Path
        if _diag_platform not in ('codex','claude'):return
        if type(frame) is not dict or set(frame)!={'stage','exception','winerror','child_rc','elapsed_ms'}:return
        if frame['stage'] not in DIAG_STAGES or frame['exception'] not in DIAG_EXCEPTIONS:return
        if type(frame['elapsed_ms']) is not int or not 0<=frame['elapsed_ms']<=99999999:return
        if any(frame[k] is not None and (type(frame[k]) is not int or not -2147483648<=frame[k]<=2147483647) for k in ('winerror','child_rc')):return
        if len((json.dumps(frame,separators=(',',':'))+'\\n').encode('ascii'))>192:return
        config=_diag_read(Path(DIAG_CONFIG),2048)
        if type(config) is not dict or set(config)!={'version','enabled','runtime_root'}:return
        if type(config['version']) is not int or config['version']!=2 or config['enabled'] is not True:return
        area=Path(config['runtime_root'])
        if not area.is_absolute() or area.resolve()!=area:return
        area=area/'diagnostics/hook-observation'
        if _diag_read(area/'.mrh-owner.json',256)!={'schema_version':1,'owner':'org.model-routing-harness','kind':'hook-observation'}:return
        path=area/('latest-'+_diag_platform+'.json')
        value={'recorded_at':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'version':2,'platform':_diag_platform,**frame}
        data=json.dumps(value,separators=(',',':'),ensure_ascii=True).encode('ascii')
        if len(data)>511:return
        fd=_diag_open(path,True)
        try:written=os.write(fd,data.ljust(511,b' ')+b'\\n')
        finally:os.close(fd)
        if written==512:return str(path)
    except BaseException:pass
'''
    return source.replace('DIAG_INDEX', '2' if child else '1').replace('DIAG_NATIVE', repr(_windows_reader() if windows else '')).replace('DIAG_STAGES', repr(tuple(sorted(STAGES)))).replace('DIAG_EXCEPTIONS', repr(tuple(sorted(EXCEPTIONS)))).replace('DIAG_CONFIG', repr(str(config_path)))


def producer(config_path, *, child=False, windows=False):
    return COMMON + _sink(config_path, child=child, windows=windows)


def _state(root):
    if not root.exists():
        return None
    owned.verify(root, CONFIG_KIND)
    if os.name != 'nt' and root.stat().st_mode & 0o077:
        raise owned.OwnedError('diagnostics_config_not_private')
    path = root / 'state.json'
    if not path.exists():
        return None
    value = json.loads(owned.read_regular(path), object_pairs_hook=owned._unique)
    version = value.get('version') if type(value) is dict else None
    keys = {'version', 'enabled', 'runtime_root'} | ({'command'} if version == 1 else set())
    if (type(version) is not int or version not in (1, 2) or set(value) != keys
            or type(value['enabled']) is not bool):
        raise owned.OwnedError('diagnostics_state_invalid')
    owned.canonical_path(value['runtime_root'])
    if version == 1 and (not isinstance(value['command'], list) or not value['command']
                         or not all(isinstance(v, str) and '\x00' not in v for v in value['command'])):
        raise owned.OwnedError('diagnostics_state_invalid')
    return value


def _record_file(path):
    data = owned.read_regular(path, RECORD_BYTES)
    if len(data) != RECORD_BYTES or not path.stat().st_mode & 0o200 or os.name != 'nt' and path.stat().st_mode & 0o077:
        raise owned.OwnedError('diagnostics_record_unsafe')
    if os.name == 'nt':
        from mrh.adapters.platforms.windows import assert_safe
        assert_safe(path, private=True)
    return data


def status(*, root=None, runtime=None, service=None):
    root = owned.canonical_path(root or config_root())
    state = _state(root)
    runtime = Path(state['runtime_root']) if state else runtime
    area = log_root(runtime)
    migration = bool(state and state['version'] == 1 or (root / 'service.json').exists())
    result = {'mode': 'direct', 'enabled': bool(state and state['enabled']),
              'resident': False, 'login': {'registered': False, 'running': False},
              'ready': False, 'log_path': str(area),
              'record_paths': {p: str(area / name) for p, name in RECORD_FILES.items()},
              'config_path': str(root), 'migration_required': migration}
    if migration:
        result['reason'] = 'diagnostics_legacy_removal_required'
        result['resident'] = None
        result['login'] = {'registered': None, 'running': None}
        return result
    if result['enabled']:
        try:
            owned.verify(area, LOG_KIND)
            for name in RECORD_FILES.values():
                _record_file(area / name)
            result['ready'] = True
        except (OSError, ValueError):
            result['reason'] = 'diagnostics_record_configuration_unavailable'
    return result


def control(action, *, root=None, runtime=None, service=None):
    root = owned.canonical_path(root or config_root())
    state = _state(root)
    runtime = owned.canonical_path(runtime or (state['runtime_root'] if state else locations.runtime_root()))
    if action == 'status':
        return status(root=root, runtime=runtime, service=service)
    if action not in ('on', 'off', 'clear'):
        raise owned.OwnedError('diagnostics_action_invalid')
    if not root.exists() and action != 'on':
        return status(root=root, runtime=runtime, service=service)
    _initialize(root, CONFIG_KIND)
    # Existing configuration lock is nonblocking; Hook records never take it.
    with owned.locked(root, CONFIG_KIND, blocking=False):
        state = _state(root)
        if state and state['version'] == 1 or (root / 'service.json').exists():
            (service or _service(root)).remove()
        _remove_endpoint(root)
        enabled = action == 'on' or action == 'clear' and bool(state and state['enabled'])
        if action == 'clear' and enabled:
            raise owned.OwnedError('diagnostics_clear_requires_off')
        area = log_root(runtime)
        if action == 'on':
            _initialize(area, LOG_KIND)
            for name in RECORD_FILES.values():
                path = area / name
                if path.exists() or path.is_symlink():
                    _record_file(path)
                else:
                    owned.replace_owned(path, b' ' * 511 + b'\n', limit=RECORD_BYTES)
        elif action == 'clear' and area.exists():
            owned.verify(area, LOG_KIND)
            for name in RECORD_FILES.values():
                path = area / name
                if path.exists() or path.is_symlink():
                    _record_file(path)
                    owned.replace_owned(path, b' ' * 511 + b'\n', limit=RECORD_BYTES)
        owned.replace_owned(root / 'state.json', _json({'version': 2, 'enabled': enabled,
                                                       'runtime_root': str(runtime)}), limit=2048)
    return status(root=root, runtime=runtime)


def after_install(archive=None, python=None):
    """Migrate old owned startup even when off; never create a receiver."""
    try:
        state = _state(config_root())
        if state or (config_root() / 'service.json').exists():
            return control('on' if state and state['enabled'] else 'off',
                           runtime=Path(state['runtime_root']) if state else None)
        return status()
    except (OSError, ValueError):
        return {'mode': 'direct', 'ready': False, 'resident': None,
                'reason': 'diagnostics_migration_or_configuration_unavailable'}


def self_check(*, root=None, runtime=None, platform='codex'):
    """One same-process direct attempt; no retry or guaranteed delivery."""
    root = owned.canonical_path(root or config_root())
    if platform not in RECORD_FILES:
        raise owned.OwnedError('diagnostics_platform_invalid')
    namespace = {'os': os, 'json': json, 'time': time, 'sys': sys}
    exec(_sink(root / 'state.json', windows=os.name == 'nt'), namespace)
    namespace['_diag_platform'] = platform
    path = namespace['_diag_send']({'stage': 'self_check', 'exception': '', 'winerror': None,
                                    'child_rc': None, 'elapsed_ms': 0})
    if not path:
        return {'received': False, 'marker_removed': False, 'mode': 'direct', 'natural_failure': False}
    path = Path(path)
    try:
        sample = json.loads(_record_file(path))
        if sample.get('stage') != 'self_check':
            return {'received': False, 'marker_removed': False, 'mode': 'direct', 'natural_failure': False}
        # Concurrent overwrites/loss are explicitly permitted, including here.
        fd = namespace['_diag_open'](path, True)
        try:os.write(fd, b' ' * 511 + b'\n')
        finally:os.close(fd)
        return {'received': True, 'sample': sample, 'marker_removed': True,
                'mode': 'direct', 'natural_failure': False}
    except (OSError, ValueError):
        return {'received': False, 'marker_removed': False, 'mode': 'direct', 'natural_failure': False}
