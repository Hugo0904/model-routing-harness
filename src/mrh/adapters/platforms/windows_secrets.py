"""Current-user Credential Manager. Secrets never enter a command or console."""
import ctypes as c
from ctypes import wintypes as w

adv = c.WinDLL('advapi32', use_last_error=True)
ui = c.WinDLL('credui', use_last_error=True)
TARGET = 'model-routing-harness/jev'

class Credential(c.Structure):
    _fields_ = [('Flags', w.DWORD), ('Type', w.DWORD), ('TargetName', w.LPWSTR),
                ('Comment', w.LPWSTR), ('LastWritten', w.FILETIME),
                ('CredentialBlobSize', w.DWORD), ('CredentialBlob', c.POINTER(w.BYTE)),
                ('Persist', w.DWORD), ('AttributeCount', w.DWORD), ('Attributes', c.c_void_p),
                ('TargetAlias', w.LPWSTR), ('UserName', w.LPWSTR)]

adv.CredReadW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, c.POINTER(c.POINTER(Credential))]
adv.CredReadW.restype = w.BOOL
adv.CredWriteW.argtypes = [c.POINTER(Credential), w.DWORD]; adv.CredWriteW.restype = w.BOOL
adv.CredFree.argtypes = [c.c_void_p]; adv.CredFree.restype = None
adv.CredDeleteW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD]; adv.CredDeleteW.restype = w.BOOL

def _lookup(metadata=False):
    cred = c.POINTER(Credential)()
    if not adv.CredReadW(TARGET, 1, 0, c.byref(cred)):
        if c.get_last_error() == 1168: return False if metadata else None
        raise OSError('windows_credential_unavailable')
    try:
        if metadata: return cred.contents.CredentialBlobSize > 0
        return c.string_at(cred.contents.CredentialBlob, cred.contents.CredentialBlobSize).decode('utf-8') or None
    finally:
        if cred.contents.CredentialBlobSize:
            c.memset(cred.contents.CredentialBlob, 0, cred.contents.CredentialBlobSize)
        adv.CredFree(cred)

def is_set():
    try: return _lookup(metadata=True)
    except OSError: return False

def read():
    try: return _lookup()
    except (OSError, UnicodeError): return None

def store_interactively():
    class UIInfo(c.Structure):
        _fields_ = [('size', w.DWORD), ('parent', w.HWND), ('message', w.LPCWSTR), ('caption', w.LPCWSTR), ('banner', w.HANDLE)]
    prompt = ui.CredUIPromptForCredentialsW
    prompt.argtypes = [c.POINTER(UIInfo), w.LPCWSTR, c.c_void_p, w.DWORD, w.LPWSTR, w.ULONG, w.LPWSTR, w.ULONG, c.POINTER(w.BOOL), w.DWORD]
    prompt.restype = w.DWORD
    user = c.create_unicode_buffer('Jev API key', 514)
    password = c.create_unicode_buffer(257)
    save = w.BOOL(False)
    info = UIInfo(c.sizeof(UIInfo), None, 'Enter your Jev API key in the password field. This is not your Windows password.', 'MRH - Jev API key', None)
    blob = None
    try:
        # Generic, always show, never let CredUI persist a second credential.
        status = prompt(c.byref(info), TARGET, None, 0, user, len(user), password, len(password), c.byref(save), 0x40000 | 0x80 | 0x2)
        if status: raise OSError('windows_credential_cancelled' if status == 1223 else 'windows_credential_prompt_failed')
        if not password.value or len(password.value) >= 256: raise OSError('windows_credential_invalid')
        raw = password.value.encode('utf-8')
        blob = (w.BYTE * len(raw)).from_buffer_copy(raw)
        del raw
        cred = Credential(Type=1, TargetName=TARGET, CredentialBlobSize=len(blob), CredentialBlob=blob, Persist=2, UserName='Jev')
        if not adv.CredWriteW(c.byref(cred), 0): raise OSError('windows_credential_store_failed')
    finally:
        c.memset(password, 0, c.sizeof(password))
        if blob is not None: c.memset(blob, 0, c.sizeof(blob))

def delete():
    if adv.CredDeleteW(TARGET, 1, 0): return True
    if c.get_last_error() == 1168: return False
    raise OSError('windows_credential_delete_failed')
