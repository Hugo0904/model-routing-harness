"""Explicit lease guard fixtures, not producer/native Hook evidence."""
import fcntl
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest

from mrh.adapters.hosts.isolated_host_export import ExportError
from mrh.adapters.hosts.isolated_live_hook import OwnedRegistration
from tests.adapters.test_isolated_host_export import fixture, SCOPE


class LiveGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        (self.root/"OWNED.json").write_text(json.dumps({"owner":"MRH-001-E8"}))
        artifacts = {}
        for name in ("producer", "bootstrap"):
            p = self.root/name; p.write_bytes(b"explicit unexecuted guard fixture");p.chmod(0o600)
            artifacts[name] = {"path":str(p),"sha256":hashlib.sha256(p.read_bytes()).hexdigest()}
        context = self.root/"context.json";context.write_text(json.dumps({**artifacts,"registration_id":"fixture-registration"}))
        (self.root/"launch.lock").touch()
        self.lock = (self.root/"launch.lock").open("r+");self.addCleanup(self.lock.close)
        fcntl.flock(self.lock,fcntl.LOCK_EX)
        self.registration = OwnedRegistration(context)
        self.event = {"session_id":SCOPE.session_id,"turn_id":SCOPE.turn_id,"tool_use_id":SCOPE.tool_call_id,
                      "tool_input":{"message":"guard fixture"},"pending_delegation":fixture()}
        (self.root/"leases").mkdir(); self.event["pending_delegation"]["validity"]["nonce"]="00000000-0000-4000-8000-000000000001"
        self.reset()

    def reset(self, **changes):
        lease = {"registration_id":"fixture-registration","admitted":False,"phase":"active","expires_at":time.time()+30,
                 "scope":SCOPE.__dict__,"routing":{k:None for k in ("model","agent_type","reasoning_effort","fork_context")},
                 "export_nonce":"00000000-0000-4000-8000-000000000001", **changes}
        (self.root/"leases/00000000-0000-4000-8000-000000000001.json").write_text(json.dumps(lease))

    def test_wire_does_not_construct_registration(self):
        with self.assertRaisesRegex(ExportError,"unverified_live_registration"):
            from mrh.adapters.hosts.isolated_live_hook import LiveExchange
            LiveExchange(fixture(),self.event)

    def test_closed_single_use_and_old_epoch_reject(self):
        exchange = self.registration.exchange(self.event)
        self.assertTrue(exchange.resolve(self.event).role_protection.known)
        exchange.close()
        with self.assertRaises(ExportError): self.registration.exchange(self.event)
        self.reset(export_nonce="new-host-epoch")
        with self.assertRaises(ExportError): self.registration.exchange(self.event)
        self.reset(admitted=True)
        with self.assertRaisesRegex(ExportError,"replayed_live_exchange"): self.registration.exchange(self.event)

    def test_input_changes_and_midflight_expiry_reject(self):
        exchange = self.registration.exchange(self.event)
        self.addCleanup(exchange.close)
        changed = {**self.event,"tool_input":{"message":"guard fixture","model":"changed"}}
        with self.assertRaisesRegex(ExportError,"changed_live_input"): exchange.resolve(changed)
        exchange._lease["phase"]="closed";exchange._write()
        with self.assertRaises(ExportError): exchange.check(self.event)

    def test_driver_lock_and_expiration_bound(self):
        fcntl.flock(self.lock,fcntl.LOCK_UN)
        with self.assertRaisesRegex(ExportError,"expired_live_exchange"): self.registration.exchange(self.event)
        fcntl.flock(self.lock,fcntl.LOCK_EX)
        self.reset(expires_at=time.time()+1000)
        with self.assertRaises(ExportError): self.registration.exchange(self.event)

    def test_overlapping_leases_and_duplicate_open_are_independent(self):
        first = self.registration.exchange(self.event)
        self.addCleanup(first.close)
        with self.assertRaisesRegex(ExportError, "busy_live_exchange"):
            self.registration.exchange(self.event)
        self.assertTrue(first.resolve(self.event).role_protection.known)
        second_event = copy.deepcopy(self.event)
        second_nonce = "00000000-0000-4000-8000-000000000002"
        second_event["tool_use_id"] = "next-call"
        second_event["pending_delegation"]["scope"]["tool_call_id"] = "next-call"
        second_event["pending_delegation"]["validity"]["nonce"] = second_nonce
        lease = copy.deepcopy(first._lease)
        lease.update(export_nonce=second_nonce, admitted=False)
        lease["scope"]["tool_call_id"] = "next-call"
        second_path = self.root/"leases"/(second_nonce+".json")
        second_path.write_text(json.dumps(lease))
        second = self.registration.exchange(second_event)
        self.addCleanup(second.close)
        first.close()
        self.assertTrue(second.resolve(second_event).role_protection.known)
        self.assertEqual(json.loads(second_path.read_text())["phase"], "active")


if __name__=="__main__": unittest.main()
