import copy
import io
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from mrh.presentation import cli; from mrh.infrastructure import settings
from mrh.routing.attempts import GuardedAttempts
from mrh.application.classifier import classifier_from_config
from mrh.adapters.providers.codex_subscription import (CodexSubscriptionClassifier, MODEL, SENTINEL,
    invocation, parse_stream, run_process, sanitized_environment, chatgpt_status)
from mrh.routing.core import ClassifierFailure
from mrh.application.runtime import configured_event
from mrh.infrastructure.settings_schema import default_settings, validate_settings
from mrh.application.simulation import demo_capabilities
from mrh.infrastructure.store import Store
from mrh.routing.types import Proposal, Decision
from mrh.adapters.providers.typesafe import TypesafeClassifier
from mrh.presentation.terminal import render_configuration, render_details


def stream(answer='{"tier":"Light","confidence":0.9}',usage=None):
    return ('\n'.join(json.dumps(e) for e in ({'type':'thread.started'}, {'type':'turn.started'},
       {'type':'item.completed','item':{'type':'agent_message','text':answer}},
       {'type':'turn.completed','usage':usage or {'input_tokens':10,'output_tokens':3}}))+'\n').encode()


class Runner:
    synthetic=True
    def __init__(self,answer=None):self.calls=0;self.answer=answer or stream()
    def request(self,data,recorder,enter):enter();self.calls+=1;return self.answer


class Host:
    synthetic=True
    def resolve(self,event):
        value=demo_capabilities();value.update(main_model='main',main_effort='low',original_model='main',original_effort='low')
        value['models']={'main':{'available':True,'efforts':['low']},'cheap':{'available':True,'efforts':['low']}}
        return value


class SubscriptionTests(unittest.TestCase):
    def test_defaults_factory_and_legacy_document(self):
        value=default_settings();self.assertEqual((value['provider'],value['classifier_model']),('codex_subscription',MODEL))
        self.assertFalse(value['enabled']);self.assertFalse(value['task_export_permitted']);self.assertEqual(value['policy']['timeout_seconds'],20)
        old=copy.deepcopy(value);old.update(provider='typesafe',classifier_model='jev-1.13.0',revision=17)
        old['policy']['timeout_seconds']=1;self.assertEqual(validate_settings(old),old)
        cfg=lambda v:{'provider':v['provider'],'model':v['classifier_model'],'schema_version':1,'enabled':True,'task_export_permitted':True}
        self.assertIsInstance(classifier_from_config(cfg(old)),TypesafeClassifier)
        self.assertIsInstance(classifier_from_config(cfg(value)),CodexSubscriptionClassifier)
        with self.assertRaises(ClassifierFailure):classifier_from_config(cfg(value),credential_resolver=lambda:'not-used')


    def test_strict_final_answer_and_official_usage(self):
        c,u=parse_stream(stream());self.assertEqual((c.tier,c.confidence,c.reason_code),('Light',.9,'classified_subscription'))
        self.assertEqual(u,{'input_tokens':10,'output_tokens':3})
        for text in ('{"tier":"Light","confidence":true}', '{"tier":"Light","confidence":NaN}',
                     '{"tier":"Light","confidence":1.1}', '{"tier":"Light","confidence":0.9,"extra":1}',
                     '{"tier":"Light","confidence":0.9,"confidence":0.8}', '{"tier":"Wrong","confidence":0.9}',
                     '```json\n{"tier":"Light","confidence":0.9}\n```'):
            with self.subTest(text=text),self.assertRaises(ClassifierFailure):parse_stream(stream(text))
        for bad in (b'{}\n',stream()+stream(),stream()[:-15],b'x'*262145):
            with self.assertRaises(ClassifierFailure):parse_stream(bad)
        self.assertEqual(parse_stream(stream(usage={'input_tokens':True,'output_tokens':-1}))[1],{})

    def test_tool_events_rejected(self):
        for kind in ('command_execution','mcp_tool_call','web_search','file_change','plan','collab_tool_call'):
            data=b'{"type":"thread.started"}\n{"type":"turn.started"}\n'+json.dumps({'type':'item.started','item':{'type':kind}}).encode()+b'\n'
            with self.assertRaises(ClassifierFailure) as caught:parse_stream(data)
            self.assertEqual(caught.exception.reason,'codex_subscription_tool_activity')

    def test_auth_source_fault_before_any_process_or_attempt(self):
        with tempfile.TemporaryDirectory() as root:
            home=Path(root);(home/'AGENTS.md').write_text('owned canary')
            events=[];rec=GuardedAttempts(2,lambda *a,**k:events.append(a))
            with patch.dict(os.environ,{'CODEX_HOME':root}),patch('mrh.adapters.catalogs.catalog.discover',return_value=[{'tool':'codex','executable':'/official'}]),\
                 patch('mrh.adapters.catalogs.catalog.executable_hash',return_value='4d210f7c5a18fd0386434df23b5bdbb8c0e7257d3e8a2b30b0769c8bbe99a878'),\
                 patch('subprocess.Popen',side_effect=AssertionError('started')):
                with self.assertRaises(ClassifierFailure) as caught:CodexSubscriptionClassifier(enabled=True,task_export_permitted=True).classify('literal',None,rec)
            self.assertEqual(caught.exception.reason,'codex_subscription_auth_source_unconfirmed');self.assertEqual(events,[]);rec.cancel()

    def test_sanitized_environment_and_home_instruction_metadata_guard(self):
        with tempfile.TemporaryDirectory() as root:
            home=Path(root)/'home';home.mkdir()
            with patch.dict(os.environ,{'CODEX_HOME':str(home),'OPENAI_API_KEY':'private-canary','CODEX_API_KEY':'private-canary',
                                       'TYPESAFE_API_KEY':'private-canary','CODEX_THREAD_ID':'private'},clear=False):
                env=sanitized_environment(Path(root))
                self.assertEqual(env['CODEX_HOME'],str(home));self.assertEqual(env[SENTINEL],'1')
                self.assertNotIn('private-canary',str(env));self.assertNotIn('CODEX_THREAD_ID',env)
                for name in ('AGENTS.md','AGENTS.override.md'):
                    path=home/name;path.write_text('PRIVATE_DO_NOT_READ')
                    with patch('pathlib.Path.read_text',side_effect=AssertionError('read')):
                        with self.assertRaises(ClassifierFailure) as caught:sanitized_environment(Path(root))
                    self.assertEqual(caught.exception.reason,'codex_subscription_home_instructions');path.unlink()

    def test_auth_api_unknown_and_failure_no_model_process_or_attempt(self):
        for status in (b'Logged in using an API key',b'Unknown auth',b'Not logged in'):
            with tempfile.TemporaryDirectory() as root:
                rec=GuardedAttempts(2);emit=[];rec.emit=lambda *a,**k:emit.append((a,k));calls=[]
                from mrh.adapters.providers.subscription_auth import FileAuthSource, source_lock
                home=Path(root).resolve();(home/'work').mkdir();(home/'auth.json').write_text('synthetic-auth');(home/'auth.json').chmod(0o600)
                source=FileAuthSource.resolve(home,home/'work')
                def run(argv,*args,**kwargs):
                    calls.append(argv)
                    return (0,b'codex-cli 0.159.3',b'') if '--version' in argv else (0,b'',status)
                with patch.dict(os.environ,{'CODEX_HOME':root}),patch('mrh.adapters.catalogs.catalog.discover',return_value=[{'tool':'codex','executable':'/official'}]),\
                     patch('mrh.adapters.catalogs.catalog.executable_hash',return_value='4d210f7c5a18fd0386434df23b5bdbb8c0e7257d3e8a2b30b0769c8bbe99a878'),\
                     patch('mrh.adapters.providers.codex_subscription.run_process',side_effect=run),\
                     patch('mrh.adapters.providers.subscription_auth.source_for_binding',return_value=source),\
                     patch('mrh.adapters.providers.subscription_auth.source_lock',side_effect=lambda s,r,_root=None:source_lock(s,r,home/'locks')):
                    with self.assertRaises(ClassifierFailure) as caught:CodexSubscriptionClassifier(enabled=True,task_export_permitted=True).classify('literal',None,rec)
                self.assertEqual(caught.exception.reason,'codex_subscription_chatgpt_login_required')
                self.assertEqual(len(calls),2);self.assertEqual(emit,[]);rec.cancel()

    def test_public_auth_status_shape_accepts_only_chatgpt(self):
        warning=b'WARNING: proceeding, even though we could not create PATH aliases: owned error\n'
        self.assertTrue(chatgpt_status(0,b'',warning+b'Logged in using ChatGPT\n'))
        for code,out in ((1,b'Logged in using ChatGPT'),(0,b'Logged in using an API key'),
                         (0,b'Logged in using ChatGPT\nUnknown auth'),(0,b'Logged in using ChatGPT\nLogged in using ChatGPT')):
            self.assertFalse(chatgpt_status(code,b'',out))

    def test_runtime_pre_spawn_gates_recursion_disabled_export_explicit_role(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root).resolve();work=root/'work';work.mkdir();path=root/'state/settings.json';settings.init(path)
            event={'hook_event_name':'PreToolUse','tool_name':'spawn_agent','session_id':'s','turn_id':'t','tool_use_id':'c',
                   'cwd':str(work),'tool_input':{'message':'Literal task'}}
            runner=Runner()
            with patch.dict(os.environ,{SENTINEL:'1'}),patch('mrh.application.runtime.read',side_effect=AssertionError('settings read')):
                self.assertEqual(configured_event(event,path),{})
            self.assertEqual(configured_event(event,path,subscription_runner=runner),{});self.assertFalse((path.parent/'events.sqlite3').exists())
            settings.update(path,enabled=True,allowed_workspaces=[str(work)])
            self.assertEqual(configured_event(event,path,subscription_runner=runner),{});self.assertFalse((path.parent/'events.sqlite3').exists())
            settings.update(path,task_export_permitted=True)
            for n,changes in enumerate(({'model':'explicit'},{'reasoning_effort':'high'},{'agent_type':'explorer'})):
                e=copy.deepcopy(event);e['tool_use_id']+=str(n);e['tool_input'].update(changes)
                self.assertEqual(configured_event(e,path,subscription_runner=runner,host_resolver=Host()),{})
            self.assertEqual(runner.calls,0)

    def test_low_confidence_and_null_hook_use_same_core_and_statistics(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root).resolve();work=root/'work';work.mkdir();path=root/'state/settings.json';settings.init(path)
            settings.update(path,enabled=True,task_export_permitted=True,allowed_workspaces=[str(work)],policy={
                'top_mode':'Main','timeout_seconds':1,'tiers':{'Light':{'model':'cheap','effort':'low'}},
                'rates':{'cheap':{'currency':'test','unit':'token','service':'test','source_ref':'test','components':{'input':1}},
                         'main':{'currency':'test','unit':'token','service':'test','source_ref':'test','components':{'input':2}}}})
            event={'hook_event_name':'PreToolUse','tool_name':'spawn_agent','session_id':'s','turn_id':'t','tool_use_id':'low',
                'cwd':str(work),'tool_input':{'message':'literal','model':None,'reasoning_effort':None}}
            runner=Runner(stream('{"tier":"Light","confidence":0.4}'))
            out=configured_event(event,path,subscription_runner=runner,host_resolver=Host());self.assertEqual(out,{})
            stats=Store(path.parent/'events.sqlite3').stats(True)
            self.assertEqual(stats['outcomes'],{'low_confidence':1});self.assertEqual(stats['jev']['source'],'unavailable')
            self.assertEqual(stats['codex_subscription']['requested_models'],{MODEL:1});self.assertEqual(stats['jev_attempts'],0)
            event['tool_use_id']='null';runner.answer=stream()
            out=configured_event(event,path,subscription_runner=runner,host_resolver=Host())
            self.assertEqual(out['hookSpecificOutput']['updatedInput']['model'],'cheap')
            self.assertEqual(out['hookSpecificOutput']['updatedInput']['reasoning_effort'],'low')

    def test_live_subscription_stats_not_jev_prices_or_confirmed_identity(self):
        with tempfile.TemporaryDirectory() as root:
            store=Store(Path(root)/'events.sqlite3');proposal=Proposal('codex','test','s','t','c',{'message':'literal'},False)
            store.claim(proposal);store.attempt(proposal.identity,'0','codex_subscription','requested',requested_model=MODEL)
            store.attempt(proposal.identity,'0','codex_subscription','started');store.attempt(proposal.identity,'0','codex_subscription','returned',input_tokens=10,output_tokens=3)
            stats=store.stats();self.assertEqual(stats['jev_attempts'],0);self.assertEqual(stats['jev']['source'],'unavailable')
            self.assertEqual(stats['codex_subscription_attempts'],1);self.assertEqual(stats['codex_subscription']['input_tokens'],10)
            self.assertEqual(stats['codex_subscription']['response_models'],{});self.assertIsNone(stats['codex_subscription']['estimated_cost'])
            self.assertIn('model self-report',render_details(stats,width=56))
            self.assertIn('Codex subscription',render_configuration(default_settings(),width=56))

    def test_process_timeout_and_cancel_kill_own_group_before_return(self):
        for cancel in (False,True):
            with tempfile.TemporaryDirectory() as root:
                root=Path(root);pidfile=root/'pid';rec=GuardedAttempts(.5 if not cancel else 5)
                script="import os,time;open('pid','w').write(str(os.getpid()));time.sleep(20)"
                errors=[]
                def run():
                    try:run_process([sys.executable,'-I','-B','-c',script],b'',root,{'PATH':os.defpath},rec)
                    except Exception as exc:errors.append(type(exc))
                thread=threading.Thread(target=run);thread.start()
                deadline=time.monotonic()+2
                while not pidfile.exists() and time.monotonic()<deadline:time.sleep(.01)
                self.assertTrue(pidfile.exists());pid=int(pidfile.read_text())
                if cancel:rec.cancel()
                thread.join(2);self.assertFalse(thread.is_alive());rec.cancel()
                with self.assertRaises(ProcessLookupError):os.kill(pid,0)
                self.assertTrue(errors)

    def test_process_output_bound_and_cancel_before_start(self):
        with tempfile.TemporaryDirectory() as root:
            rec=GuardedAttempts(2)
            with self.assertRaises(ClassifierFailure):run_process([sys.executable,'-I','-B','-c',"print('x'*300000)"],b'',root,{'PATH':os.defpath},rec)
            rec.cancel();rec=GuardedAttempts(2);rec.cancel()
            with patch('subprocess.Popen',side_effect=AssertionError('spawned')):
                with self.assertRaises(TimeoutError):run_process(['never'],b'',root,{},rec)

    def test_cancellation_removes_spawned_descendant_not_only_cli_parent(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root);rec=GuardedAttempts(5);errors=[]
            script="import os,subprocess,sys,time;child=subprocess.Popen([sys.executable,'-I','-B','-c','import time;time.sleep(20)']);open('pids','w').write(str(os.getpid())+' '+str(child.pid));time.sleep(20)"
            def run():
                try:run_process([sys.executable,'-I','-B','-c',script],b'',root,{'PATH':os.defpath},rec)
                except Exception as exc:errors.append(type(exc))
            thread=threading.Thread(target=run);thread.start();deadline=time.monotonic()+2
            while not (root/'pids').exists() and time.monotonic()<deadline:time.sleep(.01)
            pids=list(map(int,(root/'pids').read_text().split()));self.assertEqual(len(pids),2)
            rec.cancel();thread.join(2);self.assertFalse(thread.is_alive());self.assertTrue(errors)
            for pid in pids:
                deadline=time.monotonic()+1
                while time.monotonic()<deadline:
                    try:os.kill(pid,0)
                    except ProcessLookupError:break
                    time.sleep(.01)
                else:self.fail('owned descendant remains')

    def test_invocation_supported_controls_without_bypasses(self):
        argv=invocation('/official','/owned/work','/owned/schema')
        self.assertNotIn('--ignore-rules',argv);self.assertFalse(any('dangerously' in a for a in argv))
        self.assertIn('--ignore-user-config',argv);self.assertIn('--ephemeral',argv);self.assertIn('read-only',argv)
        self.assertEqual(argv[-1],'-');self.assertIn('forced_login_method="chatgpt"',argv)


if __name__=='__main__':unittest.main()
