"""Identity, accounting and upgrade guarantees at the public hook/CLI boundary."""
from contextlib import closing
import io
import json
import os
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

from mrh.adapters.hosts import codex_packets as p
from mrh.adapters.hosts.codex_packet_import import import_history
from mrh.advisory import engine
from mrh.advisory.request import AdvisoryRequest, Child
from mrh.advisory.store import AdviceStore, PacketStore, request_id
from mrh.presentation.cli import main
from tests.application import test_codex_packets as fixtures
SESSION, TURN, TASK = fixtures.SESSION, fixtures.TURN, fixtures.TASK


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.PacketTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.db = self.f.settings.parent/'advice.sqlite3'

    def query(self, packet):
        self.assertIn('classification ready', self.f.reason(self.f.run_hook(self.f.event(packet))))

    def release(self, packet, effort='max'):
        e = self.f.event(packet,True);e['tool_input']['reasoning_effort']=effort
        self.assertEqual(self.f.run_hook(e)['hookSpecificOutput']['permissionDecision'],'allow')
        self.assertEqual(self.f.run_hook({**e,'hook_event_name':'PostToolUse','tool_response':{'task_name':'child_'+packet['packet_id']}}),{})
        return e

    def public_stats(self):
        out=io.StringIO();self.assertEqual(main(['status','--json','--days','0','--settings',str(self.f.settings)],stdout=out,stderr=io.StringIO()),0)
        return json.loads(out.getvalue())

    def test_prepare_without_native_ids_then_bound_native_query_and_public_status(self):
        packet=self.f.prep();body=json.loads(Path(packet['body_path']).read_text())
        self.assertEqual(set(body['scope']),{'workspace','revision'})
        self.assertIsNone(p.status(self.f.settings,packet['packet_id'])['binding'])
        self.assertIn('not_classified',self.f.reason(self.f.run_hook(self.f.event(packet,True))))
        self.query(packet);row=p.status(self.f.settings,packet['packet_id'])
        self.assertEqual(row['binding'],{'session':SESSION,'turn':TURN,'query_call':self.f.event(packet)['tool_use_id']})
        self.assertNotIn('classification',row);self.assertFalse((Path(packet['body_path']).parent/'query.sqlite3').exists())
        self.f.run_hook(self.f.event(packet,tool_use_id='second_query'))
        self.assertEqual(self.f.fake.calls,1)
        self.release(packet,'high');data=self.public_stats()
        self.assertEqual(data['decisions'],{'advise':1});self.assertEqual(data['tiers'],{'Light':1})
        self.assertEqual((data['children_started'],data['children_following_advice'],data['packet_children_started']),(1,1,1))
        self.assertEqual(data['observed_models'],{})

    def test_cross_session_turn_and_simultaneous_first_claim_stop(self):
        packet=self.f.prep();directory=p._directory(self.f.settings,packet['packet_id'])
        with p._lock(directory):
            self.assertIn('in_progress',self.f.reason(self.f.run_hook(self.f.event(packet))))
        self.assertIsNone(p.status(self.f.settings,packet['packet_id'])['binding']);self.query(packet)
        for field in ('session_id','turn_id'):
            for release in (False,True):
                self.assertIn('scope_invalid',self.f.reason(self.f.run_hook(self.f.event(packet,release,**{field:'00000000-0000-4000-8000-000000000009'}))))
        self.assertEqual(self.f.fake.calls,1)

    def test_parallel_first_native_claim_has_one_winner(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        packet=self.f.prep();barrier=Barrier(2)
        def claim(session):
            barrier.wait()
            return self.f.run_hook(self.f.event(packet,session_id=session))
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(claim,(SESSION,'00000000-0000-4000-8000-000000000009')))
        reasons=[self.f.reason(x) for x in results]
        self.assertEqual(sum('classification ready' in r for r in reasons),1)
        self.assertEqual(self.f.fake.calls,1)

    def test_reset_during_inflight_query_never_resurrects_detached_counts(self):
        packet=self.f.prep();fake=self.f.fake
        def classify(task,context,attempts):
            AdviceStore(self.db).delete_since(0)
            return __import__('mrh.routing.types',fromlist=['Classification']).Classification('Light',.9)
        fake.classify=classify
        self.f.reason(self.f.run_hook(self.f.event(packet)))
        data=self.public_stats();self.assertEqual(data['decisions'],{});self.assertEqual(data['classifier_requests'],0)
        with closing(AdviceStore(self.db).connect()) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM packet_links').fetchone()[0],0)

    def test_parallel_same_profile_exact_association_and_other_profile_not_followed(self):
        a,b=self.f.prep(),self.f.prep();self.query(a);self.query(b)
        self.release(b,'max');self.release(a,'high')
        data=self.public_stats()
        self.assertEqual(data['decisions'],{'advise':2});self.assertEqual(data['children_started'],2)
        self.assertEqual((data['children_following_advice'],data['packet_children_started']),(1,2))
        with closing(AdviceStore(self.db).connect()) as db:
            for packet,followed in ((a,1),(b,0)):
                link=db.execute('SELECT * FROM packet_links WHERE packet_id=?',(packet['packet_id'],)).fetchone()
                child=db.execute('SELECT * FROM children WHERE call_id=?',(self.f.event(packet,True)['tool_use_id'],)).fetchone()
                self.assertEqual((child['advice_request_id'],child['followed']),(link['query_request_id'],followed))
        self.assertEqual(self.f.fake.calls,2)

    def test_packet_and_ordinary_same_text_advice_cannot_cross_dedupe_or_reissue(self):
        packet=self.f.prep();self.query(packet);store=AdviceStore(self.db)
        settings=__import__('mrh.infrastructure.settings_v2',fromlist=['read']).read(self.f.settings)
        req=AdvisoryRequest('codex',SESSION,TURN,'ordinary',TASK)
        advice=engine.decide(req,settings,store,lambda:self.f.fake,lambda:1002)
        self.assertEqual(advice.action,'advise');self.assertEqual(self.f.fake.calls,2)
        self.assertIsNone(store.call(request_id('codex',SESSION,TURN,self.f.event(packet)['tool_use_id'])))
        self.release(packet,'high')
        ordinary=engine.decide(AdvisoryRequest('codex',SESSION,TURN,'ordinary_release',TASK,explicit_model='gpt-6-luna',explicit_effort='high'),settings,store,lambda:self.f.fake,lambda:1003)
        self.assertEqual(ordinary.reason,'advice_reissue')
        store.record_child(Child('codex',SESSION,'ordinary_release','gpt-6-luna','high',None,'ordinary-child'),1004)
        data=self.public_stats();self.assertEqual(data['children_following_advice'],2);self.assertEqual(data['decisions'],{'advise':2})

    def test_unknown_release_after_central_claim_before_receipt_write_never_reallows(self):
        packet=self.f.prep();self.query(packet)
        original=p._write
        def broken(path,row):
            if row.get('state')=='released':raise OSError('isolated disk fault')
            return original(path,row)
        with patch.object(p,'_write',broken):self.f.reason(self.f.run_hook(self.f.event(packet,True)))
        self.assertIn('outcome_unknown',self.f.reason(self.f.run_hook(self.f.event(packet,True))))
        self.assertEqual(self.public_stats()['children_started'],0)

    def test_status_does_not_create_db_or_migrate_or_clean_expired_packet(self):
        packet=self.f.prep();receipt=p._directory(self.f.settings,packet['packet_id'])/'receipt.json';before=receipt.read_bytes()
        p.status(self.f.settings,packet['packet_id'],clock=lambda:2000)
        self.assertEqual(receipt.read_bytes(),before);self.assertTrue(Path(packet['body_path']).exists())
        self.assertFalse(self.db.exists());self.assertEqual(self.public_stats()['packet_classifications'],0);self.assertFalse(self.db.exists())
        p.status(self.f.settings,packet['packet_id'],finish=True,clock=lambda:2000);self.assertFalse(Path(packet['body_path']).exists())

    def legacy(self):
        packet=self.f.prep();directory=p._directory(self.f.settings,packet['packet_id'])
        Path(packet['body_path']).rename(directory/'packet.json');packet['body_path']=str(directory/'packet.json')
        body=p._read(Path(packet['body_path']));body.update(version=1,scope={'session':SESSION,'turn':TURN,**body['scope']})
        os.chmod(Path(packet['body_path']),0o600);p._write(Path(packet['body_path']),body);os.chmod(Path(packet['body_path']),0o400)
        row={k:v for k,v in body.items() if k!='task'};row.update(state='classified',created=1000,query_call='packet_query_'+packet['packet_id'])
        settings=__import__('mrh.infrastructure.settings_v2',fromlist=['read']).read(self.f.settings)
        query=AdvisoryRequest('codex',SESSION,TURN,row['query_call'],TASK)
        advice=engine.decide(query,settings,AdviceStore(directory/'query.sqlite3'),lambda:self.f.fake,lambda:1001)
        row['classification']={'action':advice.action,'reason':advice.reason,'tier':advice.tier,'confidence':advice.confidence,'candidates':list(advice.candidates),'query_request_id':advice.request_id}
        p._write(directory/'receipt.json',row)
        return packet,row,directory

    def remove_legacy_body(self, packet, directory):
        body = Path(packet['body_path'])
        self.assertEqual(directory, p._directory(self.f.settings, packet['packet_id']))
        self.assertEqual(body, directory/'packet.json')
        self.assertTrue(body.is_relative_to(self.f.root))
        p._private(body)
        if os.name == 'nt':
            os.chmod(body, 0o600)
        body.unlink()

    def test_v1_import_twice_preserves_original_rows_and_live_packet_compatibility(self):
        packet,row,directory=self.legacy()
        # Freeze the complete historical database before byte comparison. WAL
        # checkpointing by a later GC/close is not a modification of its facts.
        with closing(sqlite3.connect(directory/'query.sqlite3')) as db:
            db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        before=(directory/'query.sqlite3').read_bytes()
        self.assertEqual(import_history(self.f.settings),{'imported':1,'already_imported':0,'unknown':[]})
        self.assertEqual(import_history(self.f.settings),{'imported':0,'already_imported':1,'unknown':[]})
        self.assertEqual((directory/'query.sqlite3').read_bytes(),before)
        self.query(packet);self.assertEqual(self.f.fake.calls,1);self.release(packet,'high')
        data=self.public_stats();self.assertEqual(data['decisions'],{'advise':1});self.assertEqual(data['children_following_advice'],1)

    def test_completed_legacy_import_preserves_attempt_times_and_exact_child_without_false_adoption(self):
        packet,row,directory=self.legacy();settings=__import__('mrh.infrastructure.settings_v2',fromlist=['read']).read(self.f.settings)
        old=AdviceStore(directory/'query.sqlite3');rid=row['classification']['query_request_id']
        old.attempt(rid,'jev','started',1001.1,requested_model='jev-1.13.0')
        old.attempt(rid,'jev','returned',1001.2,response_model='jev-1.13.0',input_tokens=50,output_tokens=8)
        store=AdviceStore(self.db);call='legacy_release_'+packet['packet_id']
        engine.decide(AdvisoryRequest('codex',SESSION,TURN,call,TASK,explicit_model='gpt-6-luna',explicit_effort='max'),settings,store,lambda:self.f.fake,lambda:1002)
        store.record_child(Child('codex',SESSION,call,'gpt-6-luna','max',None,'legacy-child'),1003)
        row.update(state='completed',release_call=call,released=1002,completed=1003,requested_model='gpt-6-luna',requested_effort='max',child_id='legacy-child',transport_observation={'outbound':{'task_sha256':row['sha256'],'task_length':row['length']}})
        p._write(directory/'receipt.json',row);self.remove_legacy_body(packet,directory)
        self.assertEqual(import_history(self.f.settings)['imported'],1);self.assertEqual(import_history(self.f.settings)['already_imported'],1)
        data=self.public_stats();self.assertEqual((data['classifier_calls'],data['classifier_input_tokens']),(1,50))
        self.assertEqual((data['packet_children_started'],data['children_following_advice']),(1,0));self.assertEqual(data['decisions'],{'advise':1})
        with closing(store.connect()) as db:self.assertEqual([r[0] for r in db.execute("SELECT ts FROM attempts WHERE outcome IN ('started','returned') ORDER BY ts")],[1001.1,1001.2])

    def test_import_failure_rolls_back_then_recovers_and_reset_prevents_resurrection(self):
        packet,row,directory=self.legacy();store=AdviceStore(self.db)
        with closing(store.connect()) as db, db:db.execute("CREATE TRIGGER reject_import BEFORE INSERT ON packet_imports BEGIN SELECT RAISE(ABORT,'isolated interruption'); END")
        result=import_history(self.f.settings);self.assertEqual(len(result['unknown']),1);self.assertEqual(store.stats(0)['decisions'],{})
        with closing(store.connect()) as db, db:db.execute('DROP TRIGGER reject_import')
        self.assertEqual(import_history(self.f.settings)['imported'],1)
        self.query(packet);self.release(packet,'high')
        preview=store.preview_since(0);deleted=store.delete_since(0);self.assertEqual(deleted,preview['delete'])
        self.assertEqual(store.stats(0)['decisions'],{});self.assertEqual(store.stats(0)['children_started'],0)
        with closing(store.connect()) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM packet_links').fetchone()[0],0)
        # Native completion altered the receipt. Its old source is preserved but
        # cannot be relabelled as a new import, nor resurrect deleted statistics.
        result=import_history(self.f.settings);self.assertEqual(result['imported'],0);self.assertEqual(store.stats(0)['decisions'],{})

    def test_retention_cascades_query_lineage_with_no_orphan_counts(self):
        packet=self.f.prep();self.query(packet);self.release(packet,'high');store=AdviceStore(self.db)
        store.prune_before(1001.5)
        data=store.stats(0);self.assertEqual(data['decisions'],{});self.assertEqual(data['children_started'],0)
        with closing(store.connect()) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM packet_links').fetchone()[0],0)

    def test_legacy_missing_hash_or_conflicting_native_scope_stays_unknown(self):
        packet,row,directory=self.legacy();self.remove_legacy_body(packet,directory)
        result=import_history(self.f.settings);self.assertEqual(result['unknown'][0]['reason'],'legacy_body_hash_unknown');self.assertFalse(self.db.exists())


if __name__=='__main__':unittest.main()
