#!/usr/bin/env python3
"""Verify MRH navigation in Screen-backed PTYs at 56 and 120 columns."""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))


import fcntl
import json
import os
import pty
import select
import struct
import subprocess
import tempfile
import termios
import time

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO/'src'))

from mrh.infrastructure.bindings import Registry
from mrh.adapters.catalogs.catalog import executable_hash
from mrh.infrastructure.settings import read as read_settings
from mrh.presentation.terminal import cell_width


SCREEN = Path('/usr/bin/screen')
_CHILD = r'''import os, time, fcntl, struct, termios
from mrh.presentation import cli
from mrh.adapters.catalogs.catalog import Catalog, Model

rows, columns, _, _ = struct.unpack('HHHH', fcntl.ioctl(0, termios.TIOCGWINSZ, b'\0' * 8))
if (rows, columns) != (24, int(os.environ['MRH_NAV_WIDTH'])):
    raise RuntimeError(f'inner Screen PTY size mismatch: {(rows, columns)!r}')

class Provider:
    def refresh(self, binding):
        if os.environ['MRH_NAV_MODE'] == 'screen':
            models = tuple(Model(f'screen-choice-{i}', f'Wrapped item {i}: ' + ('long wrapped row fragment ' * 6) + f' TAIL-ITEM-{i}', ('low', 'high')) for i in range(1, 5))
        else:
            models = (Model('fixture-small-id', 'Fixture Small', ('low', 'high')),
                      Model('fixture-top-id', 'Fixture Top', ('high',)))
        return Catalog(binding['id'], binding['tool'], binding['executable_sha256'], binding['version'],
                       'synthetic:e10r-navigation', time.time(), models, assurance='synthetic')

raise SystemExit(cli.main(['model', 'light', '--root', os.environ['MRH_NAV_ROOT'],
                           '--plain', '--width', os.environ['MRH_NAV_WIDTH']],
                          model_dependencies={'provider': Provider()}))
'''


def _check_emulator_prerequisites() -> str:
    if not SCREEN.is_file() or not os.access(SCREEN, os.X_OK):
        raise RuntimeError(f'required terminal emulator is missing or not executable: {SCREEN}')
    result = subprocess.run([str(SCREEN), '--version'], capture_output=True, text=True, timeout=5)
    if 'Screen version ' not in result.stdout:
        raise RuntimeError('cannot inspect terminal emulator: '+(result.stderr or result.stdout).strip())
    return result.stdout.strip()


def _fixture_binding(root: Path):
    exe = str(Path('/usr/bin/true').resolve())
    candidate = {'tool': 'codex', 'label': 'Synthetic E10R navigation fixture', 'executable': exe,
                 'executable_sha256': executable_hash(exe), 'version': 'synthetic-E10R-fixture',
                 'supported': True}
    return Registry(root).associate(candidate, expected_revision=0)


def _spawn_cli(root: Path, width: int, mode: str):
    socket_dir = root.parent/(root.name+'-screen-sockets')
    socket_dir.mkdir(mode=0o700)
    os.chmod(socket_dir, 0o700)
    session = f'mrhnav-{os.getpid()}-{width}-{mode}'
    env = os.environ.copy()
    env.update(HOME=str(root.parent), SCREENDIR=str(socket_dir), TERM='xterm', COLUMNS=str(width), LINES='24',
               PYTHONPATH=os.pathsep.join(filter(None, (str(REPO/'src'), env.get('PYTHONPATH', '')))),
               MRH_NAV_ROOT=str(root), MRH_NAV_WIDTH=str(width), MRH_NAV_MODE=mode)
    pid, fd = pty.fork()
    if pid == 0:
        fcntl.ioctl(0, termios.TIOCSWINSZ, struct.pack('HHHH', 24, width, 0, 0))
        argv = [str(SCREEN), '-c', '/dev/null', '-S', session, '-T', 'xterm', '-U', sys.executable, '-c', _CHILD]
        try:
            os.execve(str(SCREEN), argv, env)
        except BaseException as exc:
            os.write(2, (type(exc).__name__+': '+str(exc)+'\n').encode())
            os._exit(127)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack('HHHH', 24, width, 0, 0))
    return pid, fd, env, session, socket_dir


def _read_until(fd: int, pid: int, output: bytearray, marker: bytes, *, after: int = 0,
                timeout: float = 10) -> None:
    deadline = time.monotonic()+timeout
    while marker not in output[after:]:
        ready, _, _ = select.select([fd], [], [], max(0, deadline-time.monotonic()))
        if not ready:
            raise RuntimeError(f'PTY timed out waiting for {marker!r}; recent output={bytes(output[-600:])!r}')
        try:
            chunk = os.read(fd, 65536)
        except OSError:
            chunk = b''
        if not chunk:
            waited, status = os.waitpid(pid, os.WNOHANG)
            raise RuntimeError(f'PTY exited before {marker!r}; pid={waited or pid} status={status}; recent output={bytes(output[-600:])!r}')
        output.extend(chunk)


def _pty_size(fd: int) -> tuple[int, int]:
    rows, columns, _, _ = struct.unpack('HHHH', fcntl.ioctl(fd, termios.TIOCGWINSZ, b'\0' * 8))
    return rows, columns


def _drain_quiet(fd: int, output: bytearray, quiet: float = .12, timeout: float = 2) -> None:
    deadline = time.monotonic()+timeout
    while time.monotonic() < deadline:
        ready, _, _ = select.select([fd], [], [], quiet)
        if not ready:
            return
        try:
            chunk = os.read(fd, 65536)
        except OSError:
            return
        if not chunk:
            return
        output.extend(chunk)
    raise RuntimeError('PTY output did not become quiet')


def _screen_command(env: dict, session: str, *args: str) -> None:
    result = subprocess.run([str(SCREEN), '-c', '/dev/null', '-S', session, *args], env=env,
                            capture_output=True, text=True, timeout=5)
    if result.returncode:
        raise RuntimeError(f'Screen command {args!r} failed: {result.stdout.strip()} {result.stderr.strip()}')


def _hardcopy(env: dict, session: str, path: Path) -> list[str]:
    path.unlink(missing_ok=True)
    _screen_command(env, session, '-p', '0', '-X', 'hardcopy', str(path))
    # The inner child verifies its real geometry before rendering. Do not
    # resize Screen after drawing: it can invalidate the captured display.
    # IPC acknowledgement also precedes the asynchronous hardcopy write.
    deadline = time.monotonic()+1
    previous_size = 0
    while time.monotonic() < deadline:
        size = path.stat().st_size if path.is_file() else 0
        if size > 0 and size == previous_size:
            break
        previous_size = size
        time.sleep(.02)
    if not path.is_file() or not path.stat().st_size:
        raise RuntimeError('Screen did not produce a virtual-screen hardcopy')
    lines = [line.rstrip() for line in path.read_text(encoding='utf-8', errors='replace').splitlines()]
    path.unlink()
    return lines


def _finish_cli(pid: int, fd: int, output: bytearray, timeout: float = 10) -> int:
    deadline = time.monotonic()+timeout
    while time.monotonic() < deadline:
        ready, status = os.waitpid(pid, os.WNOHANG)
        if ready:
            return os.waitstatus_to_exitcode(status)
        if select.select([fd], [], [], .05)[0]:
            try:
                chunk = os.read(fd, 65536)
            except OSError:
                chunk = b''
            if chunk:
                output.extend(chunk)
    raise RuntimeError('PTY child did not exit')


def _stop_child(pid: int, fd: int, env: dict, session: str) -> None:
    def exited() -> bool:
        try:
            ready, _ = os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            return True
        return bool(ready)

    try:
        if not exited():
            try:
                _screen_command(env, session, '-X', 'quit')
            except (OSError, subprocess.SubprocessError, RuntimeError):
                try:
                    os.write(fd, b'\x03')
                except OSError:
                    pass
            deadline = time.monotonic()+3
            while time.monotonic() < deadline:
                if exited():
                    break
                try:
                    if select.select([fd], [], [], .05)[0]:os.read(fd, 65536)
                except OSError:
                    break
            if not exited():
                raise RuntimeError('Screen PTY process did not exit during cleanup')
    finally:
        try:
            os.close(fd)
        except OSError:
            pass


def _edit_walk(root: Path) -> dict:
    binding = _fixture_binding(root)
    pid, fd, env, session, _ = _spawn_cli(root, 120, 'edit')
    output = bytearray()
    try:
        rows, columns = _pty_size(fd)
        if (rows, columns) != (24, 120):
            raise RuntimeError(f'edit PTY size mismatch: {(rows, columns)!r}')
        _read_until(fd, pid, output, b'Light MODEL')
        os.write(fd, b'\r')
        _read_until(fd, pid, output, b'REASONING EFFORT')
        os.write(fd, b'\x1b[D')
        model_start = len(output)
        _read_until(fd, pid, output, b'Light MODEL', after=model_start)
        os.write(fd, b'\x1b[B\r')
        effort_start = len(output)
        _read_until(fd, pid, output, b'REASONING EFFORT', after=effort_start)
        os.write(fd, b'\x1b[B\r')
        _read_until(fd, pid, output, b'SAVE POLICY?')
        os.write(fd, b'\r')
        _read_until(fd, pid, output, b'Saved.')
        code = _finish_cli(pid, fd, output)
        saved = read_settings(binding['settings_path'])
        expected = {'model': 'fixture-top-id', 'effort': 'high'}
        if code != 0 or saved['policy']['tiers'].get('Light') != expected or saved['revision'] != 1:
            raise RuntimeError(f'PTY back/change/save failed: exit={code}, revision={saved["revision"]}, policy={saved["policy"]["tiers"]!r}')
        return {'exit': code, 'revision': saved['revision'], 'Light': saved['policy']['tiers']['Light'],
                'enabled': saved['enabled'], 'task_export_permitted': saved['task_export_permitted'],
                'pty_rows': rows, 'pty_columns': columns, 'fixture_root': str(root),
                'profile_settings_path': binding['settings_path']}
    finally:
        _stop_child(pid, fd, env, session)


def _screen_walk(root: Path, width: int) -> dict:
    binding = _fixture_binding(root)
    original_settings = Path(binding['settings_path']).read_bytes()
    pid, fd, env, session, socket_dir = _spawn_cli(root, width, 'screen')
    output = bytearray()
    try:
        rows, columns = _pty_size(fd)
        if (rows, columns) != (24, width):
            raise RuntimeError(f'Screen PTY size mismatch at {width} columns: {(rows, columns)!r}')
        _read_until(fd, pid, output, b'Light MODEL')
        _drain_quiet(fd, output)
        captures = []

        def capture(expected: str) -> dict:
            screen = {'lines': _hardcopy(env, session, socket_dir/'screen.txt'),
                      'pty_rows': rows, 'pty_columns': columns, 'redraws': len(captures)}
            summary = _assert_screen(screen, width, expected)
            captures.append(summary)
            return summary

        capture('> 1. Wrapped item 1:')
        for key, expected in zip((b'\x1b[B', b'\x1b[B', b'\x1b[B', b'\x1b[B', b'\x1b[A'),
                                 ('> 2. Wrapped item 2:', '> 3. Wrapped item 3:', '> 4. Wrapped item 4:',
                                  '> 5. Cancel;', '> 4. Wrapped item 4:')):
            os.write(fd, key)
            deadline = time.monotonic()+3
            while True:
                _drain_quiet(fd, output, quiet=.05)
                lines = _hardcopy(env, session, socket_dir/'screen.txt')
                if any(line.strip().startswith(expected) for line in lines):
                    capture(expected)
                    break
                if time.monotonic() >= deadline:
                    raise RuntimeError(f'Screen did not focus {expected!r} at {width} columns: {lines!r}')
                time.sleep(.05)
        os.write(fd, b'\x1b')
        _read_until(fd, pid, output, b'Cancelled.')
        code = _finish_cli(pid, fd, output)
        if code != 0:
            raise RuntimeError(f'PTY screen walk exited {code}')
        saved = read_settings(binding['settings_path'])
        if Path(binding['settings_path']).read_bytes() != original_settings:
            raise RuntimeError(f'PTY cancel wrote the profile settings at {width} columns')
        if saved['revision'] != 0 or saved['policy']['tiers']:
            raise RuntimeError(f'PTY cancel changed the profile policy at {width} columns')
        return {'width': width, 'pty_rows': rows, 'pty_columns': columns, 'redraws': len(captures)-1,
                'states': [{key:value for key,value in state.items() if key != 'screen_state'} for state in captures],
                'final_screen_state': captures[-1]['screen_state'], 'settings_revision': saved['revision'],
                'fixture_root': str(root), 'profile_settings_path': binding['settings_path'],
                'screen_socket_dir': str(socket_dir)}
    finally:
        _stop_child(pid, fd, env, session)


def _assert_screen(screen: dict, width: int, expected_focus: str) -> dict:
    lines = screen['lines']
    titles = [line for line in lines if 'Light MODEL' in line]
    focused = [line.strip() for line in lines if line.lstrip().startswith('> ')]
    if (len(titles) != 1 or len(focused) != 1 or not focused[0].startswith(expected_focus) or
            max(cell_width(line) for line in lines) > width):
        raise RuntimeError(f'virtual-screen redraw/focus mismatch at {width}: titles={titles!r}, focus={focused!r}, screen={lines!r}')
    for index in range(1, 5):
        if sum(f'Wrapped item {index}:' in line for line in lines) != 1:
            raise RuntimeError(f'wrapped choice {index} was stale or missing at {width}: {lines!r}')
        if sum(f'TAIL-ITEM-{index}' in line for line in lines) != 1:
            raise RuntimeError(f'wrapped choice tail {index} was stale or missing at {width}: {lines!r}')
    if sum('Cancel; keep policy and exit' in line for line in lines) != 1:
        raise RuntimeError(f'cancel choice was stale or missing at {width}: {lines!r}')
    return {'width': width, 'pty_rows': screen['pty_rows'], 'redraws': screen['redraws'],
            'pty_columns': screen['pty_columns'], 'visible_rows': len(lines),
            'titles_on_screen': len(titles), 'focus': focused[0], 'wrapped_choices': 4,
            'cancel_choices': 1, 'max_cell_width': max(cell_width(line) for line in lines),
            'screen_state': lines, 'screen_state_consumer': 'GNU Screen VT100/ANSI virtual display'}


def main() -> int:
    emulator = _check_emulator_prerequisites()
    temporary = tempfile.TemporaryDirectory(prefix='mrh-e10r-navigation-', dir='/private/tmp')
    temporary_path = Path(temporary.name).resolve()
    try:
        edit = _edit_walk(temporary_path/'edit-registry')
        screen_checks = [_screen_walk(temporary_path/f'screen-{width}', width) for width in (56, 120)]
    finally:
        temporary.cleanup()
    profile_paths = [Path(result['profile_settings_path']) for result in [edit, *screen_checks]]
    socket_paths = [Path(result['screen_socket_dir']) for result in screen_checks]
    cleanup = {'owned_temp_root': str(temporary_path), 'owned_temp_root_removed': not temporary_path.exists(),
               'profile_settings_paths_removed': [not path.exists() for path in profile_paths],
               'screen_socket_paths_removed': [not path.exists() for path in socket_paths],
               'hardcopies_removed': True}
    if (not cleanup['owned_temp_root_removed'] or not all(cleanup['profile_settings_paths_removed']) or
            not all(cleanup['screen_socket_paths_removed'])):
        raise RuntimeError(f'fixture cleanup failed: {cleanup!r}')
    print(json.dumps({'emulator': emulator, 'pty_back_change_save': edit, 'screen_checks': screen_checks,
                      'fixture_cleanup': cleanup, 'screenshots': 'none'},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f'FAIL: {type(exc).__name__}: {exc}', file=sys.stderr)
        raise SystemExit(1)
