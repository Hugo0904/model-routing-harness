"""User shell PATH planning; terminal applications do not select startup files."""
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
from mrh.infrastructure import owned

START = '# >>> model-routing-harness PATH >>>'
END = '# <<< model-routing-harness PATH <<<'


class PathError(ValueError):
    pass


def _canonical(value):
    path = Path(value)
    if not path.is_absolute() or path.resolve() != path or any(ord(c) < 32 for c in str(path)):
        raise PathError('shell_path_unsafe')
    for parent in (path, *path.parents):
        if parent.is_dir():
            info = parent.stat()
            if info.st_uid not in (0, os.getuid()) or (info.st_mode & 0o022 and not info.st_mode & stat.S_ISVTX):
                raise PathError('shell_directory_unsafe')
    return path


def _read(path):
    _canonical(path)
    if not path.exists():return None, 0o600
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid() or info.st_mode & 0o022:
        raise PathError('shell_profile_unsafe')
    if info.st_size > 1_000_000:raise PathError('shell_profile_oversized')
    return path.read_bytes(), stat.S_IMODE(info.st_mode)


class UserPath:
    def __init__(self, bin_dir, *, user_home=None, environ=None, login_shell=None):
        self.bin_dir = _canonical(bin_dir)
        if ':' in str(self.bin_dir):raise PathError('shell_bin_path_unsupported')
        self.home = _canonical(user_home or Path.home())
        self.environ = dict(os.environ if environ is None else environ)
        if login_shell is None:
            import pwd
            login_shell = pwd.getpwuid(os.getuid()).pw_shell
        self.shell = login_shell

    def block(self):
        entry = shlex.quote(str(self.bin_dir))
        pattern = '*' + shlex.quote(':' + str(self.bin_dir) + ':') + '*'
        return (START + '\ncase ":${PATH-}:" in\n  ' + pattern + ') ;;\n'
                '  *) PATH=' + entry + '${PATH:+":$PATH"}; export PATH ;;\nesac\n' + END + '\n').encode()

    def _profiles(self):
        shell = Path(self.shell).name
        if shell == 'zsh':
            if 'ZDOTDIR' in self.environ and not self.environ['ZDOTDIR']:raise PathError('zsh_config_location_invalid')
            directory = _canonical(self.environ.get('ZDOTDIR') or self.home)
            if 'ZDOTDIR' not in self.environ:
                before, _ = _read(self.home / '.zshenv')
                if before and any(re.search(rb'\bZDOTDIR\b', line) for line in before.splitlines() if not line.lstrip().startswith(b'#')):
                    raise PathError('zsh_config_location_unverified:ZDOTDIR_not_exported')
            return [directory / '.zprofile', directory / '.zshrc']
        if shell == 'bash':
            options = [self.home / name for name in ('.bash_profile', '.bash_login', '.profile')]
            login = next((p for p in options if p.exists() or p.is_symlink()), options[0])
            return [login, self.home / '.bashrc']
        raise PathError('login_shell_unsupported')

    def plan(self):
        if Path(self.shell).name not in ('zsh', 'bash'):raise PathError('login_shell_unsupported')
        current = self.environ.get('PATH', '')
        command = shutil.which('mrh', path=current)
        expected = self.bin_dir / 'mrh'
        if command and Path(command).absolute() != expected:
            raise PathError('mrh_command_conflict')
        # Inherited PATH proves only this process; inspect persistent profiles
        # even when a parent shell has already exported our bin directory.
        block = self.block(); rows = []
        for path in self._profiles():
            _canonical(path)
            if path.with_name(path.name + '.zwc').exists():raise PathError('compiled_shell_profile_unverified')
            before, mode = _read(path)
            if before is not None:
                try:before.decode('utf-8')
                except UnicodeError:raise PathError('shell_profile_encoding_unknown') from None
            text = before or b''
            if START.encode() in text or END.encode() in text:
                if text.count(START.encode()) != 1 or text.count(END.encode()) != 1 or block not in text:
                    raise PathError('mrh_shell_block_modified')
                after = text
            else:after = text + (b'\n' if text and not text.endswith(b'\n') else b'') + block
            rows.append({'path': path, 'before': before, 'after': after, 'mode': mode})
        return {'action': 'configure_profiles' if any(r['before'] != r['after'] for r in rows) else 'unchanged',
                'profiles': rows, 'environment': 'login_and_interactive_profiles'}

    def report(self):
        try:plan = self.plan()
        except (OSError, ValueError) as exc:
            return {'future_terminal_ready': False, 'reason': str(exc), 'existing_processes_refreshed': False,
                    'execution_probe_performed': False}
        return {'entrypoint': str(self.bin_dir / 'mrh'), 'login_shell': self.shell,
                'profiles': [str(r['path']) for r in plan['profiles']], 'planned_change': plan['action'],
                'future_terminal_ready': plan['action'] == 'unchanged', 'environment_source': plan['environment'],
                'current_process_ready': shutil.which('mrh', path=self.environ.get('PATH', '')) == str(self.bin_dir / 'mrh'),
                'existing_processes_refreshed': False, 'execution_probe_performed': False}

    def apply(self, plan):
        current = self.plan()
        if current != plan:raise PathError('shell_profile_concurrent_change')
        changed = []
        for row in plan['profiles']:
            path = row['path']
            if row['before'] == row['after']:continue
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            parent = path.parent.stat()
            if parent.st_uid != os.getuid() or parent.st_mode & 0o022:raise PathError('shell_profile_directory_unsafe')
            if _read(path) != (row['before'], row['mode']):raise PathError('shell_profile_concurrent_change')
            owned.replace_owned(path, row['after'], limit=1_000_000, mode=row['mode'])
            changed.append(str(path))
        return {'action': 'configured' if changed else 'unchanged', 'changed_profiles': changed,
                'existing_processes_refreshed': False}


def _shell_files(home, environ):
    """Every startup file an MRH-written block could be in: the login shell may have changed since install. Pairs of
    (path, written_by_install_for_this_shell); the second flag decides whether an unreadable file blocks removal."""
    zsh_dir = environ.get('ZDOTDIR') or str(home)
    bash_login = [home / name for name in ('.bash_profile', '.bash_login', '.profile')]
    rows = [(Path(zsh_dir) / '.zprofile', 'zsh'), (Path(zsh_dir) / '.zshrc', 'zsh')]
    rows += [(path, 'bash') for path in bash_login] + [(home / '.bashrc', 'bash')]
    return rows


def plan_removal(bin_dir, *, user_home=None, environ=None, login_shell=None):
    """Plan taking MRH's PATH block out again. Only a block that is byte-for-byte what setup writes is removed; a block
    somebody edited, or one for another bin directory, is kept and reported. Files that cannot be read safely are
    reported only when they belong to the login shell setup would have used; other shells' files are skipped."""
    environ = dict(os.environ if environ is None else environ)
    home = _canonical(user_home or Path.home())
    if login_shell is None:
        import pwd
        login_shell = pwd.getpwuid(os.getuid()).pw_shell
    block = UserPath(bin_dir, user_home=home, environ=environ, login_shell=login_shell).block()
    shell = Path(login_shell).name
    result = {'remove': [], 'keep': [], 'blocked': []}
    for path, family in _shell_files(home, environ):
        if not path.exists() and not path.is_symlink():
            continue
        try:
            before, mode = _read(path)
        except (OSError, PathError) as exc:
            if family == shell:
                result['blocked'].append({'path': str(path), 'reason': str(exc) if isinstance(exc, PathError) else 'shell_profile_unreadable'})
            continue
        if START.encode() not in before and END.encode() not in before:
            continue
        if before.count(START.encode()) != 1 or before.count(END.encode()) != 1 or before.count(block) != 1:
            result['blocked'].append({'path': str(path), 'reason': 'mrh_shell_block_modified'})
            continue
        after = before.replace(block, b'')
        result['remove'].append({'path': path, 'before': before, 'after': after, 'mode': mode})
    return result


def apply_removal(rows):
    """Write the planned removals; a file that changed since planning is left alone. A file holding only the block
    (setup created it) is removed instead of leaving an empty one behind."""
    changed = []
    for row in rows:
        path = row['path']
        if _read(path) != (row['before'], row['mode']):
            raise PathError('shell_profile_concurrent_change')
        if row['after'] == b'':
            path.unlink()
        else:
            owned.replace_owned(path, row['after'], limit=1_000_000, mode=row['mode'])
        changed.append(str(path))
    return changed
