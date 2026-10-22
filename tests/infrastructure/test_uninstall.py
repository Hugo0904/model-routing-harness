"""`./setup --uninstall` through the same isolated roots and native-command fixtures as the install tests.

Nothing here touches the real HOME, Keychain, shells or host configuration: shell files live under a fixture home, the
Keychain functions are mocks, and the Codex CLI is the fixture script from test_setup.
"""
from functools import partial
import io
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import mrh_setup as setup
from mrh.adapters.platforms import macos_path
from mrh.application import skills
import tests.infrastructure.test_setup as base

OTHER_HOOK = {'matcher': 'Other', 'hooks': [{'type': 'command', 'command': 'other-hook'}]}


def normalized(document):
    return (json.dumps(document, indent=2, ensure_ascii=False) + '\n').encode()


class UninstallTests(unittest.TestCase):
    # Reuse the install fixtures without inheriting (and re-running) the install tests themselves.
    args = base.SetupTests.args
    fake_build = base.SetupTests.fake_build
    run_setup = base.SetupTests.run_setup
    state = base.SetupTests.state
    profile = base.SetupTests.profile
    native_change = base.SetupTests.native_change
    disk = base.SetupTests.disk

    def setUp(self):
        base.SetupTests.setUp(self)
        self.home = self.root / 'home'
        self.home.mkdir(exist_ok=True)
        environ = {k: v for k, v in os.environ.items() if k != 'CLAUDE_CONFIG_DIR'}
        environ['HOME'] = str(self.home)
        p = patch.dict(os.environ, environ, clear=True); p.start(); self.addCleanup(p.stop)
        p = patch('mrh_setup.plan_path_removal', side_effect=partial(
            macos_path.plan_removal, user_home=self.home, environ={'PATH': '/usr/bin:/bin'}, login_shell='/bin/zsh'))
        p.start(); self.addCleanup(p.stop)
        self.claude_settings = self.root / 'claude/settings.json'
        self.claude_settings.parent.mkdir()
        self.key_present = False
        self.key_deleted = []
        p = patch('mrh_setup.secrets.is_set', side_effect=lambda name: self.key_present); p.start(); self.addCleanup(p.stop)
        p = patch('mrh_setup.secrets.delete', side_effect=lambda name: self.key_deleted.append(name) or True); p.start(); self.addCleanup(p.stop)

    # -- helpers --------------------------------------------------------------------------------------------------

    def install(self, *hosts):
        extra = []
        for host in hosts:
            extra += ['--host', host]
        args = self.args('--claude-settings', str(self.claude_settings), '--claude-cli', str(self.claude), *extra)
        args.host = list(hosts)
        return self.run_setup(args)

    def uninstall_args(self, *extra):
        return setup.parser().parse_args([
            '--uninstall', '--prefix', str(self.prefix), '--config-root', str(self.config), '--bin-dir', str(self.bin),
            '--codex-cli', str(self.cli), '--claude-settings', str(self.claude_settings), *extra])

    def uninstall(self, *extra):
        return setup.uninstall(self.uninstall_args(*extra))

    def ids(self, rows):
        return [row['id'] for row in rows]

    def codex_native(self):
        return json.loads(self.native.read_text())

    # -- tests ----------------------------------------------------------------------------------------------------

    def test_preview_is_the_default_and_writes_nothing(self):
        self.claude_settings.write_bytes(normalized({'custom': 1, 'hooks': {'PreToolUse': [OTHER_HOOK]}}))
        self.install('codex', 'claude')
        before = self.disk(); mutations = self.codex_native()['mutations']
        result = self.uninstall()
        self.assertEqual(result['status'], 'planned'); self.assertEqual(result['mode'], 'preview'); self.assertFalse(result['writes'])
        self.assertEqual(self.ids(result['remove']), ['claude_hook', 'codex_plugin', 'codex_marketplace', 'shell_path', 'shell_path', 'bin_entry', 'current_link', 'setup_state'])
        self.assertEqual(self.disk(), before)
        self.assertEqual(self.codex_native()['mutations'], mutations)
        self.assertEqual(self.key_deleted, [])
        # No `--yes` means no `--purge-data` effect either.
        self.assertEqual(self.ids(self.uninstall('--purge-data')['remove'])[-2:], ['profile_data', 'settings_pointer'])
        self.assertEqual(self.disk(), before)

    def test_uninstall_returns_claude_and_shell_files_to_their_pre_install_bytes_and_keeps_user_data(self):
        original = normalized({'custom': 1, 'hooks': {'PreToolUse': [OTHER_HOOK], 'Stop': [{'hooks': [{'type': 'command', 'command': 'stop-hook'}]}]}})
        self.claude_settings.write_bytes(original)
        (self.home / '.zshrc').write_bytes(b'export EDITOR=vi\n')
        self.install('codex', 'claude')
        self.assertNotEqual(self.claude_settings.read_bytes(), original)
        profile_bytes = self.profile().read_bytes(); pointer = (self.config / 'active-settings').read_bytes()
        result = self.uninstall('--yes')
        self.assertEqual(result['status'], 'uninstalled', result)
        self.assertEqual(self.claude_settings.read_bytes(), original)
        self.assertEqual((self.home / '.zshrc').read_bytes(), b'export EDITOR=vi\n')
        self.assertFalse((self.home / '.zprofile').exists())          # setup created it with only the block
        self.assertEqual(self.codex_native(), {**self.codex_native(), 'root': None, 'installed': False})
        self.assertFalse((self.bin / 'mrh').is_symlink()); self.assertFalse((self.prefix / 'current').is_symlink())
        self.assertFalse(self.prefix.exists())
        self.assertEqual(self.profile().read_bytes(), profile_bytes); self.assertEqual((self.config / 'active-settings').read_bytes(), pointer)
        self.assertEqual(self.ids(result['keep']), ['profile_data', 'settings_pointer'])
        self.assertEqual(self.key_deleted, [])

    def test_second_run_is_idempotent_and_a_reinstall_still_works(self):
        self.install('codex')
        self.assertEqual(self.uninstall('--yes')['status'], 'uninstalled')
        after = self.disk()
        again = self.uninstall('--yes')
        self.assertEqual(again['status'], 'not_installed'); self.assertFalse(again['writes'])
        self.assertEqual(self.disk(), after)
        self.assertEqual(self.install('codex')['operation'], 'installed')

    def test_purge_data_removes_profile_pointer_and_key_but_never_without_yes(self):
        self.key_present = True
        self.install('codex')
        (self.profile().parent / 'advice.sqlite3').write_bytes(b'facts')
        result = self.uninstall('--yes', '--purge-data')
        self.assertEqual(result['status'], 'uninstalled', result)
        self.assertIn('profile_data', self.ids(result['removed'])); self.assertIn('keychain_jev', self.ids(result['removed']))
        self.assertEqual(self.key_deleted, ['jev'])
        self.assertFalse(self.profile().parent.exists()); self.assertFalse((self.config / 'active-settings').exists())
        self.assertFalse(self.config.exists()); self.assertEqual(result['keep'], [])

    def test_keychain_is_listed_as_kept_by_default(self):
        self.key_present = True
        self.install('codex')
        result = self.uninstall('--yes')
        self.assertIn('keychain_jev', self.ids(result['keep'])); self.assertEqual(self.key_deleted, [])

    def test_unrecognised_profile_directory_is_kept_even_with_purge(self):
        self.install('codex')
        (self.profile().parent / 'notes.txt').write_text('mine')
        result = self.uninstall('--yes', '--purge-data')
        self.assertEqual(result['status'], 'uninstalled')
        self.assertTrue((self.profile().parent / 'notes.txt').exists()); self.assertTrue(self.profile().exists())
        self.assertTrue(any(r['id'] == 'profile_data' and r['reason'].startswith('profile_not_verified_as_mrh_owned') for r in result['keep']))

    def test_modified_shell_block_is_left_alone_and_reported(self):
        self.install('codex')
        edited = (self.home / '.zshrc').read_text().replace('export PATH', 'export  PATH')
        (self.home / '.zshrc').write_text(edited)
        result = self.uninstall('--yes', '--purge-data')
        self.assertEqual(result['status'], 'incomplete'); self.assertEqual([b['reason'] for b in result['blocked']], ['mrh_shell_block_modified'])
        self.assertEqual((self.home / '.zshrc').read_text(), edited)
        self.assertFalse((self.home / '.zprofile').exists())          # the intact block went
        self.assertTrue(self.profile().exists())                      # nothing is purged while something is left
        self.assertIn('profile_data', [k['id'] for k in result['keep'] if k['reason'] == 'skipped_uninstall_incomplete'])
        (self.home / '.zshrc').write_text(edited.replace('export  PATH', 'export PATH'))
        self.assertEqual(self.uninstall('--yes', '--purge-data')['status'], 'uninstalled')
        self.assertFalse(self.profile().parent.exists())

    def test_foreign_claude_hook_blocks_everything_and_nothing_is_written(self):
        self.install('claude')
        document = json.loads(self.claude_settings.read_text())
        document['hooks']['PreToolUse'].append({'matcher': 'Agent|Task', 'hooks': [{'type': 'command', 'command': '/elsewhere/model-routing-harness/launcher.py claude'}]})
        self.claude_settings.write_bytes(normalized(document))
        before = self.disk()
        result = self.uninstall('--yes', '--purge-data')
        self.assertEqual(result['status'], 'incomplete'); self.assertEqual(result['blocked'][0]['reason'], 'claude_hook_unowned')
        self.assertEqual(self.disk(), before)                         # hook, links, generations, PATH blocks, profile all stay
        self.assertEqual(self.key_deleted, [])

    def test_invalid_claude_settings_json_is_not_touched(self):
        self.install('claude')
        self.claude_settings.write_text('{not json')
        before = self.disk()
        result = self.uninstall('--yes')
        self.assertEqual(result['blocked'][0]['reason'], 'claude_settings_not_json')
        self.assertEqual(self.disk(), before)

    def test_unexpected_claude_settings_shape_is_reported_by_name(self):
        self.install('claude')
        self.claude_settings.write_text('[1, 2]')
        result = self.uninstall('--yes')
        self.assertEqual(result['blocked'][0]['reason'], 'claude_settings_shape_unexpected')

    def test_claude_settings_without_an_mrh_hook_is_not_rewritten(self):
        odd = b'{ "hooks": {"Stop": []},\n   "model":"x" }\n'            # formatting setup would normalise
        self.claude_settings.write_bytes(odd)
        self.install('codex')
        result = self.uninstall('--yes')
        self.assertEqual(result['status'], 'uninstalled'); self.assertEqual(self.claude_settings.read_bytes(), odd)

    def test_native_failure_keeps_links_and_generations_and_the_rerun_finishes(self):
        self.install('codex')
        self.native_change(fail_after='plugin-remove')
        result = self.uninstall('--yes')
        self.assertEqual(result['status'], 'incomplete')
        self.assertTrue((self.prefix / 'current').is_symlink()); self.assertTrue((self.bin / 'mrh').is_symlink())
        self.assertTrue((self.prefix / 'setup-state/state.json').exists())
        again = self.uninstall('--yes')
        self.assertEqual(again['status'], 'uninstalled', again)
        self.assertFalse(self.prefix.exists()); self.assertFalse(self.codex_native()['installed']); self.assertIsNone(self.codex_native()['root'])

    def test_missing_codex_cli_blocks_when_codex_is_installed(self):
        self.install('codex')
        self.cli.unlink()
        result = self.uninstall('--yes')
        self.assertEqual(result['status'], 'incomplete'); self.assertEqual(result['blocked'][0]['id'], 'codex_plugin')
        self.assertTrue((self.prefix / 'current').is_symlink())

    def test_foreign_marketplace_or_other_settings_is_not_ours(self):
        self.install('codex')
        self.native_change(root=str(self.root / 'somewhere-else'))
        result = self.uninstall('--yes')
        self.assertEqual(result['status'], 'incomplete'); self.assertEqual(result['blocked'][0]['reason'], 'codex_registration_unowned')
        self.assertTrue(self.codex_native()['installed'])

    def test_foreign_bin_entry_and_legacy_app_are_kept(self):
        self.install('codex')
        (self.prefix / 'app').mkdir(); (self.prefix / 'app/keep').write_bytes(b'anchor')
        (self.bin / 'mrh').unlink(); (self.bin / 'mrh').write_text('#!/bin/sh\necho other tool\n')
        result = self.uninstall('--yes')
        self.assertEqual(result['status'], 'uninstalled')
        self.assertEqual((self.bin / 'mrh').read_text(), '#!/bin/sh\necho other tool\n')
        self.assertEqual((self.prefix / 'app/keep').read_bytes(), b'anchor')
        self.assertEqual(sorted(self.ids(result['keep'])), ['bin_entry', 'legacy_app', 'profile_data', 'settings_pointer'])
        self.assertFalse((self.prefix / 'setup-state').exists()); self.assertFalse((self.prefix / 'current').exists())

    def test_current_link_to_somewhere_else_blocks_before_deleting_generations(self):
        self.install('codex')
        (self.prefix / 'current').unlink(); (self.prefix / 'current').symlink_to(self.root)
        result = self.uninstall('--yes')
        self.assertEqual(result['blocked'][0]['reason'], 'current_generation_conflict')
        self.assertTrue((self.prefix / 'setup-state/state.json').exists())

    def test_unexpected_entry_in_setup_state_is_kept_and_the_state_stays_readable(self):
        self.install('codex')
        (self.prefix / 'setup-state/extra.txt').write_text('mine')
        result = self.uninstall('--yes')
        self.assertEqual(result['status'], 'incomplete'); self.assertEqual(result['blocked'][0]['reason'], 'setup_state_unexpected_entry:extra.txt')
        self.assertTrue((self.prefix / 'setup-state/owner.json').exists()); self.assertTrue((self.prefix / 'setup-state/generations').exists())
        (self.prefix / 'setup-state/extra.txt').unlink()
        self.assertEqual(self.uninstall('--yes')['status'], 'uninstalled')

    def test_read_only_generation_directories_are_removed(self):
        self.install('codex')
        generation = next((self.prefix / 'setup-state/generations').iterdir())
        os.chmod(generation / 'runtime/bin', 0o500); os.chmod(generation, 0o500)
        self.assertEqual(self.uninstall('--yes')['status'], 'uninstalled')
        self.assertFalse(self.prefix.exists())

    def test_symlink_inside_a_generation_is_unlinked_not_followed(self):
        self.install('codex')
        keep = self.root / 'outside'; keep.mkdir(); (keep / 'precious').write_text('x')
        generation = next((self.prefix / 'setup-state/generations').iterdir())
        (generation / 'dangling-link').symlink_to(keep)
        self.assertEqual(self.uninstall('--yes')['status'], 'uninstalled')
        self.assertEqual((keep / 'precious').read_text(), 'x')

    def test_unmodified_skills_are_removed_and_modified_ones_kept(self):
        self.install('codex')
        skills.run('install', 'claude'); skills.run('install', 'codex')
        modified = Path(skills.status('codex')['path']) / 'SKILL.md'
        modified.write_text(modified.read_text() + '\nmy own note\n')
        result = self.uninstall('--yes')
        self.assertEqual(result['status'], 'uninstalled')
        self.assertEqual(skills.status('claude')['status'], 'not_installed')
        self.assertEqual(skills.status('codex')['status'], 'modified')
        kept = {k['id']: k for k in result['keep']}
        self.assertEqual(kept['skill_codex']['reason'], 'skill_modified'); self.assertIn('--backup-dir', kept['skill_codex']['hint'])

    def test_host_flag_limits_hosts_and_skills(self):
        self.install('codex', 'claude')
        skills.run('install', 'claude'); skills.run('install', 'codex')
        result = self.uninstall('--yes', '--host', 'claude')
        self.assertEqual(result['hosts'], ['claude'])
        self.assertTrue(self.codex_native()['installed'])
        self.assertEqual(skills.status('claude')['status'], 'not_installed'); self.assertEqual(skills.status('codex')['status'], 'latest')

    def test_nothing_installed_reports_not_installed_without_touching_anything(self):
        before = self.disk()
        result = self.uninstall('--yes')
        self.assertEqual(result['status'], 'not_installed'); self.assertEqual(self.disk(), before)

    def test_policy_options_and_stray_flags_are_refused(self):
        for extra in (['--enable'], ['--codex-packets']):
            with self.assertRaises(setup.SetupError):
                self.uninstall(*extra)
        out = io.StringIO()
        with patch('sys.stdout', out), patch('mrh_setup.platform.system', return_value='Darwin'):
            code = setup.main(['--yes', '--json'])
        self.assertEqual(code, 2); self.assertIn('yes_and_purge_data_require_uninstall', out.getvalue())
        with patch('sys.stderr', io.StringIO()), self.assertRaises(SystemExit):
            setup.parser().parse_args(['--uninstall', '--rollback'])

    def test_main_exit_codes_and_text_output(self):
        self.install('codex')
        argv = ['--uninstall', '--prefix', str(self.prefix), '--config-root', str(self.config), '--bin-dir', str(self.bin), '--codex-cli', str(self.cli)]
        out = io.StringIO()
        with patch('sys.stdout', out):
            self.assertEqual(setup.main(argv), 0)
        self.assertIn('預覽', out.getvalue()); self.assertIn('將移除', out.getvalue()); self.assertIn('保留', out.getvalue())
        self.assertTrue((self.prefix / 'current').is_symlink())
        out = io.StringIO()
        with patch('sys.stdout', out):
            self.assertEqual(setup.main([*argv, '--yes', '--json']), 0)
        self.assertEqual(json.loads(out.getvalue())['status'], 'uninstalled')

    def test_shell_removal_covers_bash_files_and_ignores_unsafe_files_of_the_other_shell(self):
        self.install('codex')
        block = macos_path.UserPath(self.bin, user_home=self.home, environ={'PATH': '/usr/bin:/bin'}, login_shell='/bin/bash').block()
        (self.home / '.bashrc').write_bytes(b'alias ll=ls\n' + block)
        (self.home / 'dotfiles').mkdir(); (self.home / 'dotfiles/profile').write_text('x')
        (self.home / '.profile').symlink_to(self.home / 'dotfiles/profile')
        result = self.uninstall('--yes')
        self.assertEqual(result['status'], 'uninstalled', result)
        self.assertEqual((self.home / '.bashrc').read_bytes(), b'alias ll=ls\n')
        self.assertTrue((self.home / '.profile').is_symlink())


if __name__ == '__main__':
    unittest.main()
