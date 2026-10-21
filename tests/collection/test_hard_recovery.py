"""Real process death, then recovery through an ordinary native hook event."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import unittest
from tests.collection import test_daily as fixtures

daily = fixtures.daily


class HardRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.env = fixtures.CollectionTests()
        self.env.setUp()
        self.addCleanup(self.env.tearDown)
        self.capture = self.env.stage()
        self.original = Path(self.capture['request_path']).read_bytes()
        self.env.collector.hook(self.env.event('PreToolUse'))

    def killed_post(self, point):
        marker = self.env.root.parent / 'killed-window'
        # Inject process death at an OS write boundary, not an exception which
        # would run the writer's finally/context-manager cleanup.
        code = '''import importlib.util,json,os,signal,sys
from pathlib import Path
spec=importlib.util.spec_from_file_location('daily',sys.argv[1]);daily=importlib.util.module_from_spec(spec);spec.loader.exec_module(daily)
point=sys.argv[4];marker=Path(sys.argv[5]);opened={};real_open=os.open;real_fdopen=os.fdopen;real_write=daily.write;real_link=os.link
def die(label):
 marker.write_text(label);os.kill(os.getpid(),signal.SIGKILL)
def tracked_open(path,*args,**kwargs):
 fd=real_open(path,*args,**kwargs);opened[fd]=Path(path).name;return fd
class HalfWriter:
 def __init__(self,stream):self.stream=stream
 def __enter__(self):return self
 def __exit__(self,*args):return self.stream.__exit__(*args)
 def __getattr__(self,name):return getattr(self.stream,name)
 def write(self,data):
  self.stream.write(data[:max(1,len(data)//2)]);self.stream.flush();os.fsync(self.stream.fileno());die(point)
def fdopen(fd,*args,**kwargs):
 stream=real_fdopen(fd,*args,**kwargs)
 names=('.receipt.json.collector-next',) if point=='partial-receipt' else ('request.json','.request.json.collector-next')
 return HalfWriter(stream) if point in ('partial-request','partial-receipt') and opened.get(fd) in names else stream
def write(path,value):
 if point=='before-index' and path.name=='collection.json':die('before-index')
 return real_write(path,value)
def link(*args,**kwargs):
 real_link(*args,**kwargs)
 if point=='after-link':die('after-link')
os.open=tracked_open;os.fdopen=fdopen;os.link=link;daily.write=write
daily.Collector(sys.argv[2]).hook(json.loads(sys.argv[3]))
'''
        process = subprocess.run([sys.executable, '-I', '-B', '-c', code,
            str(Path(daily.__file__).resolve()), str(self.env.config),
            json.dumps(self.env.event('PostToolUse')), point, str(marker)], capture_output=True, timeout=4)
        self.assertEqual(process.returncode, -signal.SIGKILL, process.stderr.decode())
        self.assertEqual(marker.read_text(), point)
        self.assertEqual(self.env.collector.index()['count'], 2)

    def ordinary_pre(self):
        event = self.env.event('PreToolUse')
        event.update(tool_name='exec_command', tool_input={'cmd': 'synthetic ordinary work'})
        return self.env.collector.hook(event)

    def assert_recovered_once(self):
        self.ordinary_pre()
        index = self.env.collector.index()
        self.assertEqual(index['count'], 3)
        receipt = index['samples'][-1]
        request = self.env.root / receipt['canonical_message_source'].split('#')[0]
        self.assertEqual(request.read_bytes(), self.original)
        self.assertEqual(Path(self.capture['request_path']).read_bytes(), self.original)
        self.assertEqual(request.stat().st_nlink, 1)
        self.assertEqual(request.stat().st_mode & 0o777, 0o400)
        self.assertEqual(self.env.collector.state()['stages'][self.capture['capture_id']]['status'], 'counted')
        self.ordinary_pre()
        self.env.collector.hook(self.env.event('PostToolUse'))
        self.assertEqual(self.env.collector.index()['count'], 3)

    def test_killed_partial_request_recovers_exact_bytes_on_ordinary_pre(self):
        self.killed_post('partial-request')
        target = self.env.root / 'captures' / self.capture['capture_id']
        self.assertTrue((target / 'receipt.json').is_file())
        self.assertFalse((target / 'request.json').exists())
        self.assertTrue((target / '.request.json.collector-next').is_file())
        self.assert_recovered_once()

    def test_killed_after_request_before_index_recovers_on_ordinary_pre(self):
        self.killed_post('before-index')
        target = self.env.root / 'captures' / self.capture['capture_id']
        self.assertEqual((target / 'request.json').read_bytes(), self.original)
        self.assert_recovered_once()

    def test_killed_after_exclusive_link_recovers_only_its_two_verified_names(self):
        self.killed_post('after-link')
        target = self.env.root / 'captures' / self.capture['capture_id']
        self.assertEqual((target / 'request.json').stat().st_nlink, 2)
        self.assert_recovered_once()
        self.assertFalse((target / '.request.json.collector-next').exists())

    def test_no_committed_native_success_remains_unknown_without_count_or_replay(self):
        self.killed_post('partial-receipt')
        target = self.env.root / 'captures' / self.capture['capture_id']
        self.assertFalse((target / 'receipt.json').exists())
        self.assertTrue((target / '.receipt.json.collector-next').exists())
        self.ordinary_pre(); self.ordinary_pre()
        self.assertEqual(self.env.collector.index()['count'], 2)
        self.assertFalse((target / 'request.json').exists())
        self.assertEqual(self.env.collector.state()['stages'][self.capture['capture_id']]['status'], 'prepared')
        self.assertEqual(Path(self.capture['request_path']).read_bytes(), self.original)

    def test_receipt_identity_hash_and_canonical_mismatch_never_count(self):
        self.killed_post('before-index')
        path = self.env.root / 'captures' / self.capture['capture_id'] / 'receipt.json'
        receipt = daily.read(path)
        mutations = {'capture_id': '0'*32, 'source_thread_id': 'other', 'source_turn_id': 'other',
            'dispatch_call_id': 'other', 'native_agent_reference': '', 'request_file_sha256': '0'*64,
            'canonical_message_source': '../unrelated#/message', 'message_sha256': '0'*64,
            'observed_success_time': float('nan'), 'native_body_equality': 'guessed'}
        for field, value in mutations.items():
            with self.subTest(field=field):
                daily.write(path, {**receipt, field: value})
                out = self.ordinary_pre()
                self.assertIn('additionalContext', out['hookSpecificOutput'])
                self.assertEqual(self.env.collector.index()['count'], 2)
                self.assertEqual(Path(self.capture['request_path']).read_bytes(), self.original)
        daily.write(path, receipt)
        self.assert_recovered_once()

    def test_changed_or_unsafe_original_is_preserved_and_never_counted(self):
        self.killed_post('before-index')
        path = self.env.root / 'captures' / self.capture['capture_id'] / 'request.json'
        path.chmod(0o600); path.write_bytes(b'existing different original'); path.chmod(0o400)
        self.ordinary_pre()
        self.assertEqual(self.env.collector.index()['count'], 2)
        self.assertEqual(path.read_bytes(), b'existing different original')
        path.unlink()  # test-owned synthetic conflicting fixture only
        outside = self.env.root.parent / 'unrelated-original'; outside.write_bytes(b'preserve')
        path.symlink_to(outside)
        self.ordinary_pre()
        self.assertEqual(self.env.collector.index()['count'], 2)
        self.assertTrue(path.is_symlink()); self.assertEqual(outside.read_bytes(), b'preserve')
        path.unlink(); path.write_bytes(self.original); path.chmod(0o644)
        self.ordinary_pre(); self.assertEqual(self.env.collector.index()['count'], 2)
        self.assertEqual(path.stat().st_mode & 0o777, 0o644)
        path.chmod(0o400)
        os.link(path, outside.with_name('extra-link'))
        self.ordinary_pre(); self.assertEqual(self.env.collector.index()['count'], 2)
        self.assertEqual(path.stat().st_nlink, 2)
        outside.with_name('extra-link').unlink()
        self.assert_recovered_once()

    def test_pending_success_obeys_disabled_and_target_then_recovers_once(self):
        self.killed_post('before-index')
        self.env.collector.config['enabled'] = False
        self.ordinary_pre(); self.assertEqual(self.env.collector.index()['count'], 2)
        self.env.collector.config['enabled'] = True
        index = self.env.collector.index(); index['target'] = 2
        daily.write(self.env.root / 'collection.json', index)
        capped = self.ordinary_pre(); self.assertEqual(self.env.collector.index()['count'], 2)
        self.assertIn('收齊', capped['systemMessage'])
        index['target'] = 3; daily.write(self.env.root / 'collection.json', index)
        self.ordinary_pre()  # the earlier cap notice remains deduplicated
        self.assert_recovered_once()
        self.assertTrue(self.env.collector.index()['stopped_at_target'])

    def test_index_uniqueness_does_not_hide_conflicting_receipt(self):
        self.killed_post('before-index')
        receipt = daily.read(self.env.root / 'captures' / self.capture['capture_id'] / 'receipt.json')
        base = self.env.collector.index()
        for changed in ({'native_agent_reference': 'other-agent'}, {'capture_id': '1'*32}, {'dispatch_call_id': 'other-call'}):
            with self.subTest(changed=changed):
                index = {**base, 'count': 3, 'samples': base['samples'] + [{**receipt, **changed}]}
                daily.write(self.env.root / 'collection.json', index)
                before = (self.env.root / 'collection.json').read_bytes()
                self.ordinary_pre()
                self.assertEqual((self.env.root / 'collection.json').read_bytes(), before)
                self.assertEqual(self.env.collector.state()['stages'][self.capture['capture_id']]['status'], 'prepared')

    def test_changed_or_unsafe_stage_cannot_reconstruct_a_successful_capture(self):
        self.killed_post('before-index')
        source = Path(self.capture['request_path'])
        for changed in (self.original + b' ', self.original.replace(b'Complete', b'Changed!')):
            with self.subTest(changed=changed[-20:]):
                source.chmod(0o600); source.write_bytes(changed); source.chmod(0o400)
                self.ordinary_pre()
                self.assertEqual(self.env.collector.index()['count'], 2)
                self.assertEqual(source.read_bytes(), changed)
        source.chmod(0o600); source.write_bytes(self.original); source.chmod(0o400)
        source.parent.chmod(0o755)
        self.ordinary_pre(); self.assertEqual(self.env.collector.index()['count'], 2)
        self.assertEqual(source.parent.stat().st_mode & 0o777, 0o755)
        source.parent.chmod(0o700)
        self.assert_recovered_once()
