"""Native Windows guarantees; no provider calls or real credential mutation."""
import ctypes
import io
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile
from unittest.mock import patch

if os.name == 'nt':
    from mrh.adapters.platforms import windows as win, windows_process as proc
from mrh.infrastructure import owned, plugin, settings_v2 as v2
from mrh.application import advisory_runtime
from mrh.routing.types import Classification

@unittest.skipUnless(os.name == 'nt', 'native Windows only')
class PlatformTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='MRH native space ')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()

    def test_private_acl_hardlink_refusal_and_shared_read_replace(self):
        root = owned.initialize(self.root/'profile', 'fixture')
        target = root/'a.txt'; owned.replace_owned(target, b'old')
        win.assert_safe(root, True, private=True)
        fd = win.open_regular(target)
        try:
            try: owned.replace_owned(target, b'new')
            except owned.OwnedError:
                self.assertEqual(owned.read_regular(target), b'old')
        finally: os.close(fd)
        owned.replace_owned(target, b'new')
        self.assertEqual(owned.read_regular(target), b'new')
        os.link(target, root/'hard.txt')
        with self.assertRaises(ValueError): owned.read_regular(target)

    def test_lock_contends_across_processes_and_releases_after_exit(self):
        root = owned.initialize(self.root/'locks', 'fixture')
        fd = win.open_regular(root/'lock', os.O_RDWR | os.O_CREAT)
        try:
            win.lock_fd(fd)
            code = 'from mrh.adapters.platforms import windows as w;import os,sys;f=w.open_regular(sys.argv[1],os.O_RDWR);w.lock_fd(f)'
            child = subprocess.run([sys.executable, '-B', '-c', code, str(root/'lock')], capture_output=True)
            self.assertNotEqual(child.returncode, 0)
            win.unlock_fd(fd)
            child = subprocess.run([sys.executable, '-B', '-c', code, str(root/'lock')], capture_output=True)
            self.assertEqual(child.returncode, 0, child.stderr)
        finally: os.close(fd)

    def test_job_timeout_reaps_descendants_and_normal_exit_also_reaps(self):
        for timeout in (True, False):
            marker = self.root/('pid'+str(timeout))
            body = "import subprocess,sys,time;from pathlib import Path;p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']);Path(sys.argv[1]).write_text(str(p.pid));" + ('time.sleep(30)' if timeout else 'time.sleep(.1)')
            if timeout:
                with self.assertRaises(subprocess.TimeoutExpired): proc.run([sys.executable, '-c', body, str(marker)], timeout=.8)
            else: self.assertEqual(proc.run([sys.executable, '-c', body, str(marker)]).returncode, 0)
            self.assertTrue(marker.exists())
            open_process = win.api(win.k, 'OpenProcess', [win.w.DWORD, win.w.BOOL, win.w.DWORD], win.w.HANDLE)
            wait = win.api(win.k, 'WaitForSingleObject', [win.w.HANDLE, win.w.DWORD], win.w.DWORD)
            handle = open_process(0x100000, False, int(marker.read_text()))
            if handle:
                try: self.assertEqual(wait(handle, 1000), 0, 'owned descendant survived')
                finally: win.close(handle)

    def test_python_gate_executes_in_assigned_process_and_preserves_stdin(self):
        assigned = []
        original = proc.Job.assign
        def assign(job, process):
            original(job, process)
            assigned.append(process.pid)
        code = "import json,os,sys;print(json.dumps({'pid':os.getpid(),'input':sys.stdin.read(),'arg':sys.argv[1]}))"
        with patch.object(proc.Job, 'assign', assign):
            process = proc.popen_python(sys.executable, code, ['中文 argument'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            out, err = process.communicate('原始 stdin'.encode('utf-8'), timeout=3)
            self.assertEqual(process.returncode, 0, err)
            self.assertEqual(json.loads(out), {'pid':assigned[0], 'input':'原始 stdin', 'arg':'中文 argument'})
        finally: proc.finish(process)

    def test_python_gate_assignment_failure_never_executes_target(self):
        marker = self.root/'must-not-exist'
        processes = []
        def refuse(job, process):
            processes.append(process)
            raise OSError('synthetic_assignment_refused')
        code = 'from pathlib import Path;Path('+repr(str(marker))+').write_text("unsafe")'
        with patch.object(proc.Job, 'assign', refuse):
            with self.assertRaisesRegex(OSError, 'synthetic_assignment_refused'):
                proc.popen_python(sys.executable, code, [], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertFalse(marker.exists())
        self.assertIsNotNone(processes[0].poll())

    def test_python_gate_timeout_reaps_descendants(self):
        marker = self.root/'python-child-pid'
        code = ("import subprocess,sys,time;from pathlib import Path;"
                "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']);"
                "Path(sys.argv[1]).write_text(str(p.pid));time.sleep(30)")
        process = proc.popen_python(sys.executable, code, [marker], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            with self.assertRaises(subprocess.TimeoutExpired):process.communicate(timeout=1)
        finally:proc.finish(process)
        self.assertTrue(marker.exists())
        handle = win.api(win.k, 'OpenProcess', [win.w.DWORD, win.w.BOOL, win.w.DWORD], win.w.HANDLE)(0x100000, False, int(marker.read_text()))
        if handle:
            try:self.assertEqual(win.api(win.k, 'WaitForSingleObject', [win.w.HANDLE, win.w.DWORD], win.w.DWORD)(handle,1000),0)
            finally:win.close(handle)

    def test_shell_quotes_spaces_and_refuses_expansion_metacharacters(self):
        self.assertIn('"C:\\Program Files\\Python\\python.exe"', win.quote_command(['C:\\Program Files\\Python\\python.exe', '-B']))
        for unsafe in ('%TEMP%', 'a&b', 'a!b', 'a\nb'):
            with self.assertRaises(ValueError): win.quote_command([unsafe])

    def test_default_off_and_scope_boundaries_prevent_classification(self):
        settings = self.root/'profile'/'settings.json'; v2.init(settings)
        event = {'hook_event_name':'PreToolUse','tool_name':'spawn_agent','tool_input':{'message':'offline synthetic'},
                 'cwd':str(self.root/'allowed'),'session_id':'s','turn_id':'t','tool_use_id':'c'}
        calls = []
        class Fake:
            def classify(self, *args): calls.append(True); return Classification('Light', .9)
        self.assertEqual(advisory_runtime.handle(event, 'codex', settings, classifier_factory=Fake), {})
        v2.update(settings, enabled=True, task_export_permitted=True, allowed_workspaces=[str(self.root/'allowed')])
        event['cwd'] = str(self.root/'allowed-neighbor')
        self.assertEqual(advisory_runtime.handle(event, 'codex', settings, classifier_factory=Fake), {})
        self.assertEqual(calls, [])

    def test_supervisor_real_handle_channel_noop_and_integrity_failure(self):
        settings = self.root/'profile'/'settings.json'; artifact = self.root/'artifact'
        plugin.prepare(artifact, settings, advisory=True)
        launcher = artifact/'plugins/model-routing-harness/launcher.py'
        event = {'hook_event_name':'PreToolUse','tool_name':'spawn_agent','tool_input':{'message':'offline synthetic'},
                 'cwd':str(self.root),'session_id':'s','turn_id':'t','tool_use_id':'c'}
        result = subprocess.run([sys.executable, '-I', '-B', str(launcher)], input=json.dumps(event), text=True, capture_output=True, timeout=5)
        self.assertEqual(json.loads(result.stdout), {})
        (launcher.parent/'runtime.pyz').write_bytes(b'broken private fixture')
        result = subprocess.run([sys.executable, '-I', '-B', str(launcher)], input=json.dumps(event), text=True, capture_output=True, timeout=5)
        out = json.loads(result.stdout)
        self.assertIn('integrity verification failed', out['systemMessage'])
        self.assertNotIn('broken private fixture', result.stdout)

    def test_native_hook_command_runs_under_powershell_with_spaces(self):
        settings=self.root/'profile/settings.json';artifact=self.root/'artifact'
        plugin.prepare(artifact,settings,advisory=True)
        v2.update(settings,enabled=True,task_export_permitted=True,allowed_workspaces=['*'],
            policy={'tiers':{'Light':{'codex':[{'model':'gpt-6-luna','effort':'max'}]}}})
        runtime=artifact/'plugins/model-routing-harness/runtime.pyz'
        with zipfile.ZipFile(runtime) as archive:files={n:archive.read(n) for n in archive.namelist()}
        files['mrh/adapters/providers/registry.py']=b"from mrh.routing.types import Classification\ndef build(s):\n class Fake:\n  def classify(self,*a,**k):return Classification('Light',.99)\n return Fake()\n"
        with zipfile.ZipFile(runtime,'w',zipfile.ZIP_DEFLATED) as archive:
            for name,data in files.items():archive.writestr(name,data)
        binding=runtime.with_name('binding.json');value=json.loads(binding.read_bytes())
        value['runtime_sha256']=hashlib.sha256(runtime.read_bytes()).hexdigest();binding.write_text(json.dumps(value),encoding='utf-8')
        command=win.codex_hook_command(sys.executable)
        env={**os.environ,'PLUGIN_ROOT':str(artifact/'plugins/model-routing-harness')}
        shell=Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
        event={'hook_event_name':'PreToolUse','tool_name':'spawn_agent','session_id':'s','turn_id':'t','tool_use_id':'c',
            'cwd':str(self.root),'tool_input':{'message':'native UTF-8 中文 test'}}
        for outer in ([str(shell),'-NoProfile','-NonInteractive','-Command',command], [os.environ['COMSPEC'],'/D','/C',command]):
            result=subprocess.run(outer,input=json.dumps(event,ensure_ascii=False).encode('utf-8'),capture_output=True,env=env,timeout=8)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(json.loads(result.stdout)['hookSpecificOutput']['permissionDecision'],'deny')

    def test_windows_subscription_provider_and_packets_fail_closed(self):
        from mrh.adapters.providers.registry import build
        from mrh.adapters.hosts.codex_packets import root_for, PacketError
        from mrh.routing.core import ClassifierFailure
        for name in ('codex_subscription', 'claude_subscription'):
            with self.assertRaises(ClassifierFailure): build({'classifier':{'provider':name},'enabled':True,'task_export_permitted':True})
        with self.assertRaises(PacketError): root_for(self.root/'profile/settings.json')
        from mrh.adapters.hosts.registry import REGISTRATIONS
        self.assertFalse(REGISTRATIONS['codex'].public()['codex_packet'])
        self.assertEqual(REGISTRATIONS['claude'].public()['installation'],'official-plugin')

    def test_active_supervisor_utf8_policy_pipe_and_timeout(self):
        settings = self.root/'profile/settings.json'; artifact = self.root/'artifact'
        plugin.prepare(artifact, settings, advisory=True)
        v2.update(settings, enabled=True, task_export_permitted=True, allowed_workspaces=['*'],
            policy={'tiers':{'Light':{'codex':[{'model':'gpt-6-luna','effort':'max'}]}}})
        launcher = artifact/'plugins/model-routing-harness/launcher.py'
        runtime = launcher.parent/'runtime.pyz'
        original = runtime.read_bytes()
        for delay in (1.15, 30):
            with zipfile.ZipFile(io.BytesIO(original)) as archive:
                files = {n:archive.read(n) for n in archive.namelist()}
            files['mrh/adapters/providers/registry.py'] = (
                "from mrh.routing.types import Classification\n"
                "def build(settings):\n"
                " import time;time.sleep("+str(delay)+")\n"
                " class Fake:\n"
                "  def classify(self,task,*args,**kwargs):\n"
                "   assert task=='整理中文字串'\n"
                "   return Classification('Light',.99)\n"
                " return Fake()\n").encode('utf-8')
            with zipfile.ZipFile(runtime,'w',zipfile.ZIP_DEFLATED) as archive:
                for name, data in files.items(): archive.writestr(name,data)
            binding = launcher.parent/'binding.json'
            value = json.loads(binding.read_bytes()); value['runtime_sha256']=hashlib.sha256(runtime.read_bytes()).hexdigest()
            binding.write_text(json.dumps(value),encoding='utf-8')
            event={'hook_event_name':'PreToolUse','tool_name':'spawn_agent','session_id':'s'+str(delay),
                   'turn_id':'t','tool_use_id':'c','cwd':str(self.root),'tool_input':{'message':'整理中文字串'}}
            start=time.monotonic()
            result=subprocess.run([sys.executable,'-I','-B',str(launcher)],input=json.dumps(event,ensure_ascii=False).encode('utf-8'),capture_output=True,timeout=5)
            elapsed=time.monotonic()-start; out=json.loads(result.stdout)
            if delay < 2:
                self.assertGreater(elapsed,1.1)
                self.assertEqual(out['hookSpecificOutput']['permissionDecision'],'deny')
                self.assertIn('gpt-6-luna',out['hookSpecificOutput']['permissionDecisionReason'])
            else:
                self.assertGreater(elapsed,2.4);self.assertLess(elapsed,3.6)
                self.assertIn('time budget exhausted',out['systemMessage'])

    def delayed_startup_launcher(self, delay, name='artifact'):
        """Installed Windows launcher whose runtime import takes `delay` s, i.e. before it reports a policy."""
        settings = self.root/'profile/settings.json'; artifact = self.root/name
        plugin.prepare(artifact, settings, advisory=True)
        v2.update(settings, enabled=True, task_export_permitted=True, allowed_workspaces=['*'],
            policy={'tiers':{'Light':{'codex':[{'model':'gpt-6-luna','effort':'max'}]}}})
        launcher = artifact/'plugins/model-routing-harness/launcher.py'; runtime = launcher.parent/'runtime.pyz'
        with zipfile.ZipFile(runtime) as archive: files = {n:archive.read(n) for n in archive.namelist()}
        import re
        entry = files['mrh/application/advisory_runtime.py']
        # The delay must follow the future import (any line ending) and precede every other import.
        files['mrh/application/advisory_runtime.py'], count = re.subn(
            rb'(from __future__ import annotations\r?\n)', lambda m: m.group(1)+('import time;time.sleep('+str(delay)+')\n').encode(), entry, count=1)
        self.assertEqual(count, 1)
        files['mrh/adapters/providers/registry.py'] = (b"from mrh.routing.types import Classification\ndef build(s):\n class Fake:\n"
            b"  def classify(self,*a,**k):return Classification('Light',.99)\n return Fake()\n")
        with zipfile.ZipFile(runtime, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name, data in files.items(): archive.writestr(name, data)
        binding = launcher.parent/'binding.json'; value = json.loads(binding.read_bytes())
        value['runtime_sha256'] = hashlib.sha256(runtime.read_bytes()).hexdigest(); binding.write_text(json.dumps(value), encoding='utf-8')
        return launcher

    def run_launcher(self, launcher, phase, tool_input=None):
        event = {'hook_event_name':phase,'tool_name':'spawn_agent','session_id':'s','turn_id':'t','tool_use_id':'c',
                 'cwd':str(self.root),'tool_input':tool_input or {'message':'synthetic'},'tool_response':{'agent_id':'a'}}
        start = time.monotonic()
        result = subprocess.run([sys.executable,'-I','-B',str(launcher)], input=json.dumps(event).encode(), capture_output=True, timeout=8)
        return json.loads(result.stdout), time.monotonic()-start

    def test_pre_waits_up_to_the_jev_window_for_a_slow_startup(self):
        # Startup that reports its policy at ~1.3 s used to be killed at the 1.0 s first-stage deadline.
        launcher = self.delayed_startup_launcher(1.3)
        out, elapsed = self.run_launcher(launcher, 'PreToolUse')
        self.assertGreater(elapsed, 1.3)
        self.assertEqual(out['hookSpecificOutput']['permissionDecision'], 'deny')  # real advice, not a fault

    def test_pre_startup_beyond_the_jev_window_still_times_out_without_a_decision(self):
        launcher = self.delayed_startup_launcher(3.0)
        out, elapsed = self.run_launcher(launcher, 'PreToolUse')
        self.assertGreater(elapsed, 2.4); self.assertLess(elapsed, 3.6)
        self.assertIn('time budget exhausted', out['systemMessage'])
        self.assertNotIn('permissionDecision', out['hookSpecificOutput'])

    def test_local_policy_pre_and_post_use_the_windows_deadlines_and_still_time_out_beyond_them(self):
        # Explicit-model Pre (local policy 2.5 s) and Post (2.0 s) survive a 1.3 s startup...
        slow = self.delayed_startup_launcher(1.3)
        out, elapsed = self.run_launcher(slow, 'PreToolUse', {'message':'synthetic','model':'gpt-6-luna'})
        self.assertGreater(elapsed, 1.3); self.assertEqual(out, {})  # preserved: no fault, no decision
        out, elapsed = self.run_launcher(slow, 'PostToolUse')
        self.assertGreater(elapsed, 1.3); self.assertEqual(out, {})
        # ...but are still cut off at their own limits, without a decision or a long wait.
        hung = self.delayed_startup_launcher(3.5, 'artifact-hung')
        out, elapsed = self.run_launcher(hung, 'PreToolUse', {'message':'synthetic','model':'gpt-6-luna'})
        self.assertGreater(elapsed, 2.4); self.assertLess(elapsed, 3.4)
        self.assertIn('time budget exhausted', out['systemMessage']); self.assertNotIn('permissionDecision', out['hookSpecificOutput'])
        out, elapsed = self.run_launcher(hung, 'PostToolUse')
        self.assertGreater(elapsed, 1.9); self.assertLess(elapsed, 2.9)  # 2.0 s, not 1.0 s and not 2.5 s
        self.assertIn('do not repeat a successful tool', out['hookSpecificOutput']['additionalContext'])

    def test_budget_constants_are_windows_only_and_other_platforms_keep_one_second(self):
        import importlib
        from mrh.advisory import hook_budget
        self.assertEqual((hook_budget.LOCAL_SECONDS, hook_budget.POST_SECONDS), (2.5, 2.0))
        try:
            with patch.object(sys, 'platform', 'darwin'):
                importlib.reload(hook_budget)
                self.assertEqual((hook_budget.LOCAL_SECONDS, hook_budget.POST_SECONDS), (1.0, 1.0))
                settings = {'classifier':{'provider':'jev'},'enabled':True,'task_export_permitted':True}
                self.assertEqual(hook_budget.launch_seconds({'hook_event_name':'PostToolUse'}, 'claude', settings), 1.0)
        finally:
            importlib.reload(hook_budget)
        self.assertEqual((hook_budget.LOCAL_SECONDS, hook_budget.POST_SECONDS), (2.5, 2.0))
        self.assertEqual(hook_budget.launch_seconds({'hook_event_name':'PostToolUse'}, 'claude', {'classifier':{'provider':'jev'}}), 2.0)

    def test_claude_post_host_timeout_leaves_room_for_the_supervisor_deadline(self):
        import mrh_windows_setup  # noqa: F401 (import proves the module still loads)
        source = Path(mrh_windows_setup.__file__).read_text(encoding='utf-8')
        self.assertIn("'timeout':50 if event=='PreToolUse' else 5", source)
    def test_key_status_never_prints_secret(self):
        from mrh.presentation import key_cli
        backend = type('Fake', (), {'is_set': staticmethod(lambda name: True)})
        out = io.StringIO()
        with patch.dict(os.environ, {'TYPESAFE_API_KEY':'private-fixture-never-output'}):
            self.assertEqual(key_cli.run('status','jev',stdout=out,stderr=io.StringIO(),secrets_module=backend), 0)
        self.assertIn('Windows Credential Manager', out.getvalue())
        self.assertNotIn('private-fixture', out.getvalue())
