import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from mrh import owned, plugin, settings


class OwnedPluginTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.bundle = self.root / "bundle"
        self.path = self.root / "state/settings.json"

    def test_preparation_repeat_and_updated_code_preserve_settings_and_standalone_default_off(self):
        first = plugin.prepare(self.bundle, self.path)
        self.assertEqual(first["status"], "prepared")
        self.assertEqual(first["native_registration"], "unverified")
        settings.update(self.path, task_export_permitted=True, allowed_workspaces=[str(self.root)])
        state = self.path.read_bytes()
        second = plugin.prepare(self.bundle, self.path)
        self.assertEqual(second["artifact"], first["artifact"])
        self.assertEqual(self.path.read_bytes(), state)
        # A new owned artifact replaces only verified old code, preserving
        # external settings and permissions instead of restoring a snapshot.
        archive = plugin._runtime_archive() + b"\nowned-upgrade-fixture"
        with patch("mrh.plugin._runtime_archive", return_value=archive):
            upgraded = plugin.prepare(self.bundle, self.path)
        self.assertNotEqual(upgraded["artifact"]["files"], first["artifact"]["files"])
        self.assertEqual(self.path.read_bytes(), state)
        self.assertFalse(settings.read(self.path)["enabled"])
        # Prepared runtime carries the package and works from unrelated cwd
        # with no PYTHONPATH or repository dependency.
        installed = self.bundle / "plugins/model-routing-harness"
        python = upgraded["artifact"]["python"]
        event = {"tool_name": "spawn_agent", "hook_event_name": "PreToolUse", "cwd": str(self.root),
                 "session_id": "s", "turn_id": "t", "tool_use_id": "c", "tool_input": {"message": "task"}}
        run = subprocess.run([python, "-I", str(installed / "launcher.py")], input=json.dumps(event),
                             cwd=self.root, env={"PATH": "/usr/bin:/bin"}, text=True, capture_output=True, timeout=5)
        self.assertEqual(run.returncode, 0)
        self.assertEqual(json.loads(run.stdout), {})
        self.assertFalse((self.path.parent / "events.sqlite3").exists())
        self.assertEqual(self.path.read_bytes(), state)

    def test_nonowned_symlink_modified_artifact_and_binding_conflict_refuse_preserving_files(self):
        self.bundle.mkdir(); foreign = self.bundle / "third-party"; foreign.write_bytes(b"preserve")
        with self.assertRaises(owned.OwnedError): plugin.prepare(self.bundle, self.path)
        self.assertEqual(list(self.bundle.iterdir()), [foreign]); self.assertFalse(self.path.parent.exists())
        foreign.unlink(); self.bundle.rmdir()
        plugin.prepare(self.bundle, self.path)
        with self.assertRaisesRegex(owned.OwnedError, "registered_settings_conflict"):
            plugin.prepare(self.bundle, self.root / "other-state/settings.json")
        target = self.bundle / "plugins/model-routing-harness/launcher.py"
        target.write_bytes(b"external changed owned code")
        before = target.read_bytes()
        with self.assertRaisesRegex(owned.OwnedError, "owned_source_changed"):
            plugin.prepare(self.bundle, self.path)
        self.assertEqual(target.read_bytes(), before)
        link = self.root / "symlink"; link.symlink_to(self.bundle)
        with self.assertRaises(owned.OwnedError): plugin.prepare(link, self.path)

    def test_tampered_runtime_launcher_is_neutral_and_unknown_native_state_stays_unknown(self):
        result = plugin.prepare(self.bundle, self.path)
        folder = self.bundle / "plugins/model-routing-harness"
        (folder / "runtime.pyz").write_bytes(b"modified")
        run = subprocess.run([result["artifact"]["python"], "-I", str(folder / "launcher.py")],
                             input="{}", env={}, text=True, capture_output=True, timeout=5)
        self.assertEqual(json.loads(run.stdout), {})
        self.assertEqual(result["hook_trust"], "unverified")
        self.assertFalse(result["live_routing_ready"])


if __name__ == "__main__": unittest.main()
