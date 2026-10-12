"""New finite lifecycle/provenance and its actual runtime/auth consumers."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from mrh.adapters.hosts import fresh_cli_scope as fresh, codex_scope as pinned
from mrh.adapters.catalogs.catalog import executable_hash
from mrh.adapters.providers.subscription_auth import source_for_binding
from mrh.application.runtime import configured_event
from mrh.infrastructure import settings
from mrh.routing.core import ScriptedClassifier, route
from mrh.routing.types import Proposal, Classification


class FreshScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='mrh-fresh-check-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.home = self.root/'home'; self.home.mkdir()
        self.work = self.root/'work'; self.work.mkdir()
        self.profile = self.root/'profile'; self.profile.mkdir()
        self.binary = self.root/'codex'; self.binary.write_text('fixture'); self.binary.chmod(0o700)
        self.config = self.home/'config.toml'; self.config.write_text('model="gpt-6-astra"\n')
        self.project = self.work/'.codex'; self.project.mkdir()
        (self.project/'config.toml').write_text('[mcp_servers.test]\ncommand="unexecuted"\n')
        self.auth = self.home/'auth.json'; self.auth.write_text('unread synthetic credential'); self.auth.chmod(0o600)
        self.addCleanup(patch.stopall)
        patch.object(pinned, 'BINARY_SHA256', executable_hash(self.binary)).start()
        self.scope = fresh.prepare(self.binary, self.home, self.work, self.profile/'sessions', Path(sys.executable).resolve())
        self.binding = self.root/'binding.json'; self.binding.write_text(json.dumps({'codex_scope': self.scope}))
        # Fixture clock supplies an independently verified process identity;
        # none of these synthetic calls are native adoption evidence.
        self.identity = {'pid': 123, 'birth_ns': time.time_ns()+10**9, 'binary': str(self.binary),
                         'startup_cwd': str(self.work), 'codex_home': str(self.home)}
        self.real_native_identity=fresh.native_identity
        patch.object(fresh, 'native_identity', side_effect=lambda *args: copy.deepcopy(self.identity)).start()
        self.start = {'hook_event_name':'SessionStart', 'source':'startup', 'session_id':'fresh-s',
                      'cwd':str(self.work), 'model':'gpt-6.1-sol'}
        self.event = {'hook_event_name':'PreToolUse', 'tool_name':'spawn_agent', 'session_id':'fresh-s',
                      'turn_id':'t', 'tool_use_id':'c', 'cwd':str(self.work), 'model':'gpt-6.1-sol',
                      'tool_input':{'message':'bounded literal task', 'task_name':'probe'}}

    def start_session(self): return fresh.session_start(self.scope,self.start,self.binding)
    def facts(self): return pinned.check(self.scope,self.event,binding=self.binding,synthetic=True)

    def test_start_idempotent_current_model_and_static_status(self):
        self.assertIn('unverified', fresh.check(self.scope)['active_session'])
        self.start_session()
        root,path = fresh._record_path(self.scope,'fresh-s'); before=path.stat().st_ctime_ns
        self.start_session(); self.assertEqual(path.stat().st_ctime_ns,before)
        facts=self.facts()
        self.assertEqual(facts.assurance,'fresh-root-cli-configuration')
        self.assertEqual(facts.original_model.value,'gpt-6.1-sol')
        self.assertFalse(facts.original_effort.known)
        self.assertEqual(facts.validation_reason(Proposal('codex','simulation','fresh-s','t','c',self.event['tool_input'],True)),None)

    def test_pre_cannot_mint_and_conflicting_lifecycle_is_sticky(self):
        with self.assertRaisesRegex(pinned.ScopeError,'scope_fresh_start_missing'): self.facts()
        self.start_session()
        for source in ('resume','fork','compact','clear'):
            with self.subTest(source=source):
                with self.assertRaisesRegex(pinned.ScopeError,'scope_fresh_lifecycle'):
                    fresh.session_start(self.scope,{**self.start,'source':source},self.binding)
                with self.assertRaises(pinned.ScopeError): self.start_session()
                with self.assertRaises(pinned.ScopeError): self.facts()

    def test_changed_aba_missing_and_role_sources(self):
        self.start_session()
        original=self.config.read_text(); self.config.write_text(original+'personality="friendly"\n'); self.config.write_text(original)
        with self.assertRaises(pinned.ScopeError): self.facts()
        # Equal bytes in a recreated inode are not the launch source.
        self.config.unlink(); self.config.write_text(original)
        with self.assertRaises(pinned.ScopeError): self.start_session()
        # Missing-path anchors and declared default roles remain guarded.
        folder=self.home/'agents'; folder.mkdir(); role=folder/'ordinary.toml'; role.write_text('name="default"\n')
        with self.assertRaisesRegex(pinned.ScopeError,'scope_unsupported'): fresh.check(self.scope)
        role.unlink(); folder.rmdir()
        with self.assertRaises(pinned.ScopeError): self.facts()

    def test_birth_age_and_selected_overrides(self):
        self.identity['birth_ns']=1
        with self.assertRaisesRegex(pinned.ScopeError,'scope_fresh_sources_not_predated'): self.start_session()
        for body in ('profile="custom"\n','[agents.default]\nmodel="protected"\n',
                     '[agents]\ndefault_subagent_reasoning_effort="high"\n',
                     'model_provider="custom"\n','model_catalog_json="catalog.json"\n',
                     '[model_providers.openai]\nbase_url="https://invalid.example"\n'):
            with self.subTest(body=body):
                self.config.write_text(body)
                with self.assertRaisesRegex(pinned.ScopeError,'scope_unsupported'): fresh.check(self.scope)

    def test_review_role_recursion_normalization_and_external_reference(self):
        folder=self.home/'agents'/'nested';folder.mkdir(parents=True)
        file=folder/'role.toml';file.write_text('name=" default "\nmodel="protected"\n')
        with self.assertRaisesRegex(pinned.ScopeError,'scope_unsupported'):fresh.check(self.scope)
        file.write_text('name="named"\n');self.start_session()
        file.write_text('name="named"\nmodel="changed"\n')
        with self.assertRaises(pinned.ScopeError):self.facts()
        file.unlink();folder.rmdir();folder.parent.rmdir()
        external=self.root/'external.toml';external.write_text('name="default"\n')
        self.config.write_text('[agents.named]\nconfig_file='+json.dumps(str(external))+'\n')
        with self.assertRaisesRegex(pinned.ScopeError,'scope_unsupported'):fresh.check(self.scope)

    def test_review_ancestor_replacement_before_first_start(self):
        self.identity['birth_ns']=time.time_ns()
        moved=self.root/'old-project';self.project.rename(moved)
        self.project.mkdir();(self.project/'config.toml').write_text('[mcp_servers.test]\ncommand="unexecuted"\n')
        with self.assertRaisesRegex(pinned.ScopeError,'scope_fresh_sources_not_predated'):self.start_session()

    def test_startup_parser_excludes_app_exec_override_and_unknown(self):
        for args in (['app-server','--listen','stdio://'],['exec'],['resume'],['fork'],
                     ['--no-daemon','-m','chosen'],['--no-daemon','-c','agents.default.model="x"'],
                     ['--no-daemon','-p','custom'],['--no-daemon','--unknown'],['--no-daemon','prompt']):
            with self.subTest(args=args):
                with self.assertRaises(pinned.ScopeError): fresh._startup(['codex',*args])
        self.assertEqual(fresh._startup(['codex','--no-daemon','--no-alt-screen','-C',str(self.work)]),str(self.work))
        with self.assertRaises(ValueError): fresh._startup(['codex','--no-daemon','-C','relative'])

    def test_auth_binding_harmless_project_and_no_secret_read(self):
        from mrh.infrastructure import owned
        real=owned.read_regular
        def read(path,*args):
            self.assertNotEqual(Path(path),self.auth)
            return real(path,*args)
        with patch.object(owned,'read_regular',side_effect=read):
            source=source_for_binding(self.binding); source.verify()
        self.assertEqual(source.path,self.auth)
        self.config.write_text('cli_auth_credentials_store="auto"\n')
        with self.assertRaisesRegex(Exception,'auth_source_unconfirmed'): source_for_binding(self.binding)

    def test_native_ancestry_and_foreign_process_identity(self):
        launcher=str(self.binding.parent/'launcher.py')
        rows={321:{'image':self.scope['python'],'argv':[self.scope['python'],launcher],'parent':789},
              789:{'image':str(self.binary),'argv':[str(self.binary),'--no-daemon','-C',str(self.work)],
                   'parent':1,'birth_ns':1,'home_env':{'CODEX_HOME':str(self.home)}}}
        with patch.object(fresh.os,'getppid',return_value=321), patch.object(fresh,'_process',side_effect=lambda pid:rows[pid]), \
             patch.object(fresh.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout='p789\nn'+str(self.work)+'\n')):
            observed=self.real_native_identity(self.scope,self.binding)
            self.assertEqual(observed['pid'],789)
            rows[321]['image']='/untrusted/codex-exec-server'
            with self.assertRaises(pinned.ScopeError):self.real_native_identity(self.scope,self.binding)
            rows[321]['image']=self.scope['python'];rows[789]['home_env']['CODEX_HOME']=str(self.root)
            with self.assertRaises(pinned.ScopeError):self.real_native_identity(self.scope,self.binding)
        self.start_session();self.identity['pid']+=1
        with self.assertRaises(pinned.ScopeError):self.facts()

    def test_runtime_startup_protected_allowlist_and_decision_boundary(self):
        state=self.profile/'state/settings.json'; settings.init(state)
        value=settings.read(state)
        value.update(enabled=True,task_export_permitted=True,provider='typesafe',classifier_model='jev-1.13.0',allowed_workspaces=[str(self.work)])
        state.write_text(json.dumps(value))
        missing=configured_event(self.event,state,scope_binding=self.binding)
        self.assertIn('verified native startup is missing',missing.get('systemMessage',''))
        import sqlite3
        with sqlite3.connect((state.parent/'events.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
            self.assertEqual(db.execute('select count(*) from attempts').fetchone()[0],0)
            self.assertEqual(db.execute("select json_extract(decision,'$.reason') from proposals").fetchone()[0],'scope_fresh_start_missing')
        before=(state.parent/'events.sqlite3').read_bytes()
        self.assertEqual(configured_event(self.start,state,scope_binding=self.binding),{})
        self.assertEqual((state.parent/'events.sqlite3').read_bytes(),before)
        from tests.adapters.test_typesafe import FakeTransport
        transport=FakeTransport()
        for index,fields in enumerate(({'model':'chosen'},{'reasoning_effort':'high'},{'agent_type':'explorer'})):
            result=configured_event({**self.event,'tool_use_id':'protected-'+str(index),'tool_input':{**self.event['tool_input'],**fields}},
                                    state,scope_binding=self.binding,transport=transport)
            self.assertNotIn('hookSpecificOutput',result)
        self.assertEqual(transport.calls,[])
        value['allowed_workspaces']=[];state.write_text(json.dumps(value))
        with patch('mrh.application.runtime.classifier_from_config',side_effect=AssertionError('no admission')):
            self.assertEqual(configured_event(self.event,state,scope_binding=self.binding),{})
        facts=self.facts(); self.config.write_text(self.config.read_text()+'personality="friendly"\n')
        proposal=Proposal('codex','simulation','fresh-s','t','c',self.event['tool_input'],True)
        self.assertEqual(facts.validation_reason(proposal),'scope_fresh_sources_changed')

    @unittest.skipUnless(sys.platform=='darwin','Darwin native process API')
    def test_kernel_process_metadata_direct_consumer(self):
        row=fresh._process(os.getpid())
        self.assertEqual(row['pid'],os.getpid())
        self.assertEqual(row['parent'],os.getppid())
        self.assertGreater(row['birth_ns'],0)
        self.assertLessEqual(row['birth_ns'],time.time_ns())
        self.assertTrue(Path(row['image']).is_absolute())
        self.assertIn('HOME',row['home_env'])
