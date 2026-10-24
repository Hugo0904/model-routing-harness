"""Hook diagnostics: bounded producers, private per-user collection and control.

Stage/serializer/privacy/cleanup observation originates from accepted DIAG22 r2;
UDP delivery is best effort and does not participate in Hook policy or output.
"""

import ast

import builtins

import hashlib

import json

import os

from pathlib import Path

import secrets

import socket

import stat

import sys

import time

from mrh.infrastructure import owned, locations

CONFIG_KIND = 'hook-diagnostics'
LOG_KIND = 'hook-observation'
MAX_LOG_BYTES = 1024 * 1024
LOG_NAMES = ('events-0.jsonl', 'events-1.jsonl', 'events-2.jsonl')
RECEIVER_CODE = ('import sys;from pathlib import Path;sys.path.insert(0,sys.argv[1]);'
                 'from mrh.infrastructure.hook_diagnostics import receive;'
                 'raise SystemExit(receive(Path(sys.argv[2]),Path(sys.argv[3])))')


def _windows_reader():
    # Embed the existing native ownership/no-follow reader, not an MRH import.
    # It is loaded lazily only when an endpoint actually exists on Windows.
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


def producer(endpoint, *, child=False, windows=False):
    """Bound stdlib-only UDP producer, no Hook retry/ACK/process/file writes."""
    endpoint = owned.canonical_path(endpoint)
    support = '''
def _diag_read_endpoint():
    try:
        from pathlib import Path
        import stat
        path=Path(DIAG_ENDPOINT)
        if not path.exists():return None
        parent=path.parent
        if parent.resolve()!=parent or path.is_symlink():return None
        if os.name=='nt':
            native={}
            exec(DIAG_WINDOWS_READER,native)
            native['assert_safe'](parent,directory=True,private=True)
            native['assert_safe'](path,private=True)
            fd=native['open_regular'](path)
        else:
            info=parent.stat()
            if info.st_uid!=os.getuid() or info.st_mode&0o077:return None
            fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        try:
            info=os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1:return None
            if os.name!='nt' and (info.st_uid!=os.getuid() or info.st_mode&0o077):return None
            data=os.read(fd,2049)
        finally:os.close(fd)
        if len(data)>2048:return None
        value=json.loads(data)
        if type(value) is not dict or set(value)!={'version','host','port','capability'}:return None
        if value['version']!=1 or type(value['version']) is not int or value['host']!='127.0.0.1':return None
        if type(value['port']) is not int or not 1<=value['port']<=65535:return None
        token=value['capability']
        if not isinstance(token,str) or len(token)!=64 or any(c not in '0123456789abcdef' for c in token):return None
        return value
    except BaseException:return None
_diag_endpoint=_diag_read_endpoint()
_diag_platform=(sys.argv[DIAG_PLATFORM_INDEX] if len(sys.argv)>DIAG_PLATFORM_INDEX else 'codex')
def _diag_send(frame):
    try:
        endpoint=_diag_endpoint
        if endpoint is None or _diag_platform not in ('codex','claude'):return
        payload=json.dumps({'version':1,'platform':_diag_platform,'capability':endpoint['capability'],'frame':frame},separators=(',',':')).encode('ascii')
        if len(payload)>512:return
        import socket
        channel=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
        try:
            channel.setblocking(False)
            channel.sendto(payload,('127.0.0.1',endpoint['port']))
        finally:channel.close()
    except BaseException:pass
'''.replace('DIAG_ENDPOINT', repr(str(endpoint))).replace('DIAG_WINDOWS_READER', repr(_windows_reader() if windows else '')).replace('DIAG_PLATFORM_INDEX', '2' if child else '1')
    return COMMON + support

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


def _state(root):
    if not root.exists():
        return None
    owned.verify(root, CONFIG_KIND)
    if os.name != 'nt' and root.stat().st_mode & 0o077:
        raise owned.OwnedError('diagnostics_config_not_private')
    path = root / 'state.json'
    if not path.exists():
        return None
    value = json.loads(owned.read_regular(path, 65536), object_pairs_hook=owned._unique)
    if (type(value) is not dict or set(value) != {'version', 'enabled', 'runtime_root', 'command'}
            or value['version'] != 1 or type(value['enabled']) is not bool
            or type(value['command']) is not list or not value['command']
            or not all(isinstance(v, str) and '\x00' not in v for v in value['command'])):
        raise owned.OwnedError('diagnostics_state_invalid')
    owned.canonical_path(value['runtime_root'])
    return value


def _endpoint(root):
    path = root / 'endpoint.json'
    if os.name == 'nt':
        from mrh.adapters.platforms.windows import assert_safe
        assert_safe(path, private=True)
    elif path.lstat().st_mode & 0o077:
        raise owned.OwnedError('diagnostics_endpoint_not_private')
    value = json.loads(owned.read_regular(root / 'endpoint.json', 2048), object_pairs_hook=owned._unique)
    if (type(value) is not dict or set(value) != {'version', 'host', 'port', 'capability'}
            or type(value['version']) is not int or value['version'] != 1 or value['host'] != '127.0.0.1'
            or type(value['port']) is not int or not 1 <= value['port'] <= 65535
            or not isinstance(value['capability'], str) or len(value['capability']) != 64
            or any(c not in '0123456789abcdef' for c in value['capability'])):
        raise owned.OwnedError('diagnostics_endpoint_invalid')
    return value


def _service(root):
    if sys.platform == 'darwin':
        from mrh.adapters.platforms.macos_diagnostics import Service
    elif sys.platform == 'win32':
        from mrh.adapters.platforms.windows_diagnostics import Service
    else:
        raise owned.OwnedError('diagnostics_login_platform_unsupported')
    return Service(root)


def _request(root, operation='status', timeout=.3):
    endpoint = _endpoint(root)
    nonce = secrets.token_hex(16)
    payload = _json({'version': 1, 'capability': endpoint['capability'], 'operation': operation, 'nonce': nonce})
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as channel:
        channel.settimeout(timeout)
        channel.sendto(payload, ('127.0.0.1', endpoint['port']))
        raw, address = channel.recvfrom(513)
    result = json.loads(raw)
    if len(raw) > 512 or address != ('127.0.0.1', endpoint['port']) or result.get('nonce') != nonce or result.get('version') != 1:
        raise owned.OwnedError('diagnostics_readiness_invalid')
    return result


def status(*, root=None, runtime=None, service=None):
    root = owned.canonical_path(root or config_root())
    state = _state(root)
    enabled = bool(state and state['enabled'])
    runtime = Path(state['runtime_root']) if state else runtime
    result = {'enabled': enabled, 'collector': 'off' if not enabled else 'degraded',
              'ready': False, 'login': {'registered': False, 'running': False},
              'log_path': str(log_root(runtime)), 'config_path': str(root)}
    if root.exists():
        try:
            result['login'] = (service or _service(root)).inspect()
            if enabled:
                answer = _request(root)
                result['ready'] = answer.get('ready') is True and result['login']['registered']
                result['collector'] = 'ready' if result['ready'] else 'degraded'
                if answer.get('degraded'):
                    result['reason'] = 'diagnostics_log_unavailable'
        except (OSError, ValueError, KeyError):
            if enabled:
                result['reason'] = 'diagnostics_receiver_unavailable'
    return result


def receiver_command(root, runtime, *, archive=None, python=None):
    archive = owned.canonical_path(Path(archive or sys.argv[0]).resolve())
    if archive.name != 'mrh.pyz' or not archive.is_file():
        raise owned.OwnedError('diagnostics_installed_entry_required')
    owned.read_regular(archive, 16_000_000)
    python = owned.canonical_path(Path(python or sys.executable).resolve())
    return [str(python), '-I', '-B', '-c', RECEIVER_CODE, str(archive), str(root), str(runtime)]


def _remove_endpoint(root):
    path = root / 'endpoint.json'
    if path.exists() or path.is_symlink():
        owned.read_regular(path, 2048)
        path.unlink()


def control(action, *, root=None, runtime=None, service=None, command=None):
    root = owned.canonical_path(root or config_root())
    runtime = owned.canonical_path(runtime or locations.runtime_root())
    if action == 'status':
        return status(root=root, runtime=runtime, service=service)
    if action not in ('on', 'off', 'clear'):
        raise owned.OwnedError('diagnostics_action_invalid')
    if not root.exists() and action != 'on':
        return status(root=root, runtime=runtime, service=service)
    _initialize(root, CONFIG_KIND)
    service = service or _service(root)
    with owned.locked(root, CONFIG_KIND):
        previous = _state(root)
        # Native identity must be verified BEFORE desired state or endpoint edits.
        service.inspect()
        if action == 'clear':
            if previous and previous['enabled']:
                raise owned.OwnedError('diagnostics_clear_requires_off')
            area = log_root(Path(previous['runtime_root']) if previous else runtime)
            removed = []
            if area.exists():
                with owned.locked(area, LOG_KIND, blocking=False):
                    for name in LOG_NAMES:
                        path = area / name
                        if path.exists() or path.is_symlink():
                            owned.read_regular(path, MAX_LOG_BYTES)
                            path.unlink()
                            removed.append(name)
            return {**status(root=root, runtime=runtime, service=service), 'removed_logs': removed}
        if action == 'off':
            if previous:
                owned.replace_owned(root / 'state.json', _json({**previous, 'enabled': False}))
            _remove_endpoint(root)
        else:
            current = status(root=root, runtime=runtime, service=service)
            command = command or receiver_command(root, runtime)
            if current['ready'] and previous['command'] == command and previous['runtime_root'] == str(runtime):
                return current
            _remove_endpoint(root)
            proposed = {'version': 1, 'enabled': True, 'runtime_root': str(runtime), 'command': command}
            try:
                service.install(command)
                owned.replace_owned(root / 'state.json', _json(proposed))
            except (OSError, ValueError):
                # Installation has not started a receiver yet. Restore only
                # this diagnostic state; routing profiles are never opened.
                if previous:
                    owned.replace_owned(root / 'state.json', _json(previous))
                    service.install(previous['command'])
                    if previous['enabled']:
                        service.start()
                else:
                    service.remove()
                raise
    if action == 'off':
        service.remove()
        return status(root=root, runtime=runtime, service=service)
    try:
        service.start()
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            current = status(root=root, runtime=runtime, service=service)
            if current['ready']:
                return current
            time.sleep(.1)
        raise owned.OwnedError('diagnostics_readiness_failed')
    except (OSError, ValueError):
        with owned.locked(root, CONFIG_KIND):
            owned.replace_owned(root / 'state.json', _json({**proposed, 'enabled': False}))
            _remove_endpoint(root)
        service.remove()
        if previous:
            with owned.locked(root, CONFIG_KIND):
                owned.replace_owned(root / 'state.json', _json(previous))
                service.install(previous['command'])
            if previous['enabled']:
                service.start()
        raise


def after_install(archive, python):
    """Post-pointer-switch best effort; a diagnostic failure cannot undo routing."""
    root = config_root()
    try:
        state = _state(root)
        if state and state['enabled']:
            command = receiver_command(root, Path(state['runtime_root']), archive=archive, python=python)
            return control('on', root=root, runtime=Path(state['runtime_root']), command=command)
        return {'enabled': False, 'collector': 'off', 'ready': False}
    except (OSError, ValueError):
        return {'enabled': True, 'collector': 'degraded', 'ready': False, 'reason': 'diagnostics_restart_failed'}


def _prune(area, now):
    for name in LOG_NAMES:
        path = area / name
        if path.exists() or path.is_symlink():
            owned.read_regular(path, MAX_LOG_BYTES)
            if now - path.stat().st_mtime > 7 * 86400:
                path.unlink()


def _append(area, frame, platform):
    from datetime import datetime, timezone
    now = time.time()
    _prune(area, now)
    row = {'received_at': datetime.fromtimestamp(now, timezone.utc).isoformat(),
           'version': 1, 'platform': platform, **frame}
    data = _json(row)
    current = area / LOG_NAMES[0]
    prior = owned.read_regular(current, MAX_LOG_BYTES) if current.exists() else b''
    if len(prior) + len(data) > MAX_LOG_BYTES:
        last = area / LOG_NAMES[-1]
        if last.exists():
            owned.read_regular(last, MAX_LOG_BYTES)
            last.unlink()
        for source, target in ((LOG_NAMES[1], LOG_NAMES[2]), (LOG_NAMES[0], LOG_NAMES[1])):
            source, target = area / source, area / target
            if source.exists():
                owned.read_regular(source, MAX_LOG_BYTES)
                os.replace(source, target)
        prior = b''
    # Only the receiver holding the exclusive writer lock reaches this write.
    owned.replace_owned(current, prior + data, limit=MAX_LOG_BYTES)


def _remove_self_checks(area):
    removed = 0
    for name in LOG_NAMES:
        path = area / name
        if not path.exists():
            continue
        original = owned.read_regular(path, MAX_LOG_BYTES)
        kept = []
        for line in original.splitlines(keepends=True):
            if json.loads(line).get('stage') == 'self_check':
                removed += 1
            else:
                kept.append(line)
        if len(kept) != len(original.splitlines()):
            if kept:
                owned.replace_owned(path, b''.join(kept), limit=MAX_LOG_BYTES)
            else:
                path.unlink()
    return removed


def receive(root, runtime):
    """Long-lived receiver only. All waiting/filesystem work stays off Hook."""
    root, runtime = owned.canonical_path(root), owned.canonical_path(runtime)
    state = _state(root)
    if not state or not state['enabled'] or state['runtime_root'] != str(runtime):
        return 0
    area = _initialize(log_root(runtime), LOG_KIND)
    token = secrets.token_hex(32)
    try:
        with owned.locked(area, LOG_KIND, blocking=False), socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as channel:
            _prune(area, time.time())
            channel.bind(('127.0.0.1', 0))
            channel.settimeout(.3)
            endpoint = {'version': 1, 'host': '127.0.0.1', 'port': channel.getsockname()[1], 'capability': token}
            with owned.locked(root, CONFIG_KIND):
                state = _state(root)
                if not state or not state['enabled']:
                    return 0
                owned.replace_owned(root / 'endpoint.json', _json(endpoint), limit=2048)
            degraded = False
            while True:
                state = _state(root)
                if not state or not state['enabled'] or state['runtime_root'] != str(runtime):
                    break
                try:
                    raw, address = channel.recvfrom(513)
                except socket.timeout:
                    continue
                try:
                    if address[0] != '127.0.0.1' or len(raw) > 512:
                        continue
                    value = json.loads(raw, object_pairs_hook=owned._unique)
                    if (type(value) is not dict or value.get('version') != 1
                            or type(value.get('version')) is not int
                            or not isinstance(value.get('capability'), str)
                            or not secrets.compare_digest(value['capability'], token)):
                        continue
                    if set(value) == {'version', 'capability', 'operation', 'nonce'}:
                        nonce = value['nonce']
                        if not isinstance(nonce, str) or len(nonce) != 32 or any(c not in '0123456789abcdef' for c in nonce):
                            continue
                        if value['operation'] == 'remove_self_check':
                            removed = _remove_self_checks(area)
                        elif value['operation'] == 'status':
                            removed = 0
                        else:
                            continue
                        channel.sendto(_json({'version': 1, 'nonce': nonce, 'ready': not degraded,
                                              'degraded': degraded, 'removed_self_checks': removed}), address)
                    elif set(value) == {'version', 'capability', 'platform', 'frame'}:
                        if value['platform'] not in ('codex', 'claude'):
                            continue
                        frames = parse_frames(_json(value['frame']))
                        if len(frames) != 1:
                            continue
                        try:
                            _append(area, frames[0], value['platform'])
                            degraded = False
                        except (OSError, ValueError):
                            degraded = True
                except (OSError, ValueError, TypeError, KeyError):
                    # Invalid payloads are never logged, printed or echoed.
                    continue
    except (OSError, ValueError):
        return 2
    finally:
        # A retiring receiver must never delete its successor's endpoint.
        try:
            with owned.locked(root, CONFIG_KIND):
                if _endpoint(root)['capability'] == token:
                    _remove_endpoint(root)
        except (OSError, ValueError):
            pass
    return 0


def self_check(*, root=None, runtime=None, platform='codex'):
    """Explicit adoption proof, safely labelled, then removed by its writer."""
    import subprocess
    root = owned.canonical_path(root or config_root())
    state = _state(root)
    runtime = Path(state['runtime_root']) if state else runtime
    if not state or not state['enabled'] or platform not in ('codex', 'claude'):
        raise owned.OwnedError('diagnostics_self_check_requires_on')
    code = producer(root / 'endpoint.json', windows=os.name == 'nt') + '\n_diag_emit("self_check")\n'
    result = subprocess.run([sys.executable, '-I', '-B', '-c', code, platform], capture_output=True, timeout=5)
    if result.returncode or result.stdout or result.stderr:
        raise owned.OwnedError('diagnostics_self_check_producer_failed')
    area = log_root(runtime)
    deadline = time.monotonic() + 5
    found = []
    while time.monotonic() < deadline:
        found = [json.loads(line) for name in LOG_NAMES if (area / name).exists()
                 for line in owned.read_regular(area / name, MAX_LOG_BYTES).splitlines()
                 if json.loads(line).get('stage') == 'self_check' and json.loads(line).get('platform') == platform]
        if found:
            break
        time.sleep(.05)
    if not found:
        raise owned.OwnedError('diagnostics_self_check_not_received')
    answer = _request(root, 'remove_self_check', timeout=2)
    if answer.get('removed_self_checks', 0) < 1:
        raise owned.OwnedError('diagnostics_self_check_cleanup_failed')
    return {'received': True, 'sample': found[-1], 'marker_removed': True, 'natural_failure': False}
