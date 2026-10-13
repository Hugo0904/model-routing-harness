import copy, hashlib, io, json, os, subprocess, sys, tempfile, unittest, zipfile
from pathlib import Path
from mrh.infrastructure import plugin
CANARY="SYNTHETIC_LAUNCHER_CANARY"

class InstalledLauncherFaultTests(unittest.TestCase):
    def test_installed_launcher_integrity_and_runtime_load_faults_preserve_safe_call(self):
        with tempfile.TemporaryDirectory(prefix='mrh-e14-launcher-') as directory:
            root = Path(directory).resolve(); bundle = root / 'bundle'; state = root / 'state/settings.json'
            prepared = plugin.prepare(bundle, state, advisory=True)
            folder = bundle / 'plugins/model-routing-harness'
            event = {'hook_event_name': 'PreToolUse', 'tool_name': 'spawn_agent',
                     'session_id': 's', 'turn_id': 't', 'tool_use_id': 'c', 'tool_input': {'message': CANARY}}
            before = copy.deepcopy(event); state_before = state.read_bytes()
            python = prepared['artifact']['python']; launcher = folder / 'launcher.py'
            def run(value):
                result = subprocess.run([python, '-I', str(launcher)], cwd=root, env={'PATH': '/usr/bin:/bin'},
                                        input=json.dumps(value), text=True, capture_output=True, timeout=5)
                self.assertEqual(result.returncode, 0); self.assertEqual(result.stderr, '')
                self.assertNotIn('CANARY', result.stdout)
                return json.loads(result.stdout)
            self.assertEqual(run(event), {})  # default-off remains neutral
            original_runtime = (folder / 'runtime.pyz').read_bytes()
            (folder / 'runtime.pyz').write_bytes(b'broken-' + CANARY.encode())
            self.assertIn('integrity verification failed', run(event)['systemMessage'])
            self.assertEqual(run(dict(event, hook_event_name='PostToolUse')), {})
            with zipfile.ZipFile(folder / 'runtime.pyz', 'w') as archive:
                archive.writestr('__main__.py', "raise ImportError(" + repr(CANARY) + ")\n")
            binding = json.loads((folder / 'binding.json').read_text())
            binding['runtime_sha256'] = hashlib.sha256((folder / 'runtime.pyz').read_bytes()).hexdigest()
            (folder / 'binding.json').write_text(json.dumps(binding))
            self.assertIn('could not be loaded', run(event)['systemMessage'])
            # The CLI still loads, but both its configured runtime and shared
            # notice module are missing. Its catch-all must signal failure to
            # the independent launcher rather than returning a successful {}.
            with zipfile.ZipFile(io.BytesIO(original_runtime)) as original, zipfile.ZipFile(folder / 'runtime.pyz', 'w') as broken:
                for name in original.namelist():
                    if name not in ('mrh/application/advisory_runtime.py', 'mrh/routing/faults.py'):
                        broken.writestr(name, original.read(name))
            binding['runtime_sha256'] = hashlib.sha256((folder / 'runtime.pyz').read_bytes()).hexdigest()
            (folder / 'binding.json').write_text(json.dumps(binding))
            self.assertIn('could not be loaded', run(event)['systemMessage'])
            self.assertEqual(state.read_bytes(), state_before)
            self.assertFalse((state.parent / 'events.sqlite3').exists())
            self.assertEqual(event, before)
