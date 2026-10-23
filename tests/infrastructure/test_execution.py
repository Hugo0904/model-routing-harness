"""Isolated packet admission and mode transition contracts; no native/provider calls."""
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from mrh.adapters.hosts import codex_packets as packets
from mrh.infrastructure import execution, owned, settings_v2 as settings


class PacketTransitionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        if os.name == 'nt':
            from mrh.adapters.platforms.windows import protect
            protect(self.root)
        self.path = self.root/'profile/settings.json'
        settings.init(self.path)
        settings.update(self.path, enabled=True, task_export_permitted=True, allowed_workspaces=[str(self.root)])
        self.enterContext(patch.dict(os.environ, {'MRH_RUNTIME_ROOT':str(self.root/'runtime')}))

    def packet(self):
        return packets.prepare(self.path, 'isolated admission task', self.root)

    def test_prepared_and_released_refuse_then_terminal_receipt_allows_transition(self):
        item = self.packet();directory = packets.root_for(self.path)/item['packet_id']
        before = self.path.read_bytes()
        with self.assertRaisesRegex(owned.OwnedError, 'mode_change_packet_in_progress'):
            with execution.packet_mode_transition([self.path]):
                self.fail('prepared packet admitted')
        receipt = json.loads((directory/'receipt.json').read_text())
        receipt.update(state='released', expires=time.time()-1)
        packets._write(directory/'receipt.json',receipt)
        with self.assertRaisesRegex(owned.OwnedError,'mode_change_packet_in_progress'):
            with execution.packet_mode_transition([self.path]):
                self.fail('released packet admitted after TTL')
        receipt.update(state='completed')
        packets._write(directory/'receipt.json',receipt)
        with execution.packet_mode_transition([self.path]):
            self.assertEqual(self.path.read_bytes(),before)

    def test_a_busy_individual_packet_lock_refuses_transition(self):
        item = self.packet();directory = packets.root_for(self.path)/item['packet_id']
        with packets._lock(directory):
            with self.assertRaisesRegex(owned.OwnedError,'mode_change_packet_in_progress'):
                with execution.packet_mode_transition([self.path]):
                    self.fail('busy packet admitted')

    def test_switch_root_lock_prevents_real_prepare_in_another_thread(self):
        results=[]
        def prepare():
            try:self.packet()
            except packets.PacketError as error:results.append(error.reason)
        with execution.packet_mode_transition([self.path]):
            worker=threading.Thread(target=prepare);worker.start();worker.join(5)
            self.assertFalse(worker.is_alive())
            self.assertEqual(results,['packet_mode_change_in_progress'])
            self.assertFalse(any(p.is_dir() for p in packets.root_for(self.path).iterdir()))

    def test_real_prepare_holds_root_lock_until_receipt_is_published(self):
        entered, release = threading.Event(),threading.Event()
        original=packets._write;results=[];failures=[]
        def pause(path,value):
            if path.name=='receipt.json':
                entered.set()
                if not release.wait(5):raise AssertionError('test release timed out')
            return original(path,value)
        def prepare():
            try:results.append(self.packet())
            except BaseException as error:failures.append(error)
        with patch.object(packets,'_write',side_effect=pause):
            worker=threading.Thread(target=prepare);worker.start()
            try:
                self.assertTrue(entered.wait(5))
                with self.assertRaisesRegex(owned.OwnedError,'mode_change_packet_in_progress'):
                    with execution.packet_mode_transition([self.path]):
                        self.fail('prepare crossed switch lock')
            finally:
                release.set();worker.join(5)
        self.assertFalse(worker.is_alive());self.assertEqual(failures,[])
        self.assertEqual(len(results),1)
        self.assertTrue((packets.root_for(self.path)/results[0]['packet_id']/'receipt.json').is_file())

    def test_root_lock_is_released_on_failure_for_all_sorted_profiles(self):
        other=self.root/'other/settings.json';settings.init(other)
        with self.assertRaisesRegex(RuntimeError,'synthetic switch failure'):
            with execution.packet_mode_transition([other,self.path,other]):
                raise RuntimeError('synthetic switch failure')
        with execution.packet_mode_transition([self.path,other]):
            pass


if __name__=='__main__':unittest.main()
