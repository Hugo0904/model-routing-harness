import re
import tempfile
import unittest
from pathlib import Path

from mrh.advisory.request import Advice, AdvisoryRequest
from mrh.advisory.store import AdviceStore, request_id, task_hash
from mrh.presentation import dashboard, stats_view
from mrh.presentation.terminal import cell_width
from tests.presentation.test_dashboard import settings

ANSI = re.compile(r"\x1b\[[0-9;]*m")
NOW = 1_800_000_000


class ClassifierTimingTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.store = AdviceStore(Path(tmp.name) / "advice.sqlite3")

    def call(self, rid, start, took, model="jev-1.13.0", outcome="returned", kind="jev"):
        self.store.attempt(rid, kind, "classification_requested", start - 0.01)
        self.store.attempt(rid, kind, "started", start)
        if took is not None:
            self.store.attempt(rid, kind, outcome, start + took, response_model=model, input_tokens=440, output_tokens=45)

    def test_latency_averages_only_calls_that_returned_and_versions_are_counted_per_answering_model(self):
        self.call("a", NOW, 0.5)
        self.call("b", NOW + 10, 1.5)
        self.call("c", NOW + 20, 4.0, model="jev-1.14.0", outcome="late_returned")   # answered after the deadline: still an answer
        self.call("d", NOW + 30, None)                                                # no answer: not part of the average
        data = self.store.stats(0)
        self.assertEqual(data["classifier_latency"]["n"], 3)
        self.assertAlmostEqual(data["classifier_latency"]["avg"], 2.0); self.assertAlmostEqual(data["classifier_latency"]["max"], 4.0)
        self.assertEqual(data["classifier_versions"], {"jev-1.13.0": 2, "jev-1.14.0": 1})
        self.assertEqual(stats_view.main_version(data), "jev-1.13.0")
        self.assertEqual(stats_view.latency_text(data), "平均 2.0 秒、最慢 4.0 秒（3 次）")

    def test_nothing_returned_means_no_numbers_not_zeroes(self):
        self.call("x", NOW, None)
        data = self.store.stats(0)
        self.assertEqual(data["classifier_latency"], {"avg": None, "max": None, "n": 0})
        self.assertEqual(data["classifier_versions"], {})
        self.assertIsNone(stats_view.latency_text(data)); self.assertIsNone(stats_view.main_version(data))

    def seed_delegation(self):
        req = AdvisoryRequest("codex", "s", "t", "c", "task")
        self.store.save(request_id("codex", "s", "t", "c"), req, task_hash("codex", "s", "task"),
                        Advice("advise", "advice_given", "Light", .9, ({"model": "gpt-5.6-luna"},)), "jev", NOW)

    def test_cards_show_the_actual_version_and_time_at_every_width_and_text_stats_list_them(self):
        self.seed_delegation(); self.call("a", NOW, 0.8)
        data = self.store.stats(0)
        for width in (80, 100, 120):
            for color in (False, True):
                with self.subTest(width=width, color=color):
                    text = ANSI.sub("", dashboard.render(settings(), data, "全部紀錄", width, color, today="x"))
                    card = [l for l in text.splitlines() if l[:1] in "│╭╰" and cell_width(l) > 40]
                    self.assertEqual({cell_width(l) for l in card}, {width})
                    self.assertIn({80: "0.8 秒", 100: "1.13.0 · 0.8 秒", 120: "1.13.0 · 0.8 秒"}[width], text)   # longest caption that fits
        text = stats_view.render(data, "全部紀錄", 0.65, False, settings()["policy"])
        self.assertIn("耗時：平均 0.8 秒、最慢 0.8 秒（1 次）", text); self.assertIn("實際版本：jev-1.13.0 1 次", text)

    def test_without_any_returned_call_the_flow_box_keeps_its_original_caption(self):
        self.seed_delegation()
        text = ANSI.sub("", dashboard.render(settings(), self.store.stats(0), "全部紀錄", 100, False, today="x"))
        self.assertIn("一道選擇題", text); self.assertNotIn("實際 jev", text)


if __name__ == "__main__":
    unittest.main()
