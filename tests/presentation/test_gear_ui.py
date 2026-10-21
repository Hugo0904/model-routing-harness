import io
import json
import re
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

from mrh.infrastructure import settings_v2 as v2
from mrh.presentation import classify_cli, ctrl, dashboard
from mrh.presentation.terminal import cell_width
from tests.advisory.test_gears import GEARS, gear_settings
from tests.presentation.test_classify import Transport
from tests.presentation.test_dashboard import DATA

ANSI = re.compile(r"\x1b\[[0-9;]*m")


class Tty(io.StringIO):
    def isatty(self): return True
    def fileno(self): raise OSError


class GearSettingsKeys(unittest.TestCase):
    @staticmethod
    def models(_):
        return ctrl.ModelChoices([('haiku', ('medium',)), ('sonnet', ('high',)), ('opus', ('high', 'xhigh'))],
                                 status='advertised', source='unit-fixture')

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name).resolve() / "owned" / "settings.json"; v2.init(self.path)
        self.ctrl("tiers.Light.claude", "haiku:medium"); self.ctrl("tiers.Mid.claude", "sonnet:high")

    def ctrl(self, key, value):
        out, err = io.StringIO(), io.StringIO()
        code = ctrl.main(Namespace(settings=self.path, width=100, json=False, ctrl_action="set", key=key, value=value), stdin=io.StringIO(), stdout=out, stderr=err, models=self.models)
        return code, out.getvalue() + err.getvalue()

    def gears(self):
        return v2.read(self.path)["policy"].get("gears", [])

    def test_default_ladder_comes_from_the_tier_table_and_switching_the_mode_needs_one(self):
        code, text = self.ctrl("mode", "gears")
        self.assertNotEqual(code, 0); self.assertIn("還沒有檔位", text)
        self.assertEqual(self.ctrl("gears.default", "yes")[0], 0)
        gears = self.gears()
        self.assertEqual([g["from"] for g in gears], [0, 0.75, 1.5, 2.25, 2.75])
        self.assertEqual(gears[0]["candidates"]["claude"], [{"model": "haiku", "effort": "medium"}]); self.assertTrue(gears[3]["main"])
        self.assertEqual(v2.mode(v2.read(self.path)["policy"]), "tiers")                     # a draft does not switch anything
        self.assertEqual(self.ctrl("mode", "gears")[0], 0); self.assertEqual(v2.mode(v2.read(self.path)["policy"]), "gears")
        self.assertEqual(self.ctrl("mode", "tiers")[0], 0); self.assertNotIn("mode", v2.read(self.path)["policy"])

    def test_every_edit_keeps_the_ladder_valid_with_a_chinese_reason_otherwise(self):
        self.ctrl("gears.default", "yes")
        self.assertEqual(self.ctrl("gears.3.claude", "opus:high")[0], 0)
        self.assertEqual(self.gears()[2]["candidates"]["claude"], [{"model": "opus", "effort": "high"}])
        self.assertEqual(self.ctrl("gears.4.main", "off")[0], 0); self.assertEqual(self.gears()[3], {"from": 2.25, "candidates": {}})
        self.assertEqual(self.ctrl("gears.4.claude", "opus:xhigh")[0], 0)
        self.assertEqual(self.ctrl("gears.2.from", "0.5")[0], 0); self.assertEqual(self.gears()[1]["from"], 0.5)
        self.assertEqual(self.ctrl("gears.add", "1")[0], 0); self.assertEqual([g["from"] for g in self.gears()], [0, 0.5, 1, 1.5, 2.25, 2.75])
        for key, value, fragment in (("gears.add", "1", "已經有一檔"), ("gears.1.from", "0.2", "固定是 0"), ("gears.3.from", "0.4", "要比前一檔大"),
                                     ("gears.9.from", "1", "目前只有 6 檔"), ("gears.x.from", "1", "必須是整數"), ("gears.add", "4", "介於"),
                                     ("gears.2.speed", "1", "檔位可以設"), ("mode", "fast", "tiers"), ("gears.nope", "1", "檔位的設定項目")):
            code, text = self.ctrl(key, value)
            self.assertNotEqual(code, 0, key); self.assertIn(fragment, text, key)
        self.assertEqual(self.ctrl("gears.remove", "1")[0], 0)
        self.assertEqual(self.gears()[0]["from"], 0)                                           # the next gear becomes the first, from 0
        for _ in range(4):
            self.ctrl("gears.remove", "1")
        code, text = self.ctrl("gears.remove", "1"); self.assertNotEqual(code, 0); self.assertIn("至少要保留 1 檔", text)
        for n in range(8):
            self.ctrl("gears.add", str(0.1 * (n + 1)))
        code, text = self.ctrl("gears.add", "2.9"); self.assertNotEqual(code, 0); self.assertIn("最多 8 檔", text)

    def test_the_menu_builds_edits_and_switches_the_ladder_with_back_returning_one_step(self):
        def run(*lines):
            out = io.StringIO()
            ctrl.main(Namespace(settings=self.path, width=100, json=False, ctrl_action=None), stdin=Tty("\n".join(lines) + "\n"), stdout=out, stderr=io.StringIO(), models=self.models)
            return out.getvalue()
        # main menu 13 = gears; 5 = default ladder -> save; 1 = switch mode -> save; back -> main; 15 = quit
        text = run("13", "5", "1", "1", "1", "back", "15")
        self.assertIn("路徑：檔位", text); self.assertIn("目前模式：難度表", text); self.assertIn("第 1 檔  難度分數 0 起", text)
        self.assertEqual(v2.mode(v2.read(self.path)["policy"]), "gears"); self.assertEqual(len(self.gears()), 5)
        self.assertIn("檔位", ctrl.render(ctrl.snapshot(v2.read(self.path), self.path), 100))        # the settings overview shows it
        # edit gear 3's Claude candidates through the shared list editor: gear screen -> edit -> gear 3 -> claude -> type -> save
        text = run("13", "2", "3", "3", "2", "opus:high", "6", "1", "back", "back", "15")
        self.assertEqual(self.gears()[2]["candidates"]["claude"][-1], {"model": "opus", "effort": "high"})
        self.assertIn("第 3 檔 / claude", text)                                                  # the shared list editor shows which gear it edits


class GearScreens(unittest.TestCase):
    def render(self, width, color=False, **kw):
        s = gear_settings(**kw)
        return ANSI.sub("", dashboard.render(s, DATA, "過去 7 天", width, color, today="x"))

    def test_status_lists_every_gear_with_its_score_range_and_never_overflows(self):
        for width in (80, 100, 120):
            for color in (False, True):
                with self.subTest(width=width, color=color):
                    s = gear_settings()
                    text = ANSI.sub("", dashboard.render(s, DATA, "過去 7 天", width, color, today="x"))
                    card = [l for l in text.splitlines() if l[:1] in "│╭╰" and cell_width(l) > 40]
                    self.assertEqual({cell_width(l) for l in card}, {width}, text)
                    for expected in ("GEAR", "g1", "g5", "難度分數 0～0.75", "難度分數 2.75～3", "主模型自己做", "檔位模式"):
                        self.assertIn(expected, text)
                    self.assertNotIn("TIER", text)

    def test_tiers_mode_still_draws_the_original_table(self):
        from tests.presentation.test_dashboard import settings
        text = ANSI.sub("", dashboard.render(settings(), DATA, "過去 7 天", 100, False, today="x"))
        self.assertIn("TIER", text); self.assertNotIn("GEAR", text)

    def test_public_status_json_gains_mode_and_gears_only(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        path = Path(tmp.name).resolve() / "owned" / "settings.json"; v2.init(path)
        policy = ctrl.status_data(path, 7)["status"]["policy"]
        self.assertEqual((policy["mode"], policy["gears"]), ("tiers", [])); self.assertTrue({"threshold", "top_mode", "tiers", "fixed"} <= set(policy))

    def test_classify_shows_the_score_and_gear_per_platform(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        path = Path(tmp.name).resolve() / "owned" / "settings.json"; v2.init(path)
        s = v2.read(path); s["task_export_permitted"] = True
        v2.update(path, task_export_permitted=True, policy=gear_settings()["policy"])
        from mrh.adapters.providers.typesafe import TypesafeClassifier
        args = Namespace(task="do a thing", stdin=False, title=None, role=None, platform=None, json=False, settings=path)
        out = io.StringIO()
        transport = Transport({"light": 0.0, "small": 0.1, "mid": 0.7, "top": 0.2})          # score 0.1 + 1.4 + 0.6 = 2.1 -> gear 3
        classify_cli.main(args, stdin=io.StringIO(), stdout=out, stderr=io.StringIO(),
                          classifier_factory=lambda: TypesafeClassifier(enabled=True, task_export_permitted=True,
                                                                        credential_resolver=lambda: "k" * 8, transport=transport))
        text = out.getvalue()
        self.assertIn("難度分數 2.10 → 第 3 檔（檔位模式）", text); self.assertIn("sonnet:high", text); self.assertIn("sol:high", text)


if __name__ == "__main__":
    unittest.main()
