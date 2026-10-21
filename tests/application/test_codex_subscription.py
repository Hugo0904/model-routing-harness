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
from mrh.adapters.providers.codex_subscription import (CodexSubscriptionClassifier, MODEL, SENTINEL,
    invocation, parse_stream, run_process, sanitized_environment, chatgpt_status)
from mrh.routing.core import ClassifierFailure
from mrh.infrastructure.settings_schema import default_settings, validate_settings
from mrh.adapters.providers.typesafe import TypesafeClassifier


def stream(answer='{"tier":"Light","confidence":0.9}',usage=None):
    return ('\n'.join(json.dumps(e) for e in ({'type':'thread.started'}, {'type':'turn.started'},
       {'type':'item.completed','item':{'type':'agent_message','text':answer}},
       {'type':'turn.completed','usage':usage or {'input_tokens':10,'output_tokens':3}}))+'\n').encode()


class Runner:
    synthetic=True
    def __init__(self,answer=None):self.calls=0;self.answer=answer or stream()
    def request(self,data,recorder,enter):enter();self.calls+=1;return self.answer




class SubscriptionTests(unittest.TestCase):


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
            home=Path(root).resolve();(home/'AGENTS.md').write_text('owned canary')
            events=[];rec=GuardedAttempts(2,lambda *a,**k:events.append(a))
            with patch.dict(os.environ,{'CODEX_HOME':str(home)}),patch('mrh.adapters.catalogs.catalog.discover',return_value=[{'tool':'codex','executable':'/official'}]),\
                 patch('mrh.adapters.catalogs.catalog.executable_hash',return_value='4d210f7c5a18fd0386434df23b5bdbb8c0e7257d3e8a2b30b0769c8bbe99a878'),\
                 patch('subprocess.Popen',side_effect=AssertionError('started')):
                with self.assertRaises(ClassifierFailure) as caught:CodexSubscriptionClassifier(enabled=True,task_export_permitted=True).classify('literal',None,rec)
            self.assertEqual(caught.exception.reason,'codex_subscription_auth_source_invalid');self.assertEqual(events,[]);rec.cancel()

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
                     patch('mrh.adapters.providers.subscription_auth.source_for_home',return_value=source),\
                     patch('mrh.adapters.providers.subscription_auth.source_lock',side_effect=lambda s,r,_root=None:source_lock(s,r,home/'locks')):
                    with self.assertRaises(ClassifierFailure) as caught:CodexSubscriptionClassifier(enabled=True,task_export_permitted=True).classify('literal',None,rec)
                self.assertEqual(caught.exception.reason,'codex_subscription_chatgpt_login_required')
                self.assertEqual(len(calls),1);self.assertEqual(emit,[]);rec.cancel()

    def test_public_auth_status_shape_accepts_only_chatgpt(self):
        warning=b'WARNING: proceeding, even though we could not create PATH aliases: owned error\n'
        self.assertTrue(chatgpt_status(0,b'',warning+b'Logged in using ChatGPT\n'))
        for code,out in ((1,b'Logged in using ChatGPT'),(0,b'Logged in using an API key'),
                         (0,b'Logged in using ChatGPT\nUnknown auth'),(0,b'Logged in using ChatGPT\nLogged in using ChatGPT')):
            self.assertFalse(chatgpt_status(code,b'',out))




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
