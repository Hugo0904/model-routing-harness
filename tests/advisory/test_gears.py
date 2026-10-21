import tempfile
import unittest
from pathlib import Path

from mrh.advisory import advice_text, engine
from mrh.advisory.store import AdviceStore, payload
from mrh.infrastructure import settings_v2 as v2
from mrh.infrastructure.settings_schema import SettingsError
from mrh.routing.types import Classification
from tests.advisory.test_engine import Fake, req, settings

GEARS = [
    {"from": 0, "candidates": {"claude": [{"model": "haiku", "effort": "medium"}], "codex": [{"model": "luna", "effort": "high"}]}},
    {"from": 0.75, "candidates": {"claude": [{"model": "haiku", "effort": "xhigh"}]}},
    {"from": 1.5, "candidates": {"claude": [{"model": "sonnet", "effort": "high"}], "codex": [{"model": "sol", "effort": "high"}]}},
    {"from": 2.25, "main": True},
    {"from": 2.75, "candidates": {"claude": [{"model": "opus", "effort": "xhigh"}]}},
]


def gear_settings(gears=GEARS, threshold=0.65):
    s = settings()
    s["policy"] = v2.validate({**s, "policy": {"threshold": threshold, "top_mode": "Main", "mode": "gears", "gears": gears}})["policy"]
    return s


def probs(light=0.0, small=0.0, mid=0.0, top=0.0):
    return {"Light": light, "Small": small, "Mid": mid, "Top": top}


class ValidationTests(unittest.TestCase):
    def check(self, gears, ok=True):
        policy = {"threshold": 0.65, "mode": "gears", "gears": gears}
        if ok:
            return v2.validate({**settings(), "policy": policy})["policy"]
        with self.assertRaises(SettingsError):
            v2.validate({**settings(), "policy": policy})

    def test_a_well_formed_ladder_is_accepted_and_main_gears_keep_only_main(self):
        policy = self.check(GEARS)
        self.assertEqual(policy["mode"], "gears"); self.assertEqual(len(policy["gears"]), 5); self.assertEqual(policy["gears"][3], {"from": 2.25, "main": True})

    def test_the_rules(self):
        c = {"claude": [{"model": "haiku"}]}
        self.check([], ok=False)                                                            # at least one gear
        self.check([{"from": 0.5, "candidates": c}], ok=False)                              # first must start at 0
        self.check([{"from": 0, "candidates": c}, {"from": 0, "candidates": c}], ok=False)  # strictly increasing
        self.check([{"from": 0, "candidates": c}, {"from": 1, "candidates": c}, {"from": 0.5, "candidates": c}], ok=False)
        self.check([{"from": 0, "candidates": c}, {"from": 3.5, "candidates": c}], ok=False)  # within 0..3
        self.check([{"from": 0, "candidates": c, "main": True}], ok=False)                  # candidates xor main
        self.check([{"from": 0}], ok=False)
        self.check([{"from": 0, "main": False}], ok=False)
        self.check([{"from": 0, "candidates": {"unknown-host": []}}], ok=False)             # unknown platform
        self.check([{"from": 0, "candidates": c, "extra": 1}], ok=False)
        self.check([{"from": float("nan"), "candidates": c}], ok=False)
        self.check([{"from": 0, "candidates": c}] + [{"from": i, "candidates": c} for i in (0.3, 0.6, 0.9, 1.2, 1.5, 1.8, 2.1)], ok=True)   # 8 gears
        self.check([{"from": 0, "candidates": c}] + [{"from": i / 10, "candidates": c} for i in range(1, 9)], ok=False)                  # 9 gears

    def test_nothing_is_stored_unless_gears_are_on_so_existing_settings_do_not_change(self):
        s = settings()
        self.assertNotIn("mode", s["policy"]); self.assertNotIn("gears", s["policy"]); self.assertEqual(v2.mode(s["policy"]), "tiers")
        draft = v2.validate({**s, "policy": {**s["policy"], "gears": GEARS}})["policy"]       # a draft kept while mode is tiers
        self.assertNotIn("mode", draft); self.assertEqual(len(draft["gears"]), 5)


class ScoreTests(unittest.TestCase):
    def test_expectation_over_the_four_probabilities_or_the_tier_weight(self):
        self.assertAlmostEqual(v2.difficulty_score("Mid", probs(0.1, 0.1, 0.6, 0.2)), 0.1 + 1.2 + 0.6)
        self.assertEqual(v2.difficulty_score("Top"), 3.0); self.assertEqual(v2.difficulty_score("Light", None), 0.0)
        self.assertEqual(v2.difficulty_score("Small", {"Light": 1.0}), 1.0)                      # incomplete probabilities are not used

    def test_gear_boundaries_belong_to_the_higher_gear(self):
        for score, number in ((0, 1), (0.74, 1), (0.75, 2), (1.49, 2), (1.5, 3), (2.25, 4), (2.74, 4), (2.75, 5), (3, 5)):
            self.assertEqual(v2.gear_for(GEARS, score)[0], number, score)


class EngineGearTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.store = AdviceStore(Path(tmp.name) / "advice.sqlite3")

    def decide(self, call, result, platform="claude", s=None):
        return engine.decide(req(call, task=f"task {call}", platform=platform), s or gear_settings(), self.store, lambda: Fake(result))

    def row(self, call):
        import sqlite3
        from contextlib import closing
        with closing(sqlite3.connect(self.store.path)) as db:
            db.row_factory = sqlite3.Row
            return db.execute("SELECT * FROM advice WHERE call_id=?", (call,)).fetchone()

    def test_the_score_picks_the_gear_and_both_are_recorded(self):
        result = Classification("Mid", 0.7, probabilities=probs(0.0, 0.1, 0.7, 0.2), model="jev-1.13.0")     # score 0.1+1.4+0.6 = 2.1
        advice = self.decide("a", result)
        self.assertEqual((advice.action, advice.candidates), ("advise", ({"model": "sonnet", "effort": "high"},)))
        meta = payload(self.row("a")); self.assertEqual((meta["gear"], meta["score"]), (3, 2.1))
        self.assertIn("tier Mid, gear 3", advice_text.advise("claude", advice.tier, advice.confidence, advice.candidates, 3))

    def test_a_main_gear_hands_back_and_a_gear_without_the_platform_is_kept(self):
        hard = Classification("Mid", 0.7, probabilities=probs(0.0, 0.0, 0.5, 0.5), model="jev-1.13.0")        # score 2.5 -> gear 4 (main)
        advice = self.decide("b", hard)
        self.assertEqual((advice.action, advice.reason), ("continue_main", "gear_main")); self.assertEqual(payload(self.row("b"))["gear"], 4)
        easy_codex = Classification("Light", 0.9, probabilities=probs(0.1, 0.8, 0.1, 0.0))                     # score 1.0 -> gear 2, no codex
        advice = self.decide("c", easy_codex, platform="codex")
        self.assertEqual((advice.action, advice.reason), ("preserve", "no_candidates_for_platform"))

    def test_the_confidence_threshold_still_applies_and_without_probabilities_the_tier_weight_is_used(self):
        self.assertEqual(self.decide("d", Classification("Mid", 0.3, probabilities=probs(0.2, 0.2, 0.3, 0.3))).reason, "low_confidence")
        advice = self.decide("e", Classification("Top", 0.9))                                                  # subscription classifier: score 3.0
        self.assertEqual(advice.candidates, ({"model": "opus", "effort": "xhigh"},)); self.assertEqual(payload(self.row("e"))["gear"], 5)

    def test_tiers_mode_is_untouched_and_records_no_gear(self):
        s = settings(tiers={"Light": {"claude": [{"model": "haiku"}]}})
        advice = engine.decide(req("f", task="task f", platform="claude"), s, self.store,
                               lambda: Fake(Classification("Light", 0.9, probabilities=probs(0.9, 0.1, 0.0, 0.0))))
        self.assertEqual(advice.candidates, ({"model": "haiku"},)); self.assertNotIn("gear", payload(self.row("f")))
        self.assertNotIn("gear", advice_text.advise("claude", "Light", .9, advice.candidates))


if __name__ == "__main__":
    unittest.main()
