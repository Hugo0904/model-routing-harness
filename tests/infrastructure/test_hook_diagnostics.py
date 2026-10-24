"""Only changed direct-file behavior; no receiver or old fault matrix."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from mrh.infrastructure import hook_diagnostics as d, owned, plugin


class LegacyRemoval:
    def __init__(self, root):
        self.root, self.removed = root, 0
        self.registered, self.unowned = True, False
    def inspect(self):
        return {'registered': self.registered, 'running': self.registered}
    def remove(self):
        if self.unowned:raise owned.OwnedError('diagnostics_service_unowned')
        self.removed += 1; self.registered = False
        path = self.root / 'service.json'
        if path.exists():owned.read_regular(path);path.unlink()


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.root = self.base / 'config/hook-diagnostics';self.runtime = self.base / 'runtime'
        self.frame = {'stage':'result','exception':'ValueError','winerror':None,'child_rc':1,'elapsed_ms':1}
    def writer(self, platform='codex'):
        namespace = {'os':os,'json':json,'time':time,'sys':sys}
        exec(d._sink(self.root/'state.json'), namespace)
        namespace['_diag_platform'] = platform
        return namespace['_diag_send']
    def on(self):return d.control('on', root=self.root, runtime=self.runtime)
    def record(self, platform='codex'):return d.log_root(self.runtime)/d.RECORD_FILES[platform]

    def test_safe_overwrite_off_and_no_process(self):
        self.assertFalse(d.status(root=self.root,runtime=self.runtime)['enabled'])
        with patch('subprocess.Popen',side_effect=AssertionError('no service')):
            result=self.on();self.assertTrue(result['ready']);self.assertFalse(result['resident'])
            self.assertFalse(result['login']['registered']);self.assertTrue(self.on()['ready'])
        route=self.base/'settings.json';route.write_text('broken settings')
        from mrh.presentation import cli
        output=io.StringIO()
        with patch.object(d,'config_root',return_value=self.root):
            self.assertEqual(cli.main(['ctrl','--settings',str(route),'diagnostics','status','--json'],stdout=output,stderr=io.StringIO()),0)
        self.assertEqual(json.loads(output.getvalue())['mode'],'direct');self.assertEqual(route.read_text(),'broken settings')
        write=self.writer();self.assertEqual(write(self.frame),str(self.record()))
        self.assertEqual(set(json.loads(self.record().read_bytes())),{'recorded_at','version','platform',*self.frame})
        write({**self.frame,'child_rc':7});self.assertEqual(json.loads(self.record().read_bytes())['child_rc'],7)
        self.assertEqual(self.record().stat().st_size,512);self.assertEqual(self.record('claude').stat().st_size,512)
        before=self.record().read_bytes();self.assertIsNone(write({**self.frame,'private':'PRIVATE'}));self.assertEqual(self.record().read_bytes(),before)
        with self.assertRaisesRegex(owned.OwnedError,'requires_off'):d.control('clear',root=self.root,runtime=self.runtime)
        legacy=d.log_root(self.runtime)/'events-0.jsonl';legacy.write_bytes(b'old evidence')
        d.control('off',root=self.root,runtime=self.runtime)
        self.assertIsNone(write(self.frame));self.assertEqual(self.record().read_bytes(),before)
        d.control('clear',root=self.root,runtime=self.runtime)
        self.assertEqual(self.record().read_bytes().strip(),b'');self.assertEqual(legacy.read_bytes(),b'old evidence')

    def test_busy_permission_unsafe_target_and_short_write_drop(self):
        self.on();write=self.writer();target=self.record();before=target.read_bytes();original_open=os.open
        for error in (PermissionError('PRIVATE'),BlockingIOError('PRIVATE')):
            calls=[]
            def denied(path,*args,**kwargs):
                if Path(path)==target:calls.append(path);raise error
                return original_open(path,*args,**kwargs)
            with patch('os.open',side_effect=denied):self.assertIsNone(write(self.frame))
            self.assertEqual(len(calls),1);self.assertEqual(target.read_bytes(),before)
        target.chmod(0o400);self.assertIsNone(write(self.frame));self.assertEqual(target.read_bytes(),before);target.chmod(0o600)
        with patch('os.write',return_value=2) as attempt:
            self.assertIsNone(write(self.frame));self.assertEqual(attempt.call_count,1)
        original=self.base/'original';original.write_bytes(before)
        target.unlink();target.symlink_to(original);self.assertIsNone(write(self.frame));self.assertEqual(original.read_bytes(),before)
        target.unlink();os.link(original,target);self.assertIsNone(write(self.frame));self.assertEqual(original.read_bytes(),before)

    def test_prepared_hook_stdout_rc_unchanged_when_write_fails(self):
        self.on();artifact=self.base/'artifact';settings=self.base/'profile/settings.json'
        plugin.prepare(artifact,settings,sys.executable,advisory=True,diagnostics_root=self.root,runtime_root=self.runtime)
        folder=artifact/'plugins/model-routing-harness';original=folder/'original.py';original.write_bytes(plugin.LAUNCHER)
        def run(file):return subprocess.run([sys.executable,'-I','-B',str(file),'codex'],input=b'{}',capture_output=True,timeout=3)
        baseline=run(original);normal=run(folder/'launcher.py')
        self.assertEqual((normal.returncode,normal.stdout,normal.stderr),(baseline.returncode,baseline.stdout,b''))
        (folder/'runtime.pyz').write_bytes(b'PRIVATE synthetic integrity failure')
        baseline=run(original);failed=run(folder/'launcher.py')
        self.assertEqual((failed.returncode,failed.stdout,failed.stderr),(baseline.returncode,baseline.stdout,b''))
        self.assertEqual(json.loads(self.record().read_bytes())['stage'],'integrity');self.assertNotIn('PRIVATE',self.record().read_text())
        before=self.record().read_bytes();self.record().chmod(0o400);failed=run(folder/'launcher.py')
        self.assertEqual((failed.returncode,failed.stdout,failed.stderr),(baseline.returncode,baseline.stdout,b''));self.assertEqual(self.record().read_bytes(),before)

    def test_v1_enabled_and_off_stale_service_removed_preserving_data(self):
        for enabled in (True,False):
            with self.subTest(enabled=enabled):
                root=self.base/('on' if enabled else 'off');d._initialize(root,d.CONFIG_KIND)
                runtime=self.base/('runtime-on' if enabled else 'runtime-off')
                old={'version':1,'enabled':enabled,'runtime_root':str(runtime),'command':['/old/python','receiver']}
                owned.replace_owned(root/'state.json',d._json(old));owned.replace_owned(root/'service.json',b'{"legacy":"owned fixture"}');owned.replace_owned(root/'endpoint.json',b'{"legacy":"endpoint"}')
                area=d._initialize(d.log_root(runtime),d.LOG_KIND);events=area/'events-0.jsonl';events.write_bytes(b'preserve old events')
                unrelated=root/'keep';unrelated.write_bytes(b'preserve unrelated');service=LegacyRemoval(root)
                with patch.object(d,'config_root',return_value=root),patch.object(d,'_service',return_value=service),patch('subprocess.Popen',side_effect=AssertionError('no receiver start')):
                    result=d.after_install()
                self.assertEqual(service.removed,1);self.assertFalse(service.registered);self.assertEqual(d._state(root)['version'],2)
                self.assertEqual(result['enabled'],enabled);self.assertEqual(result['mode'],'direct');self.assertFalse(result['resident']);self.assertFalse(result['login']['registered'])
                self.assertFalse((root/'endpoint.json').exists());self.assertEqual(events.read_bytes(),b'preserve old events');self.assertEqual(unrelated.read_bytes(),b'preserve unrelated')
                d.control('off',root=root,runtime=runtime,service=service);self.assertEqual(service.removed,1)

    def test_unowned_legacy_refused_without_data_change(self):
        d._initialize(self.root,d.CONFIG_KIND)
        state={'version':1,'enabled':False,'runtime_root':str(self.runtime),'command':['/old/python']}
        owned.replace_owned(self.root/'state.json',d._json(state));before=(self.root/'state.json').read_bytes()
        service=LegacyRemoval(self.root);service.unowned=True
        with self.assertRaisesRegex(owned.OwnedError,'unowned'):d.control('on',root=self.root,runtime=self.runtime,service=service)
        self.assertEqual((self.root/'state.json').read_bytes(),before);self.assertTrue(service.registered)


if __name__=='__main__':unittest.main()
