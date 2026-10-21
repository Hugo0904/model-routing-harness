import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from mrh.infrastructure import owned

@unittest.skipUnless(os.name == 'nt', 'Windows native bundle')
class HostBundleTests(unittest.TestCase):
    def test_snapshot_publishes_beside_target_and_removes_failed_copy_intermediates(self):
        from mrh.adapters.platforms.windows import snapshot_codex_bundle,verify_codex_bundle
        import subprocess
        names=('codex.exe','codex-code-mode-host.exe','codex-command-runner.exe','codex-windows-sandbox-setup.exe')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();source=root/'source';source.mkdir()
            for name in names:(source/name).write_bytes(('synthetic '+name).encode())
            replace=os.replace
            def same_directory(before,after):
                self.assertEqual(Path(before).parent,Path(after).parent)
                return replace(before,after)
            signature=subprocess.CompletedProcess([],0,json.dumps({'status':'Valid','subject':'OpenAI OpCo, LLC'}),'')
            with patch('os.replace',side_effect=same_directory),patch('subprocess.run',return_value=signature):
                executable=snapshot_codex_bundle(source/'codex.exe',root/'store')
            verify_codex_bundle(executable)
            self.assertEqual(list(executable.parent.glob('.mrh-copy-*')),[])
            self.assertEqual(list(executable.parent.glob('.mrh-write-*')),[])
            with patch('shutil.copyfileobj',side_effect=OSError('synthetic copy refusal')):
                with self.assertRaises(OSError):snapshot_codex_bundle(source/'codex.exe',root/'failed-store')
            self.assertEqual(list((root/'failed-store').rglob('.mrh-copy-*')),[])
            self.assertEqual((source/'codex.exe').read_bytes(),b'synthetic codex.exe')

    def test_companion_tamper_and_missing_file_are_rejected(self):
        from mrh.adapters.platforms.windows import verify_codex_bundle
        with tempfile.TemporaryDirectory() as tmp:
            root=owned.initialize(Path(tmp).resolve()/'bundle','host_bundle')
            files={}
            for name in ('codex.exe','codex-code-mode-host.exe','codex-command-runner.exe','codex-windows-sandbox-setup.exe'):
                data=('fixture '+name).encode();owned.replace_owned(root/name,data)
                files[name]=hashlib.sha256(data).hexdigest()
            owned.replace_owned(root/'bundle.json',json.dumps({'publisher':'OpenAI OpCo, LLC','files':files}).encode())
            with owned.locked(root,'host_bundle'): pass
            verify_codex_bundle(root/'codex.exe')
            (root/'codex-code-mode-host.exe').write_bytes(b'tampered')
            with self.assertRaisesRegex(ValueError,'changed'):verify_codex_bundle(root/'codex.exe')
            (root/'codex-code-mode-host.exe').unlink()
            with self.assertRaisesRegex(ValueError,'invalid'):verify_codex_bundle(root/'codex.exe')
