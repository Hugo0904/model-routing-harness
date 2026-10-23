"""Native filesystem lifecycle evidence; host API effects use bounded fakes."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import mrh_windows_setup as setup
from mrh.adapters.catalogs.catalog import Catalog, CatalogError, Model
from mrh.adapters.hosts.claude_windows_install import ClaudeWindowsInstaller
from mrh.infrastructure import owned, settings_v2, claude_hook, plugin
import mrh_build
from tests.windows.test_claude_native import NativeFixture
if os.name == 'nt':
    from mrh.adapters.platforms.windows_path import UserPath, PathValue


class MemoryPath:
    def __init__(self):
        self.values = {'user': PathValue(), 'machine': PathValue()}
        self.writes = 0

    def read(self, scope):
        return self.values[scope]

    def write(self, expected, replacement):
        if self.values['user'] != expected: raise ValueError('user_path_concurrent_change')
        self.values['user'] = replacement
        self.writes += 1


class FakeCodex:
    def __init__(self):
        self.root = None
        self.installed = False
        self.enabled = True
        self.mutations = 0
        self.fail_after_registration = False
        self.race = None

    def observe(self):
        return {"root": self.root, "installed": self.installed, "enabled": self.enabled}

    def preflight(self, settings, packets=False):
        if self.root:
            info = plugin.show(Path(self.root))["artifact"]
            if info["settings_path"] != str(settings):
                raise setup.SetupError("codex_settings_conflict")
        return self.observe()

    def install(self, artifact, before, progress):
        if self.root not in (None, before["root"], str(artifact)):
            raise setup.SetupError("codex_native_concurrent_change")
        if self.root != str(artifact) or not self.installed:
            progress("add_plugin_intent")
            self.root, self.installed = str(artifact), True
            self.mutations += 1
            if self.race:
                self.race()
            if self.fail_after_registration:
                self.fail_after_registration = False
                raise setup.SetupError("lost_ack")
            progress("add_plugin_done")
        return self.observe()

    def trust(self, workspace):
        return "unverified"


@unittest.skipUnless(os.name == "nt", "requires native Windows filesystem/ACLs")
class WindowsSetupTests(unittest.TestCase):
    def setUp(self):
        # Lifecycle fixtures must not discover or launch the machine's real CLI.
        self.catalog = self.enterContext(patch(
            "mrh.adapters.catalogs.catalog.public_models",
            side_effect=CatalogError("host_unavailable")))
        # Use the canonical private temporary root owned by tests.__init__,
        # independently of checkout depth; preserve spaces and native ACLs.
        self.temporary = tempfile.TemporaryDirectory(prefix="s ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        # This newly created fixture belongs to the current token. Host Python
        # and checkout ACLs are deliberately not changed to make a test pass.
        setup.native().protect(self.root)
        self.runtime = self.root / "trusted fixture Python"
        setup.mkdir(self.runtime)
        for source in [Path(sys.executable), *Path(sys.base_prefix).glob("*.dll")]:
            shutil.copyfile(source, self.runtime / source.name)
        shutil.copyfile(Path(sys.base_prefix) / "LICENSE.txt", self.runtime / "LICENSE.txt")
        (self.runtime / f"python{sys.version_info.major}{sys.version_info.minor}._pth").write_text(str(Path(sys.base_prefix) / "Lib") + "\n"
            + str(Path(sys.base_prefix) / "DLLs") + "\n", encoding="utf-8")
        self.python = {"executable": str(self.runtime / Path(sys.executable).name),
            "sha256": setup.digest((self.runtime / Path(sys.executable).name).read_bytes()),
            "version": '.'.join(map(str,sys.version_info[:3])), "base_prefix": str(self.runtime), "architecture": "x64", "platform": "win32",
            "license_sha256": setup.digest((self.runtime / "LICENSE.txt").read_bytes())}
        self.source = self.root / "source fixture"
        setup.mkdir(self.source)
        shutil.copyfile(setup.ROOT / "LICENSE", self.source / "LICENSE")
        self.enterContext(patch('mrh_windows_setup.locations.default_runtime_root',return_value=self.root/'managed runtime'))
        self.enterContext(patch.dict(os.environ,MRH_RUNTIME_ROOT=str(self.root/'managed runtime')))
        self.prefix = self.root / "app space"
        self.config = self.root / "persistent data with spaces"
        self.codex = FakeCodex()
        self.revision = "one"
        self.path_store = MemoryPath()
        self.path_manager = UserPath(self.prefix/'bin', store=self.path_store,
            environ={'PATH':'','PATHEXT':'.COM;.EXE;.BAT;.CMD'}, cwd=self.root, notify=lambda:True)

    def args(self, *extra):
        return setup.parser().parse_args(["--prefix", str(self.prefix), "--config-root", str(self.config),
                                         "--host", "codex", *extra])

    def run_setup(self, args=None, adapters=None, build=setup.build_generation):
        args=args or self.args()
        source = {"head": "a" * 40, "fingerprint": hashlib.sha256((self.revision+str(args.dev)
                  +str(args.codex_packets)+str(setup.locations.default_runtime_root())).encode()).hexdigest()}
        if args.dev and not (self.source/'src').exists():
            shutil.copytree(setup.ROOT/'src',self.source/'src')
            shutil.copy2(setup.ROOT/'pyproject.toml',self.source/'pyproject.toml')
        backend_root=self.source if args.dev else mrh_build.ROOT
        with patch.object(setup, "source_identity", return_value=source), patch.object(setup, "python_metadata", return_value=self.python), patch.object(setup, "ROOT", self.source), patch.object(mrh_build,'ROOT',backend_root):
            return setup.install(args or self.args(), adapters=adapters or {"codex": self.codex}, build=build,
                                 path_manager=self.path_manager)

    def state(self):
        return setup.document(self.prefix / "setup-state/state.json")

    def profile(self):
        return self.config / "profile/settings.json"

    def disk(self):
        return {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}

    def claude(self):
        adapter = setup.ClaudeInstaller.__new__(setup.ClaudeInstaller)
        adapter.path = self.root / "Claude settings with spaces/settings.json"
        adapter.cli = {"executable": "fixture", "version": setup.CLAUDE_VERSIONS[0],
                       "catalog": "isolated_initialize", "account_availability": "not_probed"}
        return adapter

    def native_claude(self):
        executable = self.root / 'protected Claude fixture.exe'
        executable.write_bytes(b'isolated fixture, never launched')
        native = NativeFixture(self.root)
        return ClaudeWindowsInstaller(executable, run=native.run), native

    def claude_profile(self):
        return self.config / 'claude-profile/settings.json'

    def configure_policy(self, path, host, **changes):
        setup.initialize(self.config, 'windows-config')
        setup.mkdir(path.parent.parent)
        settings_v2.init(path)
        settings_v2.update(path, policy={'tiers': {tier: {host: [{'model': host + '-model', 'effort': 'high'}]}
                                                  for tier in ('Light', 'Small', 'Mid')}}, **changes)

    def available_catalogs(self):
        self.catalog.side_effect = lambda host: Catalog('fixture-' + host, host, 'public', 'fixture',
            'isolated_initialize', 1.0, (Model(host + '-model', host, ('high',)),))

    def bootstrap_environment(self, native=False):
        code = ("import json,os,runpy,sys;from pathlib import Path;target=sys.argv[1];"
                "sys.argv=sys.argv[1:];runpy.run_path=lambda *a,**k:print(json.dumps({'root':os.environ.get('MRH_RUNTIME_ROOT') or os.environ.get('MRH_PROJECT_ROOT')}));"
                "exec(compile(Path(target).read_bytes(),target,'exec'),{'__file__':target,'__name__':'__main__'})")
        return subprocess.run([self.python['executable'],'-I','-B','-X','utf8','-c',code,
            str(self.prefix/'bootstrap.py'),*(['--native-hook','codex'] if native else [])],cwd=self.root,
            env={**os.environ,'MRH_PROJECT_ROOT':str(self.root/'untrusted external override')},
            capture_output=True,encoding='utf-8',timeout=15)

    def reseal_metadata(self, identifier, metadata):
        generation=self.prefix/'setup-state/generations'/identifier
        setup.write(generation/'generation.json',setup.encoded(metadata))
        manifest=setup.document(generation/'manifest.json')
        manifest.update(setup.file_manifest(generation))
        setup.write(generation/'manifest.json',setup.encoded(manifest))
        state=self.state()
        state['generations'][identifier]=setup.digest(setup.regular(generation/'manifest.json'))
        setup.write(self.prefix/'setup-state/state.json',setup.encoded(state))

    def test_normal_runtime_is_bound_without_source_dependency_or_environment_override(self):
        result=self.run_setup()
        generation=self.prefix/'setup-state/generations'/self.state()['current']
        self.assertNotIn('project_root',setup.document(generation/'generation.json'))
        binding=setup.document(generation/'hosts/codex/plugins/model-routing-harness/binding.json')
        self.assertNotIn('project_root',binding)
        self.assertEqual(binding['runtime_root'],str(self.root/'managed runtime'))
        self.assertEqual(result['project_root'],{'status':'not_required','ready':True})
        for native in (False,True):
            run=self.bootstrap_environment(native)
            self.assertEqual(run.returncode,0,run.stderr)
            self.assertEqual(json.loads(run.stdout),{'root':str(self.root/'managed runtime')})

    def test_normal_source_identity_ignores_clone_path_but_dev_binds_it(self):
        other=self.root/'another clone';setup.mkdir(other)
        for root in (self.source,other):
            for name in ('mrh_windows_setup.py','mrh_setup.py','setup.ps1','mrh_build.py','mrh_bundle.py','pyproject.toml','LICENSE'):
                (root/name).write_bytes(b'identical fixture content')
        def identity(root, head='a'*40,dev=False):
            with patch.object(setup,'ROOT',root), patch.object(setup.subprocess,'run',return_value=SimpleNamespace(stdout=head)):
                return setup.source_identity(['codex'],False,self.profile(),self.python,dev)
        first,second=identity(self.source),identity(other)
        self.assertNotIn('project_root',first)
        self.assertNotIn('project_root',second)
        self.assertEqual(first['fingerprint'],second['fingerprint'])
        self.assertNotEqual(identity(self.source,dev=True)['fingerprint'],identity(other,dev=True)['fingerprint'])
        (self.source/'README.md').write_text('Documentation-only change',encoding='utf-8')
        docs_only=identity(self.source,'b'*40)
        self.assertEqual(docs_only['head'],'b'*40)
        self.assertEqual(first['fingerprint'],docs_only['fingerprint'])
        (self.source/'mrh_windows_setup.py').write_bytes(b'changed program content')
        self.assertNotEqual(docs_only['fingerprint'],identity(self.source,'b'*40)['fingerprint'])

    def test_native_hook_uses_selected_host_generation_and_verifies_its_metadata(self):
        self.run_setup();first=self.state()
        self.revision='two'
        with patch('mrh_windows_setup.locations.default_runtime_root',return_value=self.root/'second runtime'):
            self.run_setup()
        state=self.state();state['hosts']['codex']=first['hosts']['codex']
        setup.write(self.prefix/'setup-state/state.json',setup.encoded(state))
        run=self.bootstrap_environment()
        self.assertEqual(json.loads(run.stdout),{'root':str(self.root/'second runtime')})
        old_meta=setup.document(self.prefix/'setup-state/generations'/first['current']/'generation.json')
        run=self.bootstrap_environment(True)
        self.assertEqual(run.returncode,0,run.stderr)
        self.assertEqual(json.loads(run.stdout),{'root':old_meta['runtime_root']})
        target=self.prefix/'setup-state/generations'/first['current']/'generation.json'
        target.write_bytes(target.read_bytes()+b'\n')
        run=self.bootstrap_environment(True)
        self.assertNotIn('root',json.loads(run.stdout))
        self.assertIn('integrity check failed',run.stdout)

    def test_legacy_generation_without_project_root_still_rolls_back(self):
        self.run_setup();first=self.state()['current']
        metadata=setup.document(self.prefix/'setup-state/generations'/first/'generation.json')
        metadata.pop('runtime_root');metadata['source'].pop('project_root',None)
        self.reseal_metadata(first,metadata)
        self.revision='two';self.run_setup()
        profile=self.profile().read_bytes()
        result=self.run_setup(self.args('--rollback'))
        self.assertEqual(result['project_root'],{'status':'legacy_unbound','ready':True})
        self.assertEqual(self.profile().read_bytes(),profile)
        for native in (False,True):
            run=self.bootstrap_environment(native)
            self.assertEqual(run.returncode,0,run.stderr)
            self.assertEqual(json.loads(run.stdout),{'root':None})

    def test_missing_bound_root_stops_launch_without_system_tmp_fallback(self):
        self.run_setup()
        identifier=self.state()['current']
        metadata=setup.document(self.prefix/'setup-state/generations'/identifier/'generation.json')
        metadata.pop('runtime_root');metadata['project_root']=str(self.source)
        self.reseal_metadata(identifier,metadata)
        self.assertTrue(self.source.is_relative_to(self.root))
        (self.source/'LICENSE').unlink();self.source.rmdir()
        run=self.bootstrap_environment()
        self.assertEqual(run.returncode,2)
        self.assertIn('bound runtime or development source is not ready',run.stderr)
        self.assertNotIn('root',run.stdout)
        run=self.bootstrap_environment(True)
        self.assertEqual(run.returncode,0)
        self.assertIn('bound runtime or development source is not ready',run.stdout)
        self.assertNotIn('root',json.loads(run.stdout))
        result=self.run_setup(self.args('--check'))
        self.assertFalse(result['project_root']['ready'])
        self.assertIn('project_root',result['pending'])

    def test_unsafe_source_root_is_rejected_before_install_and_never_repaired(self):
        with patch.object(setup.native(),'assert_safe',side_effect=ValueError('windows_unsafe_acl')):
            with self.assertRaisesRegex(setup.SetupError,'project_root_not_ready:windows_unsafe_acl'):
                self.run_setup()
        self.assertFalse(self.profile().exists())
        self.assertEqual((self.path_store.writes,self.codex.mutations),(0,0))

    def test_fresh_install_has_license_provenance_native_entrypoint_and_disabled_routing(self):
        result = self.run_setup()
        self.assertTrue(result["installed"])
        self.assertEqual(result["generation_integrity"], "verified")
        self.assertEqual(result["commit"], "a" * 40)
        self.assertEqual(result["routing"], "disabled")
        self.assertFalse(result["enabled"])
        self.assertFalse(result["export_permitted"])
        self.assertFalse(result["provider_probe_performed"])
        self.assertTrue(result['command_path']['future_terminal_ready'])
        self.assertFalse(result['command_path']['current_process_ready'])
        self.assertEqual(result["macos"], "not_verified")
        state = self.state()
        generation = self.prefix / "setup-state/generations" / state["current"]
        meta = setup.verify_generation(generation, state["generations"][state["current"]])
        self.assertEqual(meta["python"]["executable"], self.python["executable"])
        self.assertEqual((generation / "licenses/LICENSE").read_bytes(), (setup.ROOT / "LICENSE").read_bytes())
        self.assertEqual((generation / "licenses/Python-LICENSE.txt").read_bytes(),
                         (Path(sys.base_prefix) / "LICENSE.txt").read_bytes())
        self.assertFalse(any(p.is_symlink() for p in self.root.rglob("*")))
        self.assertFalse((generation / "hosts/codex/plugins/model-routing-harness/skills").exists())
        artifact = generation / "hosts/codex/plugins/model-routing-harness"
        self.assertFalse((artifact / "plugin.json").exists())
        self.assertEqual(setup.document(artifact / ".codex-plugin/plugin.json")["hooks"], "./hooks/hooks.json")
        run = subprocess.run(["cmd.exe", "/d", "/c", str(self.prefix / "bin/mrh.cmd"), "--help"],
                             capture_output=True, encoding='utf-8', timeout=15)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("usage", run.stdout.lower())

    def test_repeat_is_idempotent_and_check_dry_run_are_read_only(self):
        before = self.disk()
        self.assertEqual(self.run_setup(self.args("--check"))["status"], "pending")
        self.assertEqual(self.run_setup(self.args("--dry-run"))["status"], "planned")
        self.assertEqual(self.path_store.writes, 0)
        self.assertEqual(self.disk(), before)
        self.run_setup()
        before, mutations = self.disk(), self.codex.mutations
        result = self.run_setup()
        self.assertEqual(result["operation"], "unchanged")
        self.assertTrue(result["idempotent"])
        self.assertEqual(self.codex.mutations, mutations)
        self.assertEqual(self.disk(), before)
        self.run_setup(self.args("--check"))
        self.assertEqual(self.disk(), before)

    def test_same_generation_repairs_missing_user_path_without_reregistering(self):
        self.run_setup()
        state, profile, mutations = self.state(), self.profile().read_bytes(), self.codex.mutations
        self.path_store.values['user'] = PathValue()
        result = self.run_setup(self.args('--check'))
        self.assertIn('command_path', result['pending'])
        self.assertFalse(self.path_store.read('user').exists)
        result = self.run_setup()
        self.assertEqual(result['operation'], 'unchanged')
        self.assertEqual(result['command_path']['change']['action'], 'added')
        self.assertEqual((self.state(), self.profile().read_bytes(), self.codex.mutations), (state, profile, mutations))

    def test_foreign_path_command_stops_before_install_or_registration(self):
        other = self.root/'foreign bin';setup.mkdir(other)
        (other/'mrh.cmd').write_text('@echo foreign', encoding='ascii')
        self.path_store.values['user'] = PathValue(str(other), exists=True)
        with self.assertRaisesRegex(ValueError, 'mrh_command_conflict'):
            self.run_setup()
        self.assertFalse(self.profile().exists())
        self.assertFalse(self.prefix.exists())
        self.assertEqual((self.path_store.writes,self.codex.mutations), (0,0))

    def test_path_write_failure_after_state_commit_recovers_without_duplicate_registration(self):
        with patch.object(self.path_store, 'write', side_effect=OSError('registry_busy')):
            with self.assertRaisesRegex(OSError, 'registry_busy'):self.run_setup()
        state, mutations = self.state(), self.codex.mutations
        self.assertEqual(setup.document(self.prefix/'setup-state/pending.json')['phase'], 'committing')
        result = self.run_setup()
        self.assertEqual(result['operation'], 'recovered')
        self.assertEqual(self.codex.mutations, mutations)
        self.assertEqual(self.state(), state)
        self.assertTrue(result['command_path']['future_terminal_ready'])

    def test_stable_native_hook_entry_reads_owned_generation_and_rejects_tamper(self):
        self.run_setup()
        command=setup.native().codex_hook_command(self.python['executable'],self.prefix/'bootstrap.py')
        shell=Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
        event=json.dumps({'hook_event_name':'PreToolUse','tool_name':'spawn_agent','session_id':'s','turn_id':'t',
            'tool_use_id':'c','cwd':str(self.root),'tool_input':{'message':'synthetic no-op'}}).encode()
        def run():return subprocess.run([str(shell),'-NoProfile','-NonInteractive','-Command',command],input=event,capture_output=True,timeout=8)
        result=run();self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(json.loads(result.stdout),{})
        target=self.prefix/'setup-state/generations'/self.state()['current']/'hosts/codex/plugins/model-routing-harness/launcher.py'
        target.write_bytes(b'tampered private fixture')
        result=run();reply=json.loads(result.stdout)
        self.assertIn('integrity check failed',reply['systemMessage'])
        self.assertNotIn('permissionDecision',result.stdout.decode())
        self.assertNotIn('tampered private fixture',result.stdout.decode())

    def test_update_and_rollback_keep_latest_settings_statistics_and_prior_generations(self):
        self.run_setup()
        first = self.state()["current"]
        settings_v2.update(self.profile(), retention_days=42)
        profile = self.profile().read_bytes()
        database = self.profile().parent / "advice.sqlite3"
        database.write_bytes(b"persisted facts before update")
        pointer = (self.config / "active-settings").read_bytes()
        self.revision = "two"
        self.run_setup()
        second = self.state()["current"]
        self.assertNotEqual(first, second)
        database.write_bytes(b"new persisted facts after update")
        self.run_setup(self.args("--rollback"))
        self.assertEqual(self.state()["current"], first)
        self.assertEqual(self.profile().read_bytes(), profile)
        self.assertEqual(database.read_bytes(), b"new persisted facts after update")
        self.assertEqual((self.config / "active-settings").read_bytes(), pointer)
        self.assertTrue((self.prefix / "setup-state/generations" / second).is_dir())

    def test_foreign_entrypoint_and_foreign_root_are_preserved(self):
        setup.mkdir(self.prefix / "bin")
        entry = self.prefix / "bin/mrh.cmd"
        entry.write_bytes(b"@echo user-owned entrypoint\r\n")
        with self.assertRaisesRegex(setup.SetupError, "bin_conflict"):
            self.run_setup()
        self.assertEqual(entry.read_bytes(), b"@echo user-owned entrypoint\r\n")
        self.assertFalse(self.profile().exists())
        self.assertEqual(self.codex.mutations, 0)

    def test_foreign_profile_rejected_before_native_registration(self):
        setup.mkdir(self.profile().parent)
        self.profile().write_text('{"user":"configuration"}')
        before = self.profile().read_bytes()
        with self.assertRaises(ValueError):
            self.run_setup()
        self.assertEqual(self.profile().read_bytes(), before)
        self.assertEqual(self.codex.mutations, 0)

    def test_dirty_generation_refuses_repeat_check_update_and_rollback(self):
        self.run_setup()
        first = self.state()["current"]
        self.revision = "two"
        self.run_setup()
        state = self.state()
        app = self.prefix / "setup-state/generations" / state["current"] / "app/mrh.pyz"
        app.write_bytes(b"changed locally")
        mutations = self.codex.mutations
        for args in (self.args(), self.args("--check"), self.args("--rollback")):
            with self.subTest(args=args):
                with self.assertRaisesRegex(setup.SetupError, "generation_integrity"):
                    self.run_setup(args)
        self.assertEqual(self.state()["current"], state["current"])
        self.assertEqual(self.codex.mutations, mutations)
        self.assertTrue((self.prefix / "setup-state/generations" / first).exists())

    def test_added_empty_directory_and_manifest_tamper_are_rejected(self):
        self.run_setup()
        state = self.state()
        generation = self.prefix / "setup-state/generations" / state["current"]
        setup.mkdir(generation / "foreign")
        with self.assertRaisesRegex(setup.SetupError, "generation_integrity"):
            self.run_setup(self.args("--check"))
        (generation / "foreign").rmdir()
        with (generation / "manifest.json").open("ab") as stream:
            stream.write(b" ")
        with self.assertRaisesRegex(setup.SetupError, "manifest_changed"):
            self.run_setup(self.args("--check"))

    def test_rollback_requires_compatible_reader_before_native_mutation(self):
        self.run_setup()
        first = self.state()["current"]
        self.revision = "two"
        self.run_setup()
        state = self.state()
        generation = self.prefix / "setup-state/generations" / first
        meta = setup.document(generation / "generation.json")
        meta["reader"] = {}
        setup.write(generation / "generation.json", setup.encoded(meta))
        manifest = setup.document(generation / "manifest.json")
        manifest.update(setup.file_manifest(generation))
        setup.write(generation / "manifest.json", setup.encoded(manifest))
        state["generations"][first] = setup.digest(setup.regular(generation / "manifest.json"))
        setup.write(self.prefix / "setup-state/state.json", setup.encoded(state))
        mutations = self.codex.mutations
        with self.assertRaisesRegex(setup.SetupError, "rollback_reader_incompatible"):
            self.run_setup(self.args("--rollback"))
        self.assertEqual(self.codex.mutations, mutations)

    def test_rollback_without_history_refuses_before_native_mutation(self):
        self.run_setup()
        before = (self.prefix/'setup-state/state.json').read_bytes()
        mutations = self.codex.mutations
        with self.assertRaisesRegex(setup.SetupError, 'rollback_history_missing'):
            self.run_setup(self.args('--rollback'))
        self.assertEqual((self.prefix/'setup-state/state.json').read_bytes(), before)
        self.assertEqual(self.codex.mutations, mutations)

    def test_lost_registration_ack_reruns_same_transaction_without_duplicate_registration(self):
        from mrh.adapters.hosts import codex_packets as packets
        self.run_setup()
        original_state = self.state()['current']
        settings_v2.update(self.profile(), enabled=True, task_export_permitted=True,
                           allowed_workspaces=[str(self.root)])
        database = self.profile().parent / 'advice.sqlite3'
        with closing(sqlite3.connect(database)) as connection, connection:
            connection.execute('CREATE TABLE preserved_stat(value TEXT)')
            connection.execute("INSERT INTO preserved_stat VALUES ('keep')")
        saved_profile, saved_database = self.profile().read_bytes(), database.read_bytes()
        self.revision = 'mode-and-runtime-change'
        args = self.args('--dev', '--codex-packets')
        self.codex.fail_after_registration = True
        with patch('mrh_windows_setup.locations.default_runtime_root', return_value=self.root/'new-runtime'):
            with self.assertRaisesRegex(setup.SetupError, 'lost_ack'):
                self.run_setup(args)
            pending = setup.document(self.prefix/'setup-state/pending.json')
            self.assertEqual(self.state()['current'], original_state)
            checked = self.run_setup(self.args('--check'))
            self.assertTrue(checked['installed'])
            self.assertTrue(checked['transaction_pending'])
            self.assertEqual(checked['status'], 'pending')
            self.assertIn('installation_recovery', checked['pending'])
            self.assertNotEqual(checked['routing'], 'ready')
            mutations = self.codex.mutations
            packet = packets.prepare(self.profile(), 'fixture after lost ACK', self.root)
            with self.assertRaisesRegex(ValueError, 'mode_change_packet_in_progress'):
                self.run_setup(args)
            packets.status(self.profile(), packet['packet_id'], finish=True)
            restored = self.run_setup(args)
            self.assertFalse(restored['transaction_pending'])
            self.assertEqual(restored['execution_mode'], 'development')
            self.assertEqual(self.state()['current'], pending['target'])
            self.assertEqual(self.state()['previous']['current'], original_state)
            self.assertEqual(self.codex.mutations, mutations)
        self.assertEqual(self.profile().read_bytes(), saved_profile)
        self.assertEqual(database.read_bytes(), saved_database)

    def test_pending_transaction_with_different_arguments_refuses(self):
        self.codex.fail_after_registration = True
        with self.assertRaisesRegex(setup.SetupError, "lost_ack"):
            self.run_setup()
        self.revision = "different source"
        before = self.disk()
        with self.assertRaisesRegex(setup.SetupError, "pending_operation_conflict"):
            self.run_setup()
        self.assertEqual(self.disk(), before)

    def test_foreign_concurrent_entrypoint_is_preserved(self):
        def race():
            setup.mkdir(self.prefix / "bin")
            (self.prefix / "bin/mrh.cmd").write_bytes(b"foreign racing writer")
        self.codex.race = race
        with self.assertRaisesRegex(setup.SetupError, "concurrent_change"):
            self.run_setup()
        self.assertEqual((self.prefix / "bin/mrh.cmd").read_bytes(), b"foreign racing writer")
        self.assertFalse((self.prefix / "setup-state/state.json").exists())

    def test_claude_merge_backups_and_rollback_keep_foreign_entries(self):
        claude = self.claude()
        setup.mkdir(claude.path.parent)
        before = b'{"theme":"dark","hooks":{"PreToolUse":[{"matcher":"Other","hooks":[{"command":"other-hook"}]}]}}\n'
        claude.path.write_bytes(before)
        adapters = {"codex": self.codex, "claude": claude}
        args = self.args("--host", "claude", "--claude-settings", str(claude.path))
        result = self.run_setup(args, adapters)
        self.assertFalse(result["hosts"]["claude"]["catalog"]["verified"])
        self.assertEqual(result["hosts"]["claude"]["catalog"]["reason"], "catalog_unavailable")
        after = json.loads(claude.path.read_text())
        self.assertEqual(after["theme"], "dark")
        self.assertEqual(after["hooks"]["PreToolUse"][0]["hooks"][0]["command"], "other-hook")
        self.assertEqual(len(after["hooks"]["PreToolUse"]), 2)
        self.assertEqual(next(claude.path.parent.glob("*.mrh-bak-*")).read_bytes(), before)
        first = self.state()["current"]
        self.run_setup(args, adapters)
        self.assertEqual(len(list(claude.path.parent.glob("*.mrh-bak-*"))), 1)
        self.revision = "two"
        self.run_setup(args, adapters)
        self.run_setup(self.args("--host", "claude", "--rollback"), adapters)
        self.assertEqual(self.state()["current"], first)
        after = json.loads(claude.path.read_text())
        self.assertEqual(after["hooks"]["PreToolUse"][0]["hooks"][0]["command"], "other-hook")

    def test_unowned_claude_hook_is_rejected_without_overwrite(self):
        claude = self.claude()
        setup.mkdir(claude.path.parent)
        text = claude_hook.plan("{}", '"C:\\foreign\\model-routing-harness\\launcher.py" claude')
        claude.path.write_text(text)
        with self.assertRaisesRegex(setup.SetupError, "claude_hook_unowned"):
            self.run_setup(self.args("--host", "claude"), {"codex": self.codex, "claude": claude})
        self.assertEqual(claude.path.read_text(), text)
        self.assertEqual(self.codex.mutations, 0)

    def test_unscoped_enable_is_refused(self):
        for args, reason in ((self.args("--enable"), "explicit_workspace"),):
            with self.subTest(reason=reason):
                with self.assertRaisesRegex(setup.SetupError, reason):
                    self.run_setup(args)
        self.assertFalse(self.profile().exists())
        self.assertEqual(self.codex.mutations, 0)

    def test_dev_packet_mode_uses_editable_source_then_normal_survives_source_absence(self):
        # Build the real two modes with only bounded fake native registrations.
        self.run_setup(self.args('--dev','--codex-packets'))
        self.assertTrue(self.state()['hosts']['codex']['packets'])
        self.assertEqual(self.run_setup(self.args('--check'))['execution_mode'],'development')
        site_file=next(self.runtime.glob('python*._pth'))
        self.assertNotIn('import site',site_file.read_text())
        cli=self.source/'src/mrh/cli.py';hook=self.source/'src/mrh/application/advisory_runtime.py'
        cli.write_text('def main():\n    print("editable CLI changed")\n    return 0\n',encoding='utf-8')
        hook.write_text('def run(platform,settings,stdin,stdout,stderr,**kwargs):\n    stdout.write(\'{"systemMessage":"editable Hook changed"}\\n\')\n    return 0\n',encoding='utf-8')
        def invoke(*arguments,input=None):
            return subprocess.run([self.python['executable'],'-I','-B','-X','utf8',str(self.prefix/'bootstrap.py'),*arguments],
                input=input,capture_output=True,text=True,encoding='utf-8',timeout=15)
        result=invoke();self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout.strip(),'editable CLI changed')
        result=invoke('--native-hook','codex',input=json.dumps({'hook_event_name':'PreToolUse'}))
        self.assertEqual(json.loads(result.stdout),{'systemMessage':'editable Hook changed'})
        offline=self.source.with_name('source offline');self.source.rename(offline)
        self.assertNotEqual(invoke().returncode,0)
        offline.rename(self.source)
        self.revision='normal'
        self.run_setup(self.args('--codex-packets'))
        self.source.rename(offline)
        result=invoke('--help');self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('mrh',result.stdout)
        self.assertIn('--help',result.stdout)

    def test_outer_bootstrap_faults_deny_packets_without_denying_ordinary_events(self):
        claude,_=self.native_claude()
        self.run_setup(self.args('--dev','--codex-packets','--host','claude'),{'codex':self.codex,'claude':claude})
        generation=self.prefix/'setup-state/generations'/self.state()['current']
        runtimes=[generation/('hosts/'+host+'/plugins/model-routing-harness/runtime.pyz') for host in ('codex','claude')]
        manifest=generation/'manifest.json'
        originals={path:path.read_bytes() for path in [*runtimes,manifest]}
        offline=self.source.with_name('source offline')
        def invoke(event,host='codex'):
            return subprocess.run([self.python['executable'],'-I','-B','-X','utf8',str(self.prefix/'bootstrap.py'),'--native-hook',host],
                input=json.dumps(event),capture_output=True,text=True,timeout=10)
        for fault in ('source','runtime','manifest'):
            if fault=='source':self.source.rename(offline)
            elif fault=='runtime':
                for runtime in runtimes:runtime.write_bytes(b'corrupted fixture runtime')
            else:manifest.write_bytes(b'corrupted fixture manifest')
            try:
                for prefix in ('mrh_packet_','mrh_release_'):
                    event={'hook_event_name':'PreToolUse','tool_name':'spawn_agent','tool_input':{'task_name':prefix+'a'*32}}
                    result=invoke(event);self.assertEqual(result.returncode,0,result.stderr)
                    self.assertEqual(json.loads(result.stdout)['hookSpecificOutput']['permissionDecision'],'deny')
                for host,event in [('codex',{'hook_event_name':'PreToolUse','tool_name':'spawn_agent','tool_input':{'task_name':'ordinary'}}),
                                   ('codex',{**event,'hook_event_name':'PostToolUse'}),('claude',event)]:
                    result=invoke(event,host);self.assertEqual(result.returncode,0,result.stderr)
                    self.assertIn('systemMessage',json.loads(result.stdout));self.assertNotIn('permissionDecision',result.stdout)
                    self.assertIn('bound runtime' if fault=='source' else 'integrity check failed',result.stdout)
            finally:
                if fault=='source':offline.rename(self.source)
                else:
                    for path,data in originals.items():path.write_bytes(data)

    def test_runtime_change_checks_unselected_host_profile_and_root_lock(self):
        from mrh.adapters.hosts import codex_packets as packets
        claude,_=self.native_claude();adapters={'codex':self.codex,'claude':claude}
        self.run_setup(self.args('--host','claude'),adapters)
        profile=self.claude_profile()
        settings_v2.update(profile,enabled=True,task_export_permitted=True,allowed_workspaces=[str(self.root)])
        packet=packets.prepare(profile,'isolated unselected host packet',self.root)
        old_state=(self.prefix/'setup-state/state.json').read_bytes();old_profile=profile.read_bytes()
        self.revision='new runtime'
        changed=self.root/'second runtime'
        with patch('mrh_windows_setup.locations.default_runtime_root',return_value=changed):
            with self.assertRaisesRegex(ValueError,'mode_change_packet_in_progress'):
                self.run_setup(self.args(),adapters)
            self.assertEqual((self.prefix/'setup-state/state.json').read_bytes(),old_state)
            self.assertEqual(profile.read_bytes(),old_profile)
            directory=packets.root_for(profile)/packet['packet_id']
            row=packets.status(profile,packet['packet_id']);row['state']='completed'
            packets._write(directory/'receipt.json',row)
            result=self.run_setup(self.args(),adapters)
            self.assertEqual(result['runtime_root'],str(changed))

    def test_native_claude_readiness_uses_its_independent_profile_and_one_query_per_host(self):
        claude, _ = self.native_claude()
        adapters = {'codex': self.codex, 'claude': claude}
        self.configure_policy(self.profile(), 'codex', enabled=True, task_export_permitted=True,
                              allowed_workspaces=[str(self.root)], retention_days=42)
        self.available_catalogs()
        self.codex.trust = lambda workspace: 'trusted'
        with patch.object(setup.secrets, 'is_set', return_value=True):
            result = self.run_setup(self.args('--host', 'claude'), adapters)
        codex, native = result['hosts']['codex'], result['hosts']['claude']
        self.assertEqual(codex['routing'], 'ready')
        self.assertEqual(native['settings'], str(self.claude_profile()))
        self.assertFalse(native['enabled'])
        self.assertFalse(native['export_permitted'])
        self.assertFalse(native['workspace_ready'])
        self.assertFalse(native['policy_ready'])
        self.assertEqual(native['routing'], 'disabled')
        self.assertTrue(native['catalog']['verified'])
        self.assertFalse(result['policy_ready'])
        self.assertEqual(result['routing'], 'not_ready')
        self.assertCountEqual([call.args[0] for call in self.catalog.call_args_list], ['codex', 'claude'])
        self.assertEqual(settings_v2.read(self.profile())['retention_days'], 42)
        state = self.state()
        binding = setup.document(Path(state['hosts']['claude']['artifact']) / 'plugins/model-routing-harness/binding.json')
        self.assertEqual(binding['settings_path'], str(self.claude_profile()))

    def test_claude_only_enable_validates_and_updates_only_its_selected_profile(self):
        claude, native = self.native_claude()
        self.configure_policy(self.claude_profile(), 'claude', retention_days=99)
        setup.mkdir(self.profile().parent.parent)
        settings_v2.init(self.profile())
        settings_v2.update(self.profile(), classifier={'provider': 'codex_subscription', 'model': 'codex-model', 'timeout_seconds': 10})
        main_before = self.profile().read_bytes()
        database = self.claude_profile().parent / 'advice.sqlite3'
        database.write_bytes(b'existing Claude statistics')
        self.available_catalogs()
        args = self.args('--enable', '--workspace', str(self.root))
        args.host = ['claude']
        with patch.object(setup.secrets, 'is_set', return_value=True):
            result = self.run_setup(args, {'claude': claude})
        value = settings_v2.read(self.claude_profile())
        self.assertTrue(value['enabled'])
        self.assertTrue(value['task_export_permitted'])
        self.assertEqual(value['allowed_workspaces'], [str(self.root)])
        self.assertEqual(value['retention_days'], 99)
        self.assertEqual(self.profile().read_bytes(), main_before)
        self.assertEqual(database.read_bytes(), b'existing Claude statistics')
        self.assertEqual(result['routing'], 'ready')
        self.assertEqual(result['hosts']['claude']['routing'], 'ready')
        self.assertEqual(self.catalog.call_count, 1)
        self.catalog.assert_called_with('claude')
        self.assertEqual(native.mutations, ['marketplace-add', 'install'])
        self.assertEqual(self.codex.mutations, 0)

    def test_enable_refuses_claude_profile_even_when_main_codex_profile_is_ready(self):
        claude, native = self.native_claude()
        self.configure_policy(self.profile(), 'codex', enabled=True, task_export_permitted=True,
                              allowed_workspaces=[str(self.root)])
        self.available_catalogs()
        before = self.disk()
        with patch.object(setup.secrets, 'is_set', return_value=True):
            with self.assertRaisesRegex(setup.SetupError, 'configured_classifier_key:claude'):
                self.run_setup(self.args('--host', 'claude', '--enable', '--workspace', str(self.root)),
                               {'codex': self.codex, 'claude': claude})
        self.assertEqual(self.disk(), before)
        self.assertEqual((self.codex.mutations, native.mutations), (0, []))

    def test_claude_enable_refuses_missing_key_unavailable_catalog_and_invalid_options(self):
        claude, native = self.native_claude()
        self.configure_policy(self.claude_profile(), 'claude')
        args = self.args('--enable', '--workspace', str(self.root))
        args.host = ['claude']
        for failure in ('key', 'catalog', 'model', 'effort', 'fixed', 'tier', 'classifier'):
            with self.subTest(failure=failure):
                self.configure_policy(self.claude_profile(), 'claude')
                if failure in ('model', 'effort', 'fixed', 'tier'):
                    policy = settings_v2.read(self.claude_profile())['policy']
                    if failure == 'fixed':
                        policy.update(top_mode='Fixed', fixed={'claude': [{'model': 'unknown-model'}]})
                    elif failure == 'tier':
                        policy['tiers'].pop('Mid')
                    else:
                        policy['tiers']['Mid']['claude'][0][failure] = 'unsupported'
                    settings_v2.update(self.claude_profile(), policy=policy)
                if failure == 'classifier':
                    settings_v2.update(self.claude_profile(), classifier={'provider': 'claude_subscription', 'model': 'haiku', 'timeout_seconds': 10})
                self.available_catalogs()
                if failure == 'catalog':
                    self.catalog.side_effect = CatalogError('isolated_query_failed')
                before = self.disk()
                with patch.dict(os.environ, {'TYPESAFE_API_KEY': ''}), patch.object(setup.secrets, 'is_set', return_value=failure != 'key'):
                    reason = 'configured_classifier_key' if failure in ('key', 'classifier') else 'validated_model_policy'
                    with self.assertRaisesRegex(setup.SetupError, reason + ':claude'):
                        self.run_setup(args, {'claude': claude})
                self.assertEqual(self.disk(), before)
                self.assertEqual(native.mutations, [])

    def test_enable_both_native_hosts_updates_their_separate_profiles(self):
        claude, _ = self.native_claude()
        self.configure_policy(self.profile(), 'codex', retention_days=42)
        self.configure_policy(self.claude_profile(), 'claude', retention_days=99)
        self.available_catalogs()
        self.codex.trust = lambda workspace: 'trusted'
        with patch.object(setup.secrets, 'is_set', return_value=True):
            result = self.run_setup(self.args('--host', 'claude', '--enable', '--all-workspaces'),
                                    {'codex': self.codex, 'claude': claude})
        for path, host, retention in ((self.profile(), 'codex', 42), (self.claude_profile(), 'claude', 99)):
            value = settings_v2.read(path)
            self.assertTrue(value['enabled'])
            self.assertTrue(value['task_export_permitted'])
            self.assertEqual(value['allowed_workspaces'], ['*'])
            self.assertEqual(value['retention_days'], retention)
            self.assertEqual(result['hosts'][host]['routing'], 'ready')
        self.assertEqual(result['routing'], 'ready')
        self.assertCountEqual([call.args[0] for call in self.catalog.call_args_list], ['codex', 'claude'])

    def test_claude_catalog_metadata_does_not_establish_readiness(self):
        claude, _ = self.native_claude()
        self.configure_policy(self.claude_profile(), 'claude', enabled=True, task_export_permitted=True,
                              allowed_workspaces=[str(self.root)])
        args = self.args()
        args.host = ['claude']
        with patch.object(setup.secrets, 'is_set', return_value=True):
            result = self.run_setup(args, {'claude': claude})
        info = result['hosts']['claude']
        self.assertEqual(info['cli']['catalog'], 'isolated_initialize')
        self.assertFalse(info['catalog']['verified'])
        self.assertFalse(info['policy_ready'])
        self.assertEqual(info['routing'], 'not_ready')
        self.assertEqual(result['routing'], 'not_ready')
        self.assertEqual(self.catalog.call_count, 1)

    def test_claude_profile_update_and_rollback_preserve_settings_and_statistics(self):
        claude, _ = self.native_claude()
        adapters = {'codex': self.codex, 'claude': claude}
        args = self.args('--host', 'claude')
        self.run_setup(args, adapters)
        first = self.state()['current']
        self.configure_policy(self.claude_profile(), 'claude', retention_days=66)
        profile = self.claude_profile().read_bytes()
        database = self.claude_profile().parent / 'advice.sqlite3'
        database.write_bytes(b'Claude persistent history')
        self.revision = 'two'
        self.run_setup(args, adapters)
        self.run_setup(self.args('--host', 'claude', '--rollback'), adapters)
        self.assertEqual(self.state()['current'], first)
        self.assertEqual(self.claude_profile().read_bytes(), profile)
        self.assertEqual(database.read_bytes(), b'Claude persistent history')

    def test_claude_profile_changed_during_registration_is_not_enabled_or_overwritten(self):
        claude, _ = self.native_claude()
        self.configure_policy(self.profile(), 'codex')
        self.configure_policy(self.claude_profile(), 'claude')
        self.available_catalogs()
        self.codex.race = lambda: settings_v2.update(self.claude_profile(), retention_days=77)
        with patch.object(setup.secrets, 'is_set', return_value=True):
            with self.assertRaisesRegex(setup.SetupError, 'profile_concurrent_change'):
                self.run_setup(self.args('--host', 'claude', '--enable', '--workspace', str(self.root)),
                               {'codex': self.codex, 'claude': claude})
        value = settings_v2.read(self.claude_profile())
        self.assertEqual(value['retention_days'], 77)
        self.assertFalse(value['enabled'])
        self.assertFalse(settings_v2.read(self.profile())['enabled'])

    def test_profile_changed_during_preflight_is_refused_before_install(self):
        claude, native = self.native_claude()
        self.configure_policy(self.claude_profile(), 'claude')
        original = setup.profile_preflight
        def concurrent_preflight(path):
            value = original(path)
            if path == self.claude_profile():
                settings_v2.update(path, retention_days=77)
            return value
        args = self.args('--enable', '--workspace', str(self.root))
        args.host = ['claude']
        with patch.object(setup, 'profile_preflight', side_effect=concurrent_preflight):
            with self.assertRaisesRegex(setup.SetupError, 'profile_concurrent_change'):
                self.run_setup(args, {'claude': claude})
        self.assertFalse(self.prefix.exists())
        self.assertFalse(settings_v2.read(self.claude_profile())['enabled'])
        self.assertEqual(settings_v2.read(self.claude_profile())['retention_days'], 77)
        self.assertEqual(native.mutations, [])
        self.catalog.assert_not_called()

    def test_operator_can_persist_global_scope_without_enabling(self):
        self.run_setup(self.args('--all-workspaces'))
        self.assertEqual(settings_v2.read(self.profile())['allowed_workspaces'], ['*'])
        self.assertFalse(settings_v2.read(self.profile())['enabled'])

    def test_unsupported_architecture_check_is_rejected_before_writes(self):
        with patch.object(setup.platform, 'machine', return_value='ARM64'):
            with self.assertRaisesRegex(setup.SetupError, 'unsupported_platform'):
                self.run_setup(self.args('--check'))
        self.assertFalse(self.profile().exists())
        self.assertEqual(self.codex.mutations, 0)

    def test_explicit_native_python_dependency_metadata_uses_selected_copy(self):
        metadata = setup.python_metadata(self.python["executable"])
        self.assertEqual(metadata["executable"], self.python["executable"])
        self.assertEqual(metadata["sha256"], self.python["sha256"])
        self.assertEqual(metadata["base_prefix"], str(self.runtime))
        self.assertEqual(metadata["architecture"], "x64")

    def test_concurrent_state_writer_is_not_overwritten(self):
        target = self.prefix / "setup-state/state.json"
        self.codex.race = lambda: target.write_bytes(b"foreign concurrent state")
        with self.assertRaisesRegex(setup.SetupError, "concurrent_change:state.json"):
            self.run_setup()
        self.assertEqual(target.read_bytes(), b"foreign concurrent state")

    def test_interrupted_build_retains_stage_and_rerun_builds_fresh_owned_leaf(self):
        def interrupted(stage, *args):
            setup.initialize(stage, "windows-generation")
            setup.write(stage / "partial", b"interrupted build evidence", None)
            raise setup.SetupError("interrupted")
        with self.assertRaisesRegex(setup.SetupError, "interrupted"):
            self.run_setup(build=interrupted)
        partial = next((self.prefix / "setup-state").glob(".stage-*/partial"))
        self.run_setup()
        self.assertEqual(partial.read_bytes(), b"interrupted build evidence")
        self.assertTrue(self.state())


if __name__ == "__main__":
    unittest.main()
