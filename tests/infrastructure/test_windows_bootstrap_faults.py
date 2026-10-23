"""Stdlib-only outer-fault transport evidence, not native Windows evidence."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import mrh_windows_setup as setup


class BootstrapFaultTests(unittest.TestCase):
    def invoke(self, fault, event, host='codex', native=True):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);script=root/'bootstrap.py'
            prelude=b''
            if fault=='source':
                # A synthetic safe-runtime boundary raises at assert_safe; the
                # real bind_runtime catches it as ProjectRootError. No native API.
                prelude=b"import sys,types\nm=types.ModuleType('mrh.adapters.platforms.windows')\ndef refuse(*a,**k):raise ValueError('synthetic source unavailable')\nm.assert_safe=refuse\nsys.modules[m.__name__]=m\n"
                identifier='a'*24;generation=root/'setup-state/generations'/identifier
                generation.mkdir(parents=True)
                relative='hosts/codex/plugins/model-routing-harness/'
                payloads={'app/mrh.pyz':b'synthetic safe fixture',relative+'runtime.pyz':b'synthetic runtime',relative+'launcher.py':b'',relative+'binding.json':b'{}'}
                meta={'runtime_root':str(root),'python':{'executable':str(Path(sys.executable).resolve()),'sha256':hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest()}}
                payloads['generation.json']=json.dumps(meta).encode()
                for name,data in payloads.items():
                    path=generation/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
                payloads.update({name.replace('hosts/codex/','hosts/claude/'):data for name,data in list(payloads.items()) if name.startswith('hosts/codex/')})
                for name,data in payloads.items():
                    path=generation/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
                manifest=json.dumps({'files':{name:hashlib.sha256(data).hexdigest() for name,data in payloads.items()}}).encode()
                (generation/'manifest.json').write_bytes(manifest)
                state={'current':identifier,'settings':str(root/'settings.json'),'generations':{identifier:hashlib.sha256(manifest).hexdigest()},'hosts':{host:{'generation':identifier} for host in ('codex','claude')}}
                (root/'setup-state/state.json').write_text(json.dumps(state))
            script.write_bytes(prelude+setup.BOOTSTRAP)
            return subprocess.run([str(Path(sys.executable).resolve()),'-I','-B',str(script),*(['--native-hook',host] if native else [])],input=json.dumps(event),capture_output=True,text=True,timeout=5)

    def event(self,prefix='mrh_packet_',**changes):
        return {'hook_event_name':'PreToolUse','tool_name':'spawn_agent','tool_input':{'task_name':prefix+'a'*32},**changes}

    def test_reserved_prefixes_deny_in_both_outer_fault_branches(self):
        for fault in ('integrity','source'):
            for prefix in ('mrh_packet_','mrh_release_'):
                for tool in ('spawn_agent','collaborationspawn_agent'):
                    with self.subTest(fault=fault,prefix=prefix,tool=tool):
                        result=self.invoke(fault,self.event(prefix,tool_name=tool))
                        self.assertEqual(result.returncode,0,result.stderr)
                        reply=json.loads(result.stdout)['hookSpecificOutput']
                        self.assertEqual(reply['permissionDecision'],'deny')
                        self.assertIn('outcome unknown',reply['permissionDecisionReason'])
                        self.assertIn('Do not retry',reply['permissionDecisionReason'])

    def test_ordinary_claude_and_post_are_preserved_and_cli_fails(self):
        for fault in ('integrity','source'):
            for host,event in [('codex',self.event('ordinary_')),('claude',self.event()),('codex',self.event(hook_event_name='PostToolUse')),('codex',self.event(tool_name='other'))]:
                with self.subTest(fault=fault,host=host,event=event):
                    result=self.invoke(fault,event,host)
                    self.assertEqual(result.returncode,0,result.stderr)
                    self.assertIn('systemMessage',json.loads(result.stdout))
                    self.assertIn('bound runtime' if fault=='source' else 'integrity check failed',result.stdout)
                    self.assertNotIn('permissionDecision',result.stdout)
            self.assertNotEqual(self.invoke(fault,{},native=False).returncode,0)
