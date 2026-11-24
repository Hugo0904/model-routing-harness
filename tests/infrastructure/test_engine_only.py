"""`./setup --engine-only`: hosts served by the static marketplace plugin through a hook entry file.

Same isolated roots and native-command fixtures as the install and uninstall tests. The hook entries live under
the fixture home, so nothing here reaches the real HOME, Keychain, shells or host configuration.
"""
import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

import mrh_setup as setup
from mrh.infrastructure import hook_entry, settings_v2
from mrh.presentation import setup_cli
import tests.infrastructure.test_setup as base
import tests.infrastructure.test_uninstall as removal

ADAPTER = setup.ROOT / 'plugins/mrh/scripts/mrh-hook'


class EngineOnlyTests(unittest.TestCase):
    args = base.SetupTests.args
    fake_build = base.SetupTests.fake_build
    run_setup = base.SetupTests.run_setup
    state = base.SetupTests.state
    profile = base.SetupTests.profile
    native_change = base.SetupTests.native_change
    disk = base.SetupTests.disk
    setUp = removal.UninstallTests.setUp
    uninstall_args = removal.UninstallTests.uninstall_args
    uninstall = removal.UninstallTests.uninstall
    codex_native = removal.UninstallTests.codex_native
    ids = removal.UninstallTests.ids

    def install(self, *hosts, extra=()):
        selected = []
        for host in hosts:
            selected += ['--host', host]
        args = self.args('--claude-settings', str(self.claude_settings), '--claude-cli', str(self.claude), *selected, *extra)
        args.host = list(hosts)
        return self.run_setup(args)

    def entry(self, host):
        return self.home / '.config/model-routing-harness/hook-entry' / host

    def through_adapter(self, host, event):
        return subprocess.run(['/bin/sh', str(ADAPTER), host], input=json.dumps(event), capture_output=True, text=True,
                              timeout=20, env={'HOME': str(self.home), 'PATH': '/usr/bin:/bin'})

    def test_fresh_install_writes_entries_registers_nothing_natively_and_the_adapter_reaches_the_launcher(self):
        original = removal.normalized({'custom': 1, 'hooks': {'PreToolUse': [removal.OTHER_HOOK]}})
        self.claude_settings.write_bytes(original)
        planned = self.install('codex', 'claude', extra=['--engine-only', '--dry-run'])
        self.assertEqual((planned['registration'], planned['legacy_registration'], planned['writes']), ('hook_entry', [], False))
        self.assertEqual(planned['hook_entry'], {h: str(self.entry(h)) for h in ('codex', 'claude')})
        self.assertFalse(self.entry('codex').exists())
        result = self.install('codex', 'claude', extra=['--engine-only'])
        self.assertEqual(result['status'], 'installed', result)
        self.assertEqual(self.codex_native()['mutations'], 0)
        self.assertEqual(self.claude_settings.read_bytes(), original)
        state = self.state()
        for host in ('codex', 'claude'):
            self.assertEqual(state['hosts'][host]['registration'], 'entry')
            self.assertEqual(self.entry(host).read_bytes(), hook_entry.content(state['hosts'][host]['artifact']))
            self.assertEqual((result['hosts'][host]['registration'], result['hosts'][host]['configured']), ('hook_entry', True))
        self.assertIn('/hooks', ' '.join(result['next_steps']))
        generation = self.prefix / 'setup-state/generations' / state['current']
        self.assertEqual({p.name for p in (generation / 'installer').iterdir()}, set(setup.INSTALLER_FILES))
        # The static adapter from the plugin folder finds the entry and runs the generation's own launcher.
        done = self.through_adapter('claude', {'hook_event_name': 'Stop'})
        self.assertEqual((done.returncode, done.stdout.strip()), (0, '{}'), done.stderr)
        self.entry('claude').write_text(hook_entry.FORMAT + '\n/nonexistent/python\n/nonexistent/launcher.py\n')
        self.assertIn('hook entry is unusable', json.loads(self.through_adapter('claude', {}).stdout)['systemMessage'])

    def test_migration_removes_the_native_registration_first_and_resumes_after_a_failure(self):
        original = removal.normalized({'custom': 1, 'hooks': {'PreToolUse': [removal.OTHER_HOOK]}})
        self.claude_settings.write_bytes(original)
        self.install('codex', 'claude')
        self.assertTrue(self.codex_native()['installed'])
        before = self.disk()
        planned = self.install('codex', 'claude', extra=['--engine-only', '--dry-run'])
        self.assertEqual([row['host'] for row in planned['legacy_registration']], ['codex', 'claude'])
        self.assertEqual(self.disk(), before)
        # The Codex removal fails half way: no entry may exist yet, or the hook could run through both registrations.
        self.native_change(fail_after='plugin-remove')
        with self.assertRaises(setup.SetupError):
            self.install('codex', 'claude', extra=['--engine-only'])
        self.assertFalse(self.entry('codex').exists())
        result = self.install('codex', 'claude', extra=['--engine-only'])
        self.assertEqual(result['status'], 'installed', result)
        self.assertEqual((self.codex_native()['root'], self.codex_native()['installed']), (None, False))
        self.assertEqual(self.claude_settings.read_bytes(), original)
        for host in ('codex', 'claude'):
            self.assertEqual(self.entry(host).read_bytes(), hook_entry.content(self.state()['hosts'][host]['artifact']))
            self.assertTrue(result['hosts'][host]['configured'])

    def test_a_host_on_the_plugin_refuses_native_setup(self):
        self.install('codex', extra=['--engine-only'])
        before = self.disk()
        with self.assertRaisesRegex(setup.SetupError, 'registration_conflict'):
            self.install('codex')
        self.assertEqual(self.disk(), before)
        self.assertEqual(self.codex_native()['mutations'], 0)

    def test_rollback_to_a_native_generation_restores_it_and_drops_the_entry(self):
        self.install('codex')
        native = self.state()['hosts']['codex']
        self.revision = 'two'
        self.install('codex', extra=['--engine-only'])
        self.assertTrue(self.entry('codex').is_file())
        result = self.install('codex', extra=['--rollback'])
        self.assertEqual(result['operation'], 'rollback', result)
        self.assertEqual(self.state()['hosts']['codex'], native)
        self.assertEqual((self.codex_native()['root'], self.codex_native()['installed']), (native['artifact'], True))
        self.assertFalse(self.entry('codex').exists())

    def test_codex_packets_are_refused_fresh_and_on_migration(self):
        with self.assertRaisesRegex(setup.SetupError, 'engine_only_codex_packets_unsupported'):
            self.install('codex', extra=['--engine-only', '--codex-packets'])
        self.assertFalse(self.prefix.exists())
        self.install('codex', extra=['--codex-packets'])
        before = self.disk()
        with self.assertRaisesRegex(setup.SetupError, 'engine_only_codex_packets_unsupported'):
            self.install('codex', extra=['--engine-only'])
        self.assertEqual(self.disk(), before)

    def test_uninstall_removes_the_entries_and_leaves_the_host_plugin_to_the_host(self):
        self.install('codex', 'claude', extra=['--engine-only'])
        result = self.uninstall('--yes')
        self.assertEqual(result['status'], 'uninstalled', result)
        self.assertEqual(self.ids(result['removed'])[:2], ['hook_entry', 'hook_entry'])
        self.assertFalse(self.entry('codex').parent.exists())
        self.assertFalse(self.prefix.exists())
        self.assertEqual(self.codex_native()['mutations'], 0)
        self.assertIn('marketplace_plugin', self.ids(result['keep']))

    def test_the_installed_command_enables_and_checks_without_a_source_or_a_build(self):
        self.install('codex', extra=['--engine-only'])
        common = ['--prefix', str(self.prefix), '--config-root', str(self.config), '--bin-dir', str(self.bin), '--codex-cli', str(self.cli)]
        def forbidden(*args, **kwargs):
            raise AssertionError('the installed command must not build or fingerprint a source')
        with patch('mrh_setup.source_fingerprint', forbidden), patch('mrh_setup.bundle.build', forbidden), \
                patch('builtins.print') as printed:
            self.assertEqual(setup.main([*common, '--enable', '--workspace', str(self.root), '--json'], installed=True), 0)
            report = json.loads(printed.call_args.args[0])
            self.assertEqual(setup.main([*common, '--dev', '--json'], installed=True), 2)
            self.assertIn('installed_setup_does_not_build', printed.call_args.args[0])
        self.assertEqual((report['status'], report['enabled'], report['hosts']['codex']['configured']), ('installed', True, True))
        self.assertTrue(settings_v2.read(self.profile())['enabled'])
        # Through the real installed entry point: the generation's own installer copy answers `mrh setup`.
        done = subprocess.run([str(self.bin / 'mrh'), 'setup', '--check', '--json', *common[2:]], capture_output=True, text=True,
                              timeout=60, env={**os.environ, 'TYPESAFE_API_KEY': 'fixture-not-a-key'})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout)['hosts']['codex']['registration'], 'hook_entry')


class UpdateCommandTests(unittest.TestCase):
    def test_only_semantic_release_tags_count_and_the_newest_wins(self):
        listing = '\n'.join('0' * 40 + '\trefs/tags/' + tag for tag in ('v0.9.0', 'v0.10.1', 'v0.10.0', 'nightly', 'v1', 'v0.10.1-rc1')) + '\n'
        run = lambda *a, **k: subprocess.CompletedProcess(a, 0, listing, '')
        self.assertEqual(setup_cli.release_tags('fixture', run), ['v0.9.0', 'v0.10.0', 'v0.10.1'])
        with self.assertRaisesRegex(setup_cli.SetupCommandError, 'release_list_unavailable'):
            setup_cli.release_tags('fixture', lambda *a, **k: subprocess.CompletedProcess(a, 128, '', 'fatal'))

    def test_recorded_arguments_reproduce_the_registration_and_refuse_a_development_install(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve() / 'prefix/setup-state/generations' / ('a' * 24)
            root.mkdir(parents=True)
            (root.parents[1] / 'state.json').write_text(json.dumps({'hosts': {'codex': {'registration': 'entry'}, 'claude': {'registration': 'entry'}}}))
            (root / 'generation.json').write_text('{}')
            self.assertEqual(setup_cli.recorded_arguments(root), ['--prefix', str(root.parents[2]), '--host', 'codex', '--host', 'claude', '--engine-only'])
            (root.parents[1] / 'state.json').write_text(json.dumps({'hosts': {'codex': {'packets': True}}}))
            self.assertEqual(setup_cli.recorded_arguments(root)[2:], ['--host', 'codex', '--codex-packets'])
            (root / 'generation.json').write_text(json.dumps({'dev_source': '/somewhere'}))
            with self.assertRaisesRegex(setup_cli.SetupCommandError, 'development_install'):
                setup_cli.recorded_arguments(root)


if __name__ == '__main__':
    unittest.main()
