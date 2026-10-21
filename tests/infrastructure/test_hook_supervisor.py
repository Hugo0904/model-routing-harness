import hashlib
import fcntl
import json
import os
import signal
import subprocess
import sys
import time
import unittest
import zipfile
from pathlib import Path
from tests.infrastructure import test_advisory_plugin as fixtures
from mrh.infrastructure import settings_v2 as v2


class SupervisorTests(unittest.TestCase):
    def setUp(self):
        self.env=fixtures.AdvisoryPluginTests();self.env.setUp();self.addCleanup(self.env.doCleanups)

    def event(self,phase='PreToolUse',platform='codex',explicit=False):
        return {'hook_event_name':phase,'tool_name':'spawn_agent' if platform=='codex' else 'Agent',
                'session_id':'s','turn_id':'t','prompt_id':'p','tool_use_id':'c','cwd':'/',
                'tool_input':{'message':'synthetic test','prompt':'synthetic test',**({'model':'gpt-6-luna'} if explicit else {})},
                'tool_response':{'agent_id':'a','agentId':'a'}}

    def replace_runner(self,body):
        self.replace_module('mrh/application/advisory_runtime.py',body)

    def replace_module(self,name,body):
        root=self.env.launcher.parent;runtime=root/'runtime.pyz'
        with zipfile.ZipFile(runtime) as z:files={n:z.read(n) for n in z.namelist()}
        files[name]=body.encode()
        with zipfile.ZipFile(runtime,'w',zipfile.ZIP_DEFLATED) as z:
            for name,data in files.items():z.writestr(name,data)
        binding=json.loads((root/'binding.json').read_text());binding['runtime_sha256']=hashlib.sha256(runtime.read_bytes()).hexdigest();(root/'binding.json').write_text(json.dumps(binding))

    def test_integrity_and_runtime_failures_notify_both_event_phases_for_both_hosts(self):
        runtime=self.env.launcher.parent/'runtime.pyz';runtime.write_bytes(b'corrupt secret that must not be echoed')
        for platform in ('codex','claude'):
            for phase in ('PreToolUse','PostToolUse'):
                out=self.env.launch(self.event(phase,platform),platform);context=out['hookSpecificOutput']
                self.assertEqual(context['hookEventName'],phase);self.assertIn('additionalContext',context)
                self.assertNotIn('permissionDecision',context);self.assertNotIn('updatedInput',context)
                self.assertNotIn('corrupt secret',json.dumps(out))
                if phase=='PostToolUse':self.assertIn('do not repeat a successful tool',context['additionalContext'])

    def test_child_failure_discards_private_stderr_and_does_not_override_permissions(self):
        self.replace_runner("def run(*a,**k):\n import sys\n sys.stderr.write('SECRET-private-fixture')\n raise RuntimeError('SECRET-private-fixture')\n")
        out=self.env.launch(self.event());self.assertNotIn('SECRET-private-fixture',json.dumps(out));self.assertNotIn('permissionDecision',out['hookSpecificOutput'])

    def test_timeout_reaps_owned_runtime_group_for_jev_and_local_post(self):
        pidfile=self.env.root.parent/'owned-child.pid';lease=self.env.root.parent/'owned-child.lock';ready=self.env.root.parent/'owned-child.ready'
        child="import fcntl,time;from pathlib import Path;f=open("+repr(str(lease))+",'w');fcntl.flock(f,fcntl.LOCK_EX);Path("+repr(str(ready))+").write_text('ready');time.sleep(30)"
        code="def run(*a,**k):\n import subprocess,sys,time,os,json\n from pathlib import Path\n from mrh.infrastructure.settings_v2 import read\n from mrh.advisory.hook_budget import launch_seconds\n event=json.load(a[2]);seconds=launch_seconds(event,a[0],read(a[1]));os.write(k['control_fd'],(json.dumps({'seconds':seconds})+chr(10)).encode())\n p=subprocess.Popen([sys.executable,'-I','-B','-c',"+repr(child)+"])\n Path("+repr(str(pidfile))+").write_text(str(p.pid))\n time.sleep(30)\n"
        self.replace_runner(code)
        for phase,limit in (('PreToolUse',2.9),('PostToolUse',1.35)):
            for marker in (pidfile,ready):
                if marker.exists():marker.unlink()
            started=time.monotonic();out=self.env.launch(self.event(phase));elapsed=time.monotonic()-started
            self.assertGreater(elapsed,2.4 if phase=='PreToolUse' else .9)
            self.assertLess(elapsed,limit);self.assertIn('time budget exhausted',out['hookSpecificOutput']['additionalContext'])
            self.assertTrue(pidfile.exists() and ready.exists())
            # The owned descendant acquired this lease before hanging. Kernel
            # release proves exit without a forbidden global process inventory.
            with lease.open('r+') as descriptor:
                try:fcntl.flock(descriptor,fcntl.LOCK_EX|fcntl.LOCK_NB)
                except BlockingIOError:
                    os.kill(int(pidfile.read_text()),signal.SIGKILL)
                    self.fail('owned descendant survived supervisor timeout')

    def test_actual_provider_is_revalidated_per_invocation_and_invalid_provider_is_short_failure(self):
        root=self.env.launcher.parent
        self.replace_module('mrh/adapters/providers/registry.py',
            "from mrh.routing.types import Classification\ndef build(settings):\n class Fake:\n  def classify(self,*args,**kwargs):return Classification('Top',.9)\n return Fake()\n")
        before=(root/'binding.json').read_bytes()
        config=v2.read(self.env.settings);v2.update(self.env.settings,classifier={**config['classifier'],'provider':'codex_subscription','model':'gpt-6-luna'})
        self.assertEqual(self.env.launch(self.event())['hookSpecificOutput']['permissionDecision'],'deny')
        self.assertEqual((root/'binding.json').read_bytes(),before)
        self.env.settings.write_text('{"classifier":{"provider":"unknown"}}')
        start=time.monotonic();out=self.env.launch(self.event());self.assertLess(time.monotonic()-start,.5)
        self.assertIn('settings unavailable',out['hookSpecificOutput']['additionalContext'])

    def test_installed_templates_keep_pre_compatibility_and_short_post(self):
        from mrh.infrastructure import claude_hook
        hooks=json.loads((self.env.launcher.parent/'hooks/hooks.json').read_text())['hooks']
        self.assertEqual(hooks['PreToolUse'][0]['hooks'][0]['timeout'],50)
        self.assertEqual(hooks['PostToolUse'][0]['hooks'][0]['timeout'],2)
        doc=json.loads(claude_hook.plan('{}','/private/mock/model-routing-harness launcher claude'))
        self.assertEqual(doc['hooks']['PreToolUse'][0]['hooks'][0]['timeout'],50)
        self.assertEqual(doc['hooks']['PostToolUse'][0]['hooks'][0]['timeout'],2)

    def test_verified_nonjev_can_exceed_jev_deadline_without_binding_provider_cache(self):
        body="from mrh.routing.types import Classification\ndef build(settings):\n class Fake:\n  def classify(self,*args,**kwargs):\n   import time;time.sleep(2.65);return Classification('Top',.9)\n return Fake()\n"
        self.replace_module('mrh/adapters/providers/registry.py',body)
        binding=(self.env.launcher.parent/'binding.json').read_bytes()
        config=v2.read(self.env.settings);v2.update(self.env.settings,classifier={**config['classifier'],'provider':'codex_subscription','model':'gpt-6-luna','timeout_seconds':8})
        start=time.monotonic();out=self.env.launch(self.event());elapsed=time.monotonic()-start
        self.assertGreater(elapsed,2.6);self.assertLess(elapsed,3.3)
        self.assertEqual(out['hookSpecificOutput']['permissionDecision'],'deny')  # normal Top/Main advice, not a fault
        self.assertEqual((self.env.launcher.parent/'binding.json').read_bytes(),binding)

    def test_wrong_phase_runtime_output_is_replaced_by_context_for_the_real_post(self):
        self.replace_runner("def run(*a,**k):\n import json\n print(json.dumps({'hookSpecificOutput':{'hookEventName':'PreToolUse','permissionDecision':'deny'}}))\n return 0\n")
        out=self.env.launch(self.event('PostToolUse'));specific=out['hookSpecificOutput']
        self.assertEqual(specific['hookEventName'],'PostToolUse');self.assertNotIn('permissionDecision',specific)
