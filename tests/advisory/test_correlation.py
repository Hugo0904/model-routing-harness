import io
import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from mrh.advisory import engine
from mrh.advisory.request import Advice, AdvisoryRequest, Child
from mrh.advisory.store import AdviceStore, request_id, task_hash
from mrh.infrastructure import settings_v2 as v2
from mrh.presentation import cli, ctrl, dashboard, report_html, stats_view
from mrh.routing.core import ClassifierFailure
from tests.advisory.test_engine import Fake, LISTS, settings


class CorrelationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name).resolve() / "owned" / "settings.json"; v2.init(self.path)
        self.store = AdviceStore(self.path.parent / "advice.sqlite3")
        self.now = 1000

    def request(self, call, **changes):
        values = dict(platform="codex", session_id="s", turn_id="t", call_id=call, task="sort three words")
        values.update(changes)
        return AdvisoryRequest(**values)

    def decide(self, request):
        return engine.decide(request, settings(**LISTS), self.store,
                             lambda: Fake(__import__('mrh.routing.types', fromlist=['Classification']).Classification("Light", .9)),
                             clock=lambda: self.now)

    def seed(self):
        return self.decide(self.request("original"))

    def replacement(self, call="replacement", **changes):
        values = dict(explicit_model="luna", explicit_effort="low"); values.update(changes)
        return self.request(call, **values)

    def test_same_task_replay_and_exact_post_preserve_requested_observation_boundary(self):
        self.seed(); req = self.replacement()
        self.assertEqual(self.decide(req).reason, "advice_reissue")
        self.assertEqual(self.decide(req).reason, "advice_reissue")
        child = Child("codex", "s", "replacement", "luna", "low", None, "agent")
        self.assertTrue(self.store.record_child(child, self.now))
        self.assertTrue(self.store.record_child(child, self.now))
        self.assertFalse(self.store.record_child(Child("codex", "s", "unrelated", "luna", "low", "real-luna", "other"), self.now))
        data = self.store.stats(0)
        self.assertEqual((data["decisions"], data["kept_unchanged"], data["reissues"]), ({"advise": 1}, {}, 1))
        self.assertEqual((data["children_started"], data["children_following_advice"]), (2, 1))
        self.assertEqual(data["followed_models"], {})
        self.assertEqual(data["followed_requested_models"], {"luna": 1})
        for text in (stats_view.render(data, "全部"), report_html.render(v2.read(self.path), data, "全部")):
            self.assertIn("實際模型未回報", text)
        # The status card stays short: it points at `mrh stats` for the evidence caveats instead of listing them.
        self.assertIn("資料說明，見 mrh stats", dashboard.render(v2.read(self.path), data, "全部"))
        before = self.path.parent.joinpath('advice.sqlite3').read_bytes()
        out = io.StringIO()
        self.assertEqual(cli.main(["status", "--settings", str(self.path), "--days", "0", "--json"], stdout=out, stderr=io.StringIO()), 0)
        exported = json.loads(out.getvalue()); exported.pop("status")
        self.assertEqual(exported, data)
        self.assertEqual(self.path.parent.joinpath('advice.sqlite3').read_bytes(), before)

    def test_different_task_turn_session_platform_effort_or_window_is_not_reissue(self):
        self.seed()
        for n, changes in enumerate((dict(turn_id="other"), dict(session_id="other"),
                                     dict(platform="claude"), dict(explicit_effort="high"), dict(explicit_effort=None))):
            with self.subTest(changes=changes):
                # Construct without duplicate keyword keys.
                base = self.replacement(str(n)).__dict__.copy(); base.update(changes)
                self.assertEqual(self.decide(AdvisoryRequest(**base)).reason, "explicit_model")
        self.now = 999
        self.assertEqual(self.decide(self.replacement("future-original")).reason, "explicit_model")
        self.now = 1601
        self.assertEqual(self.decide(self.replacement("expired")).reason, "explicit_model")
        self.now = 1600
        self.assertEqual(self.decide(self.replacement("boundary")).reason, "advice_reissue")

    def test_reworded_task_still_counts_and_parallel_spawns_pair_one_to_one(self):
        self.seed(); self.decide(self.request("second", task="another parallel job"))
        for n, task in enumerate(("sort the three words please", "another parallel job, tidied")):
            self.assertEqual(self.decide(self.replacement(f"r{n}", task=task)).reason, "advice_reissue")
        self.assertEqual(self.decide(self.replacement("r2")).reason, "explicit_model")     # both suggestions are used up
        for n in range(2):
            self.assertTrue(self.store.record_child(Child("codex", "s", f"r{n}", "luna", "low", None, f"a{n}"), self.now))
        self.assertEqual(self.store.stats(0)["children_following_advice"], 2)

    def test_two_replacements_compete_atomically_and_only_one_claims(self):
        self.seed(); barrier = threading.Barrier(2)
        def run(n):
            barrier.wait(); return self.decide(self.replacement(str(n))).reason
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertCountEqual(list(pool.map(run, [1, 2])), ["advice_reissue", "explicit_model"])
        self.assertEqual(self.store.stats(0)["decisions"], {"advise": 1, "preserve": 1})

    def test_older_rows_without_a_recorded_link_are_inferred_by_turn_and_model_without_rewriting_them(self):
        self.seed(); req = self.request("duplicate")
        self.store.save("duplicate", req, task_hash("codex", "s", req.task), Advice("advise", "advice_given", "Light", .9, ({"model": "luna", "effort": "low"},)), "jev", self.now)
        self.assertEqual(self.decide(self.replacement()).reason, "advice_reissue")            # claims the oldest of the two
        old = self.request("old")
        self.store.save("old", old, task_hash("codex", "s", old.task), Advice("preserve", "advice_reissue"), "jev", self.now)
        with self.store.connect() as db:
            db.execute("INSERT INTO children VALUES(?,?,?,?,?,?,?,?,?,?)", ("old", "codex", "s", self.now, "luna", "low", "real-luna", "old-agent", None, 0))
            before = [tuple(r) for r in db.execute("SELECT * FROM children")]
        data = self.store.stats(0)
        self.assertEqual((data["reissues"], data["inferred_links"], data["unverified_reissues"]), (2, 1, 0))
        self.assertEqual((data["children_following_advice"], data["followed_models"]), (1, {"real-luna": 1}))
        self.assertEqual(data["decisions"], {"advise": 2})                                    # re-issues are not separate delegations
        with self.store.connect() as db:
            self.assertEqual([tuple(r) for r in db.execute("SELECT * FROM children")], before)   # nothing is rewritten

    def test_failure_and_replayed_attempts_count_without_fabricating_cost(self):
        bad = Fake(error=ClassifierFailure("typesafe_missing_credentials"))
        engine.decide(self.request("missing"), settings(**LISTS), self.store, lambda: bad, clock=lambda: self.now)
        for _ in range(2):
            for outcome in ("requested", "started", "error"):
                self.store.attempt("failed", "jev", outcome, self.now)
            self.store.attempt("success", "jev", "returned", self.now, input_tokens=100, output_tokens=4)
        data = self.store.stats(0)
        self.assertEqual((data["classifier_requests"], data["classifier_calls"], data["classifier_failed_requests"], data["classifier_input_tokens"]), (3, 2, 2, 100))
        self.assertIn("缺少用量仍未知", stats_view.render(data, "全部"))

    def test_missing_settings_export_does_not_create_files(self):
        missing = self.path.parent / "absent" / "settings.json"
        self.assertEqual(cli.main(["status", "--settings", str(missing), "--json"], stdout=io.StringIO(), stderr=io.StringIO()), 2)
        self.assertFalse(missing.parent.exists())
