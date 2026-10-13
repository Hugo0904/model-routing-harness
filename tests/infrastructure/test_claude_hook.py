import json
import tempfile
import unittest
from pathlib import Path

from mrh.infrastructure import claude_hook as ch

CMD = "'/opt/mrh/python3.11' -I -B '/opt/mrh/plugins/model-routing-harness/launcher.py' claude"
OTHER = {"matcher": "Bash", "hooks": [{"type": "command", "command": "/usr/local/bin/audit"}]}


class ClaudeHookTests(unittest.TestCase):
    def test_other_settings_and_hooks_survive_install_update_and_removal(self):
        original = {"model": "opus", "permissions": {"allow": ["Bash(ls)"]}, "hooks": {"PreToolUse": [OTHER], "Stop": [OTHER]}}
        text = json.dumps(original, indent=2) + "\n"
        installed = ch.plan(text, CMD)
        doc = json.loads(installed)
        self.assertEqual((doc["model"], doc["permissions"], doc["hooks"]["Stop"]), ("opus", original["permissions"], [OTHER]))
        self.assertEqual(doc["hooks"]["PreToolUse"][0], OTHER)
        self.assertEqual([e["matcher"] for e in doc["hooks"]["PostToolUse"]], ["Agent|Task"])
        self.assertEqual(ch.plan(installed, CMD), installed)                       # idempotent
        moved = json.loads(ch.plan(installed, CMD.replace("/opt/mrh", "/new/place")))
        self.assertEqual(len(moved["hooks"]["PreToolUse"]), 2)                     # updated in place, never duplicated
        self.assertEqual(json.loads(ch.plan(installed, CMD, remove=True)), original)

    def test_removal_from_a_file_that_only_had_our_hook_leaves_no_empty_hooks_key(self):
        self.assertEqual(json.loads(ch.plan(ch.plan("", CMD), CMD, remove=True)), {})

    def test_unreadable_or_unexpected_files_are_refused(self):
        for text in ("{broken", "[]", '{"hooks": []}'):
            with self.subTest(text=text), self.assertRaises(ch.ClaudeHookError):
                ch.plan(text, CMD)

    def test_apply_keeps_a_backup_and_the_file_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"; path.write_text('{"model":"opus"}\n'); path.chmod(0o600)
            backup = ch.apply(path, ch.plan(path.read_text(), CMD))
            self.assertEqual(json.loads(backup.read_text()), {"model": "opus"})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertIn("Agent|Task", path.read_text())


if __name__ == "__main__":
    unittest.main()
