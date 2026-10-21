"""Current-user command discovery; never edits System PATH or shell profiles."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import ntpath
import os
from pathlib import Path
import re
import winreg


class PathError(ValueError):
    pass


@dataclass(frozen=True)
class PathValue:
    value: str = ''
    kind: int = winreg.REG_EXPAND_SZ
    exists: bool = False


class RegistryPath:
    def read(self, scope):
        root, key = ((winreg.HKEY_CURRENT_USER, 'Environment') if scope == 'user' else
                     (winreg.HKEY_LOCAL_MACHINE, r'SYSTEM\CurrentControlSet\Control\Session Manager\Environment'))
        try:
            with winreg.OpenKey(root, key) as handle:
                value, kind = winreg.QueryValueEx(handle, 'Path')
        except FileNotFoundError:
            return PathValue()
        if kind not in (winreg.REG_SZ, winreg.REG_EXPAND_SZ) or not isinstance(value, str):
            raise PathError('user_path_type_unsupported')
        return PathValue(value, kind, True)

    def write(self, expected, replacement):
        if self.read('user') != expected:
            raise PathError('user_path_concurrent_change')
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, 'Environment', 0, winreg.KEY_SET_VALUE) as handle:
            winreg.SetValueEx(handle, 'Path', 0, replacement.kind, replacement.value)
        if self.read('user') != replacement:
            raise PathError('user_path_readback_failed')


def notify_environment():
    """Ask desktop applications to reload; this cannot refresh existing shells."""
    user = ctypes.WinDLL('user32', use_last_error=True)
    send = user.SendMessageTimeoutW
    send.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPCWSTR,
                     wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t)]
    send.restype = wintypes.LPARAM
    result = ctypes.c_size_t()
    return bool(send(0xffff, 0x1a, 0, 'Environment', 2, 3000, ctypes.byref(result)))


class UserPath:
    def __init__(self, bin_dir, *, store=None, environ=None, cwd=None, notify=notify_environment):
        self.bin_dir = Path(bin_dir).absolute()
        if any(c in str(self.bin_dir) for c in ';%"\0\r\n'):
            raise PathError('mrh_path_entry_unsupported')
        self.command = self.bin_dir / 'mrh.cmd'
        self.store = store if store is not None else RegistryPath()
        self.environ = dict(os.environ if environ is None else environ)
        self.cwd = Path.cwd() if cwd is None else Path(cwd)
        self.notify = notify

    def _expand(self, text):
        environment = {k.upper(): v for k, v in self.environ.items()}
        return re.sub(r'%([^%]+)%', lambda m: environment.get(m[1].upper(), m[0]), text)

    def _text(self, value):
        if any(c in value.value for c in '\0\r\n') or re.search(r'%path%', value.value, re.I):
            raise PathError('user_path_value_unsupported')
        return self._expand(value.value) if value.kind == winreg.REG_EXPAND_SZ else value.value

    def _normal(self, text):
        text = text.strip().strip('"')
        if not ntpath.isabs(text):
            text = str(self.cwd / text)
        return ntpath.normcase(ntpath.normpath(text))

    def _matches(self, entry, value):
        text = self._expand(entry) if value.kind == winreg.REG_EXPAND_SZ else entry
        return self._normal(text) == self._normal(str(self.bin_dir))

    def _commands(self, path):
        extensions = self.environ.get('PATHEXT', '.COM;.EXE;.BAT;.CMD').split(';')
        extensions = list(dict.fromkeys(x.lower() for x in extensions + ['.com', '.exe', '.bat', '.cmd', '.ps1'] if x.startswith('.')))
        found = []
        for entry in [str(self.cwd), *path.split(';')]:
            folder = Path(entry.strip().strip('"')) if entry.strip(' "') else self.cwd
            if not folder.is_absolute(): folder = self.cwd / folder
            for extension in extensions:
                candidate = folder / ('mrh' + extension)
                if candidate.is_file() and self._normal(str(candidate)) not in {self._normal(str(p)) for p in found}:
                    found.append(candidate.absolute())
        return found

    def plan(self):
        user, machine = self.store.read('user'), self.store.read('machine')
        # Validate even when no write is needed; preserve all unrelated text.
        self._text(user); self._text(machine)
        entries = user.value.split(';') if user.value else []
        matches = [i for i, item in enumerate(entries) if self._matches(item, user)]
        if matches:
            entries = [item for i, item in enumerate(entries) if i == matches[0] or i not in matches]
        else:
            entries.append(str(self.bin_dir))
        replacement = PathValue(';'.join(entries), user.kind, True)
        future = ';'.join(filter(None, (self._text(machine), self._text(replacement))))
        if len(replacement.value) >= 32767 or len(future) >= 32767:
            raise PathError('user_path_too_long')
        current = self.environ.get('PATH', self.environ.get('Path', ''))
        commands = self._commands(future) + self._commands(current)
        conflicts = list(dict.fromkeys(str(p) for p in commands if self._normal(str(p)) != self._normal(str(self.command))))
        return {'user': user, 'machine': machine, 'replacement': replacement, 'future': future,
                'conflicts': conflicts, 'registered': bool(matches), 'duplicates': len(matches) > 1,
                'action': 'added' if not matches else 'deduplicated' if len(matches) > 1 else 'unchanged'}

    def validate(self, plan):
        if plan['conflicts']:
            raise PathError('mrh_command_conflict:' + plan['conflicts'][0])
        if '.cmd' not in self.environ.get('PATHEXT', '.COM;.EXE;.BAT;.CMD').lower().split(';'):
            raise PathError('command_pathext_missing_cmd')

    def apply(self, plan):
        self.validate(plan)
        # Recheck both registry values and command collisions after registration.
        current = self.plan()
        self.validate(current)
        if any(current[k] != plan[k] for k in ('user', 'machine')):
            raise PathError('user_path_concurrent_change')
        if plan['action'] != 'unchanged':
            self.store.write(plan['user'], plan['replacement'])
            notified = self.notify()
        else:
            notified = None
        return {'action': plan['action'], 'environment_notification': notified,
                'existing_terminals_refreshed': False}

    def report(self):
        plan = self.plan()
        current = self._commands(self.environ.get('PATH', self.environ.get('Path', '')))
        future = self._commands(plan['future'])
        expected = self._normal(str(self.command))
        def ready(commands):
            return bool(commands and self._normal(str(commands[0])) == expected)
        valid_extensions = '.cmd' in self.environ.get('PATHEXT', '.COM;.EXE;.BAT;.CMD').lower().split(';')
        process_ready = ready(current) and valid_extensions
        return {'entrypoint': str(self.command), 'user_path_registered': plan['registered'],
                'duplicate_entries': plan['duplicates'], 'conflicts': plan['conflicts'],
                'future_terminal_ready': ready(future) and plan['registered'] and not plan['duplicates'] and not plan['conflicts'] and valid_extensions,
                'current_process_ready': process_ready,
                'terminal_refresh': 'current_process_ready' if process_ready else 'new_terminal_required',
                'existing_terminals_refreshed': False, 'execution_probe_performed': False}

    def future_environment(self):
        environment = dict(self.environ)
        environment['PATH'] = self.plan()['future']
        # Windows environment keys are case insensitive; avoid a duplicate key.
        for key in list(environment):
            if key != 'PATH' and key.upper() == 'PATH': del environment[key]
        return environment
