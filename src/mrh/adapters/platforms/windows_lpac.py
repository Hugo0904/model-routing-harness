"""Credential-free metadata processes in a fresh, zero-capability Windows LPAC.

No shell or parent environment is inherited. The copied image is read-only and
locked against replacement, and the token and Job are checked while suspended.
An anonymous pipe and detached process avoid console initialization in LPAC.
This is for public CLI metadata, never authenticated tasks.
"""
from contextlib import contextmanager
import ctypes as c
from ctypes import wintypes as w
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import time
import uuid

from mrh.adapters.platforms import windows as win
from mrh.adapters.platforms.windows_process import Job, temporary_directory
from mrh.infrastructure import temporary

P = c.c_void_p
k, a = win.k, win.a
u = c.WinDLL('userenv', use_last_error=True)
api, check = win.api, win.checked
create_profile = api(u, 'CreateAppContainerProfile', [w.LPCWSTR, w.LPCWSTR, w.LPCWSTR, P, w.DWORD, c.POINTER(P)], c.c_long)
delete_profile = api(u, 'DeleteAppContainerProfile', [w.LPCWSTR], c.c_long)
free_sid = api(a, 'FreeSid', [P], P)
init_attrs = api(k, 'InitializeProcThreadAttributeList', [P, w.DWORD, w.DWORD, c.POINTER(c.c_size_t)])
update_attr = api(k, 'UpdateProcThreadAttribute', [P, w.DWORD, c.c_size_t, P, c.c_size_t, P, P])
delete_attrs = api(k, 'DeleteProcThreadAttributeList', [P], None)
pipe = api(k, 'CreatePipe', [c.POINTER(w.HANDLE), c.POINTER(w.HANDLE), P, w.DWORD])
inherit = api(k, 'SetHandleInformation', [w.HANDLE, w.DWORD, w.DWORD])
read = api(k, 'ReadFile', [w.HANDLE, P, w.DWORD, c.POINTER(w.DWORD), P])
write = api(k, 'WriteFile', [w.HANDLE, P, w.DWORD, c.POINTER(w.DWORD), P])
peek = api(k, 'PeekNamedPipe', [w.HANDLE, P, w.DWORD, P, c.POINTER(w.DWORD), P])
resume = api(k, 'ResumeThread', [w.HANDLE], w.DWORD)
terminate = api(k, 'TerminateProcess', [w.HANDLE, w.UINT])
wait = api(k, 'WaitForSingleObject', [w.HANDLE, w.DWORD], w.DWORD)
exit_code = api(k, 'GetExitCodeProcess', [w.HANDLE, c.POINTER(w.DWORD)])
in_job = api(k, 'IsProcessInJob', [w.HANDLE, w.HANDLE, c.POINTER(w.BOOL)])
query_image = api(k, 'QueryFullProcessImageNameW', [w.HANDLE, w.DWORD, w.LPWSTR, c.POINTER(w.DWORD)])
SECURITY_CAPABILITIES = 0x20009
HANDLE_LIST = 0x20002
ALL_APPLICATION_PACKAGES_POLICY = 0x2000f  # WinBase.h: attribute 15, not ChildProcessPolicy (14)


class SA(c.Structure):
    _fields_ = [('size', w.DWORD), ('descriptor', P), ('inherit', w.BOOL)]


class SI(c.Structure):
    _fields_ = [('cb', w.DWORD), ('reserved', w.LPWSTR), ('desktop', w.LPWSTR), ('title', w.LPWSTR),
                *[(n, w.DWORD) for n in ('x', 'y', 'xs', 'ys', 'xc', 'yc', 'fill', 'flags')],
                ('show', w.WORD), ('cbreserved', w.WORD), ('reserved2', P),
                ('input', w.HANDLE), ('output', w.HANDLE), ('error', w.HANDLE)]


class SIX(c.Structure):
    _fields_ = [('si', SI), ('attrs', P)]


class PI(c.Structure):
    _fields_ = [('process', w.HANDLE), ('thread', w.HANDLE), ('pid', w.DWORD), ('tid', w.DWORD)]


class CAPS(c.Structure):
    _fields_ = [('sid', P), ('capabilities', P), ('count', w.DWORD), ('reserved', w.DWORD)]


create = api(k, 'CreateProcessW', [w.LPCWSTR, w.LPWSTR, P, P, w.BOOL, w.DWORD, P, w.LPCWSTR, P, c.POINTER(PI)])


def _grant(path, sid, owner, writable=False):
    # Grant this unique package, never ALL APPLICATION PACKAGES. The executable
    # and its directory cannot be modified by the low-integrity child.
    rights = '0x1301bf' if writable else '0x1200a9'
    descriptor = P()
    sddl = f'D:P(A;OICI;FA;;;{owner})(A;OICI;FA;;;SY)(A;OICI;{rights};;;{sid})S:(ML;OICI;NW;;;LW)'
    check(win.convert_sd(sddl, 1, c.byref(descriptor), None))
    try:
        check(win.set_security(str(path), 0x80000004 | 0x10, descriptor))
    finally:
        win.local_free(descriptor)


def _token_value(token, kind):
    size = w.DWORD()
    win.token_info(token, kind, None, 0, c.byref(size))
    data = c.create_string_buffer(size.value)
    check(win.token_info(token, kind, data, size, c.byref(size)))
    return data


def _package_access(token, sid):
    """Read back LPAC semantics on Windows versions without token class 46.

    An ordinary AppContainer can use ALL APPLICATION PACKAGES; an LPAC must
    fail that access check, while still accepting its own unique package SID.
    This checks the actual token rather than trusting the creation attribute.
    """
    duplicate = api(a, 'DuplicateToken', [w.HANDLE, c.c_int, c.POINTER(w.HANDLE)])
    access = api(a, 'AccessCheck', [P, w.HANDLE, w.DWORD, P, P, c.POINTER(w.DWORD), c.POINTER(w.DWORD), c.POINTER(w.BOOL)])
    impersonation = w.HANDLE(); descriptor = P()
    check(duplicate(token, 2, c.byref(impersonation)))
    try:
        owner = win.current_sid()
        check(win.convert_sd(f'O:{owner}G:{owner}D:(A;;1;;;WD)(A;;1;;;{sid})', 1, c.byref(descriptor), None))
        mapping = (w.DWORD*4)(1, 1, 1, 1)
        privileges = c.create_string_buffer(1024); size = w.DWORD(len(privileges))
        granted = w.DWORD(); allowed = w.BOOL()
        check(access(descriptor, impersonation, 1, mapping, privileges, c.byref(size), c.byref(granted), c.byref(allowed)))
        return bool(allowed.value and granted.value & 1)
    finally:
        if descriptor: win.local_free(descriptor)
        win.close(impersonation)


def _verify(process, sid, job, executable):
    token = w.HANDLE()
    check(win.open_token(process, 8|2, c.byref(token)))
    try:
        def scalar(kind):
            value = w.DWORD(); size = w.DWORD()
            check(win.token_info(token, kind, c.byref(value), c.sizeof(value), c.byref(size)))
            return value.value
        package = _token_value(token, 31)  # TOKEN_APPCONTAINER_INFORMATION
        integrity = _token_value(token, 25)  # TOKEN_MANDATORY_LABEL
        capabilities = _token_value(token, 30)
        if (scalar(29) != 1 or c.cast(capabilities, c.POINTER(w.DWORD))[0] != 0
                or win.sid_text(c.cast(package, c.POINTER(P))[0]) != sid
                or win.sid_text(c.cast(integrity, c.POINTER(P))[0]) != 'S-1-16-4096'
                or not _package_access(token, sid) or _package_access(token, 'S-1-15-2-1')):
            raise OSError('windows_lpac_token_invalid')
    finally:
        win.close(token)
    assigned = w.BOOL()
    check(in_job(process, job.handle, c.byref(assigned)))
    image = c.create_unicode_buffer(32768); size = w.DWORD(len(image))
    check(query_image(process, 0, image, c.byref(size)))
    if not assigned.value or Path(image.value) != executable:
        raise OSError('windows_lpac_process_invalid')


class Sandbox:
    def __init__(self, root, sid):
        self.root, self.sid = root, sid
        self.executable = root/'cli.exe'
        self.work = root/'runtime'
        self.env = {'SystemRoot': os.environ['SystemRoot'], 'WINDIR': os.environ['SystemRoot'],
                    'PATH': str(Path(os.environ['SystemRoot'])/'System32'),
                    'HOME': str(self.work), 'USERPROFILE': str(self.work),
                    'APPDATA': str(self.work/'config'), 'LOCALAPPDATA': str(self.work/'config'),
                    'TEMP': str(self.work/'tmp'), 'TMP': str(self.work/'tmp'),
                    'CLAUDE_CONFIG_DIR': str(self.work/'config'), 'CLAUDE_CODE_TMPDIR': str(self.work/'tmp'),
                    'XDG_CONFIG_HOME': str(self.work/'config'), 'XDG_CACHE_HOME': str(self.work/'cache'),
                    'OPENSSL_CONF': str(self.work/'config/openssl.cnf'), 'DISABLE_TELEMETRY': '1',
                    'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC': '1', 'NO_COLOR': '1'}

    def capture(self, args, *, timeout, input=b'', until=None, limit=262144):
        """Return bounded stdout, optionally ending at a matching metadata frame.

        `until` inspects the received bytes; it must not send further requests.
        All exits reap descendants, including normal EOF and failed assignment.
        """
        if not isinstance(input, bytes) or len(input) > 4096:
            raise ValueError('windows_lpac_input_limit')
        handles = []; attrs = None; pi = PI(); job = None
        image_lock = None
        try:
            # Deny write/delete sharing throughout CreateProcess and execution.
            image_lock = win.create_file(str(self.executable), 0x80000000, 1, None, 3, 0x00200000, None)
            if image_lock == w.HANDLE(-1).value:
                image_lock = None
                raise c.WinError(c.get_last_error())
            if hashlib.sha256(self.executable.read_bytes()).hexdigest() != self.digest:
                raise OSError('windows_lpac_image_changed')
            sa = SA(c.sizeof(SA), None, True)
            rin, win_, rout, wout = [w.HANDLE() for _ in range(4)]
            check(pipe(c.byref(rin), c.byref(win_), c.byref(sa), 4096)); handles.extend([rin, win_])
            check(pipe(c.byref(rout), c.byref(wout), c.byref(sa), 4096)); handles.extend([rout, wout])
            check(inherit(win_, 1, 0)); check(inherit(rout, 1, 0))
            null = win.create_file('NUL', 0x40000000, 3, c.byref(sa), 3, 0, None)
            if null == w.HANDLE(-1).value: raise c.WinError(c.get_last_error())
            handles.append(null)
            size = c.c_size_t(); init_attrs(None, 3, 0, c.byref(size))
            buffer = c.create_string_buffer(size.value)
            check(init_attrs(buffer, 3, 0, c.byref(size))); attrs = buffer
            caps = CAPS(self._sid, None, 0, 0); opt = w.DWORD(1)
            inherited = (w.HANDLE*3)(rin.value, wout.value, null)
            for key, value in ((SECURITY_CAPABILITIES, caps), (ALL_APPLICATION_PACKAGES_POLICY, opt), (HANDLE_LIST, inherited)):
                check(update_attr(attrs, 0, key, c.byref(value), c.sizeof(value), None, None))
            si = SIX(); si.si.cb = c.sizeof(si); si.attrs = c.cast(attrs, P)
            si.si.flags = 0x100; si.si.input = rin; si.si.output = wout; si.si.error = null
            env = c.create_unicode_buffer('\0'.join(f'{key}={value}' for key, value in sorted(self.env.items()))+'\0\0')
            command = c.create_unicode_buffer(subprocess.list2cmdline([str(self.executable), *map(str, args)]))
            # CREATE_SUSPENDED | EXTENDED_STARTUPINFO_PRESENT | UNICODE_ENVIRONMENT
            # | DETACHED_PROCESS. CREATE_NO_WINDOW fails console init in LPAC.
            check(create(str(self.executable), command, None, None, True, 4|0x80000|0x400|8,
                         env, str(self.work), c.byref(si), c.byref(pi)))
            job = Job()
            child = type('Child', (), {'_handle': pi.process})()
            job.assign(child)
            _verify(pi.process, self.sid, job, self.executable)
            if resume(pi.thread) == 0xffffffff: raise c.WinError(c.get_last_error())
            for handle in (rin, wout, null):
                win.close(handle); handles.remove(handle)
            n = w.DWORD()
            if input:
                check(write(win_, input, len(input), c.byref(n), None))
                if n.value != len(input): raise OSError('windows_lpac_write_failed')
            else:
                win.close(win_); handles.remove(win_)
            result = b''; deadline = time.monotonic()+timeout
            while time.monotonic() < deadline:
                available = w.DWORD()
                if not peek(rout, None, 0, None, c.byref(available), None):
                    if c.get_last_error() == 109: break
                    raise c.WinError(c.get_last_error())
                if available.value:
                    data = c.create_string_buffer(min(available.value, 16384))
                    check(read(rout, data, len(data), c.byref(n), None))
                    result += data.raw[:n.value]
                    if len(result) > limit: raise OSError('windows_lpac_output_limit')
                    if until is not None and until(result): return result
                elif wait(pi.process, 0) == 0:
                    break
                else:
                    time.sleep(.01)
            else:
                raise subprocess.TimeoutExpired([str(self.executable), *args], timeout)
            code = w.DWORD(); check(exit_code(pi.process, c.byref(code)))
            if code.value: raise OSError('windows_lpac_process_failed:'+hex(code.value))
            return result
        finally:
            # Even an unassigned, suspended child must be terminated. Closing a
            # just-created Job alone does not own that child on assignment failure.
            try:
                if pi.process:
                    terminate(pi.process, 125)
                    if wait(pi.process, 2000) != 0: raise OSError('windows_lpac_cleanup_failed')
            finally:
                try:
                    if job is not None: job.close()
                finally:
                    for handle in (pi.thread, pi.process, *handles, image_lock):
                        if handle: win.close(handle)
                    if attrs is not None: delete_attrs(attrs)


@contextmanager
def isolated(executable):
    """Fresh profile/SID and private files; no persistent package or credentials."""
    from mrh.adapters.catalogs.catalog import executable_hash
    digest = executable_hash(executable)
    name = 'mrh.catalog.'+uuid.uuid4().hex
    sid = P()
    result = create_profile(name, name, name, None, 0, c.byref(sid))
    if result < 0: raise OSError('windows_lpac_profile_create_failed:'+hex(result & 0xffffffff))
    try:
        # Use the existing Windows retrying cleanup for asynchronous file leases.
        with temporary_directory(prefix='mrh-claude-lpac-', dir=temporary.area()) as directory:
            root = Path(directory)
            win.protect(root)
            sid_text = win.sid_text(sid); owner = win.current_sid()
            sandbox = Sandbox(root, sid_text); sandbox._sid = sid; sandbox.digest = digest
            sandbox.profile_name = name
            shutil.copyfile(executable, sandbox.executable)
            if hashlib.sha256(sandbox.executable.read_bytes()).hexdigest() != digest or executable_hash(executable) != digest:
                raise OSError('windows_lpac_image_changed')
            _grant(root, sid_text, owner)
            _grant(sandbox.executable, sid_text, owner)
            sandbox.work.mkdir(); _grant(sandbox.work, sid_text, owner, True)
            for part in ('config', 'cache', 'tmp'): (sandbox.work/part).mkdir()
            (sandbox.work/'config/settings.json').write_text('{}', encoding='utf-8')
            (sandbox.work/'config/mcp.json').write_text('{"mcpServers":{}}', encoding='utf-8')
            (sandbox.work/'config/openssl.cnf').write_text('', encoding='utf-8')
            yield sandbox
    finally:
        free_sid(sid)
        for attempt in range(21):
            if delete_profile(name) >= 0: break
            if attempt == 20: raise OSError('windows_lpac_profile_cleanup_failed:'+name)
            time.sleep(.05)
