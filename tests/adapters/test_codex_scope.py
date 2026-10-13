"""Inspected config assurance and direct routing/lifecycle consumers."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from mrh.adapters.hosts import codex_scope; from mrh.infrastructure import plugin; from mrh.infrastructure import settings
from mrh.adapters.catalogs.catalog import executable_hash
from mrh.routing.core import ScriptedClassifier,route,cached_effect_blocker,cached_operator_stop
from mrh.routing.facts import HostSnapshot
from mrh.routing.types import Proposal,Classification
from dataclasses import replace
from mrh.routing.facts import Fact


class ScopeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='mrh-scope-check-');self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve();self.home=self.root/'home';self.home.mkdir();self.work=self.root/'work';self.work.mkdir()
        self.exe=self.root/'codex';self.exe.write_text('#!/bin/sh\nexit 0\n');self.exe.chmod(0o755)
        self.addCleanup(patch.stopall)
        patch('mrh.adapters.hosts.codex_scope.BINARY_SHA256',executable_hash(self.exe)).start()
        patch.dict(os.environ,{'CODEX_HOME':str(self.home)}).start()
        self.config=self.home/'config.toml';self.config.write_text('model="gpt-6.1-sol"\nmodel_reasoning_effort="low"\n')
        self.version=lambda *a,**k:SimpleNamespace(returncode=0,stdout=codex_scope.VERSION+'\n')
        self.event={'hook_event_name':'PreToolUse','tool_name':'spawn_agent','session_id':'s','turn_id':'t',
                    'tool_use_id':'c','cwd':str(self.work),'model':'gpt-6.1-sol','tool_input':{'message':'owned synthetic task','task_name':'task','fork_turns':'none'}}
        self.proposal=Proposal('codex','simulation','s','t','c',self.event['tool_input'],True)
        rate=lambda n:{'currency':'test-units','unit':'token','service':'scripted-fixture','source_ref':'configured-test-cost','components':{'input':n,'output':n}}
        self.policy={'top_mode':'Fixed','fixed':{'model':'gpt-5.6-luna','effort':'low'},
                     'tiers':{'Light':{'model':'gpt-5.6-luna','effort':'low'}},
                     'rates':{'gpt-6.1-sol':rate(2),'gpt-5.6-luna':rate(1)}}

    def descriptor(self):
        with patch('mrh.adapters.hosts.codex_scope.subprocess.run',side_effect=self.version):
            return codex_scope.prepare(self.exe,self.home,self.work)

    def facts(self,descriptor=None):
        return codex_scope.check(descriptor or self.descriptor(),self.event,native=False,synthetic=True)

    def test_configuration_basis_cannot_be_promoted_to_observed_host_snapshot(self):
        assurance=self.facts();self.assertEqual(assurance.assurance,'inspected-configuration')
        self.assertEqual(assurance.role_protection.basis,'configuration')
        self.assertEqual(assurance.parent_model.basis,'observed')
        self.assertIsNone(assurance.validation_reason(self.proposal))
        self.assertEqual(assurance.facts.validation_reason(self.proposal),'invalid_host_facts')

    def test_generic_routes_known_cost_and_native_main_fixed_branches(self):
        for tier,mode,action in (('Light','Fixed','request_child'),('Top','Fixed','request_child'),('Top','Main','return_to_main')):
            policy=copy.deepcopy(self.policy);policy['top_mode']=mode
            result=route(self.proposal,policy,self.facts(),ScriptedClassifier([Classification(tier,.9)]))
            self.assertEqual(result.action,action)
            if action=='request_child':self.assertEqual(result.patch,{'model':'gpt-5.6-luna','reasoning_effort':'low'})

    def test_omitted_and_null_generic_effort_use_same_mapping_without_mutating_arguments(self):
        for fields in ({},{'model':None,'reasoning_effort':None}):
            original={**self.event['tool_input'],**fields};before=copy.deepcopy(original)
            proposal=replace(self.proposal,tool_input=original)
            decision=route(proposal,self.policy,self.facts(),ScriptedClassifier([Classification('Light',.9)]))
            self.assertEqual(decision.patch,{'model':'gpt-5.6-luna','reasoning_effort':'low'})
            self.assertEqual(original,before)

    def test_null_selected_unsupported_effort_keeps_d23_and_cached_replay_stop(self):
        proposal=replace(self.proposal,tool_input={**self.event['tool_input'],'model':None,'reasoning_effort':None})
        assurance=self.facts();initial=route(proposal,self.policy,assurance,ScriptedClassifier([Classification('Top',.9)]))
        policy=copy.deepcopy(self.policy);policy['fixed']['effort']='unsupported-selected'
        stopped=route(proposal,policy,assurance,ScriptedClassifier([Classification('Top',.9)]))
        self.assertEqual((stopped.action,stopped.reason),('operator_update_required','unsupported_effort'))
        targets=tuple(replace(t,efforts=Fact.configured(t.efforts.scope,('high',),'synthetic-effort-change'))
                      if t.model=='gpt-5.6-luna' else t for t in assurance.targets)
        changed=replace(assurance,facts=replace(assurance.facts,targets=targets))
        replay=cached_operator_stop(proposal,self.policy,changed,initial)
        self.assertEqual((replay.action,replay.reason,replay.target_model),('operator_update_required','unsupported_effort','gpt-5.6-luna'))

    def test_startup_override_forms_refused_and_direct_local_modes_retained(self):
        valid=[['codex','--no-daemon'],['codex','--no-daemon','--no-alt-screen','-C',str(self.work)],
               ['codex','--no-daemon','--cd='+str(self.work)],['codex','--no-daemon','-C'+str(self.work)],
               ['codex','app-server','--listen','stdio://'],['codex','app-server','--listen=stdio://']]
        for args in valid:self.assertTrue(codex_scope.supported_startup(args),args)
        forms=json.loads((Path(__file__).resolve().parents[2]/'tests/fixtures/e17r-parser-forms.json').read_text())['rows']
        for row in forms:self.assertFalse(codex_scope.supported_startup(['codex','--no-daemon',*row['argv']]),row['argv'])
        for args in (['codex'],['codex','--remote=unix://x'],['codex','resume','--no-daemon'],
                     ['codex','--no-daemon','--unknown-mode'],['codex','--no-daemon','app-server','--listen=ws://localhost']):
            self.assertFalse(codex_scope.supported_startup(args),args)

    def test_visible_startup_override_stops_before_key_or_jev(self):
        from mrh.application.runtime import configured_event
        from tests.adapters.test_typesafe import FakeTransport
        descriptor=self.descriptor();binding=self.root/'binding.json';binding.write_text(json.dumps({'codex_scope':descriptor}))
        path=self.root/'state/settings.json';settings.init(path)
        settings.update(path,provider='typesafe',classifier_model='jev-1.13.0',enabled=True,
                        task_export_permitted=True,allowed_workspaces=[str(self.work)],policy=self.policy)
        transport=FakeTransport();keys=[]
        def native(scope):
            if not codex_scope.supported_startup(['codex','--no-daemon','--config=agents.default_subagent_model="protected"']):
                raise codex_scope.ScopeError('scope_host_unverified')
        with patch('mrh.adapters.hosts.codex_scope._native_parent',side_effect=native):
            output=configured_event(self.event,path,transport=transport,credential_resolver=lambda:keys.append(1),scope_binding=binding)
        self.assertIn('systemMessage',output);self.assertNotIn('hookSpecificOutput',output)
        self.assertEqual((keys,transport.calls),([],[]))

    def test_explicit_model_effort_and_special_role_skip_classifier(self):
        for fields,reason in (({'model':'chosen'},'explicit_model'),({'reasoning_effort':'high'},'explicit_effort'),
                              ({'agent_type':'explorer'},'unsupported_role')):
            proposal=Proposal('codex','simulation','s','t','c',{**self.event['tool_input'],**fields},True)
            classifier=ScriptedClassifier([Classification('Top',.9)])
            decision=route(proposal,self.policy,None,classifier)
            self.assertEqual((decision.reason,classifier.calls),(reason,0))

    def test_changed_config_and_default_role_override_invalidate_before_effect(self):
        descriptor=self.descriptor()
        self.config.write_text(self.config.read_text()+'\n[agents]\ndefault_subagent_model="gpt-5.6-luna"\n')
        with self.assertRaisesRegex(codex_scope.ScopeError,'scope_changed'):self.facts(descriptor)
        self.config.write_text('model="gpt-6.1-sol"\n[agents.default]\nconfig_file="default.toml"\n')
        with self.assertRaisesRegex(codex_scope.ScopeError,'scope_unsupported'):self.descriptor()

    def test_standalone_default_role_project_layer_profile_and_foreign_home_refuse(self):
        descriptor=self.descriptor();folder=self.home/'agents';folder.mkdir();file=folder/'named.toml';file.write_text('name="default"\nmodel="protected"\n')
        with self.assertRaises(codex_scope.ScopeError):self.descriptor()
        file.unlink();project=self.work/'.codex';project.mkdir();(project/'config.toml').write_text('model="other"\n')
        with self.assertRaises(codex_scope.ScopeError):self.descriptor()
        (project/'config.toml').unlink();self.config.write_text('profile="special"\n')
        with self.assertRaises(codex_scope.ScopeError):self.descriptor()
        self.config.write_text('model="gpt-6.1-sol"\nmodel_reasoning_effort="low"\n')
        with patch.dict(os.environ,{'CODEX_HOME':str(self.root/'other')}):
            with self.assertRaises(codex_scope.ScopeError):self.facts(descriptor)

    def test_unknown_cost_or_inherit_preserves_only_that_branch(self):
        policy=copy.deepcopy(self.policy);policy['rates']={}
        self.assertEqual(route(self.proposal,policy,self.facts(),ScriptedClassifier([Classification('Light',.9)])).reason,'cost_unknown')
        policy['fixed'].pop('effort')
        self.assertEqual(route(self.proposal,policy,self.facts(),ScriptedClassifier([Classification('Top',.9)])).reason,'missing_effective_effort')
        policy['top_mode']='Main'
        self.assertEqual(route(self.proposal,policy,self.facts(),ScriptedClassifier([Classification('Top',.9)])).action,'return_to_main')

    def test_configuration_changed_during_classifier_and_cached_replay_is_neutral(self):
        assurance=self.facts();first=route(self.proposal,self.policy,assurance,ScriptedClassifier([Classification('Top',.9)]))
        self.config.write_text(self.config.read_text()+'\n[agents]\ndefault_subagent_reasoning_effort="high"\n')
        self.assertEqual(cached_effect_blocker(self.proposal,self.policy,assurance,first),'scope_changed')
        descriptor=self.descriptor();assurance=self.facts(descriptor)
        owner=self
        class Changing(ScriptedClassifier):
            def classify(self,*args):
                result=super().classify(*args);owner.config.write_text('model="different"\n');return result
        decision=route(self.proposal,self.policy,assurance,Changing([Classification('Top',.9)]))
        self.assertEqual(decision.reason,'scope_changed');self.assertEqual(decision.patch,{})



if __name__=='__main__':unittest.main()
