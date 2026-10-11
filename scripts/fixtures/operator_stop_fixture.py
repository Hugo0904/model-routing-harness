#!/usr/bin/env python3
"""Explicit isolated CLI Hook fixture for A's step-by-step stop acceptance.

No provider/network/model request: the real parser/factory sees synthetic HTTP.
The owned root remains for operator-controlled steps; no automatic rerun.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import argparse
import io
import json
import shutil

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'src'))
from mrh.presentation import cli; from mrh.infrastructure import settings
from mrh.routing.facts import CallScope, Fact, HostSnapshot, TargetFacts
from mrh.infrastructure.store import Store
from mrh.adapters.providers.typesafe import HttpResponse

MARKER = 'mrh-e10r-operator-stop-fixture-v1'


class Transport:
    synthetic = True

    def __init__(self):
        self.calls = 0

    def request(self, body, headers, deadline, enter):
        enter()
        self.calls += 1
        return HttpResponse(200, json.dumps({
            'model': 'jev-1.13.0', 'answers': {'tier': {'type': 'choice', 'choice': 'top',
            'probabilities': {'light': .02, 'small': .03, 'mid': .05, 'top': .9}, 'confidence': .9}},
            'usage': {'input_tokens': 100, 'output_tokens': 10}}).encode())


class Host:
    synthetic = True

    def __init__(self, available):
        self.available = available

    def resolve(self, event):
        scope = CallScope.for_hook(event)
        known = lambda value: Fact.observed(scope, value, 'synthetic-e10r-stop-fixture')
        targets = tuple(TargetFacts(model, known(self.available if model == 'selected-target' else True),
                                    known(('high',)), known('high'))
                        for model in ('selected-target', 'replacement-target'))
        return HostSnapshot(scope, True, role_protection=known('unprotected'),
                            deny_supported=known(True), rewrite_supported=known(True), targets=targets)


def step(root, action):
    raw = Path(root).expanduser().absolute()
    if raw.is_symlink() or raw.resolve() != raw or raw == Path('/'):
        raise ValueError('unsafe_fixture_root')
    marker = raw / '.operator-stop-fixture'
    if raw.exists():
        if not marker.is_file() or marker.is_symlink() or marker.read_text() != MARKER:
            raise ValueError('not_owned_fixture_root')
    elif action not in ('prepare-allow', 'stop'):
        raise ValueError('fixture_missing')
    else:
        raw.mkdir(mode=0o700, parents=True)
        marker.write_text(MARKER)
        path = raw / 'profile' / 'settings.json'
        settings.init(path)
        settings.update(path, enabled=True, task_export_permitted=True,
                        allowed_workspaces=[str(raw)],
                        policy={'top_mode': 'Fixed', 'fixed': {'model': 'selected-target', 'effort': 'high'}, 'tiers': {}})
    if action == 'cleanup':
        shutil.rmtree(raw)
        return {'fixture_only': True, 'removed_root': str(raw), 'absent': not raw.exists()}
    path = raw / 'profile' / 'settings.json'
    if action == 'after-update':
        value = settings.read(path)
        settings.update(path, expected_revision=value['revision'],
                        policy={'top_mode': 'Fixed', 'fixed': {'model': 'replacement-target', 'effort': 'high'}, 'tiers': {}})
    transport = Transport()
    event = {'hook_event_name': 'PreToolUse', 'tool_name': 'spawn_agent', 'session_id': 'e10r-fixture',
             'turn_id': 'operator-turn', 'tool_use_id': 'operator-rerun' if action == 'rerun' else 'same-call',
             'cwd': str(raw), 'tool_input': {'message': 'Synthetic isolated operator stop acceptance'}}
    if action == 'receipt':
        event.update(hook_event_name='PostToolUse', tool_response={'agent_id': 'unexpected-fixture-child'})
    output, diagnostic = io.StringIO(), io.StringIO()
    if action != 'status':
        code = cli.main(['hook', '--settings', str(path)], stdin=io.StringIO(json.dumps(event)),
                        stdout=output, stderr=diagnostic,
                        runtime_dependencies={'host_resolver': Host(action != 'stop'), 'transport': transport,
                                              'credential_resolver': lambda: 'synthetic-fixture-key'})
        if code:
            raise RuntimeError('fixture_hook_failed')
    return {'fixture_only': True, 'step': action, 'settings_path': str(path),
            'hook_output': json.loads(output.getvalue()) if output.getvalue() else None,
            'diagnostic': diagnostic.getvalue(), 'synthetic_requests_this_step': transport.calls,
            'policy': settings.read(path)['policy'], 'stats': Store(path.parent / 'events.sqlite3').stats(True)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, help='fresh absolute private fixture root')
    parser.add_argument('--step', required=True,
                        choices=('prepare-allow', 'stop', 'after-update', 'rerun', 'receipt', 'status', 'cleanup'))
    args = parser.parse_args()
    print(json.dumps(step(args.root, args.step), indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
