import json
import os
from pathlib import Path
import tempfile
import unittest
from mrh.infrastructure import settings_v2 as v2
from mrh.application.advisory_runtime import _real

@unittest.skipUnless(os.name == 'nt', 'Windows path semantics')
class WorkspaceTests(unittest.TestCase):
    def test_persistent_all_projects_covers_other_drives_spaces_and_unc(self):
        with tempfile.TemporaryDirectory(prefix='mrh scope ') as tmp:
            settings = Path(tmp).resolve()/'profile/settings.json'
            v2.init(settings)
            saved = v2.update(settings, allowed_workspaces=['*'])
            self.assertEqual(v2.read(settings)['allowed_workspaces'], ['*'])
            for cwd in ('C:\\Projects\\Project One', 'D:\\Other Projects\\Two', 'Z:\\future-drive\\Three', '\\\\server\\share\\Project Four'):
                with self.subTest(cwd=cwd):
                    self.assertTrue(v2.workspace_allowed(saved, cwd))
                    self.assertIsNotNone(_real(cwd))
            for cwd in ('relative', 'D:drive-relative', '\\current-drive-only', '/', '\\\\server', '\\\\?\\C:\\device', 'C:\\a:stream', 'C:\\bad\nname', '\\\\server\\share:stream\\bad', 'D:\\project*'):
                with self.subTest(cwd=cwd): self.assertFalse(v2.workspace_allowed(saved, cwd))
            self.assertFalse(saved['enabled'])
            self.assertFalse(saved['task_export_permitted'])

    def test_finite_root_is_case_insensitive_without_neighbor_prefix_match(self):
        from mrh.adapters.platforms.windows_workspace import allowed
        roots = ['C:\\Projects\\Project One', '\\\\server\\share\\Team']
        self.assertTrue(allowed(roots, 'c:\\projects\\project one\\child'))
        self.assertTrue(allowed(roots, '\\\\SERVER\\SHARE\\TEAM\\child'))
        for cwd in ('D:\\Projects\\Project One', 'C:\\Projects\\Project One-backup', '\\\\server\\share\\TeamElse', '\\\\server\\share2\\Team'):
            self.assertFalse(allowed(roots, cwd))

    def test_all_projects_marker_is_not_a_settings_or_allowlist_file_path(self):
        from mrh.infrastructure.settings_schema import _validate_workspace_path, SettingsError
        with self.assertRaises(SettingsError): _validate_workspace_path('*')
        self.assertEqual(_validate_workspace_path('*', allow_all=True), '*')

    def test_control_center_can_set_all_projects(self):
        from mrh.application.ctrl_logic import changes_for
        self.assertEqual(changes_for(v2.default_settings(), 'allowed_workspaces', '*'), {'allowed_workspaces':['*']})
