"""Contract fixtures recorded from native Claude Code 2.1.303 on 2026-10-21.

Actual isolated CLI add/install/list/uninstall/remove was separately exercised.
These deterministic tests establish ownership, preservation and recovery rules.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from mrh.adapters.hosts.claude_windows_install import ClaudeWindowsInstaller, ClaudeInstallError, TESTED_VERSION
from mrh.infrastructure import owned, plugin


class NativeFixture:
    def __init__(self, root):
        self.fixture = root
        self.root = None
        self.row = None
        self.other_markets = [{"name": "other-market", "source": "github", "repo": "example/other"}]
        self.other_plugins = [{"id": "other@other-market", "enabled": False}]
        self.commands = []
        self.mutations = []
        self.fail_after = None
        self.version = TESTED_VERSION
        self.market_override = None
        self.list_override = None
        self.bad_reply = None

    def market(self):
        return {"name": plugin.MARKETPLACE, "source": "directory", "path": self.root, "installLocation": self.root}

    def installed_row(self):
        return {"id": plugin.PLUGIN_ID, "version": "0.4.0", "scope": "user", "enabled": True,
            "installPath": str(self.fixture / "native cache" / plugin.NAME / "0.4.0"),
            "readFromFolder": str(Path(self.root) / "plugins" / plugin.NAME), "folderVersion": "0.4.0",
            "installedAt": "2026-10-21T04:46:37.381Z", "lastUpdated": "2026-10-21T04:46:37.381Z",
            "projectEnabled": False}

    def run(self, argv, **kwargs):
        args = argv[1:]
        self.commands.append(args)
        if args == ["--version"]:
            return subprocess.CompletedProcess(argv, 0, self.version + "\n", "")
        if args == ["plugin", "marketplace", "list", "--json"]:
            result = copy.deepcopy(self.other_markets) + ([self.market()] if self.root else [])
            if self.market_override is not None:
                result = self.market_override
            return subprocess.CompletedProcess(argv, 0, json.dumps(result), "")
        if args == ["plugin", "list", "--json"]:
            result = copy.deepcopy(self.other_plugins) + ([copy.deepcopy(self.row)] if self.row else [])
            if self.list_override is not None:
                result = self.list_override
            return subprocess.CompletedProcess(argv, 0, json.dumps(result), "")
        assert args[0] == "plugin" and args[-1] == "--json"
        assert args[args.index("--scope") + 1] == "user"
        if args[1:3] == ["marketplace", "add"]:
            assert self.root is None
            self.root = args[3]
            command = "marketplace-add"
            reply = {"command": command, "outcome": "ok", "marketplace": plugin.MARKETPLACE, "message": "added"}
        elif args[1:3] == ["marketplace", "remove"]:
            assert args[3] == plugin.MARKETPLACE and self.row is None
            self.root = None
            command = "marketplace-remove"
            reply = {"command": command, "outcome": "ok", "marketplace": plugin.MARKETPLACE, "message": "removed"}
        else:
            command = args[1]
            assert args[2] == plugin.PLUGIN_ID
            reply = {"command": command, "outcome": "ok", "plugin": plugin.PLUGIN_ID,
                     "pluginId": plugin.PLUGIN_ID, "scope": "user", "message": "completed"}
            if command == "install":
                assert self.root and self.row is None
                self.row = self.installed_row()
            elif command == "uninstall":
                assert "--keep-data" in args
                self.row = None
                reply["keptData"] = True
            else:
                raise AssertionError(args)
        self.mutations.append(command)
        if self.fail_after == command:
            self.fail_after = None
            return subprocess.CompletedProcess(argv, 7, "", "unrecorded native error")
        if self.bad_reply:
            reply.update(self.bad_reply)
        return subprocess.CompletedProcess(argv, 0, json.dumps(reply) + "\n", "")


@unittest.skipUnless(os.name == "nt", "requires native Windows owned paths")
class ClaudeNativeInstallTests(unittest.TestCase):
    def setUp(self):
        evidence_root = Path(__file__).resolve().parents[2] / 'runtime'
        evidence_root.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="mrh Claude native contract ", dir=evidence_root)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        from mrh.adapters.platforms.windows import protect
        protect(self.root)
        self.executable = self.root / "protected fixture cli.exe"
        self.executable.write_bytes(b"version-pinned native runner fixture")
        self.settings = self.root / "persistent/settings.json"
        self.native = NativeFixture(self.root)
        self.adapter = ClaudeWindowsInstaller(self.executable, run=self.native.run)
        self.first = self.artifact("generation one")
        self.second = self.artifact("generation two")

    def artifact(self, name, settings=None):
        root = owned.initialize(self.root / name, "bundle")
        files = {
            ".claude-plugin/marketplace.json": {"name": plugin.MARKETPLACE, "owner": {"name": "MRH"},
                "plugins": [{"name": plugin.NAME, "source": "./plugins/" + plugin.NAME, "version": "0.4.0"}]},
            "plugins/" + plugin.NAME + "/.claude-plugin/plugin.json": {"name": plugin.NAME, "version": "0.4.0"},
        }
        hashes = {}
        for relative, value in files.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            data = (json.dumps(value) + "\n").encode()
            owned.replace_owned(path, data)
            hashes[relative] = hashlib.sha256(data).hexdigest()
        meta = {"schema_version": 1, "owner": owned.OWNER, "version": "0.4.0", "python": "fixture",
                "settings_path": str(settings or self.settings), "files": hashes}
        owned.replace_owned(root / "artifact.json", (json.dumps(meta) + "\n").encode())
        return root

    def install(self, target=None, before=None, progress=None):
        return self.adapter.install(target or self.first, before or self.adapter.preflight(self.settings), progress or (lambda step: None))

    def test_pinned_version_metadata_and_empty_observation(self):
        self.assertEqual(self.adapter.cli["version"], TESTED_VERSION)
        self.assertEqual(self.adapter.cli["catalog"], "isolated_initialize")
        self.assertEqual(self.adapter.observe()["root"], None)
        self.native.version = "2.1.304 (Claude Code)"
        with self.assertRaisesRegex(ClaudeInstallError, "unsupported_version"):
            ClaudeWindowsInstaller(self.executable, run=self.native.run)
        self.assertEqual(self.native.mutations, [])

    def test_install_idempotency_preserves_unrelated_disabled_plugin(self):
        others = copy.deepcopy((self.native.other_markets, self.native.other_plugins))
        steps = []
        self.install(progress=steps.append)
        self.assertTrue(self.adapter.configured(self.first))
        self.assertEqual(self.native.mutations, ["marketplace-add", "install"])
        self.assertEqual(steps, ["add_marketplace_intent", "add_marketplace_done", "add_plugin_intent", "add_plugin_done"])
        self.install()
        self.assertEqual(self.native.mutations, ["marketplace-add", "install"])
        self.assertEqual((self.native.other_markets, self.native.other_plugins), others)
        self.assertFalse(any("--yes" in row or "-y" in row or "--prune" in row for row in self.native.commands))

    def test_update_and_rollback_only_replace_exact_owned_user_registration(self):
        self.install()
        before = self.adapter.preflight(self.settings)
        self.install(self.second, before)
        self.assertTrue(self.adapter.configured(self.second))
        self.assertEqual(self.native.mutations[-4:], ["uninstall", "marketplace-remove", "marketplace-add", "install"])
        self.install(self.first, self.adapter.preflight(self.settings))
        self.assertTrue(self.adapter.configured(self.first))
        uninstalls = [args for args in self.native.commands if args[:2] == ["plugin", "uninstall"]]
        self.assertTrue(all("--keep-data" in args and plugin.PLUGIN_ID in args for args in uninstalls))

    def test_lost_acknowledgement_resumes_each_mutation_without_duplicate(self):
        self.install()
        baseline = self.adapter.preflight(self.settings)
        for command in ("uninstall", "marketplace-remove", "marketplace-add", "install"):
            with self.subTest(command=command):
                self.native.root = str(self.first)
                self.native.row = self.native.installed_row()
                self.native.mutations.clear()
                self.native.fail_after = command
                with self.assertRaisesRegex(ClaudeInstallError, "native_command_failed"):
                    self.install(self.second, baseline)
                self.install(self.second, baseline)
                self.assertTrue(self.adapter.configured(self.second))
                self.assertEqual(self.native.mutations, ["uninstall", "marketplace-remove", "marketplace-add", "install"])

    def test_disabled_and_nonuser_scope_entries_are_never_changed(self):
        self.install()
        mutations = len(self.native.mutations)
        self.native.row["enabled"] = False
        with self.assertRaisesRegex(ClaudeInstallError, "disabled_plugin_preserved"):
            self.adapter.preflight(self.settings)
        self.native.row["enabled"] = True
        self.native.row["scope"] = "project"
        with self.assertRaisesRegex(ClaudeInstallError, "schema_unknown"):
            self.adapter.preflight(self.settings)
        self.assertEqual(len(self.native.mutations), mutations)

    def test_remote_marketplace_wrong_name_and_same_market_other_plugin_refused(self):
        self.native.market_override = [{"name": plugin.MARKETPLACE, "source": "github", "repo": "foreign/repo"}]
        with self.assertRaisesRegex(ClaudeInstallError, "marketplace_unowned"):
            self.adapter.preflight(self.settings)
        self.native.market_override = None
        for identity in (plugin.NAME + "@foreign-market", "other@" + plugin.MARKETPLACE):
            self.native.list_override = [{"id": identity}]
            with self.assertRaisesRegex(ClaudeInstallError, "name_conflict"):
                self.adapter.preflight(self.settings)
        self.assertEqual(self.native.mutations, [])

    def test_foreign_directory_and_artifact_tamper_rejected(self):
        foreign = self.root / "unowned marketplace"
        foreign.mkdir()
        self.native.root = str(foreign)
        with self.assertRaises(ValueError):
            self.adapter.preflight(self.settings)
        self.native.root = str(self.first)
        manifest = self.first / ".claude-plugin/marketplace.json"
        manifest.write_text("{}")
        with self.assertRaises(ValueError):
            self.adapter.preflight(self.settings)
        self.assertEqual(self.native.mutations, [])

    def test_settings_binding_and_read_from_folder_must_match_owned_generation(self):
        self.native.root = str(self.artifact("different profile", self.root / "other/settings.json"))
        with self.assertRaisesRegex(ClaudeInstallError, "settings_conflict"):
            self.adapter.preflight(self.settings)
        self.native.root = str(self.first)
        self.native.row = self.native.installed_row()
        self.native.row["readFromFolder"] = str(self.second / "plugins" / plugin.NAME)
        with self.assertRaisesRegex(ClaudeInstallError, "registration_conflict"):
            self.adapter.preflight(self.settings)

    def test_update_cannot_change_persistent_settings_binding(self):
        self.install()
        before = self.adapter.preflight(self.settings)
        target = self.artifact("new settings binding", self.root / "foreign/settings.json")
        mutations = list(self.native.mutations)
        with self.assertRaisesRegex(ClaudeInstallError, "settings_conflict"):
            self.install(target, before)
        self.assertEqual(self.native.mutations, mutations)

    def test_unknown_duplicate_and_missing_native_schema_fail_closed(self):
        self.native.root = str(self.first)
        self.native.row = self.native.installed_row()
        for override in ({"installed": [self.native.row]}, [self.native.row, self.native.row], [{"id": plugin.PLUGIN_ID}],
                         [{**self.native.row, "unverifiedNewField": True}]):
            with self.subTest(override=override):
                self.native.list_override = override
                with self.assertRaises(ClaudeInstallError):
                    self.adapter.preflight(self.settings)
        self.assertEqual(self.native.mutations, [])

    def test_concurrent_mapping_change_during_journal_intent_is_preserved(self):
        self.install()
        before = self.adapter.preflight(self.settings)
        self.native.mutations.clear()
        def progress(step):
            if step == "remove_plugin_intent":
                self.native.root = str(self.artifact("concurrent generation"))
                self.native.row = self.native.installed_row()
        with self.assertRaisesRegex(ClaudeInstallError, "native_concurrent_change"):
            self.install(self.second, before, progress)
        self.assertEqual(self.native.mutations, [])
        self.assertIn("concurrent generation", self.native.root)

    def test_native_mutation_false_success_is_not_accepted(self):
        self.native.bad_reply = {"outcome": "unverified"}
        with self.assertRaisesRegex(ClaudeInstallError, "mutation_response_invalid"):
            self.install()
        self.assertIsNone(self.native.row)


if __name__ == "__main__":
    unittest.main()
