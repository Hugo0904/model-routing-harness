import io
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

from mrh.advisory import calibration
from mrh.advisory.request import Advice, AdvisoryRequest, Child
from mrh.advisory.store import AdviceStore, request_id, task_hash
from mrh.infrastructure import settings_v2 as v2
from mrh.presentation import ctrl

NOW = 1_800_000_000
POLICY = v2.validate({**v2.default_settings(), "policy": {"threshold": 0.65, "top_mode": "Main", "tiers": {
    "Light": {"claude": [{"model": "haiku", "effort": "medium"}]},
    "Mid": {"claude": [{"model": "sonnet", "effort": "high"}]}}}})["policy"]


def row(n, confidence, *, ts=None, action="advise", tier="Light", turn=None, session="s", call=None, platform="claude"):
    return {"request_id": f"r{n}", "ts": ts if ts is not None else NOW - 1000 - n, "platform": platform, "session_id": session,
            "turn_id": turn or f"t{n}", "call_id": call or f"c{n}", "action": action, "reason": "x", "tier": tier,
            "confidence": confidence}


class SuggestTests(unittest.TestCase):
    def test_too_few_classifications_give_no_number(self):
        result = calibration.suggest_threshold([row(n, .9) for n in range(29)], [], POLICY, NOW)
        self.assertEqual(result, {"status": "insufficient", "n": 29, "need": 30, "days": 30})
        self.assertIn("樣本不足（最近 30 天只有 29 次分級，需要 30 次）", calibration.describe(result)[0])

    def test_old_rows_and_rows_without_confidence_do_not_count(self):
        rows = [row(n, .9) for n in range(20)] + [row(100 + n, .9, ts=NOW - 40 * 86400) for n in range(50)] \
             + [row(200 + n, None) for n in range(50)]
        self.assertEqual(calibration.suggest_threshold(rows, [], POLICY, NOW)["status"], "insufficient")

    def test_threshold_sits_where_about_eighty_percent_pass_rounded_to_five_hundredths(self):
        rows = [row(n, round(0.50 + n * 0.005, 4)) for n in range(50)]          # 0.500 .. 0.745, evenly spread
        result = calibration.suggest_threshold(rows, [], POLICY, NOW)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["suggested"], 0.55)                              # nearest rank 10 of 50 = 0.545 -> 0.55
        self.assertGreaterEqual(result["pass_share"], 0.78); self.assertFalse(result["raised"])
        self.assertIn("建議：0.55（依最近 30 天 50 次分級，約 80% 會通過）", calibration.describe(result)[0])

    def test_suggestion_is_clamped_to_the_allowed_range(self):
        high = calibration.suggest_threshold([row(n, .99) for n in range(40)], [], POLICY, NOW)
        low = calibration.suggest_threshold([row(n, .10) for n in range(40)], [], POLICY, NOW)
        self.assertEqual((high["suggested"], low["suggested"]), (0.90, 0.50))

    def children_after(self, advice_rows, models):
        """For each advised row, one later delegation in the same turn using `models[i]` (None = inherited)."""
        pre, children = [], []
        for i, (a, model) in enumerate(zip(advice_rows, models)):
            pre.append(row(1000 + i, None, ts=a["ts"] + 30, action="preserve", tier=None, turn=a["turn_id"], session=a["session_id"],
                           call=f"k{i}"))
            children.append({"platform": "claude", "session_id": a["session_id"], "call_id": f"k{i}", "requested_model": model})
        return pre, children

    def advised(self, count):
        return [row(n, .8, turn=f"t{n}", session=f"s{n}") for n in range(count)]

    def test_replacing_advice_with_a_stronger_model_often_enough_raises_the_suggestion_by_one_step(self):
        advice = self.advised(30)
        pre, children = self.children_after(advice, ["opus"] * 8 + ["haiku"] * 22)     # 8 of 30 = 27% >= 20% and >= 5
        result = calibration.suggest_threshold(advice + pre, children, POLICY, NOW)
        self.assertTrue(result["raised"]); self.assertEqual((result["overrides"], result["followups"]), (8, 30))
        self.assertEqual(result["suggested"], 0.85)                                     # base 0.80 + 0.05
        self.assertIn("已 +0.05：主模型常改用更強的模型（8／30 次）", " ".join(calibration.describe(result)))

    def test_inheriting_the_main_model_counts_as_a_replacement(self):
        advice = self.advised(30)
        pre, children = self.children_after(advice, [None] * 6 + ["haiku"] * 24)
        self.assertTrue(calibration.suggest_threshold(advice + pre, children, POLICY, NOW)["raised"])

    def test_too_few_or_too_small_a_share_does_not_raise(self):
        advice = self.advised(30)
        for models in (["opus"] * 4 + ["haiku"] * 26,                                   # 4 < 5 replacements
                       ["haiku"] * 30):                                                  # none
            pre, children = self.children_after(advice, models)
            self.assertFalse(calibration.suggest_threshold(advice + pre, children, POLICY, NOW)["raised"])
        big = self.advised(60)                                                           # 6 of 60 = 10% < 20%
        pre, children = self.children_after(big, ["opus"] * 6 + ["haiku"] * 54)
        self.assertFalse(calibration.suggest_threshold(big + pre, children, POLICY, NOW)["raised"])

    def test_a_delegation_in_another_turn_or_after_the_window_is_not_a_follow_up(self):
        advice = self.advised(30)
        pre, children = self.children_after(advice, ["opus"] * 30)
        for p in pre:
            p["turn_id"] = "other"
        self.assertEqual(calibration.suggest_threshold(advice + pre, children, POLICY, NOW)["followups"], 0)
        pre, children = self.children_after(advice, ["opus"] * 30)
        for p in pre:
            p["ts"] += 700
        self.assertEqual(calibration.suggest_threshold(advice + pre, children, POLICY, NOW)["followups"], 0)

    def test_the_window_can_be_limited_to_newer_data(self):
        rows = [row(n, .9) for n in range(40)]
        self.assertEqual(calibration.suggest_threshold(rows, [], POLICY, NOW, since=NOW)["status"], "insufficient")


class MenuTests(unittest.TestCase):
    def test_threshold_menu_shows_the_suggestion_computed_from_the_stored_rows_and_never_in_status(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        path = Path(tmp.name).resolve() / "owned" / "settings.json"; v2.init(path)
        store = AdviceStore(path.parent / "advice.sqlite3")
        import time
        now = time.time()
        for n in range(40):
            req = AdvisoryRequest("claude", f"s{n}", "t", f"c{n}", f"task {n}")
            store.save(request_id("claude", f"s{n}", "t", f"c{n}"), req, task_hash("claude", f"s{n}", f"task {n}"),
                       Advice("advise", "advice_given", "Light", 0.6 + n * 0.005, ({"model": "haiku"},)), "jev", now - n)
        out = io.StringIO()
        script = "\n".join(["5", "0.7", "14"]) + "\n"                               # threshold entry, a value, quit
        class Tty(io.StringIO):
            def isatty(self): return True
            def fileno(self): raise OSError
        ctrl.main(Namespace(settings=path, width=100, json=False, ctrl_action=None), stdin=Tty(script), stdout=out, stderr=io.StringIO())
        text = out.getvalue()
        self.assertIn("建議：", text); self.assertIn("依最近 30 天 40 次分級", text)
        status = ctrl.dashboard_text(path, 7, 100, False)
        self.assertNotIn("建議：", status)


if __name__ == "__main__":
    unittest.main()
