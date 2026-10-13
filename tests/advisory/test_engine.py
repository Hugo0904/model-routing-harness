import tempfile
import unittest
from pathlib import Path

from mrh.advisory import engine
from mrh.advisory.request import AdvisoryRequest
from mrh.advisory.store import AdviceStore
from mrh.infrastructure import settings_v2 as v2
from mrh.routing.core import ClassifierFailure
from mrh.routing.types import Classification


class Fake:
    """Stands in for a provider; records how often it was called."""
    def __init__(self, result=None, error=None, delay=0):
        self.result, self.error, self.delay, self.calls = result, error, delay, 0

    def classify(self, task, context, recorder):
        self.calls += 1
        if self.delay:
            import time; time.sleep(self.delay)
        if self.error:
            raise self.error
        return self.result


def settings(**policy):
    base = v2.default_settings()
    base["enabled"] = base["task_export_permitted"] = True
    base["classifier"] = {**base["classifier"], "timeout_seconds": 1}
    base["policy"] = v2.validate({**base, "policy": policy})["policy"]
    return base


LISTS = {"tiers": {"Light": {"codex": [{"model": "luna", "effort": "low"}, {"model": "luna-b"}], "claude": [{"model": "haiku"}]}},
         "fixed": {"codex": [{"model": "sol", "effort": "high"}]}}


def req(call="c1", task="rename a variable", **kw):
    return AdvisoryRequest(**{"platform": "codex", "session_id": "s", "turn_id": "t", "call_id": call, "task": task, **kw})


class EngineTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.store = AdviceStore(Path(tmp.name) / "advice.sqlite3")

    def run_engine(self, request, fake, **policy):
        return engine.decide(request, settings(**(policy or LISTS)), self.store, lambda: fake)

    def test_explicit_choices_are_respected_without_classifying(self):
        fake = Fake(Classification("Light", 0.9))
        for n, kw in enumerate(({"explicit_model": "x"}, {"explicit_effort": "high"}, {"role": "reviewer"})):
            advice = self.run_engine(req(f"c{n}", **kw), fake)
            self.assertEqual(advice.action, "preserve")
        self.assertEqual(fake.calls, 0)

    def test_only_habitual_generic_roles_are_classified_specialised_ones_are_respected(self):
        fake = Fake(Classification("Light", 0.9))
        self.assertEqual(self.run_engine(req("w", role="worker"), fake).action, "advise")        # Codex sends `worker` on nearly every spawn
        for n, role in enumerate(("luna_worker", "risk_reviewer", "explorer")):
            self.assertEqual(self.run_engine(req(f"r{n}", task=f"t{n}", role=role), fake).reason, "named_role")
        custom = settings(**LISTS, generic_roles={"codex": ["explorer"]})
        self.assertEqual(engine.decide(req("x", task="other", role="explorer"), custom, self.store, lambda: fake).action, "advise")
        self.assertEqual(engine.decide(req("y", task="other2", role="worker"), custom, self.store, lambda: fake).reason, "named_role")

    def test_a_call_carrying_the_advised_model_is_a_reissue_not_a_new_delegation(self):
        fake = Fake(Classification("Light", 0.9))
        self.run_engine(req("c1"), fake)                                              # advises luna
        same_session = self.run_engine(req("c2", task="again", explicit_model="luna"), fake)
        self.assertEqual(same_session.reason, "advice_reissue")
        other = self.run_engine(req("c3", task="x", explicit_model="some-other-model"), fake)
        self.assertEqual(other.reason, "explicit_model")                              # a model nobody suggested is the parent's own choice
        stats = self.store.stats(0)
        self.assertEqual((stats["reissues"], stats["decisions"]), (1, {"advise": 1, "preserve": 1}))   # the re-issue is not counted twice

    def test_light_advice_lists_candidates_in_user_order_for_the_calling_platform(self):
        advice = self.run_engine(req(), Fake(Classification("Light", 0.9)))
        self.assertEqual((advice.action, advice.tier), ("advise", "Light"))
        self.assertEqual([c["model"] for c in advice.candidates], ["luna", "luna-b"])
        claude = self.run_engine(req("c2", task="other", platform="claude"), Fake(Classification("Light", 0.9)))
        self.assertEqual([c["model"] for c in claude.candidates], ["haiku"])

    def test_threshold_empty_lists_and_top_modes(self):
        self.assertEqual(self.run_engine(req("a"), Fake(Classification("Light", 0.49))).reason, "low_confidence")
        self.assertEqual(self.run_engine(req("b", task="x2"), Fake(Classification("Mid", 0.9))).reason, "no_candidates_for_platform")
        self.assertEqual(self.run_engine(req("c", task="x3"), Fake(Classification("Top", 0.9))).action, "continue_main")
        fixed = self.run_engine(req("d", task="x4"), Fake(Classification("Top", 0.9)), **LISTS, top_mode="Fixed")
        self.assertEqual((fixed.action, fixed.candidates[0]["model"]), ("advise", "sol"))
        strict = self.run_engine(req("e", task="x5"), Fake(Classification("Light", 0.7)), **LISTS, threshold=0.8)
        self.assertEqual(strict.reason, "low_confidence")

    def test_same_task_is_advised_once_and_a_replayed_call_is_not_reclassified(self):
        fake = Fake(Classification("Light", 0.9))
        first = self.run_engine(req("c1"), fake)
        again = self.run_engine(req("c2"), fake)                   # model ignored the advice and retried unchanged
        self.assertEqual((first.action, again.action, again.reason), ("advise", "preserve", "advice_already_given"))
        replay = self.run_engine(req("c1"), fake)                  # the host retried the same hook call
        self.assertEqual((replay.action, replay.request_id), ("advise", first.request_id))
        self.assertEqual(fake.calls, 1)

    def test_classifier_failures_keep_the_call_and_warn_once_per_session(self):
        for reason in ("typesafe_http_402", "typesafe_missing_credentials"):
            fake = Fake(error=ClassifierFailure(reason))
            first = self.run_engine(req(f"{reason}-1", task=reason), fake)
            second = self.run_engine(req(f"{reason}-2", task=reason + " again"), fake)
            self.assertEqual((first.action, first.reason), ("preserve", reason))
            self.assertIn("proceeds unchanged", first.notice)
            self.assertIsNone(second.notice)
        timed = self.run_engine(req("slow", task="slow"), Fake(Classification("Light", 0.9), delay=3))
        self.assertEqual(timed.reason, "classifier_timeout")
        weird = self.run_engine(req("bad", task="bad"), Fake(result="not a classification"))
        self.assertEqual(weird.reason, "malformed_classification")
        crash = self.run_engine(req("boom", task="boom"), Fake(error=RuntimeError("traceback with /secret/path")))
        self.assertEqual((crash.reason, crash.notice is None), ("classifier_error", False))
        self.assertNotIn("secret", crash.notice)

    def test_following_advice_is_recorded_once(self):
        from mrh.advisory.request import Child
        self.run_engine(req("c1"), Fake(Classification("Light", 0.9)))
        child = Child("codex", "s", "k1", "luna", "low", None, "agent-1")
        self.assertTrue(self.store.record_child(child, __import__("time").time()))
        other = Child("codex", "s", "k2", "luna", "low", None, "agent-2")   # the advice was already consumed
        self.assertFalse(self.store.record_child(other, __import__("time").time()))
        self.assertEqual(self.store.stats(0)["children_following_advice"], 1)


if __name__ == "__main__":
    unittest.main()
