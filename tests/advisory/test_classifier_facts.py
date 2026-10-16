import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from mrh.advisory import engine
from mrh.advisory.store import AdviceStore, candidates, payload
from mrh.routing.types import Classification
from tests.advisory.test_engine import Fake, LISTS, req, settings

PROBS = {"Light": 0.62, "Small": 0.21, "Mid": 0.12345678, "Top": 0.04654322}


class ClassifierFactsTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.db = Path(tmp.name) / "advice.sqlite3"
        self.store = AdviceStore(self.db)

    def rows(self):
        with sqlite3.connect(self.db) as db:
            db.row_factory = sqlite3.Row
            return {r["call_id"]: r for r in db.execute("SELECT * FROM advice")}

    def decide(self, call, result, **policy):
        return engine.decide(req(call, task=f"task {call}"), settings(**(policy or LISTS)), self.store, lambda: Fake(result))

    def test_probabilities_and_answering_model_are_kept_for_advice_top_and_low_confidence(self):
        full = Classification("Light", .9, probabilities=PROBS, model="jev-1.13.0")
        self.decide("advise", full)
        self.decide("top", Classification("Top", .9, probabilities=PROBS, model="jev-1.13.0"))
        self.decide("low", Classification("Light", .2, probabilities=PROBS, model="jev-1.13.0"))
        rows = self.rows()
        self.assertEqual([rows[k]["action"] for k in ("advise", "top", "low")], ["advise", "continue_main", "preserve"])
        for call in ("advise", "top", "low"):
            meta = payload(rows[call])
            self.assertEqual(meta["probabilities"], {"Light": 0.62, "Small": 0.21, "Mid": 0.1235, "Top": 0.0465})   # 4 decimals
            self.assertEqual(meta["classifier_model"], "jev-1.13.0")
        self.assertEqual(candidates(rows["advise"]), ({"model": "luna", "effort": "low"}, {"model": "luna-b"}))     # candidates untouched

    def test_classifiers_without_probabilities_write_neither_key(self):
        self.decide("sub", Classification("Light", .9))
        meta = payload(self.rows()["sub"])
        self.assertNotIn("probabilities", meta); self.assertNotIn("classifier_model", meta)

    def test_malformed_probabilities_or_model_are_dropped_not_stored(self):
        bad = Classification("Light", .9, probabilities={"Light": 1.0}, model="Bearer abc")
        self.decide("bad", bad)
        meta = payload(self.rows()["bad"])
        self.assertNotIn("probabilities", meta); self.assertNotIn("classifier_model", meta)
        wrong = Classification("Light", .9, probabilities={**PROBS, "Top": float("nan")}, model="jev-1.13.0")
        self.decide("nan", wrong)
        self.assertNotIn("probabilities", payload(self.rows()["nan"]))

    def test_rows_written_before_this_change_still_read_and_the_column_layout_is_unchanged(self):
        with sqlite3.connect(self.db) as db:
            columns = [r[1] for r in db.execute("PRAGMA table_info(advice)")]
            db.execute("INSERT INTO advice VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       ("old", 1.0, "codex", "s", "t", "old", "h", "advise", "advice_given", "Light", .9, "jev",
                        json.dumps([{"model": "luna"}])))
        self.assertEqual(columns, ["request_id", "ts", "platform", "session_id", "turn_id", "call_id", "task_hash", "action",
                                   "reason", "tier", "confidence", "provider", "candidates"])
        old = self.rows()["old"]
        self.assertEqual(candidates(old), ({"model": "luna"},)); self.assertNotIn("probabilities", payload(old))
        self.assertEqual(self.store.stats(0)["decisions"], {"advise": 1})


if __name__ == "__main__":
    unittest.main()
