#!/usr/bin/env python3
"""E15 actual unpacked entry/relocation/keyboard/plugin, no real provider."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
import argparse
import errno
import fcntl
import hashlib
import json
import os
import pty
import re
import select
import shutil
import signal
import struct
import subprocess
import tempfile
import termios
import time

PROJECT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT))
from mrh_bundle import extract_runtime, sha256


def inspect(archive):
    started = time.monotonic(); commands = []; pids = []; captures = {}
    with tempfile.TemporaryDirectory(prefix='mrh-e15-verify-', dir='/private/tmp') as tmp:
        root = Path(tmp).resolve()
        for name in ('home', 'bin', 'work', 'first', 'Moved MRH With Spaces'):
            (root / name).mkdir()
        initial = root / 'first/application'
        # Only the exact locally built archive is extracted, through the same
        # path/link/type guard used for the pinned runtime.
        prefix = archive.name.removesuffix('.tar.gz')
        extract_runtime(archive, initial, prefix=prefix)
        env = {'PATH': str(root / 'bin'), 'HOME': str(root / 'home'), 'TMPDIR': str(root),
               'LANG': 'en_US.UTF-8', 'TERM': 'xterm-256color', 'NO_COLOR': '1'}
        def run(args):
            proc = subprocess.Popen(list(map(str, args)), cwd=root / 'work', env=env,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
            pids.append(proc.pid)
            try:
                out, err = proc.communicate(timeout=30)
            except BaseException:
                if proc.poll() is None and os.getpgid(proc.pid) == proc.pid:
                    os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(); raise
            commands.append({'argv': list(map(str, args)), 'exit': proc.returncode, 'stderr': err[:500]})
            assert proc.returncode == 0, err[:500]
            return out
        run([initial / 'mrh', '--help'])
        moved = root / 'Moved MRH With Spaces/application'
        initial.rename(moved); entry = moved / 'mrh'; python = moved / 'runtime/bin/python3.11'
        run([entry, '--help']); doctor = run([entry, 'doctor', '--plain'])
        assert 'Credentials and network: not probed' in doctor
        (root / 'bin/mrh').symlink_to(entry)
        run(['mrh', '--help'])
        def private(code, *args):
            return run([python, '-I', '-B', '-c', "import sys;sys.path.insert(0,sys.argv[1]);" + code, moved / 'app/mrh.pyz', *args])
        identity = json.loads(private("import mrh,sysconfig,json,ssl,zlib,sqlite3;print(json.dumps({'executable':sys.executable,'prefix':sys.prefix,'sys_path':sys.path,'stdlib':sysconfig.get_path('stdlib'),'mrh':mrh.__file__,'version':sys.version,'isolated':sys.flags.isolated,'no_bytecode':sys.flags.dont_write_bytecode,'ssl':ssl.OPENSSL_VERSION,'ca_stats':ssl.create_default_context().cert_store_stats(),'zlib':zlib.ZLIB_RUNTIME_VERSION,'sqlite':sqlite3.sqlite_version}))"))
        assert Path(identity['executable']).is_relative_to(moved)
        assert all(Path(p).is_relative_to(moved) for p in identity['sys_path'])
        assert identity['isolated'] == 1 and identity['no_bytecode'] == 1
        assert '/app/mrh.pyz/mrh/' in identity['mrh']
        assert not any((root / 'bin' / n).exists() for n in ('python', 'python3', 'node', 'uv'))
        state = root / 'external-profile/settings.json'
        run([entry, 'settings', 'init', '--path', state])
        settings = json.loads(run([entry, 'settings', 'show', '--path', state]))
        assert settings['settings']['enabled'] is False
        # Both vendor binaries are existing native installations, not copied
        # SDKs/Node wrappers. Ordinary platform utility aliases are permitted.
        codex = Path('/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex')
        claude = Path('/opt/homebrew/bin/claude').resolve()
        assert codex.is_file() and claude.is_file()
        for name, path in [('codex', codex), ('claude', claude), ('dirname', Path('/usr/bin/dirname')),
                           ('readlink', Path('/usr/bin/readlink'))]:
            (root / 'bin' / name).symlink_to(path)
        candidates = json.loads(private("import json;from mrh.adapters.catalogs.catalog import discover;print(json.dumps(discover()))"))
        claude_index = next(i for i, c in enumerate(candidates) if c['tool'] == 'claude' and c['supported'])
        codex_index = next(i for i, c in enumerate(candidates) if c['tool'] == 'codex' and c['supported'])
        def terminal(args, answers):
            pid, fd = pty.fork()
            if pid == 0:
                os.chdir(root / 'work'); os.execve(str(args[0]), list(map(str, args)), env)
            pids.append(pid); fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack('HHHH', 24, 56, 0, 0))
            data = bytearray(); consumed = 0; index = 0; deadline = time.monotonic() + 30; waited = False
            try:
                while True:
                    if time.monotonic() > deadline:
                        raise TimeoutError('standalone_keyboard_deadline')
                    if not select.select([fd], [], [], .2)[0]: continue
                    try: chunk = os.read(fd, 65536)
                    except OSError as exc:
                        if exc.errno == errno.EIO: break
                        raise
                    if not chunk: break
                    data.extend(chunk)
                    if index < len(answers):
                        heading, keys = answers[index]; pos = data.find(heading.encode(), consumed)
                        if pos >= 0:
                            consumed = pos + len(heading); os.write(fd, keys); index += 1
                _, status = os.waitpid(pid, 0); waited = True
                assert os.waitstatus_to_exitcode(status) == 0, data[-1000:]
                assert index == len(answers), (index, data[-1000:])
            finally:
                if not waited:
                    try:
                        if os.getpgid(pid) == pid: os.killpg(pid, signal.SIGKILL)
                    except ProcessLookupError: pass
                    os.waitpid(pid, 0)
                os.close(fd)
            commands.append({'argv': list(map(str, args)), 'exit': 0, 'pty': [24, 56],
                             'keys': [k.decode() for _, k in answers]})
            plain = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', data.decode())
            return '\n'.join(line.rstrip() for line in plain.splitlines()).rstrip() + '\n'
        down = b'\x1b[B'; enter = b'\r'; registry = root / 'bindings'
        args = [entry, 'model', 'light', '--root', registry, '--width', '56', '--plain']
        captures['save'] = terminal(args, [('FIRST USE', down * claude_index + enter), ('CONFIRM MRH PROFILE', enter),
                                           ('Light MODEL', down + enter), ('REASONING EFFORT', down + enter), ('SAVE POLICY?', enter)])
        binding = json.loads((registry / 'registry.json').read_text())['bindings'][0]
        saved = Path(binding['settings_path']); before = saved.read_bytes(); value = json.loads(before)
        assert value['revision'] == 1 and value['policy']['tiers']['Light'] == {'model': 'opus[1m]', 'effort': 'low'}
        assert not value['enabled'] and not value['task_export_permitted'] and value['allowed_workspaces'] == []
        captures['cancel'] = terminal(args, [('Light MODEL', down + enter), ('REASONING EFFORT', down + enter),
                                             ('SAVE POLICY?', down * 2 + enter)])
        assert saved.read_bytes() == before
        captures['codex-metadata-cancel'] = terminal(args + ['--bind'], [('FIRST USE', down * codex_index + enter),
                                                                      ('CONFIRM MRH PROFILE', enter), ('Light MODEL', b'\x1b')])
        bindings = json.loads((registry / 'registry.json').read_text())['bindings']
        assert len(bindings) == 2
        assert {b['tool'] for b in bindings} == {'codex', 'claude'}
        for b in bindings:
            assert b['catalog']['assurance'] == 'tool-advertised' and b['catalog']['models']
            assert not json.loads(Path(b['settings_path']).read_text())['enabled']
        stats = json.loads(run([entry, 'stats', '--settings', saved, '--json']))
        assert stats['proposals'] == 0 and stats['jev_attempts'] == 0
        plugin = json.loads(run([entry, 'plugin', 'prepare', '--root', root / 'plugin', '--settings', state]))
        private_python = Path(plugin['artifact']['python'])
        assert private_python == python.resolve()
        launcher = root / 'plugin/plugins/model-routing-harness/launcher.py'
        event = {'hook_event_name': 'PreToolUse', 'tool_name': 'spawn_agent', 'session_id': 's', 'turn_id': 't',
                 'tool_use_id': 'c', 'cwd': str(root / 'work'), 'tool_input': {'message': 'isolated default-off fixture'}}
        def invoke():
            p = subprocess.run([str(private_python), "-B", '-I', str(launcher)], input=json.dumps(event),
                               env=env, cwd=root / 'work', capture_output=True, text=True, timeout=10)
            assert p.returncode == 0 and not p.stderr
            return json.loads(p.stdout)
        assert invoke() == {}
        (launcher.parent / 'runtime.pyz').write_bytes(b'owned fixture integrity failure')
        warning = invoke(); assert set(warning) == {'systemMessage'}
        assert 'original tool call preserved' in warning['systemMessage']
        assert 'integrity verification failed' in warning['systemMessage']
        assert not (state.parent / 'events.sqlite3').exists()
        result = {'artifact': str(archive), 'artifact_sha256': sha256(archive), 'private_runtime': identity,
                  'entry_help_doctor_and_owned_path_symlink': True, 'moved_path_contains_spaces': str(moved),
                  'fresh_home': str(root / 'home'), 'controlled_path': env['PATH'], 'developer_pythonpath': False,
                  'external_python_node_sdk_needed': False, 'commands': commands, 'keyboard': 'directional keys/Enter; Escape only to cancel Codex metadata screen',
                  'save': value, 'cancel_policy_bytes_unchanged': True,
                  'catalogs': [{'tool': b['tool'], 'version': b['version'], 'executable_sha256': b['executable_sha256'],
                                'snapshot': b['catalog']} for b in bindings],
                  'plugin_interpreter': str(private_python), 'plugin_default_disabled': True,
                  'plugin_integrity_warning': warning, 'real_provider_requests': 0, 'formal_registration': False,
                  'owned_pids': pids, 'owned_root': str(root), 'captures': captures}
    result.update(owned_root_absent=not root.exists(), elapsed_seconds=round(time.monotonic() - started, 3))
    assert result['owned_root_absent']
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True); args = parser.parse_args()
    evidence = inspect(args.archive.resolve())
    for name, text in evidence.pop('captures').items():
        (args.output.parent / ('e15-' + name + '.txt')).write_text(text)
    args.output.write_text(json.dumps(evidence, indent=2) + '\n')
    print(json.dumps({'standalone_entry': True, 'moved_path': True, 'keyboard_save_cancel': True,
                      'catalog_tools': [x['tool'] for x in evidence['catalogs']], 'private_plugin_interpreter': True,
                      'owned_root_absent': evidence['owned_root_absent'], 'seconds': evidence['elapsed_seconds']}))
