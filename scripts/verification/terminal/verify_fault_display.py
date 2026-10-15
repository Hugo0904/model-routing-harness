#!/usr/bin/env python3
"""E14's affected compact footer, actual 24x56/120 Screen-backed PTYs."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
import argparse
import fcntl
import json
import os
import pty
import struct
import tempfile
import termios

from mrh.adapters.hosts.codex import handle_event
from mrh.routing.core import ScriptedClassifier
from mrh.infrastructure.store import Store
from mrh.presentation.terminal import cell_width
from scripts.verification.terminal.verify_model_navigation import (SCREEN, REPO, _check_emulator_prerequisites, _read_until,
                                    _drain_quiet, _hardcopy, _finish_cli, _stop_child)

CHILD = '''import fcntl,json,os,struct,termios
from mrh.presentation import cli
size=struct.unpack('HHHH',fcntl.ioctl(0,termios.TIOCGWINSZ,b'\\0'*8))[:2]
assert size==(24,int(os.environ['MRH_FAULT_WIDTH']))
assert cli.main(['stats','--db',os.environ['MRH_FAULT_DB'],'--synthetic'])==0
print('MRH_FAULT_DISPLAY_READY',flush=True)
input()
'''


def inspect():
    emulator = _check_emulator_prerequisites(); captures = []
    with tempfile.TemporaryDirectory(prefix='mrh-e14-screen-', dir='/private/tmp') as directory:
        root = Path(directory).resolve(); store = Store(root / 'events.sqlite3')
        def event(call, **extra):
            return {'hook_event_name': 'PreToolUse', 'tool_name': 'spawn_agent', 'session_id': 'synthetic-session',
                    'turn_id': 'turn', 'tool_use_id': call, 'tool_input': {'message': 'isolated display fixture', **extra}}
        handle_event(event('fault'), store, True, classifier=ScriptedClassifier([RuntimeError('FIXTURE_ERROR_CANARY')]))
        handle_event(event('normal', model='explicit-model'), store, True, classifier=ScriptedClassifier([]))
        before = store.stats(True)
        for width in (56, 120):
            sockets = root / ('sockets-' + str(width)); sockets.mkdir(mode=0o700)
            session = 'mrhfault-' + str(os.getpid()) + '-' + str(width)
            env = {'HOME': str(root), 'TMPDIR': str(root), 'PATH': '/usr/bin:/bin', 'TERM': 'xterm',
                   'SCREENDIR': str(sockets), 'PYTHONPATH': str(REPO / 'src'), 'PYTHONDONTWRITEBYTECODE': '1',
                   'MRH_FAULT_WIDTH': str(width), 'MRH_FAULT_DB': str(store.path)}
            pid, fd = pty.fork()
            if pid == 0:
                fcntl.ioctl(0, termios.TIOCSWINSZ, struct.pack('HHHH', 24, width, 0, 0))
                os.execve(str(SCREEN), [str(SCREEN), '-c', '/dev/null', '-S', session, '-T', 'xterm', '-U', sys.executable, "-B", '-c', CHILD], env)
            fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack('HHHH', 24, width, 0, 0))
            output = bytearray()
            try:
                _read_until(fd, pid, output, b'MRH_FAULT_DISPLAY_READY'); _drain_quiet(fd, output)
                lines = _hardcopy(env, session, sockets / 'capture.txt')
                compact = ''.join(''.join(lines).split())
                for expected in ('Faultfallbackproposals1/normalretention1', 'Faultstate:Activefault/activesessions1',
                                 'Faultobservations1/warningclaims1/recoveries0', '--detailsfulltelemetry'):
                    assert expected in compact, 'affected_footer_missing_at_' + str(width)
                assert max(map(cell_width, lines)) <= width
                os.write(fd, b'\r'); code = _finish_cli(pid, fd, output); assert code == 0
                captures.append({'columns': width, 'rows': 24, 'pid': pid, 'exit': code,
                                 'screen_state_consumer': 'GNU Screen VT100/ANSI virtual display',
                                 'affected_footer_visible': True, 'max_cell_width': max(map(cell_width, lines)), 'lines': lines})
            finally:
                _stop_child(pid, fd, env, session)
        assert store.stats(True) == before, 'display_changed_history'
    return {'emulator': emulator, 'captures': captures, 'canonical_history_unchanged': True,
            'owned_root': str(root), 'owned_root_absent': not root.exists(), 'screenshots': 'none'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); result = inspect(); args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'widths': [x['columns'] for x in result['captures']], 'affected_footer_visible': True,
                      'canonical_history_unchanged': True, 'owned_root_absent': result['owned_root_absent']}))
