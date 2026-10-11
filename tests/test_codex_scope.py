"""Inspected config assurance and direct routing/lifecycle consumers."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from mrh import codex_scope,plugin,settings
from mrh.catalog import executable_hash
from mrh.core import ScriptedClassifier,route,cached_effect_blocker
from mrh.facts import HostSnapshot
from mrh.types import Proposal,Classification


class ScopeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='mrh-scope-check-');self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve();self.home=self.root/'home';self.home.mkdir();self.work=self.root/'work';self.work.mkdir()
        self.exe=self.root/'codex';self.exe.write_text('#!/bin/sh\nexit 0\n');self.exe.chmod(0o755)
        self.addCleanup(patch.stopall)
        patch('mrh.codex_scope.BINARY_SHA256',executable_hash(self.exe)).start()
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
        with patch('mrh.codex_scope.subprocess.run',side_effect=self.version):
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

    def test_scope_preparation_update_preserves_disabled_export_and_user_models(self):
        descriptor=self.descriptor();root=self.root/'bundle';path=self.root/'state/settings.json'
        with patch('mrh.codex_scope.prepare',return_value=descriptor):
            first=plugin.prepare(root,path,scope_workspace=self.work,codex_binary=self.exe)
        settings.update(path,policy=self.policy,task_export_permitted=True,allowed_workspaces=[str(self.work)])
        before=path.read_bytes();again=plugin.prepare(root,path)
        self.assertEqual(again['artifact']['codex_scope'],first['artifact']['codex_scope'])
        self.assertEqual(path.read_bytes(),before);self.assertFalse(settings.read(path)['enabled'])
        self.assertEqual(again['configuration_scope']['assurance'],'inspected-configuration')
        self.assertFalse(again['live_routing_ready'])


if __name__=='__main__':unittest.main()
