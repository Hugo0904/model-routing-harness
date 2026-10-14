import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor

spec = importlib.util.spec_from_file_location('daily', Path(__file__).resolve().parents[2] / 'scripts/collection/daily.py')
daily = importlib.util.module_from_spec(spec)
spec.loader.exec_module(daily)


class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve() / 'dataset'; self.root.mkdir(mode=0o700)
        os.chmod(self.root, 0o700)
        self.spool = self.root.parent / 'spool'; self.spool.mkdir(mode=0o700)
        self.config = self.root.parent / 'config.json'
        daily.write(self.config, {'enabled': True, 'dataset': str(self.root), 'spool_root': str(self.spool), 'workspace_roots': [str(self.root)]})
        daily.write(self.spool / 'owner.json', {'owner': daily.SPOOL_OWNER, 'config': str(self.config.resolve())})
        daily.write(self.root / 'collection.json', {'count': 2, 'target': 10, 'samples': [{'legacy': 1}, {'legacy': 2}]})
        self.collector = daily.Collector(self.config)
        self.req = {'task_name': 'repair_real_issue', 'message': 'Complete the already authorized change.\nExact final newline stays.\n',
                    'model': 'example-model', 'reasoning_effort': 'high', 'agent_type': 'worker', 'fork_turns': 'none'}

    def tearDown(self):
        self.temp.cleanup()

    def stage(self, session='chat-a', req=None):
        event = self.event('UserPromptSubmit', session=session)
        self.collector.hook(event)
        key = daily.digest(session + '\0native-turn\0' + str(self.root.resolve()))
        context = self.spool / 'prompt-contexts' / (key + '.json')
        return self.collector.stage(req or self.req, session=session, cwd=str(self.root), natural=True, safe=True, context=context)

    def event(self, phase, session='chat-a', call='native-call', req=None, response=None):
        return {'hook_event_name': phase, 'session_id': session, 'cwd': str(self.root), 'turn_id': 'native-turn',
                'tool_name': 'spawn_agent', 'tool_use_id': call, 'tool_input': req or self.req,
                'tool_response': {'task_name': '/root/repair_real_issue'} if response is None else response}

    def dispatch(self, session='chat-a', call='native-call', req=None):
        self.collector.hook(self.event('PreToolUse', session, call, req))
        return self.collector.hook(self.event('PostToolUse', session, call, req))

    def test_cross_chat_exact_capture_and_duplicate_post(self):
        for session in ('chat-a', 'chat-b'):
            result = self.stage(session)
            self.assertEqual(daily.read(Path(result['request_path']))['message'], self.req['message'])
            self.dispatch(session)
            self.dispatch(session)
        index = self.collector.index()
        self.assertEqual(index['count'], 4)
        self.assertEqual(index['samples'][:2], [{'legacy': 1}, {'legacy': 2}])
        for sample in index['samples'][2:]:
            self.assertEqual(sample['native_body_equality'], 'verified_plaintext')
            self.assertIsNone(sample['actual_model'])
            persistent = self.root / sample['canonical_message_source'].split('#')[0]
            self.assertTrue(persistent.exists())
            self.assertFalse(persistent.is_relative_to(self.spool))

    def test_encrypted_native_body_retains_truthful_boundary(self):
        self.stage()
        encrypted = dict(self.req, message='gAAAA' + 'x' * 70)
        self.dispatch(req=encrypted)
        sample = self.collector.index()['samples'][-1]
        self.assertEqual(sample['native_body_equality'], 'unobservable_ciphertext')
        self.assertEqual(sample['capture_source'], 'parent_pre_dispatch_attestation')

    def test_missing_mismatch_wrong_session_and_continuation_do_not_count(self):
        self.dispatch()
        self.stage()
        self.dispatch('chat-other')
        self.dispatch(req=dict(self.req, message='changed body'))
        self.dispatch(req=dict(self.req, model='different-model'))
        event = self.event('PostToolUse'); event['tool_name'] = 'followup_task'
        self.collector.hook(event)
        self.assertEqual(self.collector.index()['count'], 2)

    def test_failure_then_retry_counts_once(self):
        first = self.stage()
        self.collector.hook(self.event('PreToolUse'))
        self.collector.hook(self.event('PostToolUse', response={'error': 'failed'}))
        self.assertEqual(self.collector.index()['count'], 2)
        again = self.stage()
        self.assertEqual(first['capture_id'], again['capture_id'])
        self.dispatch(call='retry')
        self.dispatch(call='retry-again')
        self.assertEqual(self.collector.index()['count'], 3)

    def test_atomic_cap_with_parallel_chats(self):
        for n in range(12):
            self.stage('chat-' + str(n))
        with ThreadPoolExecutor(max_workers=12) as pool:
            list(pool.map(lambda n: self.dispatch('chat-' + str(n)), range(12)))
        index = self.collector.index()
        self.assertEqual(index['count'], 10)
        self.assertTrue(index['stopped_at_target'])
        self.assertEqual(self.stage('more')['status'], 'collection_stopped')

    def test_crash_after_index_commit_repaired_without_double_count(self):
        self.stage()
        self.collector.hook(self.event('PreToolUse'))
        before = self.collector.state()
        self.dispatch()
        daily.write(self.spool / 'collector-state.json', before)
        self.collector.hook(self.event('PostToolUse'))
        self.assertEqual(self.collector.index()['count'], 3)
        self.assertTrue(all(row['status'] == 'counted' for row in self.collector.state()['stages'].values()))

    def test_symlink_or_public_capture_parent_rejected_before_write(self):
        outside = self.root / 'outside'; outside.mkdir(mode=0o700)
        captures = self.spool / 'captures'; captures.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError): self.stage()
        self.assertEqual(list(outside.iterdir()), [])
        captures.unlink(); captures.mkdir(mode=0o755)
        with self.assertRaises(ValueError): self.stage()
        self.assertEqual(captures.stat().st_mode & 0o777, 0o755)

    def test_capacity_and_metadata_are_bounded_without_removing_originals(self):
        with patch.object(daily, 'MAX_STAGES', 2), patch.object(daily, 'MAX_METADATA', 3):
            first = self.stage(); self.stage('chat-b')
            self.assertEqual(self.stage('chat-c')['status'], 'capture_capacity_reached')
            for n in range(8): self.collector.hook(self.event('PreToolUse', session='missing', call=str(n)))
            self.assertLessEqual(len(self.collector.state()['events']), 3)
            self.assertEqual(len(list((self.spool / 'captures').iterdir())), 2)
            self.assertTrue(Path(first['request_path']).exists())

    def test_last_post_announces_stop_without_another_event(self):
        index = self.collector.index(); index['target'] = 3
        daily.write(self.root / 'collection.json', index)
        self.stage(); self.collector.hook(self.event('PreToolUse'))
        before = self.collector.state()
        result = self.collector.hook(self.event('PostToolUse'))
        self.assertIn('已收齊並停止', result['systemMessage'])
        daily.write(self.spool / 'collector-state.json', before)
        self.collector.hook(self.event('PostToolUse'))
        self.assertTrue(all(row['status'] == 'counted' for row in self.collector.state()['stages'].values()))
        self.assertEqual(self.collector.index()['count'], 3)

    def test_missing_stage_notice_and_origin_or_post_changes_never_count(self):
        result = self.collector.hook(self.event('PreToolUse'))
        self.assertIn('下次自然派工前先 stage', result['systemMessage'])
        self.assertNotIn('permissionDecision', json.dumps(result))
        self.stage(); self.collector.hook(self.event('PreToolUse'))
        post = self.event('PostToolUse'); post['turn_id'] = 'another-turn'
        self.collector.hook(post)
        post = self.event('PostToolUse'); post['tool_input'] = dict(self.req, model='changed')
        self.collector.hook(post)
        self.assertEqual(self.collector.index()['count'], 2)

    def test_excluded_implementation_chat_does_not_stage_or_inject(self):
        self.collector.config['excluded_threads'] = ['chat-a']
        self.assertEqual(self.stage()['status'], 'scope_excluded')
        self.assertEqual(self.collector.hook(self.event('UserPromptSubmit')), {})
        self.assertFalse((self.root / 'captures').exists())

    def test_old_root_turn_and_same_session_child_turn_cannot_bind_ciphertext(self):
        self.stage()
        for turn in ('next-root-turn', 'child-turn'):
            encrypted = dict(self.req, message='gAAAA' + 'x' * 70)
            pre = self.event('PreToolUse', call=turn, req=encrypted); pre['turn_id'] = turn
            post = dict(pre, hook_event_name='PostToolUse')
            self.assertIn('systemMessage', self.collector.hook(pre))
            self.collector.hook(post)
        self.assertEqual(self.collector.index()['count'], 2)

    def test_unrecorded_context_and_child_environment_cannot_stage(self):
        self.collector.hook(self.event('UserPromptSubmit'))
        key = daily.digest('chat-a\0native-turn\0' + str(self.root.resolve()))
        path = self.spool / 'prompt-contexts' / (key + '.json')
        with self.assertRaises(ValueError):
            self.collector.stage(self.req, session='child-id', cwd=str(self.root), natural=True, safe=True, context=path)
        forged = self.root / 'forged.json'; daily.write(forged, daily.read(path))
        with self.assertRaises(ValueError):
            self.collector.stage(self.req, session='chat-a', cwd=str(self.root), natural=True, safe=True, context=forged)
        self.assertFalse((self.root / 'captures').exists())

    def test_stage_succeeds_when_central_dataset_is_write_denied(self):
        self.collector.hook(self.event('UserPromptSubmit'))
        key = daily.digest('chat-a\0native-turn\0' + str(self.root.resolve()))
        context = self.spool / 'prompt-contexts' / (key + '.json')
        original_open = os.open
        before = {p.name: p.read_bytes() for p in self.root.iterdir() if p.is_file()}
        def restricted_open(path, flags, *args, **kwargs):
            if Path(path).is_relative_to(self.root) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT):
                raise PermissionError('fixture central write denied')
            return original_open(path, flags, *args, **kwargs)
        with patch.object(daily.os, 'open', side_effect=restricted_open):
            result = self.collector.stage(self.req, session='chat-a', cwd=str(self.root), natural=True, safe=True, context=context)
        self.assertTrue(Path(result['request_path']).is_relative_to(self.spool))
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir() if p.is_file()})
        self.dispatch()
        sample = self.collector.index()['samples'][-1]
        persistent = self.root / sample['canonical_message_source'].split('#')[0]
        self.assertEqual(persistent.read_bytes(), Path(result['request_path']).read_bytes())

    def test_unowned_or_symlink_spool_is_rejected(self):
        daily.write(self.spool / 'owner.json', {'owner': 'another owner'})
        with self.assertRaises(ValueError): daily.Collector(self.config)
        original = self.spool.with_name('real-spool'); self.spool.rename(original)
        self.spool.symlink_to(original, target_is_directory=True)
        with self.assertRaises(ValueError): daily.Collector(self.config)

    def test_sensitive_or_unattested_input_never_saved(self):
        for req in (dict(self.req, message='api_key=sk-' + 'a' * 24), dict(self.req, message='-----BEGIN PRIVATE KEY-----')):
            with self.assertRaises(ValueError):
                self.stage(req=req)
        with self.assertRaises(ValueError):
            self.collector.stage(self.req, session='a', cwd=str(self.root), natural=False, safe=True)
        self.assertFalse((self.root / 'captures').exists())

    def test_private_files_and_symlink_rejection(self):
        result = self.stage()
        self.assertEqual(Path(result['request_path']).stat().st_mode & 0o777, 0o400)
        self.assertEqual((self.spool / 'collector-state.json').stat().st_mode & 0o777, 0o600)
        self.config.unlink(); self.config.symlink_to(self.root / 'collection.json')
        with self.assertRaises(ValueError):
            daily.Collector(self.config)

    def test_prompt_injection_nonblocking_and_no_wait(self):
        result = self.collector.hook(self.event('UserPromptSubmit'))
        self.assertIn('--natural --safe-to-store', result['hookSpecificOutput']['additionalContext'])
        self.assertNotIn('permissionDecision', json.dumps(result))
        self.assertEqual(self.collector.index()['count'], 2)


if __name__ == '__main__':
    unittest.main()
