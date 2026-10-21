"""Native Windows file ownership, ACLs, no-follow handles and byte-range locks."""
import ctypes as c
from ctypes import wintypes as w
import msvcrt
import os
from pathlib import Path
import stat
import subprocess

k = c.WinDLL('kernel32', use_last_error=True)
a = c.WinDLL('advapi32', use_last_error=True)
P = c.c_void_p

def api(dll, name, args, result=w.BOOL):
    f = getattr(dll, name); f.argtypes = args; f.restype = result
    return f

close = api(k, 'CloseHandle', [w.HANDLE])
local_free = api(k, 'LocalFree', [P], P)
get_current = api(k, 'GetCurrentProcess', [], w.HANDLE)
open_token = api(a, 'OpenProcessToken', [w.HANDLE, w.DWORD, c.POINTER(w.HANDLE)])
token_info = api(a, 'GetTokenInformation', [w.HANDLE, c.c_int, P, w.DWORD, c.POINTER(w.DWORD)])
sid_string = api(a, 'ConvertSidToStringSidW', [P, c.POINTER(w.LPWSTR)])
get_security = api(a, 'GetNamedSecurityInfoW', [w.LPWSTR, c.c_int, w.DWORD, c.POINTER(P), c.POINTER(P), c.POINTER(P), c.POINTER(P), c.POINTER(P)], w.DWORD)
get_ace = api(a, 'GetAce', [P, w.DWORD, c.POINTER(P)])
convert_sd = api(a, 'ConvertStringSecurityDescriptorToSecurityDescriptorW', [w.LPCWSTR, w.DWORD, c.POINTER(P), c.POINTER(w.DWORD)])
set_security = api(a, 'SetFileSecurityW', [w.LPCWSTR, w.DWORD, P])
create_file = api(k, 'CreateFileW', [w.LPCWSTR, w.DWORD, w.DWORD, P, w.DWORD, w.DWORD, w.HANDLE], w.HANDLE)

def checked(ok):
    if not ok: raise c.WinError(c.get_last_error())
    return ok

def sid_text(sid):
    value = w.LPWSTR(); checked(sid_string(sid, c.byref(value)))
    try: return value.value
    finally: local_free(value)

def current_sid():
    token = w.HANDLE(); checked(open_token(get_current(), 8, c.byref(token)))
    try:
        size = w.DWORD(); token_info(token, 1, None, 0, c.byref(size))
        data = c.create_string_buffer(size.value)
        checked(token_info(token, 1, data, size, c.byref(size)))
        return sid_text(c.cast(data, c.POINTER(P))[0])
    finally: close(token)

class ACL(c.Structure):
    _fields_ = [('revision', w.BYTE), ('reserved', w.BYTE), ('size', w.WORD), ('count', w.WORD), ('reserved2', w.WORD)]

def assert_safe(path, directory=False, *, private=False, ancestor=False):
    """Reject reparse points, foreign owners and ACLs writable by other users.

    System and Administrators retain their normal OS authority. A private MRH
    directory also rejects read access granted to other principals.
    """
    path = Path(path)
    if not path.is_absolute() or path.drive.startswith('\\\\') or any(':' in part or part.endswith((' ', '.')) for part in path.parts[1:]):
        raise ValueError('windows_unsafe_path')
    info = path.lstat()
    if getattr(info, 'st_file_attributes', 0) & 0x400:
        raise ValueError('windows_reparse_point')
    if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
        raise ValueError('windows_file_type')
    if not directory and info.st_nlink != 1: raise ValueError('windows_hardlink')
    owner = P(); dacl = P(); descriptor = P()
    result = get_security(str(path), 1, 5, c.byref(owner), None, c.byref(dacl), None, c.byref(descriptor))
    if result: raise c.WinError(result)
    try:
        trusted = {current_sid(), 'S-1-5-18', 'S-1-5-32-544'}
        if sid_text(owner) not in trusted or not dacl: raise ValueError('windows_unsafe_owner_or_acl')
        for i in range(c.cast(dacl, c.POINTER(ACL)).contents.count):
            ace = P(); checked(get_ace(dacl, i, c.byref(ace)))
            header = c.string_at(ace, 4)
            if header[1] & 8: continue  # inherit-only, does not apply to this object
            if header[0] == 1: continue  # deny ACE; never grants authority
            if header[0] != 0: raise ValueError('windows_acl_type_unsupported')
            mask = c.cast(ace.value + 4, c.POINTER(w.DWORD)).contents.value
            sid = sid_text(ace.value + 8)
            # Write, append, delete-child, attributes, DELETE, DAC, owner,
            # GENERIC_WRITE and GENERIC_ALL. Conservative: deny ACEs don't
            # cancel an unsafe allow ACE in this verifier.
            unsafe = (0x500D0040 if ancestor and directory else 0x500D0156) | (0x80000089 if private else 0)
            if sid not in trusted and mask & unsafe: raise ValueError('windows_unsafe_acl')
    finally: local_free(descriptor)
    return path

def snapshot_executable(source, store, publisher):
    """Pin signed native hosts in private storage; leave their original ACLs.

    Some Windows profiles deliberately grant another local account write access.
    Such a live executable cannot satisfy MRH's immutable host binding. Only a
    valid, expected-publisher signed copy is accepted in this path.
    """
    import hashlib
    import json
    from mrh.infrastructure import owned
    source = Path(source).resolve()
    if source.suffix.lower() != '.exe' or source.is_symlink(): raise ValueError('windows_host_executable_required')
    if publisher not in ('OpenAI OpCo, LLC', 'Anthropic, PBC'): raise ValueError('windows_publisher_unknown')
    store = owned.initialize(Path(store), 'host_tools')
    data = source.read_bytes(); digest = hashlib.sha256(data).hexdigest()
    target = store / (source.stem + '-' + digest[:24] + '.exe')
    with owned.locked(store, 'host_tools'):
        if not target.exists(): owned.replace_owned(target, data, limit=600_000_000)
        if hashlib.sha256(owned.read_regular(target, 600_000_000)).hexdigest() != digest:
            raise ValueError('windows_host_snapshot_changed')
        if hashlib.sha256(source.read_bytes()).hexdigest() != digest:
            raise ValueError('windows_host_source_changed')
        # Paths are passed via a child-only environment, never inserted in PS.
        import shutil
        ps = Path(shutil.which('pwsh.exe') or Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe')
        script = '$s=Get-AuthenticodeSignature -LiteralPath $env:MRH_VERIFY_EXE; @{status=$s.Status.ToString();subject=$s.SignerCertificate.Subject} | ConvertTo-Json -Compress'
        env = {**os.environ, 'MRH_VERIFY_EXE': str(target)}
        result = subprocess.run([str(ps), '-NoProfile', '-NonInteractive', '-Command', script], env=env, capture_output=True, text=True, timeout=40)
        info = json.loads(result.stdout) if result.returncode == 0 else {}
        if info.get('status') != 'Valid' or publisher not in info.get('subject', ''):
            raise ValueError('windows_host_signature_invalid')
    assert_safe(target, private=True)
    return target

def snapshot_codex_bundle(source, store):
    """Codex resolves its signed code-mode/sandbox companions beside codex.exe."""
    import hashlib
    import json
    import shutil
    import tempfile
    from mrh.infrastructure import owned
    source = Path(source).resolve()
    names = ('codex.exe', 'codex-code-mode-host.exe', 'codex-command-runner.exe', 'codex-windows-sandbox-setup.exe')
    if source.name != 'codex.exe' or any(not (source.parent/n).is_file() for n in names):
        raise ValueError('windows_codex_bundle_incomplete')
    def sha(path):
        result=hashlib.sha256()
        with Path(path).open('rb') as stream:
            for chunk in iter(lambda:stream.read(1024*1024), b''):result.update(chunk)
        return result.hexdigest()
    hashes={name:sha(source.parent/name) for name in names}
    store=owned.initialize(Path(store),'host_tools')
    target=owned.initialize(store/('codex-'+hashes['codex.exe'][:24]),'host_bundle')
    with owned.locked(target,'host_bundle'):
        for name in names:
            src=source.parent/name;destination=target/name
            if not destination.exists():
                fd,temporary=tempfile.mkstemp(prefix='.mrh-copy-', dir=target)
                try:
                    with os.fdopen(fd,'wb') as output,src.open('rb') as input_stream:
                        shutil.copyfileobj(input_stream,output,1024*1024)
                        output.flush();os.fsync(output.fileno())
                    protect(temporary)
                    if sha(temporary)!=hashes[name]:raise ValueError('windows_host_source_changed')
                    os.replace(temporary,destination)
                finally:
                    if os.path.exists(temporary):os.unlink(temporary)
            assert_safe(destination,private=True)
            if sha(destination)!=hashes[name] or sha(src)!=hashes[name]:raise ValueError('windows_host_snapshot_changed')
            ps=Path(shutil.which('pwsh.exe') or Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe')
            env={**os.environ,'MRH_VERIFY_EXE':str(destination)}
            script='$s=Get-AuthenticodeSignature -LiteralPath $env:MRH_VERIFY_EXE; @{status=$s.Status.ToString();subject=$s.SignerCertificate.Subject} | ConvertTo-Json -Compress'
            check=subprocess.run([str(ps),'-NoProfile','-NonInteractive','-Command',script],env=env,capture_output=True,text=True,timeout=40)
            info=json.loads(check.stdout) if check.returncode==0 else {}
            if info.get('status')!='Valid' or 'OpenAI OpCo, LLC' not in info.get('subject',''):
                raise ValueError('windows_host_signature_invalid')
        owned.replace_owned(target/'bundle.json',(json.dumps({'publisher':'OpenAI OpCo, LLC','files':hashes},sort_keys=True)+'\n').encode())
    return target/'codex.exe'

def verify_codex_bundle(executable):
    import hashlib,json
    from mrh.infrastructure import owned
    root=owned.verify(Path(executable).parent,'host_bundle')
    manifest=json.loads(owned.read_regular(root/'bundle.json'))
    files=manifest.get('files',{})
    expected={'codex.exe','codex-code-mode-host.exe','codex-command-runner.exe','codex-windows-sandbox-setup.exe'}
    if (manifest.get('publisher')!='OpenAI OpCo, LLC' or set(files)!=expected
            or {p.name for p in root.iterdir()} != expected | {owned.MARKER,'.mrh.lock','bundle.json'}):
        raise ValueError('windows_codex_bundle_invalid')
    for name,wanted in files.items():
        assert_safe(root/name,private=True)
        h=hashlib.sha256()
        fd=open_regular(root/name)
        with os.fdopen(fd,'rb') as stream:
            for chunk in iter(lambda:stream.read(1024*1024),b''):h.update(chunk)
        if h.hexdigest()!=wanted:raise ValueError('windows_codex_bundle_changed')
    return manifest

def protect(path):
    """Only call for newly created MRH-owned objects, never a foreign tree."""
    descriptor = P()
    flags = 'OICI' if Path(path).is_dir() else ''
    sddl = f'D:P(A;{flags};FA;;;{current_sid()})(A;{flags};FA;;;SY)(A;{flags};FA;;;BA)'
    checked(convert_sd(sddl, 1, c.byref(descriptor), None))
    try: checked(set_security(str(path), 0x80000004, descriptor))
    finally: local_free(descriptor)
    assert_safe(path, Path(path).is_dir(), private=True)

def open_regular(path, flags=os.O_RDONLY, mode=0o600):
    path = Path(path)
    if path.exists(): assert_safe(path)
    access = 0x80000000 | (0x40000000 if flags & (os.O_RDWR | os.O_WRONLY) else 0)
    disposition = 1 if flags & os.O_EXCL else 4 if flags & os.O_CREAT else 3
    # Share read/write/delete so atomic replaces can coexist with MRH readers;
    # FILE_FLAG_OPEN_REPARSE_POINT prevents following a raced final link.
    handle = create_file(str(path), access, 7, None, disposition, 0x00200000, None)
    if handle == w.HANDLE(-1).value: raise c.WinError(c.get_last_error())
    try:
        class INFO(c.Structure):
            _fields_ = [('attributes', w.DWORD), ('times', w.DWORD * 6), ('volume', w.DWORD), ('size_hi', w.DWORD), ('size_lo', w.DWORD), ('links', w.DWORD), ('index_hi', w.DWORD), ('index_lo', w.DWORD)]
        get_info = api(k, 'GetFileInformationByHandle', [w.HANDLE, c.POINTER(INFO)])
        info = INFO(); checked(get_info(handle, c.byref(info)))
        if info.attributes & (0x400 | 0x10) or info.links != 1: raise ValueError('windows_unsafe_file_handle')
        fd = msvcrt.open_osfhandle(handle, flags | os.O_BINARY)
        handle = None
        return fd
    finally:
        if handle is not None: close(handle)

def lock_fd(fd, blocking=False):
    os.lseek(fd, 0, os.SEEK_SET)
    try: msvcrt.locking(fd, msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK, 1)
    except OSError as exc: raise BlockingIOError('windows_lock_busy') from exc

def unlock_fd(fd):
    os.lseek(fd, 0, os.SEEK_SET)
    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)

def quote_command(argv):
    # cmd.exe expands these even inside quotes. Refuse rather than silently
    # executing a different path; spaces and ordinary Unicode are supported.
    if any(any(ch in str(arg) for ch in '\r\n\x00%"!&|<>^') for arg in argv):
        raise ValueError('windows_shell_path_unsupported')
    return ' '.join('"' + str(arg) + '"' if (' ' in str(arg) or '\\' in str(arg) or '/' in str(arg)) else str(arg) for arg in argv)

def codex_hook_command(python, bootstrap=None, host='codex'):
    """A quote-free outer command works in both Codex's PS and cmd runners.

    The inner PowerShell expression uses the native call operator and literal
    arguments. No execution policy override; no paths are interpolated into a
    shell token. PLUGIN_ROOT is resolved from the host-provided environment.
    """
    import base64
    interpreter = str(python)
    if any(ord(ch)<32 for ch in interpreter):raise ValueError('windows_shell_path_unsupported')
    literal = "'" + interpreter.replace("'", "''") + "'"
    if host not in ('codex','claude'):raise ValueError('windows_hook_host_unknown')
    if bootstrap is None:
        code = ("$mrhRoot=$env:PLUGIN_ROOT; if ([string]::IsNullOrEmpty($mrhRoot)) { exit 2 }; "
                "& " + literal + " -I -B (Join-Path $mrhRoot 'launcher.py') "+host+"; exit $LASTEXITCODE")
    else:
        script="'"+str(bootstrap).replace("'","''")+"'"
        code="& "+literal+" -I -B "+script+" --native-hook "+host+"; exit $LASTEXITCODE"
    shell=Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
    if any(ch in str(shell) for ch in ' \r\n\x00%"!&|<>^'):raise ValueError('windows_native_shell_path_unsupported')
    return str(shell)+' -NoProfile -NonInteractive -EncodedCommand '+base64.b64encode(code.encode('utf-16-le')).decode('ascii')
