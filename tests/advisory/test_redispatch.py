import tempfile
import unittest
from pathlib import Path

from mrh.advisory.request import Advice, AdvisoryRequest
from mrh.advisory.store import AdviceStore, redispatch, request_id, task_hash
from mrh.presentation import stats_view

NOW = 1_800_000_000


def row(n, ts, *, task="a", session="s", platform="claude", tier="Light", reason="advice_given"):
    return {"request_id": f"r{n}", "ts": ts, "platform": platform, "session_id": session, "task_hash": task, "tier": tier, "reason": reason}


class PureTests(unittest.TestCase):
    def test_a_repeat_within_the_window_counts_and_the_window_boundary_is_inclusive(self):
        self.assertEqual(redispatch([row(1, 0), row(2, 1800)])["total"], 1)                # exactly 30 minutes
        self.assertEqual(redispatch([row(1, 0), row(2, 1801)])["total"], 0)                # one second later
        self.assertEqual(redispatch([row(1, 0)])["total"], 0)

    def test_the_gap_is_measured_from_the_previous_dispatch_and_a_long_gap_starts_a_new_run(self):
        result = redispatch([row(1, 0), row(2, 1500), row(3, 3000), row(4, 9000), row(5, 10000)])
        self.assertEqual((result["total"], result["tasks"]), (3, 1))                        # 2nd, 3rd (each within 30 min of the one before), 5th

    def test_only_the_same_task_in_the_same_session_and_platform_counts(self):
        rows = [row(1, 0), row(2, 60, task="b"), row(3, 120, session="other"), row(4, 180, platform="codex")]
        self.assertEqual(redispatch(rows)["total"], 0)

    def test_repeats_are_filed_under_the_first_dispatchs_tier_or_unclassified(self):
        result = redispatch([row(1, 0, tier="Mid"), row(2, 10, tier=None), row(3, 20, task="z", tier=None), row(4, 30, task="z", tier=None)])
        self.assertEqual(result["by_tier"], {"Mid": 1, "未分級": 1}); self.assertEqual(result["tasks"], 2)


class StatsTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.store = AdviceStore(Path(tmp.name) / "advice.sqlite3")

    def save(self, call, ts, task="same task", **advice):
        req = AdvisoryRequest("claude", "s", "t", call, task)
        self.store.save(request_id("claude", "s", "t", call), req, task_hash("claude", "s", task),
                        Advice(advice.get("action", "preserve"), advice.get("reason", "named_role"), advice.get("tier"), advice.get("conf"),
                               ({"model": "haiku", "effort": "high"},) if advice.get("action") == "advise" else ()), "jev", ts)

    def test_mrh_own_follow_the_advice_reissue_is_not_a_repeat_but_a_second_plain_dispatch_is(self):
        self.save("a", NOW, action="advise", reason="advice_given", tier="Small", conf=.9)
        reissue = AdvisoryRequest("claude", "s", "t", "b", "same task", "haiku", "high")
        self.store.preserve_explicit(request_id("claude", "s", "t", "b"), reissue, task_hash("claude", "s", "same task"), "jev", NOW + 20)   # MRH's own re-issue
        self.assertEqual(self.store.stats(0)["redispatch"]["total"], 0)
        self.save("c", NOW + 600, reason="explicit_model")                                                                                    # the parent sends it again later
        data = self.store.stats(0)["redispatch"]
        self.assertEqual((data["total"], data["by_tier"], data["window_minutes"]), (1, {"Small": 1}, 30))

    def test_the_screen_states_the_count_and_does_not_judge_it(self):
        self.save("a", NOW, action="advise", reason="advice_given", tier="Light", conf=.9); self.save("b", NOW + 30, reason="explicit_model")
        text = stats_view.render(self.store.stats(0), "全部紀錄", 0.65, False)
        self.assertIn("文字相同的任務，在 30 分鐘內又派了一次：1 次（1 個任務）；依第一次的級別：light 1", text)
        self.assertIn("只計次數，不判斷原因。", text)
        for word in ("返工", "品質", "失敗"):
            self.assertNotIn(word, text.split("■ 同一任務重派")[1].split("■")[0])
        empty = AdviceStore(Path(tempfile.mkdtemp()) / "x.sqlite3")
        self.assertNotIn("同一任務重派", stats_view.render(empty.stats(0), "全部紀錄", 0.65, False))


if __name__ == "__main__":
    unittest.main()
