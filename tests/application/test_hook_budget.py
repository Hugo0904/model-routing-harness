import io
import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from mrh.advisory import engine
from mrh.advisory.hook_budget import HookBudget, HookExpired, HookStoreBusy, LOCAL_SECONDS, launch_seconds, settings_digest
from mrh.advisory.store import AdviceStore
from mrh.application import advisory_runtime as rt
from mrh.infrastructure import settings_v2 as v2
from mrh.routing.core import ClassifierFailure
from mrh.routing.types import Classification
from tests.application import test_advisory_runtime as fixtures
from tests.application.test_advisory_runtime import codex_pre, Fixed, SECRET


class BudgetTests(unittest.TestCase):
    def test_absolute_deadlines_and_aggregate_wait_reservations(self):
        now = [0.0]; budget = HookBudget(clock=lambda: now[0]); budget.provider('jev')
        self.assertEqual(budget.classification_timeout(10, 'jev'), 1.5)
        self.assertEqual(budget.classification_timeout(.2, 'jev'), .2)
        with budget.sql() as first:
            self.assertEqual(first, 100); now[0] += .060
            with budget.sql() as concurrent:
                self.assertEqual(concurrent, 0)
        with budget.sql() as second:
            self.assertLessEqual(second, 40); now[0] += .040
        with budget.sql() as third:
            self.assertEqual(third, 0)
        now[0] = 2.4
        with self.assertRaises(HookExpired):budget.classification_timeout(10, 'jev')
        now[0] = 2.6
        with self.assertRaises(HookExpired):budget.check()
        local = HookBudget(started=2.0, clock=lambda: now[0]);local.local();now[0]=2.0+LOCAL_SECONDS+.01
        with self.assertRaises(HookExpired):local.local()  # no fresh local window per phase (1.0 s; 2.5 s on Windows)

    def test_sqlite_wait_is_shared_and_cli_default_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'db.sqlite3';normal=AdviceStore(path)
            with normal.connect() as db:self.assertEqual(db.execute('PRAGMA busy_timeout').fetchone()[0],5000)
            budget=HookBudget();store=AdviceStore(path,hook_budget=budget)
            with sqlite3.connect(path) as holder:
                holder.execute('BEGIN IMMEDIATE');start=time.monotonic()
                for _ in range(3):
                    with self.assertRaises((sqlite3.OperationalError, HookStoreBusy)):
                        with store.connect() as db:db.execute('BEGIN IMMEDIATE')
                self.assertLess(time.monotonic()-start,.18)
                self.assertLess(budget.sqlite_left,.005)

    def test_maintenance_skip_or_failure_does_not_mark_day_completed(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=AdviceStore(Path(tmp)/'db.sqlite3')
            budget=HookBudget(started=time.monotonic()-.8);budget.local();store.hook_budget=budget
            with store.connect() as db:before=db.execute('PRAGMA user_version').fetchone()[0]
            self.assertEqual(store.maintain(30,time.time()),0)
            with store.connect() as db:self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],before)
            store.hook_budget=None
            with patch.object(store,'prune_before',side_effect=sqlite3.OperationalError('busy')):
                with self.assertRaises(sqlite3.OperationalError):store.maintain(30,time.time())
            with store.connect() as db:self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],before)


class HookRuntimeBudgetTests(unittest.TestCase):
    def setUp(self):
        self.env=fixtures.RuntimeTests();self.env.setUp();self.addCleanup(self.env.doCleanups);self.env.configure()

    def assert_notice(self,out,phase):
        specific=out['hookSpecificOutput'];self.assertEqual(specific['hookEventName'],phase)
        self.assertIn('additionalContext',specific);self.assertNotIn('permissionDecision',specific)
        self.assertNotIn('updatedInput',specific);self.assertNotIn(SECRET,json.dumps(out))

    def test_runtime_faults_are_context_for_each_host_and_post_never_requests_reissue(self):
        for platform,tool in (('codex','spawn_agent'),('claude','Agent')):
            for phase in ('PreToolUse','PostToolUse'):
                event=codex_pre();event.update(hook_event_name=phase,tool_name=tool,prompt_id='p')
                event['tool_input']={'prompt':'synthetic test','message':'synthetic test'}
                if phase=='PostToolUse':event['tool_response']={'agent_id':'a','agentId':'a'}
                with patch.object(rt,'AdviceStore',side_effect=RuntimeError(SECRET)):
                    out=rt.handle(event,platform,self.env.path)
                self.assert_notice(out,phase)
                if phase=='PostToolUse':self.assertIn('do not repeat a successful tool',out['hookSpecificOutput']['additionalContext'])

    def test_busy_database_returns_context_quickly_without_classifier_or_duplicate_write(self):
        path=self.env.path.parent/'advice.sqlite3';AdviceStore(path);fake=Fixed()
        with sqlite3.connect(path) as holder:
            holder.execute('BEGIN IMMEDIATE');start=time.monotonic()
            out=rt.handle(codex_pre(model='gpt-6-luna'),'codex',self.env.path,classifier_factory=lambda:fake)
        self.assertLess(time.monotonic()-start,.20);self.assert_notice(out,'PreToolUse');self.assertEqual(fake.calls,0)
        self.assertEqual(AdviceStore.read_stats(path,0)['decisions'],{})

    def test_jev_cap_fault_notice_dedup_and_nonjev_settings_are_respected(self):
        seen=[]
        class Fake:
            def classify(self,task,context,attempts):seen.append(attempts.remaining());raise ClassifierFailure('classifier_timeout')
        first=rt.handle(codex_pre(),'codex',self.env.path,classifier_factory=Fake)
        event=codex_pre(message='different synthetic task');event['tool_use_id']='call2'
        second=rt.handle(event,'codex',self.env.path,classifier_factory=Fake)
        self.assert_notice(first,'PreToolUse');self.assertEqual(second,{})
        self.assertTrue(all(t<=1.5 for t in seen))
        config=v2.read(self.env.path);v2.update(self.env.path,classifier={**config['classifier'],'provider':'codex_subscription','model':'gpt-6-luna','timeout_seconds':8})
        event['tool_use_id']='call3';event['tool_input']['message']='third synthetic task'
        rt.handle(event,'codex',self.env.path,classifier_factory=Fake)
        self.assertGreater(seen[-1],7.5)
        self.assertEqual(launch_seconds(event,'codex',v2.read(self.env.path)),48)

    def test_settings_race_or_invalid_settings_has_no_classifier_call(self):
        before=v2.read(self.env.path);digest=settings_digest(before);fake=Fixed();v2.update(self.env.path,enabled=False)
        out=rt.handle(codex_pre(),'codex',self.env.path,classifier_factory=lambda:fake,expected_settings=digest)
        self.assert_notice(out,'PreToolUse');self.assertEqual(fake.calls,0)
        self.env.path.write_text('{"classifier":{"provider":"unknown"}}')
        out=rt.handle(codex_pre(),'codex',self.env.path,classifier_factory=lambda:fake)
        self.assert_notice(out,'PreToolUse');self.assertEqual(fake.calls,0)

    def test_hanging_jev_returns_once_within_inner_budget_and_keeps_remote_uncertainty(self):
        class Slow:
            calls=0
            def classify(self,task,context,attempts):
                self.calls+=1;time.sleep(2.2);return Classification('Light',.9)
        slow=Slow();start=time.monotonic()
        out=rt.handle(codex_pre(),'codex',self.env.path,classifier_factory=lambda:slow)
        elapsed=time.monotonic()-start
        self.assertLess(elapsed,1.9);self.assertGreater(elapsed,1.4);self.assertEqual(slow.calls,1)
        self.assert_notice(out,'PreToolUse');self.assertIn('does not prove remote cancellation',out['hookSpecificOutput']['additionalContext'])

    def test_packet_failure_stays_closed_before_dispatch_and_is_context_only_after_return(self):
        from mrh.adapters.hosts import codex_packets
        event=codex_pre(task_name='mrh_packet_'+'f'*32)
        denied={'hookSpecificOutput':{'hookEventName':'PreToolUse','permissionDecision':'deny','permissionDecisionReason':'unknown; do not retry'}}
        with patch.object(codex_packets,'handle',return_value=denied):
            out=rt.handle(event,'codex',self.env.path,codex_packets=True)
            self.assertEqual(out,denied)
            event.update(hook_event_name='PostToolUse',tool_response={'agent_id':'a'})
            out=rt.handle(event,'codex',self.env.path,codex_packets=True)
            self.assert_notice(out,'PostToolUse')
            self.assertIn('do not repeat a successful tool',out['hookSpecificOutput']['additionalContext'])

    def test_timeout_policy_uses_native_effort_fields_and_keeps_packet_query_classification(self):
        settings=v2.read(self.env.path)
        codex=codex_pre(effort='unsupported-other-host-field')
        self.assertEqual(launch_seconds(codex,'codex',settings),2.5)
        claude={**codex_pre(),'tool_name':'Agent','prompt_id':'p','tool_input':{'prompt':'synthetic','reasoning_effort':'high','effort':False}}
        self.assertEqual(launch_seconds(claude,'claude',settings),2.5)
        packet=codex_pre(task_name='mrh_packet_'+'f'*32,model='gpt-6-luna')
        self.assertEqual(launch_seconds(packet,'codex',settings),2.5)
        packet['tool_input']['task_name']='mrh_release_'+'f'*32
        self.assertEqual(launch_seconds(packet,'codex',settings),LOCAL_SECONDS)

    def test_factory_time_is_charged_once_and_busy_telemetry_does_not_start_classifier(self):
        seen=[];call=engine.bounded_call
        def bounded(fn,seconds):seen.append(seconds);return call(fn,seconds)
        def factory():time.sleep(.04);return Fixed()
        with patch.object(engine,'bounded_call',side_effect=bounded):
            rt.handle(codex_pre(),'codex',self.env.path,classifier_factory=factory)
        self.assertLess(seen[0],1.48)
        path=self.env.path.parent/'advice.sqlite3';fake=Fixed();event=codex_pre(message='new synthetic task');event['tool_use_id']='busy-call'
        with sqlite3.connect(path) as holder:
            holder.execute('BEGIN IMMEDIATE')
            out=rt.handle(event,'codex',self.env.path,classifier_factory=lambda:fake)
        self.assertEqual(fake.calls,0);self.assert_notice(out,'PreToolUse')

    def test_revalidated_settings_change_before_policy_has_no_classifier_call(self):
        first=v2.read(self.env.path);changed={**first,'enabled':False};fake=Fixed()
        with patch.object(rt.v2,'read',side_effect=[first,changed]):
            out=rt.handle(codex_pre(),'codex',self.env.path,classifier_factory=lambda:fake)
        self.assert_notice(out,'PreToolUse');self.assertEqual(fake.calls,0)
