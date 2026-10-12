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
    args = parser.parse_args()
    result = (prepare(args.root, args.session_id, args.cwd) if args.action == 'prepare'
              else hook(args.scope, sys.stdin.buffer.read(MAX_BYTES + 1)))
    print(json.dumps(result, separators=(',', ':')))


if __name__ == '__main__':
    main()
