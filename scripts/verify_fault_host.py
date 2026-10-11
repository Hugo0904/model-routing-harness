#!/usr/bin/env python3
"""E14: installed Hook warnings and original dispatch, owned loopback fixture.

Reuses E4/E5's native protocol/trust helpers. No account authentication, real
model, global Hook registration or source build. Desktop UI is not inspected.
"""
import argparse
import copy
import fcntl
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import pty
import re
import select
import shlex
import struct
import subprocess
import sys
import termios
import threading
import time

from mrh import plugin, settings
from mrh.store import Store
from verify_host import CATALOG_HASHES, OwnedScratch, Fixture, Rpc, trust_fixture, curate_events, stop_owned
from verify_plugin_host import BOOTSTRAP


def native_terminal(binary, env, work, scope, fixture):
    """Capture actual 30x100 PTY output, never substitute event logs for UI."""
    fixture.scenario = 'failure'; fixture.step = 0
    request_start = len(fixture.requests)
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 30, 100, 0, 0))
    proc = subprocess.Popen([binary, '--no-daemon', '--no-alt-screen', '-C', str(work)],
                            stdin=slave, stdout=slave, stderr=slave, env=env, cwd=work,
                            start_new_session=True, preexec_fn=lambda: fcntl.ioctl(0, termios.TIOCSCTTY, 0))
    scope.processes.append(proc); os.close(slave)
    captured = bytearray()
    def pump():
        if select.select([master], [], [], .1)[0]:
            try:
                chunk = os.read(master, 65536)
            except OSError:
                return
            captured.extend(chunk)
            if b'\x1b[6n' in chunk: os.write(master, b'\x1b[1;1R')
            if b'\x1b[c' in chunk: os.write(master, b'\x1b[?1;2c')
    def plain():
        return re.sub(rb'\x1b\[[0-?]*[ -/]*[@-~]', b'', captured)
    try:
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            pump()
            compact = re.sub(rb'\s+', b'', plain())
            if any(needle in compact for needle in (b'Togetstarted', b'mrh-synthetic-parent', b'MRHsyntheticparent')):
                break
        else:
            raise RuntimeError('native_terminal_start_unverified:' + plain().decode(errors='replace')[-1800:])
        os.write(master, b'MRH_PARENT_launcher_fault synthetic fixture\r')
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            pump()
            compact = re.sub(rb'\s+', b'', plain())
            requests = fixture.requests[request_start:]
            if b'runtimeintegrityverificationfailed' in compact and any(not r['is_parent'] for r in requests) and b'MRHscriptedfixturecomplete.' in compact:
                break
        requests = copy.deepcopy(fixture.requests[request_start:])
        text = plain().decode(errors='replace')
        compact = re.sub(r'\s+', '', text)
        visible = 'runtimeintegrityverificationfailed' in compact and 'originaltoolcallpreserved' in compact
        child_requests = [r for r in requests if not r['is_parent']]
        assert child_requests, 'native_terminal_original_child_missing'
        assert all(r['model'] == 'mrh-synthetic-parent' and r['reasoning']['effort'] == 'low' for r in requests), 'original_model_or_effort_changed'
        assert 'CANARY' not in text, 'raw_runtime_error_leaked'
        return {'warning_visible_in_actual_terminal': visible,
                'terminal_geometry': {'rows': 30, 'columns': 100},
                'scripted_child_requests': len(child_requests), 'requests': requests,
                'original_dispatch_preserved': True, 'transcript': text}
    finally:
        try:
            os.write(master, b'\x03'); pump(); os.write(master, b'\x03')
            stop_owned(proc, pump)
        finally:
            os.close(master)


def inspect(binary):
    started = time.monotonic(); fixture = Fixture('failure')
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_): pass
        def do_POST(self):
            assert self.path.endswith('/responses') and self.headers.get('Authorization') is None
            size = int(self.headers['Content-Length']); assert size <= 2_000_000
            output = fixture.response(json.loads(self.rfile.read(size)), self.headers)
            rid = 'response-' + str(len(fixture.requests))
            events = [{'type': 'response.created', 'response': {'id': rid, 'status': 'in_progress', 'output': []}}]
            for index, item in enumerate(output):
                events.extend([{'type': 'response.output_item.added', 'output_index': index, 'item': item},
                               {'type': 'response.output_item.done', 'output_index': index, 'item': item}])
            events.append({'type': 'response.completed', 'response': {'id': rid, 'status': 'completed', 'output': output,
                          'usage': {'input_tokens': 1, 'output_tokens': 1, 'total_tokens': 2, 'input_tokens_details': {'cached_tokens': 0}}}})
            data = ''.join('data: ' + json.dumps(e) + '\n\n' for e in events).encode()
            self.send_response(200); self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler); server.daemon_threads = True
    serving = threading.Thread(target=server.serve_forever, daemon=True); serving.start()
    scope = OwnedScratch()
    result = {'evidence_kind': 'installed_native_plugin_scripted_loopback_provider',
              'real_provider_requests': 0, 'formal_global_changes': False, 'desktop_ui_validation': False,
              'cases': [], 'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    try:
        with scope as alias:
            root = alias.resolve(); home = root / 'home'; work = root / 'workspace'; home.mkdir(); work.mkdir()
            env = {'PATH': str(Path(binary).parent) + ':/usr/bin:/bin:/usr/sbin:/sbin',
                   'HOME': str(root), 'CODEX_HOME': str(home), 'TMPDIR': str(root),
                   'LANG': 'en_US.UTF-8', 'TERM': 'xterm-256color'}
            def command(args):
                run = subprocess.run(args, cwd=work, env=env, capture_output=True, text=True, timeout=30)
                assert run.returncode == 0, 'native_fixture_command_failed'
                return json.loads(run.stdout) if run.stdout.strip().startswith(('{', '[')) else run.stdout.strip()
            version = command([binary, '--version']).split()[-1]
            assert version == '0.159.3', 'exact_native_version_required'
            result.update(version=version, binary=binary, binary_sha256=hashlib.sha256(Path(binary).read_bytes()).hexdigest())
            catalog_source = root / 'public-catalog.json'
            command(['/usr/bin/curl', '--fail', '--silent', '--show-error', '--location', '--max-time', '20',
                     'https://raw.githubusercontent.com/openai/codex/rust-v' + version + '/codex-rs/models-manager/models.json', '-o', str(catalog_source)])
            original = catalog_source.read_bytes(); digest = hashlib.sha256(original).hexdigest()
            assert digest == CATALOG_HASHES[version], 'catalog_pin_mismatch'
            entry = next(x for x in json.loads(original)['models'] if x['slug'] == 'gpt-6.1-sol')
            aliases = []
            for suffix, effort in (('parent', 'low'), ('fixed', 'high')):
                model = copy.deepcopy(entry)
                model.update(slug='mrh-synthetic-' + suffix, display_name='MRH synthetic ' + suffix,
                             description='Scripted loopback fixture only; no actual model', upgrade=None,
                             availability_nux=None, default_reasoning_level=effort, tool_mode=None,
                             multi_agent_version='v1', use_responses_lite=False, supports_search_tool=False)
                aliases.append(model)
            catalog = root / 'models.json'; catalog.write_text(json.dumps({'models': aliases}))
            result['catalog'] = {'tag': 'rust-v' + version, 'sha256': digest, 'synthetic_overrides': True}
            (home / 'config.toml').write_text('model="mrh-synthetic-parent"\nmodel_reasoning_effort="low"\nmodel_provider="mrh_fixture"\nmodel_catalog_json=' + json.dumps(str(catalog)) + '\nsandbox_mode="workspace-write"\napproval_policy="never"\n[model_providers.mrh_fixture]\nname="MRH loopback"\nbase_url="http://127.0.0.1:' + str(server.server_address[1]) + '/v1"\nrequires_openai_auth=false\nwire_api="responses"\nrequest_max_retries=0\nstream_max_retries=0\n[analytics]\nenabled=false\n')
            state = root / 'state/settings.json'; bundle = root / 'bundle'
            prepared = plugin.prepare(bundle, state)
            command([binary, '--no-daemon', 'plugin', 'marketplace', 'add', str(bundle), '--json'])
            installed = command([binary, '--no-daemon', 'plugin', 'add', plugin.PLUGIN_ID, '--json'])
            installed_path = Path(installed['installedPath']); runtime = installed_path / 'runtime.pyz'
            original_runtime = runtime.read_bytes()
            assert hashlib.sha256(original_runtime).hexdigest() == prepared['artifact']['files']['plugins/model-routing-harness/runtime.pyz']
            result['installed_runtime_sha256'] = hashlib.sha256(original_runtime).hexdigest()
            result['installed_launcher_sha256'] = hashlib.sha256((installed_path / 'launcher.py').read_bytes()).hexdigest()
            settings.update(state, enabled=True, task_export_permitted=True, allowed_workspaces=[str(work)],
                            policy={'top_mode': 'Fixed', 'fixed': {'model': 'mrh-synthetic-fixed', 'effort': 'high'}, 'tiers': {}, 'timeout_seconds': 1.0})
            hook_file = installed_path / 'hooks/hooks.json'; original_hooks = hook_file.read_bytes()
            definition = json.loads(original_hooks)
            bootstrap = root / 'fault_bootstrap.py'; log = root / 'faults.jsonl'; control = root / 'scenario'; control.write_text('failure')
            bootstrap.write_text(BOOTSTRAP.replace('synthetic failure', 'RAW_EXCEPTION_CANARY'))
            definition['hooks']['PreToolUse'][0]['hooks'][0]['command'] = shlex.join([prepared['artifact']['python'], '-I', str(bootstrap), str(runtime), str(state), str(control), str(log)])
            hook_file.write_text(json.dumps(definition))
            result['classifier_trust'] = trust_fixture(binary, env, work, scope)
            rpc = Rpc(binary, env, work, scope)
            try:
                rpc.request('initialize', {'clientInfo': {'name': 'mrh-e14', 'version': '1'}, 'capabilities': {'experimentalApi': True}})
                rpc.write({'method': 'initialized'})
                hooks = rpc.request('hooks/list', {'cwd': str(work)})['result']['data']
                assert all(h['trustStatus'] == 'trusted' for row in hooks for h in row['hooks']), 'native_hook_untrusted'
                parent = rpc.request('thread/start', {'cwd': str(work), 'model': 'mrh-synthetic-parent', 'modelProvider': 'mrh_fixture',
                                                     'sandbox': 'workspace-write', 'approvalPolicy': 'never'})['result']['thread']['id']
                done = rpc.turn(parent, 'MRH_PARENT_classifier_failure synthetic fixture')
                ids = {i for e in rpc.events if e.get('method') == 'item/completed' for i in e.get('params', {}).get('item', {}).get('receiverThreadIds', [])}
                rpc.await_children(ids)
                rows = [json.loads(x) for x in log.read_text().splitlines()]
                assert len(rows) == 1 and set(rows[0]['output']) == {'systemMessage'}
                assert rows[0]['http_calls'] == 1 and rows[0]['key_resolutions'] == 1
                assert 'CANARY' not in json.dumps(rows[0]['output'])
                events = curate_events(rpc.events)
                warnings = [entry for e in events if e['method'] == 'hook/completed' for entry in e['run']['entries'] or [] if entry['kind'] == 'warning']
                assert len(warnings) == 1 and warnings[0]['text'] == rows[0]['output']['systemMessage'], 'exact_native_warning_missing'
                assert len(ids) == 1 and len([r for r in fixture.requests if not r['is_parent']]) == 1
                assert all(r['model'] == 'mrh-synthetic-parent' and r['reasoning']['effort'] == 'low' for r in fixture.requests)
                result['cases'].append({'scenario': 'classifier_connection_failure', 'native_events': events,
                                        'completed_turn': done, 'requests': copy.deepcopy(fixture.requests),
                                        'injected_runtime_events': rows, 'original_dispatch_preserved': True,
                                        'warning_event_verified': True, 'display_claim': 'event only; separate TUI case below'})
                result['canonical_stats'] = Store(state.parent / 'events.sqlite3').stats(True)
                assert result['canonical_stats']['routing_status']['fault_fallback'] == 1
            finally:
                result['rpc_exit_code'] = rpc.close()
            # Same fresh native plugin, original independent launcher. No core
            # import can rescue this intentionally broken owned-fixture archive.
            hook_file.write_bytes(original_hooks); runtime.write_bytes(b'BROKEN_RUNTIME_CANARY')
            result['launcher_trust'] = trust_fixture(binary, env, work, scope)
            terminal = native_terminal(binary, env, work, scope, fixture)
            result['terminal_transcript'] = terminal.pop('transcript')
            result['cases'].append(dict(scenario='independent_launcher_integrity_failure', **terminal))
            result['owned_processes'] = [{'pid': p.pid, 'exit_code': p.poll()} for p in scope.processes]
            result['owned_root'] = str(root)
        result['cleanup'] = {'root_absent': not Path(result['owned_root']).exists(),
                             'all_owned_processes_reaped': all(p.poll() is not None for p in scope.processes)}
        result['elapsed_seconds'] = round(time.monotonic() - started, 3)
        return result
    finally:
        server.shutdown(); server.server_close(); serving.join(timeout=2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--transcript', type=Path, required=True)
    args = parser.parse_args(); result = inspect(args.binary)
    args.transcript.write_text(result.pop('terminal_transcript'))
    result['terminal_transcript_sha256'] = hashlib.sha256(args.transcript.read_bytes()).hexdigest()
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'version': result['version'], 'cases': [c['scenario'] for c in result['cases']],
                      'terminal_visible': result['cases'][-1]['warning_visible_in_actual_terminal'],
                      'cleanup': result['cleanup'], 'elapsed_seconds': result['elapsed_seconds']}))


if __name__ == '__main__': main()
