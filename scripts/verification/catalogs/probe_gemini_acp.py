#!/usr/bin/env python3
"""E16 owned offline public ACP experiment; never a prompt/auth request."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
import argparse
import hashlib
import json
import os
import queue
import shutil
import signal
import subprocess
import tempfile
import threading
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'src'))
from mrh.adapters.catalogs.claude_catalog import isolation_profile


def probe():
    started = time.monotonic(); results = []
    source = Path('/Users/shawn/.nvm/versions/node/v20.19.4/lib/node_modules/@google/gemini-cli')
    node = Path('/Users/shawn/.nvm/versions/node/v20.19.4/bin/node').resolve()
    with tempfile.TemporaryDirectory(prefix='mrh-e16-acp-', dir='/private/tmp') as tmp:
        root = Path(tmp).resolve(); copied = root / 'public-cli'; shutil.copytree(source, copied, symlinks=True)
        for path in copied.rglob('*'):
            if path.is_symlink() and not path.resolve().is_relative_to(copied):
                raise RuntimeError('public_payload_external_symlink')
        runtime = root / 'node'; shutil.copy2(node, runtime)
        script = copied / 'bundle/gemini.js'
        profile = root / 'isolation.sb'; profile.write_text(isolation_profile(root, runtime))
        conf = root / 'openssl.cnf'; conf.write_text('')
        for placeholder in (False, True):
            case = root / ('placeholder' if placeholder else 'no-key'); case.mkdir(); home = case / 'home'; home.mkdir()
            work = case / 'work'; work.mkdir(); config = home / '.gemini'; config.mkdir()
            settings = {'security': {'auth': {'selectedType': 'gemini-api-key'}}, 'general': {'enableAutoUpdate': False, 'enableAutoUpdateNotification': False},
                        'advanced': {'autoConfigureMemory': False}, 'telemetry': {'enabled': False}, 'experimental': {'autoMemory': False},
                        'hooksConfig': {'enabled': False}, 'hooks': {}, 'mcpServers': {}}
            (config / 'settings.json').write_text(json.dumps(settings))
            env = {'PATH': '/usr/bin:/bin', 'HOME': str(home), 'TMPDIR': str(case), 'OPENSSL_CONF': str(conf),
                   'NO_COLOR': '1', 'LANG': 'en_US.UTF-8'}
            if placeholder: env['GEMINI_API_KEY'] = 'mrh-invalid-offline-placeholder'
            command = ['/usr/bin/sandbox-exec', '-f', str(profile), str(runtime), str(script), '--acp']
            p = subprocess.Popen(command, cwd=work, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 text=True, start_new_session=True)
            inbox = queue.Queue(); stderr = []
            def read():
                for line in p.stdout:
                    try: inbox.put(json.loads(line))
                    except ValueError: inbox.put({'non_json': line[:1000]})
            def errors():
                for line in p.stderr: stderr.append(line.rstrip())
            threading.Thread(target=read, daemon=True).start(); threading.Thread(target=errors, daemon=True).start()
            sent = []; received = []; failure = None
            def rpc(identity, method, params):
                request = {'jsonrpc': '2.0', 'id': identity, 'method': method, 'params': params}; sent.append(request)
                p.stdin.write(json.dumps(request) + '\n'); p.stdin.flush()
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    item = inbox.get(timeout=max(.01, deadline - time.monotonic())); received.append(item)
                    if item.get('id') == identity: return item
                raise TimeoutError('acp_metadata_timeout')
            try:
                init = rpc(1, 'initialize', {'protocolVersion': 1, 'clientCapabilities': {}})
                if 'result' in init:
                    rpc(2, 'session/new', {'cwd': str(work), 'mcpServers': []})
            except Exception as exc:
                failure = type(exc).__name__
            finally:
                try: p.stdin.close()
                except OSError: pass
                try: p.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    if os.getpgid(p.pid) == p.pid: os.killpg(p.pid, signal.SIGTERM)
                    try: p.wait(timeout=1)
                    except subprocess.TimeoutExpired: os.killpg(p.pid, signal.SIGKILL); p.wait(timeout=2)
                p.stdout.close(); p.stderr.close()
            results.append({'invalid_placeholder': placeholder, 'sent': sent, 'received': received,
                            'diagnostic': stderr[-15:], 'failure': failure, 'pid': p.pid, 'exit': p.returncode})
    return {'cases': results, 'owned_root': str(root), 'owned_root_absent': not root.exists(),
            'seconds': round(time.monotonic() - started, 3), 'real_credential': False, 'provider_or_prompt_requests': 0,
            'private_data_and_outbound_denied': True}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--output', type=Path, required=True); args = parser.parse_args()
    result = probe(); args.output.write_text(json.dumps(result, indent=2) + '\n'); print(json.dumps(result))
