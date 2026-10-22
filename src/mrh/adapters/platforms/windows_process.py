"""Owned process trees: a Python gate enters a kill-on-close Job before exec.

This file is stdlib-only and is embedded verbatim in the independent Windows
hook supervisor. Never put MRH imports or credential handling in this module.
"""
import ctypes
from ctypes import wintypes
import json
import os
import subprocess
import sys
import time
import threading
import tempfile
from pathlib import Path
from contextlib import contextmanager

_kernel = ctypes.WinDLL('kernel32', use_last_error=True)

def _api(name, args, result=wintypes.BOOL):
    f = getattr(_kernel, name); f.argtypes = args; f.restype = result
    return f

_close = _api('CloseHandle', [wintypes.HANDLE])
_create = _api('CreateJobObjectW', [ctypes.c_void_p, wintypes.LPCWSTR], wintypes.HANDLE)
_set = _api('SetInformationJobObject', [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD])
_assign = _api('AssignProcessToJobObject', [wintypes.HANDLE, wintypes.HANDLE])
_terminate = _api('TerminateJobObject', [wintypes.HANDLE, wintypes.UINT])
_query = _api('QueryInformationJobObject', [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p])

class _BasicLimit(ctypes.Structure):
    _fields_ = [('process_time', ctypes.c_longlong), ('job_time', ctypes.c_longlong),
                ('flags', wintypes.DWORD), ('min_working', ctypes.c_size_t), ('max_working', ctypes.c_size_t),
                ('active_limit', wintypes.DWORD), ('affinity', ctypes.c_size_t),
                ('priority', wintypes.DWORD), ('scheduling', wintypes.DWORD)]

class _IO(ctypes.Structure):
    _fields_ = [(n, ctypes.c_ulonglong) for n in ('read_ops', 'write_ops', 'other_ops', 'read_bytes', 'write_bytes', 'other_bytes')]

class _ExtendedLimit(ctypes.Structure):
    _fields_ = [('basic', _BasicLimit), ('io', _IO), ('process_memory', ctypes.c_size_t),
                ('job_memory', ctypes.c_size_t), ('peak_process', ctypes.c_size_t), ('peak_job', ctypes.c_size_t)]

class _Accounting(ctypes.Structure):
    _fields_ = [('times', ctypes.c_longlong * 4), ('page_faults', wintypes.DWORD),
                ('total', wintypes.DWORD), ('active', wintypes.DWORD), ('terminated', wintypes.DWORD)]

class Job:
    def __init__(self):
        self._lock = threading.Lock()
        self.handle = _create(None, None)
        if not self.handle: raise OSError('windows_job_create_failed')
        limits = _ExtendedLimit(); limits.basic.flags = 0x2000
        if not _set(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            _close(self.handle); self.handle = None
            raise OSError('windows_job_limits_failed')

    def assign(self, process):
        if not _assign(self.handle, int(process._handle)):
            raise OSError('windows_job_assignment_failed')

    def close(self):
        with self._lock:
            return self._close_locked()

    def _close_locked(self):
        if self.handle is None: return
        try:
            if not _terminate(self.handle, 125): raise OSError('windows_job_terminate_failed')
            deadline = time.monotonic() + 2
            while True:
                stats = _Accounting()
                if not _query(self.handle, 1, ctypes.byref(stats), ctypes.sizeof(stats), None):
                    raise OSError('windows_job_readback_failed')
                if not stats.active: break
                if time.monotonic() > deadline: raise OSError('windows_job_cleanup_timeout')
                time.sleep(.01)
        finally:
            _close(self.handle); self.handle = None

_GATE = '''import os,sys,json,subprocess
if os.read(sys.stdin.fileno(),1)!=b"G":raise SystemExit(125)
p=subprocess.Popen(json.loads(sys.argv[1]),stdin=sys.stdin,stdout=sys.stdout,stderr=sys.stderr,close_fds=False)
raise SystemExit(p.wait())
'''

_PYTHON_GATE = '''import os
if os.read(0,1)!=b"G":raise SystemExit(125)
'''

def popen(argv, **kwargs):
    """Caller must call finish even after normal exit, to reap descendants.

    Child startup is gated until Job assignment succeeds; an assignment failure
    aborts before the target CLI can run. No global process inventory or kill.
    """
    return _popen_gate([sys.executable, '-I', '-B', '-c', _GATE, json.dumps([str(x) for x in argv])], kwargs)


def popen_python(python, code, args, **kwargs):
    """Run bound Hook Python code in the gate itself, after Job assignment.

    The caller already verifies the bound interpreter/runtime. A second Python
    process spends most of the local Hook deadline merely starting on Windows.
    Only the stdlib gate runs before assignment; application code follows the
    same private one-byte release protocol as the generic process gate.
    """
    return _popen_gate([str(python), '-I', '-B', '-X', 'utf8', '-c', _PYTHON_GATE + code,
                        *[str(value) for value in args]], kwargs)


def _popen_gate(command, kwargs):
    job = Job(); process = None
    try:
        kwargs.pop('start_new_session', None)
        kwargs.setdefault('stdin', subprocess.PIPE)
        process = subprocess.Popen(command, **kwargs)
        job.assign(process)
        process._mrh_job = job
        process.stdin.write('G' if kwargs.get('text') or kwargs.get('encoding') else b'G')
        process.stdin.flush()
        # A descendant may inherit stdout after its parent exits. Reap it at
        # root exit, before communicate waits forever for that inherited pipe.
        def reap_on_exit():
            process.wait()
            try: job.close()
            except OSError: process._mrh_cleanup_failed = True
        process._mrh_watcher = threading.Thread(target=reap_on_exit, daemon=True)
        process._mrh_watcher.start()
        return process
    except BaseException:
        if process is not None:
            process.kill(); process.wait(timeout=2)
        job.close()
        raise

def finish(process):
    try: process._mrh_job.close()
    finally:
        process.wait(timeout=2)
        watcher = getattr(process, '_mrh_watcher', None)
        if watcher is not None: watcher.join(timeout=2)
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None and not stream.closed: stream.close()
        if getattr(process, '_mrh_cleanup_failed', False): raise OSError('windows_job_cleanup_failed')

def run(argv, *, timeout=40, input=None, capture_output=True, text=True, **kwargs):
    process = popen(argv, stdout=subprocess.PIPE if capture_output else None,
                    stderr=subprocess.PIPE if capture_output else None, text=text, **kwargs)
    try:
        out, err = process.communicate(input, timeout=timeout)
        return subprocess.CompletedProcess(argv, process.returncode, out, err)
    finally: finish(process)

@contextmanager
def temporary_directory(*, prefix, dir=None):
    """Windows can release terminated-process file leases asynchronously."""
    base = Path(dir) if dir is not None else Path(os.environ["MRH_PROJECT_ROOT"])/"runtime/tmp/mrh"
    if not base.is_absolute() or base.resolve()!=base:raise OSError("windows_temp_root_invalid")
    base.mkdir(parents=True,exist_ok=True)
    temporary = tempfile.TemporaryDirectory(prefix=prefix, dir=base)
    target = Path(temporary.name).absolute()
    if target.parent != base.resolve() or not target.name.startswith(prefix):
        raise OSError('windows_temp_cleanup_scope_invalid')
    try: yield temporary.name
    finally:
        for attempt in range(21):
            try:
                temporary.cleanup()
                break
            except PermissionError:
                if attempt == 20: raise OSError('windows_temp_cleanup_failed') from None
                time.sleep(.05)
