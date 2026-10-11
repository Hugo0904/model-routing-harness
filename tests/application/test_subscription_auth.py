"""Synthetic credential fixtures only; never use the operator's real auth."""
import os
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from mrh.adapters.providers.subscription_auth import FileAuthSource, execution_home, source_lock, source_for_binding
from mrh.adapters.providers.codex_subscription import run_process, sanitized_environment
from mrh.infrastructure import owned
from mrh.routing.attempts import GuardedAttempts
from mrh.routing.core import ClassifierFailure


class SubscriptionAuthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.home = self.root/'source';self.home.mkdir()
        self.work = self.root/'work';self.work.mkdir()
        self.auth = self.home/'auth.json';self.auth.write_text('synthetic-old');self.auth.chmod(0o600)
        self.lock_root = self.root/'locks'

    def source(self):
        return FileAuthSource.resolve(self.home,self.work)

    def test_metadata_rejections_and_unconfirmed_modes_never_open_auth(self):
        original = owned.read_regular
        def read(path,*a,**k):
            self.assertNotEqual(Path(path),self.auth,'MRH opened credentials')
            return original(path,*a,**k)
        with patch('mrh.infrastructure.owned.read_regular',side_effect=read):
            for mode in ('keyring','auto','ephemeral'):
                (self.home/'config.toml').write_text('cli_auth_credentials_store="'+mode+'"')
                with self.assertRaises(ClassifierFailure) as e:self.source()
                self.assertEqual(e.exception.reason,'codex_subscription_auth_source_unconfirmed')
            (self.home/'config.toml').unlink()
            self.source()
            self.auth.chmod(0o644)
            with self.assertRaises(ClassifierFailure):self.source()
            self.auth.chmod(0o600)
            with patch('mrh.adapters.providers.subscription_auth.os.getuid',return_value=-1):
                with self.assertRaises(ClassifierFailure):self.source()
            self.auth.unlink();self.auth.mkdir()
            with self.assertRaises(ClassifierFailure):self.source()
            self.auth.rmdir();target=self.home/'other';target.write_text('synthetic');target.chmod(0o600)
            self.auth.symlink_to(target)
            with self.assertRaises(ClassifierFailure):self.source()
            self.auth.unlink()
            with self.assertRaises(ClassifierFailure):self.source()

    def test_source_canary_isolation_cli_style_refresh_and_target_preserving_teardown(self):
        (self.home/'AGENTS.md').write_text('DO_NOT_LOAD_CANARY')
        recorder=GuardedAttempts(3)
        source=self.source();read=owned.read_regular
        with patch('mrh.infrastructure.owned.read_regular',side_effect=lambda p,*a,**k:read(p,*a,**k) if Path(p)!=self.auth else self.fail('secret read')):
            with execution_home(source,recorder,self.lock_root) as execution:
                scratch=execution.root;env=sanitized_environment(scratch)
                self.assertNotEqual(env['CODEX_HOME'],str(self.home))
                self.assertFalse((execution.home/'AGENTS.md').exists())
                self.assertEqual(list(execution.home.iterdir()),[execution.home/'auth.json'])
                script="import os;from pathlib import Path;p=Path(os.environ['CODEX_HOME'])/'auth.json';fd=os.open(p,os.O_WRONLY|os.O_TRUNC|os.O_CREAT,0o600);os.write(fd,b'synthetic-refreshed');os.close(fd)"
                self.assertEqual(run_process([sys.executable,'-I','-B','-c',script],b'',execution.work,env,execution)[0],0)
                execution.verify_reference()
            self.assertFalse(scratch.exists())
        self.assertEqual(self.auth.read_text(),'synthetic-refreshed')
        self.assertEqual((self.home/'AGENTS.md').read_text(),'DO_NOT_LOAD_CANARY')
        recorder.cancel()

    def test_binding_configuration_and_file_mode_must_still_be_current(self):
        from mrh.adapters.hosts import codex_scope as scope
        descriptor={'contract':scope.CONTRACT,'binary':'/synthetic-official','binary_sha256':scope.BINARY_SHA256,
                    'codex_home':str(self.home),'workspace':str(self.work),'models':scope.DEFAULT_MODELS,
                    'configuration_fingerprint':scope._hash(scope._configuration(self.home,self.work))}
        binding=self.root/'binding.json';binding.write_text(json.dumps({'codex_scope':descriptor}))
        with patch('mrh.adapters.hosts.codex_scope.executable_hash',return_value=scope.BINARY_SHA256):
            self.assertEqual(source_for_binding(binding).path,self.auth)
            (self.home/'config.toml').write_text('cli_auth_credentials_store="keyring"')
            with self.assertRaises(ClassifierFailure) as e:source_for_binding(binding)
            self.assertEqual(e.exception.reason,'codex_subscription_auth_source_unconfirmed')
            (self.home/'config.toml').write_text('model="changed"')
            with self.assertRaises(ClassifierFailure) as e:source_for_binding(binding)
            self.assertEqual(e.exception.reason,'codex_subscription_auth_source_unconfirmed')

    def test_reference_tamper_and_cancel_remove_scratch_after_owned_process(self):
        recorder=GuardedAttempts(4);source=self.source()
        with execution_home(source,recorder,self.lock_root) as execution:
            reference=execution.home/'auth.json';reference.unlink();reference.symlink_to(self.home/'wrong')
            with self.assertRaises(ClassifierFailure):execution.verify_reference()
            reference.unlink();reference.symlink_to(self.auth)
            scratch=execution.root;pidfile=execution.work/'pid';errors=[]
            def run():
                try:run_process([sys.executable,'-I','-B','-c',"import os,time;open('pid','w').write(str(os.getpid()));time.sleep(20)"],b'',execution.work,sanitized_environment(scratch),execution)
                except Exception as e:errors.append(type(e))
            thread=threading.Thread(target=run);thread.start()
            end=time.monotonic()+2
            while not pidfile.exists() and time.monotonic()<end:time.sleep(.01)
            self.assertTrue(pidfile.exists());pid=int(pidfile.read_text())
            recorder.cancel()
            self.assertFalse(scratch.exists())
            with self.assertRaises(ProcessLookupError):os.kill(pid,0)
            thread.join(2);self.assertFalse(thread.is_alive());self.assertTrue(errors)
        self.assertTrue(self.auth.is_file())

    def test_replaced_config_fifo_is_rejected_before_process_and_cancel_cleans(self):
        recorder=GuardedAttempts(2)
        with execution_home(self.source(),recorder,self.lock_root) as execution:
            scratch=execution.root
            os.mkfifo(self.home/'config.toml',0o600)
            with patch('subprocess.Popen',side_effect=AssertionError('process started')):
                with self.assertRaises(ClassifierFailure) as e:
                    run_process([sys.executable,'--version'],b'',execution.work,sanitized_environment(scratch),execution)
            self.assertEqual(e.exception.reason,'codex_subscription_auth_source_invalid')
            recorder.cancel()
            self.assertFalse(scratch.exists())
        self.assertTrue(self.auth.is_file())

    def test_cross_process_lock_deadline_and_cancellation_before_reference(self):
        source=self.source();recorder=GuardedAttempts(5)
        # Initialize once before concurrent contenders; the actual flock crosses processes.
        with source_lock(source,recorder,self.lock_root):pass
        code="from pathlib import Path;import sys;from mrh.adapters.providers.subscription_auth import FileAuthSource,source_lock;from mrh.routing.attempts import GuardedAttempts;s=FileAuthSource.resolve(Path(sys.argv[1]),Path(sys.argv[2]));r=GuardedAttempts(3);\nwith source_lock(s,r,Path(sys.argv[3])):print('acquired',flush=True)"
        env={**os.environ,'PYTHONPATH':str(Path(__file__).resolve().parents[2]/'src')}
        with source_lock(source,recorder,self.lock_root):
            proc=subprocess.Popen([sys.executable,'-B','-c',code,str(self.home),str(self.work),str(self.lock_root)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env)
            def cleanup():
                if proc.poll() is None:proc.kill()
                proc.communicate(timeout=3)
            self.addCleanup(cleanup)
            time.sleep(.1);self.assertIsNone(proc.poll())
            for cancel in (False,True):
                waiting=GuardedAttempts(.08 if not cancel else 2);errors=[]
                def wait():
                    try:
                        with execution_home(source,waiting,self.lock_root):self.fail('reference admitted while locked')
                    except TimeoutError:errors.append('timeout')
                thread=threading.Thread(target=wait);thread.start()
                if cancel:time.sleep(.02);waiting.cancel()
                thread.join(1);self.assertFalse(thread.is_alive());self.assertEqual(errors,['timeout'])
        out,err=proc.communicate(timeout=3)
        self.assertEqual((proc.returncode,out),(0,b'acquired\n'),err.decode())
        recorder.cancel()

    def test_default_lock_owner_is_independent_of_profile_home(self):
        source=self.source();recorder=GuardedAttempts(2)
        expected=self.root/'.local/state/model-routing-harness/subscription-auth'
        with patch('mrh.adapters.providers.subscription_auth.pwd.getpwuid',return_value=SimpleNamespace(pw_dir=str(self.root))):
            with patch.dict(os.environ,{'HOME':str(self.root/'profile-one')}):
                with source_lock(source,recorder):self.assertTrue((expected/'.mrh.lock').exists())
            with patch.dict(os.environ,{'HOME':str(self.root/'profile-two')}):
                with source_lock(source,recorder):self.assertTrue((expected/'.mrh.lock').exists())
            self.assertFalse((self.root/'profile-one').exists());self.assertFalse((self.root/'profile-two').exists())
        recorder.cancel()
