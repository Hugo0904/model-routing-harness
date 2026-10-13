import io
import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

from mrh.application import ctrl_logic as logic
from mrh.infrastructure import settings_v2 as v2
from mrh.presentation import ctrl
from mrh.presentation.menu import Menu


class Keys:
    """Secret store stand-in: reports state only."""
    ENV_VARS = {"jev": "TYPESAFE_API_KEY"}
    def is_set(self, name): return True


class CtrlTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name).resolve() / "owned" / "settings.json"
        v2.init(self.path)

    def cli(self, *argv, stdin=""):
        out, err = io.StringIO(), io.StringIO()
        args = Namespace(settings=self.path, width=100, json=False, ctrl_action=None)
        if argv:
            args.ctrl_action = argv[0]
            if argv[0] == "set": args.key, args.value = argv[1], argv[2]
            if argv[0] == "show": args.json = "--json" in argv
        code = ctrl.main(args, stdin=io.StringIO(stdin), stdout=out, stderr=err, secrets_module=Keys())
        return code, out.getvalue(), err.getvalue()

    def test_set_accepts_every_kind_of_key_and_rejects_bad_values_without_writing(self):
        good = [("enabled", "on"), ("task_export", "yes"), ("classifier.provider", "codex_subscription"),
                ("classifier.model", "gpt-5.6-luna"), ("classifier.timeout", "12"), ("threshold", "0.8"),
                ("tiers.Light.codex", "gpt-5.6-luna:low, gpt-6-luna"), ("tiers.mid.claude", "haiku"),
                ("fixed.codex", "gpt-6.1-sol:high"), ("top_mode", "fixed"), ("allowed_workspaces", "/")]
        for key, value in good:
            with self.subTest(key=key):
                self.assertEqual(self.cli("set", key, value)[0], 0)
        saved = v2.read(self.path)
        self.assertEqual((saved["enabled"], saved["policy"]["threshold"], saved["policy"]["top_mode"]), (True, 0.8, "Fixed"))
        self.assertEqual(saved["classifier"], {"provider": "codex_subscription", "model": "gpt-5.6-luna", "timeout_seconds": 12.0})
        self.assertEqual([c["model"] for c in saved["policy"]["tiers"]["Light"]["codex"]], ["gpt-5.6-luna", "gpt-6-luna"])
        before = self.path.read_bytes()
        self.cli("set", "top_mode", "main"); self.cli("set", "fixed.codex", ""); before = self.path.read_bytes()
        for key, value in [("top_mode", "Fixed"), ("threshold", "0.2"), ("threshold", "abc"), ("enabled", "maybe"), ("tiers.Top.codex", "x"), ("tiers.Light.cursor", "x"),
                           ("classifier.provider", "openai_api"), ("tiers.Light.codex", "a,b,c,d,e,f"), ("tiers.Light.codex", "sk-secret"),
                           ("allowed_workspaces", "relative/dir"), ("nonsense", "1")]:
            with self.subTest(bad=(key, value)):
                code, _, err = self.cli("set", key, value)
                self.assertEqual(code, 2); self.assertTrue(err.startswith("mrh: "))
        self.assertEqual(self.path.read_bytes(), before)

    def test_switching_provider_resets_model_and_timeout_to_that_provider(self):
        self.cli("set", "classifier.timeout", "3")
        self.cli("set", "classifier.provider", "claude_subscription")
        self.assertEqual(v2.read(self.path)["classifier"], {"provider": "claude_subscription", "model": "haiku", "timeout_seconds": 25})
        self.cli("set", "classifier.provider", "jev")
        self.assertEqual(v2.read(self.path)["classifier"]["model"], "jev-1.13.0")

    def test_show_json_has_state_but_no_secret_and_text_view_is_compact(self):
        self.cli("set", "tiers.Light.codex", "gpt-5.6-luna:low")
        data = json.loads(self.cli("show", "--json")[1])
        self.assertEqual(data["api_key"], {"jev": {"environment": False, "keychain": True}})
        text = self.cli("show")[1]
        self.assertIn("gpt-5.6-luna:low", text)
        self.assertRegex(text, r"light\s+haiku|light\s+gpt-5\.6-luna:low")
        self.assertLess(text.count("\n"), 22)

    def test_interactive_flow_enables_routing_and_edits_a_list(self):
        script = "\n".join(["1", "1", "1",                         # Routing -> ON -> Save
                            "3", "1", "1", "2", "gpt-5.6-luna:low", "6", "1",   # Tier models -> Light -> codex -> type -> done -> Save
                            "9"]) + "\n"                          # Quit
        out, err = io.StringIO(), io.StringIO()
        args = Namespace(settings=self.path, width=100, json=False, ctrl_action=None)
        class Tty(io.StringIO):
            def isatty(self): return True
            def fileno(self): raise OSError          # forces the numbered fallback, not raw key reads
        code = ctrl.main(args, stdin=Tty(script), stdout=out, stderr=err, secrets_module=Keys())
        saved = v2.read(self.path)
        self.assertEqual(code, 0, err.getvalue())
        self.assertTrue(saved["enabled"] and saved["task_export_permitted"])
        self.assertEqual(saved["policy"]["tiers"]["Light"]["codex"], [{"model": "gpt-5.6-luna", "effort": "low"}])

    def test_a_concurrent_edit_is_never_overwritten(self):
        class Racing(Menu):
            def pick(self, title, items, current=None):
                v2.update(ctrl_path, enabled=True)               # another writer wins while the dialog is open
                return True
        ctrl_path = self.path
        out = io.StringIO()
        menu = Racing(io.StringIO(), out, 100, False)
        session = ctrl.Session(self.path, menu, out, secrets_module=Keys())
        self.assertFalse(session.set_key("threshold", "0.8", "x"))
        saved = v2.read(self.path)
        self.assertEqual((saved["enabled"], saved["policy"]["threshold"]), (True, 0.5))
        self.assertIn("被別處改過", out.getvalue())

    def test_scope_lives_in_the_allowlist_file_when_one_is_configured(self):
        allow = self.path.parent.parent / "allowlist.json"
        allow.write_text('{"schema_version": 1, "roots": ["/"]}')
        v2.update(self.path, workspace_allowlist_file=str(allow))
        self.assertIn("適用範圍      /", self.cli("show")[1])
        revision = v2.read(self.path)["revision"]
        work = self.path.parent.parent / "work"; work.mkdir()
        self.assertEqual(self.cli("set", "allowed_workspaces", str(work))[0], 0)
        self.assertEqual(json.loads(allow.read_text())["roots"], [str(work)])     # the file the hook really reads
        self.assertEqual(v2.read(self.path)["revision"], revision)                 # settings untouched
        self.assertTrue(v2.workspace_allowed(v2.read(self.path), str(work)))

    def test_menu_never_starts_on_quit(self):
        from mrh.presentation.menu import initial_focus
        items = [("Routing", object()), ("Quit", None)]
        self.assertEqual(initial_focus(items, None), 0)          # Quit's value is None; that is not "current"
        self.assertEqual(initial_focus(items, items[0][1]), 0)
        self.assertEqual(initial_focus([("a", 1), ("b", 2)], 2), 1)

    def test_candidate_text_round_trip(self):
        items = logic.parse_candidates("a:low, b")
        self.assertEqual(logic.format_candidates(items), "a:low, b")
        self.assertEqual(logic.parse_candidates(" , "), [])


if __name__ == "__main__":
    unittest.main()
