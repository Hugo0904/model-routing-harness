import json
import os
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from tests.collection import test_daily as fixtures

daily=fixtures.daily


class LightCollectorTests(unittest.TestCase):
    def setUp(self):
        self.env=fixtures.CollectionTests();self.env.setUp();self.addCleanup(self.env.tearDown)

    def test_both_hook_locks_fail_immediately_without_modifying_captures_or_index(self):
        e=self.env;e.stage();before=e.root.joinpath('collection.json').read_bytes();state=(e.spool/'collector-state.json').read_bytes()
        for root in (e.spool,e.root):
            with daily.locked(root):
                started=time.monotonic();out=e.collector.hook(e.event('PreToolUse'))
            self.assertLess(time.monotonic()-started,.08)
            self.assertIn('additionalContext',out['hookSpecificOutput']);self.assertNotIn('permissionDecision',out['hookSpecificOutput'])
            self.assertEqual(out['hookSpecificOutput']['hookEventName'],'PreToolUse')
            self.assertEqual(e.root.joinpath('collection.json').read_bytes(),before)
            self.assertEqual((e.spool/'collector-state.json').read_bytes(),state)

    def test_existing_exact_turn_context_avoids_all_locks_and_dataset_scans(self):
        e=self.env;e.collector.hook(e.event('UserPromptSubmit'))
        event=e.event('PreToolUse');event.update(tool_name='exec_command',tool_input={'cmd':'synthetic'})
        with patch.object(daily,'locked',side_effect=AssertionError('locked')),patch.object(e.collector,'index',side_effect=AssertionError('dataset read')):
            self.assertEqual(e.collector.hook(event),{})
        event['turn_id']='new-turn'
        out=e.collector.hook(event);self.assertIn('additionalContext',out['hookSpecificOutput'])

    def test_expired_hook_does_not_start_persistence(self):
        e=self.env;before=(e.root/'collection.json').read_bytes()
        out=e.collector.hook(e.event('PreToolUse'),deadline=time.monotonic()-1)
        self.assertIn('時間已到',out['hookSpecificOutput']['additionalContext'])
        self.assertEqual((e.root/'collection.json').read_bytes(),before)
        self.assertFalse((e.spool/'collector-state.json').exists())

    def test_deadline_is_not_raised_halfway_through_atomic_promotion(self):
        e=self.env;capture=e.stage();original=Path(capture['request_path']).read_bytes();e.collector.hook(e.event('PreToolUse'))
        now=[0.0];write=daily.write
        def durable(path,value):
            if path.name=='receipt.json':now[0]=2.0
            return write(path,value)
        with patch.object(daily.time,'monotonic',side_effect=lambda:now[0]),patch.object(daily,'write',side_effect=durable):
            e.collector.hook(e.event('PostToolUse'),deadline=1.0)
        self.assertEqual(e.collector.index()['count'],3)
        self.assertEqual(Path(capture['request_path']).read_bytes(),original)
        e.collector.hook(e.event('PostToolUse'));self.assertEqual(e.collector.index()['count'],3)

    def test_interrupted_state_write_recovers_on_next_natural_event_without_double_count(self):
        e=self.env;e.stage();e.collector.hook(e.event('PreToolUse'));write=daily.write
        def interrupted(path,value):
            if path==e.spool/'collector-state.json':raise OSError('synthetic interruption')
            return write(path,value)
        with patch.object(daily,'write',side_effect=interrupted):
            with self.assertRaises(OSError):e.collector.hook(e.event('PostToolUse'))
        self.assertEqual(e.collector.index()['count'],3)
        event=e.event('PreToolUse');event.update(tool_name='exec_command',tool_input={})
        e.collector.hook(event)
        self.assertTrue(all(row['status']=='counted' for row in e.collector.state()['stages'].values()))
        e.collector.hook(e.event('PostToolUse'));self.assertEqual(e.collector.index()['count'],3)

    def test_owned_partial_slot_recovers_but_unsafe_orphan_is_not_deleted(self):
        e=self.env;e.collector.hook(e.event('UserPromptSubmit'));state=e.spool/'collector-state.json';before=daily.read(state)
        temp=state.with_name('.'+state.name+'.collector-next');temp.write_bytes(b'{partial');temp.chmod(0o600)
        e.collector.hook(e.event('UserPromptSubmit'));self.assertFalse(temp.exists())
        self.assertEqual(e.collector.index()['count'],2)
        target=e.root.parent/'unrelated';target.write_text('untouched');temp.symlink_to(target)
        with self.assertRaises(ValueError):daily.write(state,before)
        self.assertTrue(temp.is_symlink());self.assertEqual(target.read_text(),'untouched')
