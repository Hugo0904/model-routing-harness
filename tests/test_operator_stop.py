"""D23 selected unusable target -> actual supported Hook deny, synthetic facts."""
import unittest
import json
import tempfile
import io
from contextlib import redirect_stderr
from dataclasses import replace
from pathlib import Path
from mrh.codex import handle_event
from mrh.core import ScriptedClassifier, Classification
from mrh.facts import CallScope, Fact, HostSnapshot, TargetFacts
from mrh.store import Store
from mrh.core import route
from mrh.service import process
from mrh.types import Proposal, Decision
from mrh.terminal import render_details, cell_width


class OperatorStopTests(unittest.TestCase):
    def event(self, call='call'):
        return {'hook_event_name':'PreToolUse','tool_name':'spawn_agent','session_id':'session',
                'turn_id':'turn','tool_use_id':call,'tool_input':{'message':'synthetic fixture'}}
    def facts(self, event, *, available=False, efforts=('high',), deny=True):
        scope=CallScope.for_hook(event)
        known=lambda v:Fact.observed(scope,v,'synthetic-stop-facts')
        return HostSnapshot(scope,True,role_protection=known('unprotected'),deny_supported=known(deny),
                            rewrite_supported=known(True),targets=(TargetFacts('selected-target',known(available),known(efforts),known('high')),))
    def policy(self):
        return {'top_mode':'Fixed','fixed':{'model':'selected-target','effort':'high'},'tiers':{}}
    def proposal(self, event):
        return Proposal('codex','simulation',event['session_id'],event['turn_id'],event['tool_use_id'],event['tool_input'],True)
    def test_selected_unavailable_target_denies_and_names_operator_update_command(self):
        e=self.event();classifier=ScriptedClassifier([Classification('Top',.9)])
        response=handle_event(e,candidate=True,classifier=classifier,policy=self.policy(),capabilities=self.facts(e))
        out=response.get('hookSpecificOutput',{})
        self.assertEqual(out.get('permissionDecision'),'deny')
        self.assertIn('selected-target',out['permissionDecisionReason'])
        self.assertIn('mrh model top',out['permissionDecisionReason'])
        self.assertNotIn('updatedInput',out)
        self.assertEqual(classifier.calls,1)

    def test_cached_child_stop_is_latched_without_reclassifying_or_rewriting_history(self):
        with tempfile.TemporaryDirectory(prefix='mrh-stop-') as root:
            store=Store(Path(root)/'events.sqlite')
            e=self.event(); classifier=ScriptedClassifier([Classification('Top',.9)])
            def run(event, available, policy=None):
                return handle_event(event,store,candidate=True,classifier=classifier,policy=policy or self.policy(),capabilities=self.facts(event,available=available))
            self.assertEqual(run(e,True)['hookSpecificOutput']['permissionDecision'],'allow')
            with store.connect() as db:
                history=db.execute('SELECT decision FROM proposals').fetchone()[0]
            self.assertEqual(run(e,False)['hookSpecificOutput']['permissionDecision'],'deny')
            # Even changing Top mode to Main and restoring availability cannot resume this call.
            stopped=run(e,True,{'top_mode':'Main'})['hookSpecificOutput']
            self.assertEqual(stopped['permissionDecision'],'deny')
            self.assertIn('mrh model top',stopped['permissionDecisionReason'])
            self.assertEqual(classifier.calls,1)
            with store.connect() as db:
                self.assertEqual(db.execute('SELECT decision FROM proposals').fetchone()[0],history)
            fresh=self.event('operator-rerun')
            self.assertEqual(run(fresh,True)['hookSpecificOutput']['permissionDecision'],'allow')
            self.assertEqual(classifier.calls,2)

    def test_stop_receipt_remains_factual_and_has_its_own_anomaly_count(self):
        with tempfile.TemporaryDirectory(prefix='mrh-stop-') as root:
            store=Store(Path(root)/'events.sqlite'); e=self.event()
            classifier=ScriptedClassifier([Classification('Top',.9)])
            handle_event(e,store,candidate=True,classifier=classifier,policy=self.policy(),capabilities=self.facts(e))
            handle_event(dict(e,hook_event_name='PostToolUse',tool_response={'agent_id':'unexpected-child'}),store,candidate=True,classifier=classifier)
            stats=store.stats(synthetic=True)
            self.assertEqual(stats['operator_stops'],1)
            self.assertEqual(stats['stopped_targets'],{'selected-target':1})
            self.assertEqual(stats['requested_models'],{})
            self.assertEqual(stats['handback_anomalies'],0)
            self.assertEqual(stats['operator_stop_anomalies'],1)
            self.assertEqual(stats['simulated_children'],1)
            self.assertEqual(stats['operator_stop_anomaly_evidence']['synthetic'],1)
            self.assertEqual(stats['tiers']['Top'],1)
            self.assertEqual(store.stats()['operator_stops'],0)
            for width in (28,56,120):
                text=render_details(stats,width=width)
                self.assertIn('STOPPED DELEGATIONS',text)
                self.assertIn('Operator updates required: 1',' '.join(text.split()))
                self.assertTrue(all(cell_width(line)<=width for line in text.splitlines()))

    def test_unavailable_effort_and_authoritative_veto_stop_without_rewrite_support(self):
        for tier in ('Light','Small','Mid','Top'):
            with self.subTest(tier=tier):
                e=self.event(tier); p=self.proposal(e); facts=self.facts(e,available=True,efforts=('low',))
                facts=replace(facts,rewrite_supported=Fact.observed(facts.scope,False,'synthetic-stop-facts'))
                policy=dict(self.policy(),tiers={tier:{'model':'selected-target','effort':'high'}})
                d=route(p,policy,facts,ScriptedClassifier([Classification(tier,.9)]))
                self.assertEqual(d.action,'operator_update_required'); self.assertEqual(d.reason,'unsupported_effort')
                self.assertEqual(d.tier,tier); self.assertEqual(d.patch,{})
        for reason in ('catalog_model_retired','catalog_model_unavailable'):
            policy=dict(self.policy(),_target_veto={'selected-target':reason})
            d=route(p,policy,self.facts(e,available=True),ScriptedClassifier([Classification('Top',.9)]))
            self.assertEqual(d.reason,reason); self.assertEqual(d.action,'operator_update_required')
        facts=self.facts(e,available=True,efforts=('high',))
        facts=replace(facts,targets=(replace(facts.targets[0],inherited_effort=Fact.observed(facts.scope,None,'synthetic-stop-facts')),))
        policy=dict(self.policy(),fixed={'model':'selected-target'})
        d=route(p,policy,facts,ScriptedClassifier([Classification('Top',.9)]))
        self.assertEqual((d.action,d.reason),('operator_update_required','unsupported_effort'))

    def test_unknown_availability_and_unverified_stop_control_do_not_invent_a_stop(self):
        e=self.event(); p=self.proposal(e); facts=self.facts(e)
        for deny in (Fact(),Fact.observed(facts.scope,False,'synthetic-stop-facts')):
            classifier=ScriptedClassifier([Classification('Top',.9)])
            d=route(p,self.policy(),replace(facts,deny_supported=deny),classifier)
            self.assertEqual((d.action,d.reason),('preserve','operator_stop_unavailable'))
            self.assertEqual(classifier.calls,0)
        unknown=replace(facts,targets=(replace(facts.targets[0],available=Fact()),))
        classifier=ScriptedClassifier([Classification('Top',.9)])
        d=route(p,self.policy(),unknown,classifier)
        self.assertEqual((d.action,d.reason),('preserve','missing_target_model')); self.assertEqual(classifier.calls,0)

    def test_protection_explicit_and_low_confidence_keep_prior_guards(self):
        e=self.event(); p=self.proposal(e); facts=self.facts(e)
        for protected in ('model','effort'):
            classifier=ScriptedClassifier([Classification('Top',.9)])
            d=route(p,self.policy(),replace(facts,role_protection=Fact.observed(facts.scope,protected,'synthetic-stop-facts')),classifier)
            self.assertEqual(d.action,'preserve');self.assertEqual(classifier.calls,0)
        classifier=ScriptedClassifier([Classification('Top',.9)])
        d=route(replace(p,tool_input=dict(p.tool_input,model='explicit')),self.policy(),facts,classifier)
        self.assertEqual(d.reason,'explicit_model');self.assertEqual(classifier.calls,0)
        d=route(p,self.policy(),facts,ScriptedClassifier([Classification('Top',.49)]))
        self.assertEqual((d.action,d.reason),('preserve','low_confidence'))

    def test_stop_survives_completion_and_latch_write_faults_with_safe_diagnostics(self):
        class FaultStore(Store):
            fail_complete=False
            fail_stop=False
            def complete(self,*args):
                if self.fail_complete: raise OSError('secret-raw-exception-must-not-leak')
                return super().complete(*args)
            def record_stop(self,*args):
                if self.fail_stop: raise OSError('secret-raw-exception-must-not-leak')
                return super().record_stop(*args)
        for stage in ('complete','latch'):
            with self.subTest(stage=stage),tempfile.TemporaryDirectory(prefix='mrh-stop-') as root:
                store=FaultStore(Path(root)/'events.sqlite');e=self.event();p=self.proposal(e)
                classifier=ScriptedClassifier([Classification('Top',.9)])
                if stage=='latch':
                    process(p,self.policy(),self.facts(e,available=True),store,classifier)
                    store.fail_stop=True
                else:store.fail_complete=True
                stderr=io.StringIO()
                with redirect_stderr(stderr):d=process(p,self.policy(),self.facts(e),store,classifier)
                self.assertEqual(d.action,'operator_update_required');self.assertEqual(classifier.calls,1)
                self.assertIn('delegation remains denied',stderr.getvalue())
                self.assertNotIn('secret-raw',stderr.getvalue())

    def test_stop_shape_validates_and_legacy_decisions_still_read(self):
        old=Decision().as_dict();self.assertNotIn('target_model',old)
        self.assertEqual(Decision.from_dict(old),Decision())
        valid=Decision('operator_update_required','unsupported_model','Top',.9,target_model='selected-target')
        self.assertEqual(Decision.from_dict(valid.as_dict()),valid)
        for invalid in (replace(valid,target_model='bad model'),replace(valid,patch={'model':'other'}),replace(valid,confidence=.49),replace(valid,reason='classifier_error')):
            with self.assertRaises(ValueError):invalid.validate()

    def test_cached_unavailable_child_without_deny_reports_the_stop_capability_gap(self):
        with tempfile.TemporaryDirectory(prefix='mrh-stop-') as root:
            store=Store(Path(root)/'events.sqlite'); e=self.event();p=self.proposal(e)
            classifier=ScriptedClassifier([Classification('Top',.9)])
            self.assertEqual(process(p,self.policy(),self.facts(e,available=True),store,classifier).action,'request_child')
            with redirect_stderr(io.StringIO()):
                d=process(p,self.policy(),self.facts(e,deny=False),store,classifier)
            self.assertEqual((d.action,d.reason),('preserve','operator_stop_unavailable'))
            self.assertEqual(classifier.calls,1)


if __name__=='__main__':unittest.main()
