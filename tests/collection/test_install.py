import copy
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[2] / 'scripts/collection'
spec = importlib.util.spec_from_file_location('collector_install', SOURCE / 'install.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve(); self.base.chmod(0o700)
        self.root = self.base / 'collector'; self.dataset = self.base / 'dataset'; self.dataset.mkdir(mode=0o700)
        self.hooks = self.base / 'hooks.json'
        self.before = {'description': 'preserve Canopy', 'hooks': {
            event: [{'matcher': '*', 'hooks': [{'type': 'command', 'command': 'canopy ' + event}]}]
            for event in ('UserPromptSubmit', 'PreToolUse', 'PostToolUse', 'Stop')}}
        self.hooks.write_text(json.dumps(self.before)); self.hooks.chmod(0o644)
        installer.daily.write(self.dataset / 'collection.json', {'count': 2, 'target': 10, 'samples': [{'old': 1}, {'old': 2}], 'scope': 'old ABC'})
        (self.dataset / 'COLLECTION.md').write_text('old rules'); (self.dataset / 'COLLECTION.md').chmod(0o600)
        self.args = (self.root, self.hooks, self.dataset, Path(sys.executable).resolve(), [str(self.base)], ['implementation'], 'test-authorized', self.base / 'spool')

    def test_install_idempotent_disable_and_uninstall_preserve_foreign_handlers_and_samples(self):
        result = installer.install(*self.args)
        self.assertTrue(result['installed_files_verified']); self.assertEqual(result['own_handlers'], 3)
        state = installer.daily.read(self.root / 'installation.json')
        configured = json.loads(self.hooks.read_bytes())
        self.assertEqual(installer.without_ours(configured, {state['command']}), self.before)
        self.assertEqual(installer.daily.read(self.dataset / 'collection.json')['samples'], [{'old': 1}, {'old': 2}])
        self.assertEqual(self.hooks.stat().st_mode & 0o777, 0o644)
        self.assertEqual(installer.install(*self.args)['own_handlers'], 3)
        # Simulate another owner adding a handler after installation.
        configured = json.loads(self.hooks.read_bytes()); other = {'hooks': [{'type': 'command', 'command': 'other-owner'}]}
        configured['hooks']['Stop'].append(other); self.hooks.write_text(json.dumps(configured))
        self.assertFalse(installer.disable(self.root)['configured_enabled'])
        self.assertEqual(installer.status(self.root)['own_handlers'], 0)
        self.assertIn(other, json.loads(self.hooks.read_bytes())['hooks']['Stop'])
        self.assertEqual(installer.disable(self.root, True)['own_handlers'], 0)
        self.assertTrue((self.dataset / 'collection.json').exists())

    def test_changed_hook_file_refuses_cas_without_replacing_other_owner(self):
        installer.install(*self.args)
        before, value, mode = installer.hooks_read(self.hooks)
        self.hooks.write_text(json.dumps({'hooks': {'Stop': []}, 'new-owner': True}))
        with self.assertRaisesRegex(ValueError, 'concurrent_change'):
            installer.hooks_commit(self.hooks, before, value, mode, self.root)
        self.assertTrue(json.loads(self.hooks.read_bytes())['new-owner'])

    def test_symlink_hook_file_and_unowned_install_root_rejected(self):
        original = self.hooks.read_bytes(); self.hooks.rename(self.base / 'real-hooks')
        self.hooks.symlink_to(self.base / 'real-hooks')
        with self.assertRaises(ValueError): installer.install(*self.args)
        self.assertEqual((self.base / 'real-hooks').read_bytes(), original)
        self.hooks.unlink(); self.hooks.write_bytes(original); self.hooks.chmod(0o644)
        # A separate, nonempty root must not become collector-owned.
        other = self.base / 'unknown'; other.mkdir(mode=0o700); (other / 'original').write_text('keep')
        with self.assertRaises(ValueError): installer.install(other, *self.args[1:])
        self.assertEqual((other / 'original').read_text(), 'keep')
