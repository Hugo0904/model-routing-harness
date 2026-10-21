import tempfile
import time
import unittest
from pathlib import Path

from mrh.advisory.request import Advice, AdvisoryRequest, Child
from mrh.advisory.store import AdviceStore, request_id, task_hash
from mrh.presentation import stats_view
from mrh.presentation.terminal import cell_width


class StatsViewTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.store = AdviceStore(Path(tmp.name) / "advice.sqlite3")
        now = time.time()
        def add(n, platform, action, reason, tier=None, cands=()):
            req = AdvisoryRequest(platform, "s", "t", f"c{n}", f"task {n}")
            self.store.save(f"r{n}", req, task_hash(platform, "s", f"task {n}"), Advice(action, reason, tier, 0.9 if tier else None, cands), "jev", now)
        add(1, "claude", "advise", "advice_given", "Light", ({"model": "haiku"},))
        add(2, "claude", "advise", "advice_given", "Mid", ({"model": "sonnet"},))
        add(3, "claude", "continue_main", "top_main_requested", "Top")
        add(4, "codex", "preserve", "named_role")
        add(5, "claude", "preserve", "low_confidence", "Small")
        self.store.attempt("r1", "jev", "returned", now, input_tokens=440, output_tokens=45)
        pre = AdvisoryRequest("claude", "s", "t", "k1", "task 1", "haiku", "medium")
        self.store.preserve_explicit(request_id("claude", "s", "t", "k1"), pre, task_hash("claude", "s", "task 1"), "jev", now)
        self.store.record_child(Child("claude", "s", "k1", "haiku", "medium", "claude-haiku-5-5", "a1"), now)

    def test_readable_summary_answers_what_why_effect_and_cost(self):
        text = stats_view.render(self.store.stats(0), "全部紀錄", 0.65)
        for expected in ("共 5 次（Claude Code 4、Codex 1）", "專門角色、fork 或自訂子代理", "分級信心低於門檻（門檻 0.65）",
                         "1 / 5 次委派（20%）", "其中照 MRH 建議 1 / 2 次", "claude-haiku-5-5 1 次", "分級信心：24 小時內 0.90（4 次）、總平均 0.90（4 次）；門檻 0.65",
                         "light 1（25%）", "Jev：呼叫 1 次，輸入 440 tokens，估計 < $0.0001"):
            self.assertIn(expected, text)
        counts = [l for l in text.splitlines() if l.rstrip().endswith(" 次") and l.startswith("    ") and "→" not in l and "：" not in l]
        self.assertEqual(len({cell_width(l) for l in counts[:3]}), 1)          # the three totals line up despite CJK widths

    def test_empty_period_explains_why_nothing_is_there(self):
        self.assertIn("沒有任何子代理委派經過 MRH", stats_view.render(self.store.stats(time.time() + 60), "過去 24 小時"))


if __name__ == "__main__":
    unittest.main()
