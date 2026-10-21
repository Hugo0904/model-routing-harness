import json
import io
import sqlite3
from unittest.mock import patch
from pathlib import Path
import tempfile
import unittest

from mrh.advisory.request import Advice
from mrh.advisory.store import AdviceStore
from mrh.infrastructure import settings_v2 as v2
from mrh.presentation import ctrl, cli
from tests.advisory import test_engine as fixtures


class StatusEventsTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.path = Path(temp.name).resolve() / 'profile/settings.json'; v2.init(self.path)
        self.store = AdviceStore(self.path.parent / 'advice.sqlite3')

    def test_opt_in_events_reuse_aggregates_and_keep_stable_decision_identity(self):
        self.store.save('q-1', fixtures.req(), 'PRIVATE_TASK_HASH',
            Advice('advise', 'advice_given', 'Light', .9, ({'model': 'luna', 'effort': 'low'},)), 'jev', 10)
        plain = ctrl.status_data(self.path, None)
        detailed = ctrl.status_data(self.path, None, include_events=True)
        self.assertNotIn('events', plain)
        self.assertEqual({k:v for k,v in detailed.items() if k not in ('events','status')},
                         {k:v for k,v in plain.items() if k != 'status'})
        self.assertEqual(detailed['events'], {'format_version': 1, 'since': 0, 'items': [{
            'event_id': 'decision:q-1', 'kind': 'decision', 'timestamp': 10.0,
            'platform': 'codex', 'request_id': 'q-1', 'action': 'advise', 'reason': 'advice_given',
            'tier': 'Light', 'confidence': .9, 'provider': 'jev', 'candidates': [{'model': 'luna','effort': 'low'}],
            'origin': 'ordinary', 'counted_in_decisions': True,
            'recorded_links': {'advice_request_id': None, 'packet_query_request_id': None, 'packet_release_request_id': None}}]})
        self.assertEqual(ctrl.status_data(self.path, None, include_events=True)['events'], detailed['events'])
        self.assertNotIn('PRIVATE_TASK_HASH', json.dumps(detailed))

    def decision(self, rid='q-1', call='c1', ts=10, action='advise', reason='advice_given', extra=None):
        request=fixtures.req(call)
        self.store.save(rid,request,'PRIVATE_TASK_HASH',Advice(action,reason,'Light',.9,
            ({'model':'luna','effort':'low'},),extra=extra or {}),'jev',ts)

    def test_grouped_request_ids_are_stable_unknown_models_are_not_guessed(self):
        self.decision()
        self.store.attempt('q-1','jev','started',11,requested_model='jev-latest')
        self.store.attempt('q-1','jev','returned',12,response_model='jev-v1',input_tokens=40)
        first=self.store.read_stats(self.store.path,0,include_events=True)
        item=next(i for i in first['events']['items'] if i['kind']=='classification_request')
        self.assertEqual(item['event_id'],'classification:d376c2eed20e51b6739919dccdbfd4ac32e740b8878cc682e1e6c50a7786390e')
        self.assertEqual((item['platform'],item['input_tokens'],item['output_tokens']),('codex',40,None))
        self.assertEqual(first['classifier_calls'],1)
        self.store.attempt('q-1','jev','late_returned',13,response_model='jev-v2',input_tokens=55,error_reason='PRIVATE_EXCEPTION')
        self.store.attempt('manual-unlinked','jev','classification_requested',14)
        second=self.store.read_stats(self.store.path,0,include_events=True)
        group=next(i for i in second['events']['items'] if i['event_id']==item['event_id'])
        self.assertIsNone(group['response_model']);self.assertEqual(group['input_tokens'],55)
        self.assertEqual(group['phases'],['started','returned','late_returned'])
        manual=next(i for i in second['events']['items'] if i.get('request_id')=='manual-unlinked')
        self.assertIsNone(manual['platform']);self.assertIsNone(manual['input_tokens']);self.assertFalse(manual['entered'])
        self.assertEqual(second['classifier_calls'],1);self.assertEqual(second['classifier_requests'],2)
        self.assertNotIn('PRIVATE_EXCEPTION',json.dumps(second['events']))

    def test_child_ids_use_native_identity_and_never_requested_as_resolved(self):
        with self.store.connect() as db:
            db.executemany('INSERT INTO children VALUES(?,?,?,?,?,?,?,?,?,?)',[
                ('call-1','codex','synthetic-session',10,'luna','high',None,'PRIVATE_AGENT',None,0),
                ('call-2','codex','synthetic-session',10,'luna','high',None,'PRIVATE_AGENT_2',None,0)])
        data=self.store.read_stats(self.store.path,0,include_events=True);items=data['events']['items']
        self.assertEqual(len({item['event_id'] for item in items}),2)
        golden='child:be088471a9cda899609f5243fa767c8f10e36a1bbe94350fc0fe9d8f0e5bb51b'
        self.assertIn(golden,{item['event_id'] for item in items})
        for item in items:self.assertEqual(item['requested_model'],'luna');self.assertIsNone(item['resolved_model'])
        text=json.dumps(data['events'])
        for private in ('synthetic-session','call-1','call-2','PRIVATE_AGENT'):
            self.assertNotIn(private,text)
        with self.store.connect() as db:db.execute("UPDATE children SET requested_model='sol',resolved_model='sol' WHERE call_id='call-1'")
        updated=self.store.read_stats(self.store.path,0,include_events=True)['events']['items']
        self.assertIn(golden,{item['event_id'] for item in updated})

    def test_ordinary_reissue_and_packet_entities_preserve_the_real_denominators(self):
        self.decision('ordinary','ordinary',10)
        self.store.preserve_explicit('reissue', fixtures.req('r',explicit_model='luna',explicit_effort='low'),
            'PRIVATE_TASK_HASH','jev',11)
        self.decision('packet-q','pq',12)
        self.decision('packet-r','pr',13,'preserve','explicit_model')
        with self.store.connect() as db:
            db.execute('''INSERT INTO packet_links(packet_id,query_request_id,platform,session_id,turn_id,
                task_hash,body_sha256,body_length,workspace,revision,query_call_id,ts,release_request_id,
                release_call_id,release_ts,selected_model,selected_effort,origin) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                ('PRIVATE_PACKET','packet-q','codex','s','t','PRIVATE_TASK_HASH','PRIVATE_BODY_HASH',12,
                 '/PRIVATE_WORKSPACE',1,'pq',12,'packet-r','pr',13,'luna','low','legacy_import'))
        data=self.store.read_stats(self.store.path,0,include_events=True)
        items={item['request_id']:item for item in data['events']['items']}
        self.assertEqual(data['decisions'],{'advise':2})
        self.assertEqual({rid:item['counted_in_decisions'] for rid,item in items.items()},
            {'ordinary':True,'reissue':False,'packet-q':True,'packet-r':False})
        self.assertEqual(items['packet-q']['origin'],'packet_query');self.assertEqual(items['packet-r']['origin'],'packet_release')
        self.assertEqual(items['packet-r']['recorded_links']['packet_query_request_id'],'packet-q')
        self.assertEqual(items['reissue']['recorded_links']['advice_request_id'],'ordinary')
        self.assertNotIn('PRIVATE_',json.dumps(data['events']))

    def test_whitelist_excludes_arbitrary_payload_context_and_private_paths(self):
        self.decision()
        with self.store.connect() as db:
            db.execute('UPDATE advice SET candidates=?', (json.dumps({'candidates':[{'model':'luna','effort':'low'}],
                'context_summary':'PRIVATE_SUMMARY','source_ref':'PRIVATE_SOURCE','workspace':'/PRIVATE_WORKSPACE',
                'credential':'PRIVATE_CREDENTIAL','task':'PRIVATE_TASK'}),))
        events=self.store.read_stats(self.store.path,0,include_events=True)['events']
        self.assertNotIn('PRIVATE_',json.dumps(events))
        self.assertEqual(events['items'][0]['candidates'],[{'model':'luna','effort':'low'}])

    def test_old_schema_and_missing_database_are_read_only_known_empty_snapshots(self):
        with self.store.connect() as db:
            db.executescript('DROP TABLE packet_links;DROP TABLE packet_imports;DROP TABLE child_usage;')
        self.decision()
        path=Path(self.store.path);before=path.read_bytes()
        data=ctrl.status_data(self.path,None,include_events=True)
        self.assertEqual(len(data['events']['items']),1);self.assertEqual(path.read_bytes(),before)
        missing=self.path.parent.parent/'empty/settings.json';v2.init(missing);dbpath=missing.parent/'advice.sqlite3'
        self.assertEqual(ctrl.status_data(missing,None,include_events=True)['events'],{'format_version':1,'since':0,'items':[]})
        self.assertFalse(dbpath.exists())

    def test_cli_option_rejects_text_and_serializes_only_the_opt_in_json(self):
        args=['status','--settings',str(self.path),'--days','0'];out=io.StringIO();err=io.StringIO()
        self.assertEqual(cli.main(args+['--include-events'],stdout=out,stderr=err),2)
        self.assertIn('requires --json',err.getvalue());self.assertEqual(out.getvalue(),'')
        for option in ([],['--include-events']):
            out=io.StringIO();err=io.StringIO()
            self.assertEqual(cli.main(args+['--json']+option,stdout=out,stderr=err),0)
            self.assertEqual('events' in json.loads(out.getvalue()),bool(option))
        invalid=self.path.parent.parent/'invalid/settings.json';v2.init(invalid);(invalid.parent/'advice.sqlite3').write_bytes(b'not a database')
        out=io.StringIO();err=io.StringIO()
        self.assertEqual(cli.main(['status','--json','--include-events','--settings',str(invalid)],stdout=out,stderr=err),2)
        self.assertEqual(out.getvalue(),'');self.assertIn('cli_error',err.getvalue())

    def test_aggregate_and_event_inventory_share_the_same_read_transaction(self):
        self.decision();real_connect=sqlite3.connect;path=self.store.path;written=[]
        class ConcurrentConnection(sqlite3.Connection):
            def execute(connection,sql,*args,**kwargs):
                if sql.startswith('SELECT * FROM attempts') and not written:
                    written.append(True)
                    with real_connect(path) as writer:
                        writer.execute("INSERT INTO advice VALUES('new',20,'codex','other-session','turn','call','private','preserve','explicit_model',NULL,NULL,'jev','[]')")
                        writer.execute("INSERT INTO attempts(request_id,ts,kind,outcome) VALUES('new',20,'jev','started')")
                return super().execute(sql,*args,**kwargs)
        def reader(*args,**kwargs):return real_connect(*args,**kwargs,factory=ConcurrentConnection)
        with patch('mrh.advisory.store.sqlite3.connect',side_effect=reader):
            first=self.store.read_stats(path,0,include_events=True)
        self.assertEqual(written,[True]);self.assertEqual(first['decisions'],{'advise':1})
        self.assertEqual([item['event_id'] for item in first['events']['items']],['decision:q-1'])
        later=self.store.read_stats(path,0,include_events=True)
        self.assertEqual(later['decisions'],{'advise':1,'preserve':1});self.assertEqual(len(later['events']['items']),3)

    def test_unicode_identity_and_order_do_not_depend_on_row_order_or_window(self):
        self.decision('b','cb',10);self.decision('a','ca',10)
        self.store.attempt('a','jev','started',11)
        with self.store.connect() as db:
            db.execute('INSERT INTO children VALUES(?,?,?,?,?,?,?,?,?,?)',('呼叫','codex','合成',12,None,None,None,None,None,0))
        baseline=self.store.read_stats(self.store.path,0,include_events=True)['events']
        self.assertEqual([i['event_id'] for i in baseline['items'][:2]],['decision:a','decision:b'])
        self.assertEqual(baseline['items'][-1]['event_id'],'child:15b9b73efbd4de478a398eade7682492f7c93c124347a5d14cc24dee2c34b95c')
        real_connect=sqlite3.connect
        def reversed_reader(*args,**kwargs):
            connection=real_connect(*args,**kwargs);connection.execute('PRAGMA reverse_unordered_selects=ON');return connection
        with patch('mrh.advisory.store.sqlite3.connect',side_effect=reversed_reader):
            self.assertEqual(self.store.read_stats(self.store.path,0,include_events=True)['events'],baseline)
        selected=self.store.read_stats(self.store.path,11,include_events=True)['events']
        self.assertEqual(len(selected['items']),2);self.assertEqual(selected['items'][0]['platform'],'codex')

    def test_opt_in_refuses_nonfinite_legacy_aggregates_instead_of_invalid_json(self):
        self.decision()
        with self.store.connect() as db:db.execute('UPDATE advice SET confidence=?',(float('inf'),))
        out=io.StringIO();err=io.StringIO()
        code=cli.main(['status','--json','--include-events','--settings',str(self.path)],stdout=out,stderr=err)
        self.assertEqual(code,2);self.assertEqual(out.getvalue(),'');self.assertIn('cli_error',err.getvalue())

    def test_published_schema_fields_match_real_producer_and_synthetic_examples(self):
        root=Path(__file__).resolve().parents[2]/'docs/contracts'
        schema=json.loads((root/'monitor-v1.schema.json').read_text());example=json.loads((root/'monitor-v1.synthetic.json').read_text())
        self.assertTrue(example['example_only']);self.assertEqual(example['events']['format_version'],1)
        self.decision();self.store.attempt('manual-x','jev','started',11)
        with self.store.connect() as db:db.execute('INSERT INTO children VALUES(?,?,?,?,?,?,?,?,?,?)',('c','codex','s',12,None,None,None,None,None,0))
        live=self.store.read_stats(self.store.path,0,include_events=True)['events']['items']
        for item in example['events']['items']+live:
            name='classification' if item['kind']=='classification_request' else item['kind']
            shape=schema['definitions'][name]
            self.assertEqual(set(item),set(shape['properties']));self.assertEqual(set(item),set(shape['required']))
            self.assertFalse(shape['additionalProperties'])
