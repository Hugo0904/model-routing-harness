"""E14 preserve/warn/history boundary; no real provider or child execution."""
import copy
from concurrent.futures import ThreadPoolExecutor
import contextlib
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from mrh.presentation import cli; from mrh.infrastructure import plugin; from mrh.infrastructure import settings
from mrh.adapters.hosts.codex import handle_event, serialize
from mrh.routing.core import Classification, ScriptedClassifier
from mrh.routing.faults import FAULTS, category, notice_for, warning
from mrh.application.runtime import configured_event
from mrh.application.simulation import demo_capabilities, demo_policy
from mrh.infrastructure.store import Store
from mrh.routing.types import Decision, Proposal

CANARY = 'TASK_PRIVATE_CANARY sk-CREDENTIAL_CANARY /private/UNTRUSTED_CANARY'


class FaultNoticesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='mrh-e14-notices-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.store = Store(self.root / 'events.sqlite3')

    def event(self, call='fault', session='session', **input):
        return {'hook_event_name': 'PreToolUse', 'tool_name': 'spawn_agent',
                'session_id': session, 'turn_id': 'turn', 'tool_use_id': call,
                'tool_input': {'message': CANARY, 'unknown': {'preserve': True}, **input}}

    def run_event(self, event, result, store=None, caps=None):
        classifier = ScriptedClassifier([result])
        before = copy.deepcopy(event)
        with contextlib.redirect_stderr(io.StringIO()):
            response = handle_event(event, self.store if store is None else store, True,
                                    classifier=classifier, policy=demo_policy(),
                                    capabilities=demo_capabilities() if caps is None else caps)
        self.assertEqual(event, before)
        if 'hookSpecificOutput' not in response:
            self.assertNotIn('CANARY', json.dumps(response))
        return response, classifier

    def history(self):
        with self.store.connect() as db:
            return {table: [tuple(r) for r in db.execute('SELECT * FROM ' + table + ' ORDER BY id')]
                    for table in ('proposals', 'attempts', 'receipts')}

    def test_timeout_error_malformed_preserve_safe_original_and_record_fault(self):
        for index, result in enumerate((TimeoutError(CANARY), RuntimeError(CANARY), {'unsafe': CANARY})):
            with self.subTest(result=type(result).__name__):
                event = self.event(str(type(result).__name__))
                out, classifier = self.run_event(event, result)
                if index == 0:
                    self.assertEqual(set(out), {'systemMessage'})
                    self.assertIn('original tool call preserved', out['systemMessage'])
                    self.assertIn('mrh stats --details', out['systemMessage'])
                else:
                    self.assertEqual(out, {})
                self.assertEqual(classifier.calls, 1)
        stats = self.store.stats(True)
        self.assertEqual(stats['routing_status']['fault_fallback'], 3)
        self.assertEqual(stats['classified_tasks'], 0)
        self.assertEqual(stats['synthetic_attempts'], 3)
        self.assertEqual(stats['notifications']['warning_claims'], 1)
        self.assertEqual(stats['notifications']['fault_observations'], 3)
        self.assertEqual(stats['confirmed_children'], 0)
        self.assertEqual(stats['simulated_children'], 0)
        self.assertIsNone(stats['cost']); self.assertIsNone(stats['quota'])
        self.assertEqual(stats['schema_version'], 2)
        self.assertEqual(self.store.stats()['routing_status']['fault_fallback'], 0)
        self.assertNotIn('CANARY', json.dumps(stats))

    def test_duplicate_concurrent_observations_dedup_without_canonical_history_change(self):
        event = self.event(); first, _ = self.run_event(event, RuntimeError(CANARY))
        self.assertIn('systemMessage', first)
        history = self.history()
        with ThreadPoolExecutor(max_workers=8) as pool:
            rows = list(pool.map(lambda _: self.run_event(event, RuntimeError(CANARY)), range(16)))
        self.assertTrue(all(out == {} and classifier.calls == 0 for out, classifier in rows))
        self.assertEqual(self.history(), history)
        stats = self.store.stats(True)
        self.assertEqual(stats['proposals'], 1)
        self.assertEqual(stats['synthetic_attempts'], 1)
        self.assertEqual(stats['notifications']['fault_observations'], 17)
        self.assertEqual(stats['notifications']['warning_claims'], 1)
        before = self.store.stats(True)
        self.assertEqual(self.store.stats(True), before)
        self.assertEqual(self.history(), history)

    def test_concurrent_new_faults_claim_one_warning_for_session(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            rows = list(pool.map(lambda i: self.run_event(self.event('new-' + str(i)), RuntimeError(CANARY)), range(8)))
        self.assertEqual(sum('systemMessage' in out for out, _ in rows), 1)
        stats = self.store.stats(True)
        self.assertEqual(stats['proposals'], 8)
        self.assertEqual(stats['routing_status']['fault_fallback'], 8)
        self.assertEqual(stats['notifications']['fault_observations'], 8)
        self.assertEqual(stats['notifications']['warning_claims'], 1)

    def test_recovery_requires_subsequent_relevant_evaluation_not_old_success_or_save(self):
        old_success = self.event('old-success')
        self.run_event(old_success, Classification('Light', .9))
        fault = self.event(); self.run_event(fault, RuntimeError(CANARY))
        history = self.history()
        self.run_event(old_success, Classification('Light', .9))
        self.run_event(self.event('explicit', model='explicit'), RuntimeError(CANARY))
        state = self.root / 'profile/settings.json'; settings.init(state)
        settings.update(state, enabled=False)
        self.assertEqual(self.store.stats(True)['notifications']['state'], 'active_fault')
        self.assertEqual(self.store.stats(True)['notifications']['recoveries'], 0)
        self.run_event(self.event('new-success'), Classification('Light', .49))
        stats = self.store.stats(True)
        self.assertEqual(stats['notifications']['state'], 'recovered')
        self.assertEqual(stats['notifications']['recoveries'], 1)
        self.assertEqual(stats['routing_status']['normal_retention'], 3)
        # A replay of the old failed proposal remains a historical fault, without
        # reopening an episode or running the classifier again.
        replay, classifier = self.run_event(fault, RuntimeError(CANARY))
        self.assertEqual(replay, {}); self.assertEqual(classifier.calls, 0)
        self.assertEqual(self.store.stats(True)['notifications']['state'], 'recovered')
        fresh, _ = self.run_event(self.event('new-fault'), RuntimeError(CANARY))
        self.assertIn('systemMessage', fresh)
        self.assertEqual(self.store.stats(True)['notifications']['warning_claims'], 2)
        current = {r[0]: r for r in self.history()['proposals']}
        self.assertTrue(all(current[r[0]] == r for r in history['proposals']))

    def test_scope_sessions_and_profiles_do_not_suppress_each_other(self):
        for session in ('session-a', 'session-b'):
            out, _ = self.run_event(self.event(session=session), RuntimeError(CANARY))
            self.assertIn('systemMessage', out)
        other = Store(self.root / 'other-profile/events.sqlite3')
        out, _ = self.run_event(self.event(session='session-a'), RuntimeError(CANARY), store=other)
        self.assertIn('systemMessage', out)
        self.assertEqual(self.store.stats(True)['notifications']['active_sessions'], 2)
        self.assertEqual(other.stats(True)['notifications']['active_sessions'], 1)

    def test_normal_retention_and_readiness_are_neutral_not_faults_or_recovery(self):
        for name, event, caps, result in (
            ('explicit', self.event('explicit', model='explicit'), demo_capabilities(), RuntimeError(CANARY)),
            ('unknown', self.event('unknown'), {'configuration_known': False}, RuntimeError(CANARY)),
            ('low', self.event('low'), demo_capabilities(), Classification('Light', .49))):
            with self.subTest(name=name):
                out, classifier = self.run_event(event, result, caps=caps)
                self.assertEqual(out, {})
                self.assertEqual(classifier.calls, int(name == 'low'))
        stats = self.store.stats(True)
        self.assertEqual(stats['routing_status']['normal_retention'], 2)
        self.assertEqual(stats['routing_status']['unavailable_readiness'], 1)
        self.assertEqual(stats['routing_status']['fault_fallback'], 0)
        self.assertEqual(stats['notifications']['state'], 'unobserved')
        self.assertEqual(stats['classified_tasks'], 1)
        self.assertEqual(sum(stats['tiers'].values()), 1)

    def test_persistence_fault_warns_each_time_without_claiming_recorded_fault(self):
        event = self.event()
        with patch.object(self.store, 'claim', side_effect=OSError(CANARY)):
            for _ in range(2):
                out, classifier = self.run_event(event, RuntimeError(CANARY))
                self.assertIn('Recording and warning deduplication are unavailable', out['systemMessage'])
                self.assertEqual(classifier.calls, 0)
        self.assertEqual(self.store.stats(True)['proposals'], 0)
        self.assertEqual(self.store.stats(True)['notifications']['warning_claims'], 0)
        with patch.object(self.store, 'observe_notice', side_effect=OSError(CANARY)):
            out, _ = self.run_event(event, RuntimeError(CANARY))
            self.assertIn('this fault may be absent from history', out['systemMessage'])
        self.assertEqual(self.store.stats(True)['routing_status']['fault_fallback'], 1)
        self.assertEqual(self.store.stats(True)['notifications']['warning_claims'], 0)

    def test_only_allowlisted_faults_emit_fixed_messages(self):
        for reason in FAULTS:
            decision = Decision(reason=reason)
            self.assertEqual(category(decision), 'fault_fallback')
            out = serialize(decision, {'message': CANARY}, CANARY)
            self.assertEqual(set(out), {'systemMessage'})
            self.assertLess(len(out['systemMessage']), 400)
            self.assertNotIn('CANARY', json.dumps(out))
        for reason in ('explicit_model', 'low_confidence', 'missing_role_protection', 'typesafe_missing_credentials', 'operator_stop_unavailable'):
            self.assertEqual(serialize(Decision(reason=reason), {}, 'call'), {})
        self.assertNotIn('CANARY', json.dumps(warning(CANARY)))

    def test_valid_called_runtime_settings_failure_is_safe_without_provider_or_facts(self):
        path = self.root / 'missing/settings.json'; event = self.event()
        with patch('mrh.application.runtime.classifier_from_config', side_effect=AssertionError('provider ran')), contextlib.redirect_stderr(io.StringIO()):
            out = configured_event(event, path)
        self.assertIn('systemMessage', out)
        self.assertNotIn('CANARY', json.dumps(out)); self.assertFalse(path.parent.exists())
        self.assertEqual(configured_event(dict(event, hook_event_name='PostToolUse'), path), {})


    def test_known_operator_stop_write_fault_warns_without_weakening_deny(self):
        from tests.routing.test_operator_stop import OperatorStopTests
        fixture = OperatorStopTests()
        for stage in ('complete', 'record_stop'):
            with self.subTest(stage=stage):
                event = fixture.event('stop-' + stage)
                classifier = ScriptedClassifier([Classification('Top', .9)])
                if stage == 'record_stop':
                    first = handle_event(event, self.store, True, classifier=classifier,
                                         policy=fixture.policy(), capabilities=fixture.facts(event, available=True))
                    self.assertEqual(first['hookSpecificOutput']['permissionDecision'], 'allow')
                with patch.object(self.store, stage, side_effect=OSError(CANARY)), contextlib.redirect_stderr(io.StringIO()):
                    stopped = handle_event(event, self.store, True, classifier=classifier,
                                           policy=fixture.policy(), capabilities=fixture.facts(event))
                self.assertEqual(stopped['hookSpecificOutput']['permissionDecision'], 'deny')
                self.assertNotIn('updatedInput', stopped['hookSpecificOutput'])
                self.assertIn('delegation remains denied', stopped['systemMessage'])
                self.assertIn('may be absent from history', stopped['systemMessage'])
                self.assertNotIn('CANARY', stopped['systemMessage'])
                self.assertEqual(classifier.calls, 1)

    def test_notification_write_fault_does_not_authorize_or_change_known_routing(self):
        for mode in ('Main', 'Fixed'):
            event = self.event('notices-' + mode); policy = demo_policy(); policy['top_mode'] = mode
            with patch.object(self.store, 'observe_notice', side_effect=OSError(CANARY)):
                response = handle_event(event, self.store, True, classifier=ScriptedClassifier([Classification('Top', .9)]),
                                        policy=policy, capabilities=demo_capabilities())
            self.assertIn('routing decision retained', response['systemMessage'])
            self.assertNotIn('CANARY', response['systemMessage'])
            output = response['hookSpecificOutput']
            self.assertEqual(output['permissionDecision'], 'deny' if mode == 'Main' else 'allow')
            if mode == 'Fixed':
                self.assertEqual(output['updatedInput']['message'], event['tool_input']['message'])
        self.assertEqual(self.store.stats(True)['routing_status']['fault_fallback'], 0)


class InstalledLauncherFaultTests(unittest.TestCase):
    def test_installed_launcher_integrity_and_runtime_load_faults_preserve_safe_call(self):
        with tempfile.TemporaryDirectory(prefix='mrh-e14-launcher-') as directory:
            root = Path(directory).resolve(); bundle = root / 'bundle'; state = root / 'state/settings.json'
            prepared = plugin.prepare(bundle, state)
            folder = bundle / 'plugins/model-routing-harness'
            event = {'hook_event_name': 'PreToolUse', 'tool_name': 'spawn_agent',
                     'session_id': 's', 'turn_id': 't', 'tool_use_id': 'c', 'tool_input': {'message': CANARY}}
            before = copy.deepcopy(event); state_before = state.read_bytes()
            python = prepared['artifact']['python']; launcher = folder / 'launcher.py'
            def run(value):
                result = subprocess.run([python, '-I', str(launcher)], cwd=root, env={'PATH': '/usr/bin:/bin'},
                                        input=json.dumps(value), text=True, capture_output=True, timeout=5)
                self.assertEqual(result.returncode, 0); self.assertEqual(result.stderr, '')
                self.assertNotIn('CANARY', result.stdout)
                return json.loads(result.stdout)
            self.assertEqual(run(event), {})  # default-off remains neutral
            original_runtime = (folder / 'runtime.pyz').read_bytes()
            (folder / 'runtime.pyz').write_bytes(b'broken-' + CANARY.encode())
            self.assertIn('integrity verification failed', run(event)['systemMessage'])
            self.assertEqual(run(dict(event, hook_event_name='PostToolUse')), {})
            with zipfile.ZipFile(folder / 'runtime.pyz', 'w') as archive:
                archive.writestr('__main__.py', "raise ImportError(" + repr(CANARY) + ")\n")
            binding = json.loads((folder / 'binding.json').read_text())
            binding['runtime_sha256'] = hashlib.sha256((folder / 'runtime.pyz').read_bytes()).hexdigest()
            (folder / 'binding.json').write_text(json.dumps(binding))
            self.assertIn('could not be loaded', run(event)['systemMessage'])
            # The CLI still loads, but both its configured runtime and shared
            # notice module are missing. Its catch-all must signal failure to
            # the independent launcher rather than returning a successful {}.
            with zipfile.ZipFile(io.BytesIO(original_runtime)) as original, zipfile.ZipFile(folder / 'runtime.pyz', 'w') as broken:
                for name in original.namelist():
                    if name not in ('mrh/application/runtime.py', 'mrh/routing/faults.py'):
                        broken.writestr(name, original.read(name))
            binding['runtime_sha256'] = hashlib.sha256((folder / 'runtime.pyz').read_bytes()).hexdigest()
            (folder / 'binding.json').write_text(json.dumps(binding))
            self.assertIn('could not be loaded', run(event)['systemMessage'])
            self.assertEqual(state.read_bytes(), state_before)
            self.assertFalse((state.parent / 'events.sqlite3').exists())
            self.assertEqual(event, before)


if __name__ == '__main__':
    unittest.main()
