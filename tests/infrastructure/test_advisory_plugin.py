import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from mrh.infrastructure import plugin, settings_v2 as v2


class AdvisoryPluginTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        base = Path(tmp.name).resolve()
        self.root, self.settings = base / "artifact", base / "profile" / "settings.json"
        plugin.prepare(self.root, self.settings, sys.executable, advisory=True)
        self.launcher = self.root / "plugins/model-routing-harness/launcher.py"
        v2.update(self.settings, enabled=True, task_export_permitted=True, allowed_workspaces=["/"])

    def launch(self, event, *args):
        run = subprocess.run([sys.executable, "-I", "-B", str(self.launcher), *args], input=json.dumps(event),
                             capture_output=True, text=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stderr)
        return json.loads(run.stdout)

    def test_artifact_shape(self):
        hooks = json.loads((self.root / "plugins/model-routing-harness/hooks/hooks.json").read_text())["hooks"]
        self.assertEqual(set(hooks), {"PreToolUse", "PostToolUse"})        # no SessionStart / scope machinery
        binding = json.loads((self.root / "plugins/model-routing-harness/binding.json").read_text())
        self.assertEqual(binding["platform"], "codex")
        self.assertNotIn("codex_scope", binding)

    def test_installed_launcher_reaches_the_advisory_path_for_both_platforms(self):
        codex = {"hook_event_name": "PreToolUse", "tool_name": "spawn_agent", "session_id": "s", "turn_id": "t",
                 "tool_use_id": "c1", "cwd": "/", "tool_input": {"message": "do x", "model": "gpt-5.6-luna"}}
        claude = {"hook_event_name": "PreToolUse", "tool_name": "Agent", "session_id": "s", "prompt_id": "p",
                  "tool_use_id": "c2", "cwd": "/", "tool_input": {"prompt": "do y", "model": "haiku", "subagent_type": "general-purpose"}}
        self.assertEqual(self.launch(codex), {})                # explicit model: respected, no classifier needed
        self.assertEqual(self.launch(claude, "claude"), {})     # platform comes from the hook command argument
        with sqlite3.connect(self.settings.parent / "advice.sqlite3") as db:
            rows = db.execute("SELECT platform, reason FROM advice ORDER BY platform").fetchall()
        self.assertEqual(rows, [("claude", "explicit_model"), ("codex", "explicit_model")])

    def test_unknown_platform_argument_never_blocks_the_delegation(self):
        out = self.launch({"hook_event_name": "PreToolUse", "tool_name": "Agent", "tool_input": {"prompt": "x"}}, "gemini-x")
        self.assertNotIn("hookSpecificOutput", out)             # no deny: the original call proceeds
        self.assertIn("original tool call preserved", out["systemMessage"])


if __name__ == "__main__":
    unittest.main()
