#!/usr/bin/env python3
"""Bounded stock-App Hook transport probe; never a product classifier.

Prepare a separate external plugin. Registration/trust use official Codex
interfaces; this helper does not edit the normal home or run a model.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

OWNER = 'MRH-001-D70-C'
NAME = 'mrh-app-advisory-probe'
MARKETPLACE = 'mrh-app-advisory-probe-local'
TASK = ('Return the words amber blue cedar in reverse order, separated by one '
        'space. Do not use any tools.')
MAX_BYTES = 1048576


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    path.chmod(0o600)


def prepare(root, session, cwd):
    root = root.resolve()
    cwd = cwd.resolve(strict=True)
    if root.exists():
        raise ValueError('probe root already exists; preserve it')
    root.mkdir(parents=True, mode=0o700)
    plugin = root / 'plugins' / NAME
    (plugin / 'hooks').mkdir(parents=True)
    market = root / '.agents' / 'plugins'
    market.mkdir(parents=True)
    write_json(root / 'OWNED.json', {'owner': OWNER, 'normal_home_modified': False})
    write_json(plugin / 'scope.json', {'owner': OWNER, 'session_id': session,
        'cwd': str(cwd), 'task_sha256': digest(TASK),
        'candidate': {'model': 'gpt-5.6-luna', 'effort': 'low'}})
    shutil.copyfile(Path(__file__).resolve(), plugin / 'probe.py')
    (plugin / 'probe.py').chmod(0o600)
    command = ' '.join("'" + str(p).replace("'", "'\\''") + "'" for p in
        (Path(sys.executable).resolve(), '-I', '-B', plugin / 'probe.py', 'hook',
         '--scope', plugin / 'scope.json'))
    write_json(plugin / 'plugin.json', {'name': NAME,
        'version': '0.0.1', 'description': 'Session-scoped fixed advisory transport probe',
        'extensions': {'com.openai': {'hooks': './hooks/hooks.json'}}})
    write_json(plugin / 'hooks' / 'hooks.json', {'hooks': {
        event: [{'matcher': '^(spawn_agent|collaborationspawn_agent)$',
                 'hooks': [{'type': 'command', 'command': command, 'timeout': 5}]}]
        for event in ('PreToolUse', 'PostToolUse')}})
    write_json(market / 'marketplace.json', {'name': MARKETPLACE, 'plugins': [{
        'name': NAME, 'source': {'source': 'local', 'path': './plugins/' + NAME},
        'policy': {'installation': 'AVAILABLE', 'authentication': 'ON_USE'},
        'category': 'Productivity'}]})
    return {'status': 'prepared; not registered or trusted', 'root': str(root),
        'task': TASK, 'fixture_only': True,
        'native_commands': [
            ['codex', 'plugin', 'marketplace', 'add', str(root), '--json'],
            ['codex', 'plugin', 'add', NAME + '@' + MARKETPLACE, '--json'],
            ['codex', 'plugin', 'list', '--json']],
        'trust': 'Review these exact two definitions in official /hooks; no private trust edits',
        'removal': ['codex', 'plugin', 'remove', NAME + '@' + MARKETPLACE, '--json']}


def prepare_installed(root, session, cwd, artifact, settings):
    """Scope the existing real product; never rebuild or replace its classifier."""
    root = root.resolve(); cwd = cwd.resolve(strict=True); artifact = artifact.resolve(strict=True)
    if root.exists():
        raise ValueError('probe root already exists; preserve it')
    binding = json.loads((artifact / 'binding.json').read_text())
    archive = (artifact / 'runtime.pyz').read_bytes()
    if hashlib.sha256(archive).hexdigest() != binding['runtime_sha256']:
        raise ValueError('installed runtime/binding mismatch')
    values = json.loads(settings.read_text())
    if values.get('schema_version') != 2 or values.get('classifier', {}).get('provider') != 'jev':
        raise ValueError('expected current Jev settings v2')
    root.mkdir(parents=True, mode=0o700)
    plugin = root / 'plugins' / 'mrh-codex-app-c-check'
    (plugin / 'hooks').mkdir(parents=True)
    profile = root / 'profile'; profile.mkdir(mode=0o700)
    write_json(root / 'OWNED.json', {'owner': OWNER, 'kind': 'real-product-scoped-App-probe'})
    values.update(enabled=True, task_export_permitted=True,
                  allowed_workspaces=[str(cwd)])
    values.pop('workspace_allowlist_file', None)
    write_json(profile / 'settings.json', values)
    marker = settings.parent / '.mrh-owner.json'
    if marker.exists(): shutil.copyfile(marker, profile / marker.name)
    binding['settings_path'] = str(profile / 'settings.json')
    write_json(plugin / 'binding.json', binding)
    (plugin / 'runtime.pyz').write_bytes(archive)
    shutil.copyfile(artifact / 'launcher.py', plugin / 'launcher.py')
    tasks = ['alphabetize_words_app_c' + str(n).zfill(2) for n in range(1, 12)]
    write_json(plugin / 'scope.json', {'session_id': session, 'cwd': str(cwd),
        'task_names': tasks, 'python': binding['python']})
    wrapper = '''import json,subprocess,sys,time
from pathlib import Path
p=Path(__file__).resolve().parent
try:
 s=json.loads((p/'scope.json').read_text()); raw=sys.stdin.buffer.read(2000001)
 if len(raw)>2000000: print('{}'); raise SystemExit(0)
 e=json.loads(raw); v=e.get('tool_input',{})
 if (e.get('session_id')!=s['session_id'] or e.get('cwd')!=s['cwd']
     or v.get('task_name') not in s['task_names']):
  print('{}'); raise SystemExit(0)
 r=subprocess.run([s['python'],'-I','-B',str(p/'launcher.py')],input=raw,capture_output=True,timeout=50)
 out=json.loads(r.stdout)
 record={'ts':time.time(),'session_id':e.get('session_id'),'turn_id':e.get('turn_id'),
  'tool_use_id':e.get('tool_use_id'),'event':e.get('hook_event_name'),
  'tool_name':e.get('tool_name'),'task_name':v.get('task_name'),
  'parent_model_reported':e.get('model'),'requested_model':v.get('model'),
  'requested_effort':v.get('reasoning_effort'),'fork_turns':v.get('fork_turns'),
  'advice':out.get('hookSpecificOutput',{}).get('permissionDecisionReason')}
 with (p/'observations.jsonl').open('a') as f: f.write(json.dumps(record)+'\\n')
 print(json.dumps(out))
except Exception:
 print('{}')
'''
    (plugin / 'scope.py').write_text(wrapper)
    command = ' '.join("'" + str(p).replace("'", "'\\''") + "'" for p in
                      (binding['python'], '-I', '-B', plugin / 'scope.py'))
    write_json(plugin / 'hooks' / 'hooks.json', {'hooks': {
        event: [{'matcher': '^(spawn_agent|collaborationspawn_agent)$',
                 'hooks': [{'type': 'command', 'command': command, 'timeout': 55}]}]
        for event in ('PreToolUse', 'PostToolUse')}})
    write_json(plugin / 'plugin.json', {'name': 'mrh-codex-app-c-check', 'version': '0.4.0',
        'description': 'Original C and literal tasks only; existing real MRH runtime',
        'extensions': {'com.openai': {'hooks': './hooks/hooks.json'}}})
    market = root / '.agents' / 'plugins'; market.mkdir(parents=True)
    write_json(market / 'marketplace.json', {'name': 'mrh-codex-app-c-check-local',
        'plugins': [{'name': 'mrh-codex-app-c-check',
        'source': {'source': 'local', 'path': './plugins/mrh-codex-app-c-check'},
        'policy': {'installation': 'AVAILABLE', 'authentication': 'ON_USE'},
        'category': 'Productivity'}]})
    return {'status': 'real product scoped; not registered or trusted', 'fixture_only': False,
        'root': str(root), 'runtime_sha256': binding['runtime_sha256'], 'task_names': tasks}


def hook(scope_path, raw):
    # Malformed/unrelated inputs fail open. No task body or raw response is logged.
    try:
        if len(raw) > MAX_BYTES:
            return {}
        scope = json.loads(scope_path.read_bytes())
        event = json.loads(raw)
        params = event.get('tool_input')
        if (scope.get('owner') != OWNER or not isinstance(params, dict)
                or event.get('session_id') != scope['session_id']
                or event.get('cwd') != scope['cwd']
                or event.get('tool_name') not in ('spawn_agent', 'collaborationspawn_agent')
                or not isinstance(params.get('message'), str)
                or digest(params['message']) != scope['task_sha256']):
            return {}
        protected = (any(params.get(key) is not None for key in
                     ('model', 'reasoning_effort', 'thinking', 'effort'))
                     or params.get('agent_type') not in (None, 'default'))
        phase = event.get('hook_event_name')
        if phase not in ('PreToolUse', 'PostToolUse'):
            return {}
        record = {'kind': 'fixed-transport-probe', 'event': phase,
            'session_id': scope['session_id'], 'cwd': scope['cwd'],
            'turn_id': event.get('turn_id'), 'tool_use_id': event.get('tool_use_id'),
            'task_sha256': scope['task_sha256'], 'protected': protected,
            'parent_model_reported': event.get('model'),
            'requested_model': params.get('model'),
            'requested_effort': params.get('reasoning_effort', params.get('thinking')),
            'deny_emitted': phase == 'PreToolUse' and not protected}
        encoded = (json.dumps(record, separators=(',', ':')) + '\n').encode()
        fd = os.open(scope_path.parent / 'observations.jsonl',
                     os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(fd, encoded)
        finally:
            os.close(fd)
        if phase != 'PreToolUse' or protected:
            return {}
        reason = ('The original pending subtask did not run. This is a fixed Hook '
            'transport probe, not a classifier result. Advisory tier: Small. '
            'Candidates by platform: Codex=[gpt-5.6-luna/low]; Claude=[]; Gemini=[]. '
            'As the original parent, use only a supported candidate for your own '
            'platform and explicitly select its model/effort when creating the '
            'child. If unavailable or unsupported, finish the unexecuted subtask '
            'yourself. Do not request classification again for this subtask.')
        return {'hookSpecificOutput': {'hookEventName': 'PreToolUse',
            'permissionDecision': 'deny', 'permissionDecisionReason': reason}}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    p = sub.add_parser('prepare')
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--session-id', required=True)
    p.add_argument('--cwd', type=Path, required=True)
    p = sub.add_parser('hook')
    p.add_argument('--scope', type=Path, required=True)
    p = sub.add_parser('prepare-installed')
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--session-id', required=True)
    p.add_argument('--cwd', type=Path, required=True)
    p.add_argument('--artifact', type=Path, required=True)
    p.add_argument('--settings', type=Path, required=True)
    args = parser.parse_args()
    if args.action == 'prepare':
        result = prepare(args.root, args.session_id, args.cwd)
    elif args.action == 'prepare-installed':
        result = prepare_installed(args.root, args.session_id, args.cwd, args.artifact, args.settings)
    else:
        result = hook(args.scope, sys.stdin.buffer.read(MAX_BYTES + 1))
    print(json.dumps(result, separators=(',', ':')))


if __name__ == '__main__':
    main()
