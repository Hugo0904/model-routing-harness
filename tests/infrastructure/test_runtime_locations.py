"""Isolated location contracts; no installed config, provider, or native ACL claims."""
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from mrh.infrastructure import locations, owned, temporary
from mrh.infrastructure.settings_schema import SettingsError


class RuntimeLocationsTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="mrh-locations-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.home = self.root / "home"
        self.home.mkdir()
        self.module = self.root / "standalone" / "app" / "mrh.pyz" / "mrh" / "infrastructure" / "locations.py"
        env = patch.dict(os.environ, {"HOME": str(self.home), "USERPROFILE": str(self.home),
                                     "PROGRAMDATA": str(self.root / "ProgramData")}, clear=True)
        env.start(); self.addCleanup(env.stop)
        module = patch.object(locations, "__file__", str(self.module))
        module.start(); self.addCleanup(module.stop)

    def generation(self, value):
        root = self.root / "standalone"
        root.mkdir(exist_ok=True)
        (root / "generation.json").write_text(json.dumps(value), encoding="utf-8")

    def snapshot(self):
        return {str(p.relative_to(self.root)): p.read_bytes() if p.is_file() else None
                for p in self.root.rglob("*")}

    def test_no_repository_or_environment_uses_default_without_writes(self):
        before = self.snapshot()
        self.assertEqual(locations.runtime_root(), locations.default_runtime_root(home=self.home))
        self.assertEqual(temporary.area(create=False), locations.runtime_root() / "tmp" / "mrh")
        self.assertEqual(self.snapshot(), before)

    def test_source_checkout_is_not_discovered_as_a_runtime(self):
        checkout = self.root / "checkout"
        (checkout / "src" / "mrh").mkdir(parents=True)
        (checkout / "pyproject.toml").write_text("[project]\n")
        with patch.object(locations, "__file__", str(checkout / "src/mrh/infrastructure/locations.py")):
            self.assertEqual(locations.runtime_root(), locations.default_runtime_root(home=self.home))

    def test_metadata_runtime_wins_over_environment_and_cwd_even_without_source(self):
        runtime = self.root / "bound-runtime"
        self.generation({"runtime_root": str(runtime), "project_root": str(self.root / "removed-source")})
        unrelated = self.root / "unrelated"; unrelated.mkdir()
        original = Path.cwd()
        try:
            os.chdir(unrelated)
            with patch.dict(os.environ, MRH_RUNTIME_ROOT="relative", MRH_PROJECT_ROOT="relative"):
                self.assertEqual(locations.runtime_root(), runtime)
                self.assertEqual(temporary.area(create=False), runtime / "tmp/mrh")
        finally:
            os.chdir(original)
        self.assertFalse(runtime.exists())

    def test_explicit_dev_runtime_wins_over_legacy_generation(self):
        runtime = self.root / "development-runtime"
        self.generation({"project_root": str(self.root / "removed-source")})
        with patch.dict(os.environ, MRH_RUNTIME_ROOT=str(runtime), MRH_PROJECT_ROOT="relative"):
            self.assertEqual(locations.runtime_root(), runtime)
            self.assertEqual(temporary.area(), runtime / "tmp/mrh")
            owned.verify(runtime / "tmp/mrh", "disposable_tmp")

    def test_old_generation_and_explicit_project_root_remain_supported(self):
        project = self.root / "project"; project.mkdir()
        with patch.dict(os.environ, MRH_PROJECT_ROOT=str(project)):
            self.assertEqual(locations.runtime_root(), project / "runtime")
        self.generation({"project_root": str(project)})
        with patch.dict(os.environ, MRH_PROJECT_ROOT="relative"):
            self.assertEqual(locations.runtime_root(), project / "runtime")

    def test_invalid_explicit_roots_fail_closed(self):
        bad = ("", "relative", str(self.root / "bad\npath"), str(self.root / "missing/../runtime"))
        for value in bad:
            with self.subTest(value=value), patch.dict(os.environ, MRH_RUNTIME_ROOT=value):
                with self.assertRaises(owned.OwnedError):locations.runtime_root()
        for value in ("relative", str(self.root / "missing")):
            with self.subTest(project=value), patch.dict(os.environ, MRH_PROJECT_ROOT=value):
                with self.assertRaises(owned.OwnedError):locations.runtime_root()
        target = self.root / "file"; target.write_bytes(b"keep")
        with patch.dict(os.environ, MRH_RUNTIME_ROOT=str(target)):
            with self.assertRaises(owned.OwnedError):locations.runtime_root()

    def test_invalid_metadata_does_not_fall_back_to_environment(self):
        for value in ("", "relative", None, []):
            self.generation({"runtime_root": value})
            with self.subTest(value=value), patch.dict(os.environ, MRH_RUNTIME_ROOT=str(self.root / "valid")):
                with self.assertRaises(owned.OwnedError):locations.runtime_root()
        path = self.root / "standalone/generation.json"
        for raw in ('{"runtime_root":', '[]', '{"runtime_root":"a","runtime_root":"b"}'):
            path.write_text(raw)
            with self.subTest(raw=raw), self.assertRaises(owned.OwnedError):locations.runtime_root()

    def test_symlinked_runtime_is_rejected_before_any_writes(self):
        outside = self.root / "outside"; outside.mkdir()
        linked = self.root / "linked"
        try:linked.symlink_to(outside, target_is_directory=True)
        except OSError:self.skipTest("host cannot create an unprivileged symlink")
        with patch.dict(os.environ, MRH_RUNTIME_ROOT=str(linked / "runtime")):
            with self.assertRaises(owned.OwnedError):temporary.area()
        self.assertEqual(list(outside.iterdir()), [])

    def test_default_posix_roots_and_resolution_are_read_only(self):
        before = self.snapshot()
        for platform, suffix in (("darwin", "Library/Caches"), ("linux", ".cache")):
            with self.subTest(platform=platform), patch.object(locations.sys, "platform", platform):
                self.assertEqual(locations.default_runtime_root({}, self.home), self.home / suffix / "model-routing-harness")
                self.assertEqual(locations.default_config_root({}, self.home), self.home / ".config/model-routing-harness")
        self.assertEqual(self.snapshot(), before)

    def test_windows_default_path_policy_uses_native_sid_without_loading_native_apis(self):
        # This proves only location composition, not Windows ownership or ACLs.
        program_data = self.root / "ProgramData"
        native = SimpleNamespace(current_sid=lambda: "S-1-5-21-fixture")
        before = self.snapshot()
        with patch.object(locations.sys, "platform", "win32"), \
             patch.dict(sys.modules, {"mrh.adapters.platforms.windows": native}):
            base = program_data / "ModelRoutingHarness-S-1-5-21-fixture"
            self.assertEqual(locations.default_config_root({"PROGRAMDATA": str(program_data)}), base / "config")
            self.assertEqual(locations.default_runtime_root({"PROGRAMDATA": str(program_data)}), base / "runtime")
            with self.assertRaises(owned.OwnedError):locations.default_runtime_root({"PROGRAMDATA": "relative"})
        self.assertEqual(self.snapshot(), before)

    def test_settings_precedence_and_pointer_have_existing_error_contract(self):
        environ = {"PROGRAMDATA": str(self.root / "ProgramData")}
        pointer = locations.default_config_root(environ, self.home) / "active-settings"
        pointer.parent.mkdir(parents=True)
        paths = {name: self.root / name / "settings.json" for name in ("flag", "env", "pointer")}
        pointer.write_text(str(paths["pointer"]) + "\n", encoding="utf-8")
        before = self.snapshot()
        self.assertEqual(locations.resolve_settings_path(None, environ, self.home), paths["pointer"])
        self.assertEqual(locations.resolve_settings_path(None, {**environ, "MRH_SETTINGS": "  " + str(paths["env"]) + "\n"}, self.home), paths["env"])
        self.assertEqual(locations.resolve_settings_path(paths["flag"], {**environ, "MRH_SETTINGS": "relative"}, self.home), paths["flag"])
        for value in ("relative/settings.json", str(self.root / "wrong.json")):
            with self.subTest(value=value), self.assertRaises(SettingsError) as caught:
                locations.resolve_settings_path(value, environ, self.home)
            self.assertEqual(caught.exception.reason, "settings_path_invalid")
        self.assertEqual(self.snapshot(), before)
        pointer.unlink()
        with self.assertRaises(SettingsError):locations.resolve_settings_path(None, environ, self.home)
        with patch.object(locations, "default_config_root", side_effect=owned.OwnedError("unsafe_path")):
            with self.assertRaises(SettingsError):locations.resolve_settings_path(None, environ, self.home)

    def test_windows_settings_pointer_uses_the_native_default_config(self):
        config = self.root / "native-config"; config.mkdir()
        expected = self.root / "profile/settings.json"
        (config / "active-settings").write_text(str(expected) + "\n")
        with patch.object(locations, "default_config_root", return_value=config):
            self.assertEqual(locations.resolve_settings_path(None, {}, self.home), expected)
            self.assertEqual(locations.resolve_settings_path(expected, {"MRH_SETTINGS": "relative"}, self.home), expected)

    def test_cleanup_only_removes_disposable_content_and_preserves_siblings(self):
        runtime = self.root / "runtime"
        protected = [runtime / "settings/settings.json", runtime / "stats/events.sqlite3", runtime / "collection/request.json"]
        for path in protected:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(str(path).encode())
        before = {path: path.read_bytes() for path in protected}
        with patch.dict(os.environ, MRH_RUNTIME_ROOT=str(runtime)):
            for kind in ("tmp", "cache"):
                (temporary.area(kind) / "discard").write_bytes(b"disposable")
            self.assertEqual(temporary.cleanup()["files"], 2)
            self.assertEqual(temporary.cleanup(apply=True)["files"], 2)
            self.assertEqual(temporary.cleanup(apply=True)["files"], 0)
            for kind in ("tmp", "cache"):
                owned.verify(temporary.area(kind, create=False), "disposable_" + kind)
        self.assertEqual({path: path.read_bytes() for path in protected}, before)


if __name__ == "__main__":
    unittest.main()
