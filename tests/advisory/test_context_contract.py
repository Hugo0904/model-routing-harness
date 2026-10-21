import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from mrh.adapters.providers.typesafe_protocol import serialize_request
from mrh.advisory import engine
from mrh.advisory.store import AdviceStore
from mrh.application import classify as manual
from mrh.advisory.hook_budget import HookBudget
from mrh.routing.types import Classification, ContextSummary
from tests.advisory import test_engine as fixtures
from tests.presentation import test_classify as wire_fixtures
from mrh.adapters.providers.typesafe import TypesafeClassifier


class WireClassifier:
    def __init__(self):
        self.contexts = []
        self.wire = []

    def classify(self, task, context, recorder):
        self.contexts.append(context)
        self.wire.append(serialize_request(task, context))
        return Classification('Light', .9)


class ContextContractTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.store = AdviceStore(Path(temp.name) / 'advice.sqlite3')
        self.settings = fixtures.settings(**fixtures.LISTS)

    def test_only_approved_summary_reaches_existing_jev_state_without_changing_confidence(self):
        fake = WireClassifier(); lookups = []
        def producer(task, timeout_seconds):
            lookups.append((task, timeout_seconds))
            return ContextSummary('Synthetic minimal approved context.', 'private-local-reference', True)
        advice = engine.decide(fixtures.req(), self.settings, self.store, lambda: fake, context_provider=producer)
        self.assertEqual(fake.contexts, ['Synthetic minimal approved context.'])
        self.assertEqual(len(lookups), 1); self.assertGreater(lookups[0][1], 0); self.assertLessEqual(lookups[0][1], .1)
        self.assertEqual(advice.confidence, .9)
        self.assertIn('Synthetic minimal approved context.', json.dumps(fake.wire[0]))
        self.assertNotIn('private-local-reference', json.dumps(fake.wire[0]))

    def test_default_none_is_task_only_and_summary_provenance_never_persist(self):
        fake = WireClassifier()
        engine.decide(fixtures.req(), self.settings, self.store, lambda: fake)
        self.assertEqual(fake.wire, [serialize_request(fixtures.req().task)])
        self.assertNotIn('events', self.store.stats(0))
        second = WireClassifier()
        manual.run(self.settings, 'manual synthetic', store=self.store, classifier_factory=lambda: second,
            context_provider=lambda *args: ContextSummary('approved secret-free context','PRIVATE_PROVENANCE',True))
        self.assertEqual(second.contexts, ['approved secret-free context'])
        with self.store.connect(readonly=True) as db:
            saved = '\n'.join(str(tuple(row)) for table in ('advice','attempts','notices') for row in db.execute('SELECT * FROM '+table))
        for value in ('approved secret-free context', 'PRIVATE_PROVENANCE'):
            self.assertNotIn(value, saved)

    def test_protected_replayed_and_duplicate_tasks_do_not_look_up_context(self):
        calls = []; fake = WireClassifier()
        def producer(*args): calls.append(args); return None
        for n, fields in enumerate(({'explicit_model':'luna'},{'explicit_effort':'high'},{'role':'reviewer'})):
            engine.decide(fixtures.req('protected'+str(n), **fields), self.settings, self.store, lambda: fake, context_provider=producer)
        self.assertEqual(calls, [])
        engine.decide(fixtures.req('first'), self.settings, self.store, lambda: fake, context_provider=producer)
        engine.decide(fixtures.req('first'), self.settings, self.store, lambda: fake, context_provider=producer)
        engine.decide(fixtures.req('dedup'), self.settings, self.store, lambda: fake, context_provider=producer)
        self.assertEqual(len(calls), 1)

    def test_both_permissions_provider_and_typed_limits_are_conservative(self):
        cases = [None, {'summary':'untyped'}, ContextSummary('ok','ref',False), ContextSummary('ok','ref',1),
            ContextSummary(' ','ref',True), ContextSummary(7,'ref',True), ContextSummary('ok','',True),
            ContextSummary('ok','ref\nCANARY',True), ContextSummary('ok','x'*257,True),
            ContextSummary('ok','ref\u202eCANARY',True), ContextSummary('ok',7,True),
            ContextSummary('界'*1366,'ref',True), ContextSummary('\ud800','ref',True)]
        for n, value in enumerate(cases):
            with self.subTest(value=repr(value)):
                fake = WireClassifier()
                manual.run(self.settings,'synthetic',store=self.store,classifier_factory=lambda:fake,
                    request_hex='invalid'+str(n),context_provider=lambda *args:value)
                self.assertEqual(fake.wire, [serialize_request('synthetic')])
        fake = WireClassifier()
        manual.run(self.settings,'limit',store=self.store,classifier_factory=lambda:fake,
            context_provider=lambda *args:ContextSummary('a'*4096,'r'*256,True))
        self.assertEqual(fake.contexts,['a'*4096])
        for provider, allowed in (('codex_subscription',True),('claude_subscription',True),('jev',False),('jev',1)):
            settings={**self.settings,'classifier':{**self.settings['classifier'],'provider':provider},'task_export_permitted':allowed}
            if allowed is not True:
                with self.assertRaises(manual.ClassifyError):manual.run(settings,'x',store=self.store,context_provider=lambda *args:self.fail('lookup'))
            else:
                fake=WireClassifier();manual.run(settings,'x',store=self.store,classifier_factory=lambda:fake,context_provider=lambda *args:self.fail('lookup'))
                self.assertEqual(fake.contexts,[None])
        fake=WireClassifier()
        engine.decide(fixtures.req('no-export'),{**self.settings,'task_export_permitted':False},self.store,lambda:fake,
            context_provider=lambda *args:self.fail('lookup'))
        self.assertEqual(fake.contexts,[None])

    def test_context_exception_and_late_return_fall_back_without_second_export(self):
        def broken(*args):raise RuntimeError('PRIVATE_EXCEPTION_CONTEXT')
        fake=WireClassifier();manual.run(self.settings,'exception',store=self.store,classifier_factory=lambda:fake,context_provider=broken)
        self.assertEqual(fake.contexts,[None])
        finish=threading.Event(); release=threading.Event()
        def slow(*args):
            release.wait(1);finish.set();return ContextSummary('LATE_PRIVATE_SUMMARY','ref',True)
        fake=WireClassifier();start=time.monotonic()
        manual.run(self.settings,'late',store=self.store,classifier_factory=lambda:fake,context_provider=slow)
        self.assertLess(time.monotonic()-start,.3);self.assertEqual(fake.contexts,[None])
        before=self.store.stats(0);release.set();self.assertTrue(finish.wait(1))
        self.assertEqual(fake.contexts,[None]);self.assertEqual(self.store.stats(0),before)

    def test_context_wait_uses_original_deadline_and_hook_budget(self):
        release=threading.Event();self.addCleanup(release.set)
        settings={**self.settings,'classifier':{**self.settings['classifier'],'timeout_seconds':.04}}
        fake=WireClassifier();start=time.monotonic()
        with self.assertRaises(manual.ClassifyError) as error:
            manual.run(settings,'deadline',store=self.store,classifier_factory=lambda:fake,
                context_provider=lambda *args:(release.wait(.2),ContextSummary('late','ref',True))[1])
        self.assertEqual(error.exception.reason,'classifier_timeout');self.assertEqual(fake.contexts,[])
        self.assertLess(time.monotonic()-start,.18)
        budget=HookBudget();self.store.hook_budget=budget;budget.local()
        calls=[]
        engine.decide(fixtures.req('bounded',task='new synthetic'),self.settings,self.store,lambda:WireClassifier(),
            context_provider=lambda task,seconds:(calls.append(seconds),None)[1])
        self.assertEqual(len(calls),1);self.assertLessEqual(calls[0],.1)

    def test_actual_jev_serializer_receives_only_approved_summary(self):
        for permitted in (True, False):
            with self.subTest(permitted=permitted):
                transport=wire_fixtures.Transport()
                classifier=TypesafeClassifier(enabled=True,task_export_permitted=True,
                    credential_resolver=lambda:'synthetic-credential',transport=transport)
                result=manual.run(self.settings,'synthetic permitted task',store=self.store,
                    classifier_factory=lambda:classifier,context_provider=lambda *args:ContextSummary(
                        'Approved minimal summary','PRIVATE_PROVENANCE_ONLY',permitted))
                state=transport.bodies[0]['state']
                self.assertEqual(state.get('context_summary'),'Approved minimal summary' if permitted else None)
                self.assertNotIn('PRIVATE_PROVENANCE_ONLY',json.dumps(transport.bodies))
                self.assertEqual(result['confidence'],.72)

    def test_classifier_gets_only_deadline_remaining_after_context(self):
        from mrh.routing.core import bounded_call
        now=[0.0];waits=[]
        def producer(*args):now[0]=.06;return ContextSummary('ok','ref',True)
        def observed(function, timeout):waits.append(timeout);return bounded_call(function,timeout)
        with patch('mrh.routing.attempts.time.monotonic',side_effect=lambda:now[0]),patch.object(manual,'bounded_call',side_effect=observed):
            manual.run(self.settings,'shared deadline',store=self.store,classifier_factory=WireClassifier,context_provider=producer)
        self.assertEqual(len(waits),1);self.assertAlmostEqual(waits[0],.94)

    def test_outer_hook_remaining_time_also_bounds_manual_context_lookup(self):
        release=threading.Event();self.addCleanup(release.set);limits=[]
        budget=HookBudget(started=time.monotonic()-.93);budget.local();self.store.hook_budget=budget
        def slow(task, seconds):limits.append(seconds);release.wait(.2);return ContextSummary('late','ref',True)
        fake=WireClassifier()
        with self.assertRaises(manual.ClassifyError):
            manual.run(self.settings,'outer budget',store=self.store,classifier_factory=lambda:fake,context_provider=slow)
        self.assertEqual(len(limits),1);self.assertLessEqual(limits[0],.07);self.assertEqual(fake.contexts,[])
