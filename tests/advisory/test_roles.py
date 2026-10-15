import json
import re
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from mrh.advisory.request import Advice, AdvisoryRequest, Child
from mrh.advisory.store import AdviceStore, candidates, request_id, task_hash
from mrh.presentation import dashboard, stats_view
from mrh.presentation.terminal import cell_width
from tests.presentation.test_dashboard import settings

ANSI = re.compile(r"\x1b\[[0-9;]*m")


class RoleRecordingTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.db = Path(tmp.name) / "advice.sqlite3"
        self.store = AdviceStore(self.db)
        self.now = time.time()

    def explicit(self, call, model, effort, role=None, platform="codex"):
        req = AdvisoryRequest(platform, "s", "t", call, f"task {call}", model, effort, role)
        self.store.preserve_explicit(request_id(platform, "s", "t", call), req, task_hash(platform, "s", f"task {call}"), "jev", self.now)
        self.store.record_child(Child(platform, "s", call, model, effort, None, "a-" + call), self.now)

    def save(self, call, action, reason, role=None, platform="codex", cands=()):
        req = AdvisoryRequest(platform, "s", "t", call, f"task {call}", role=role)
        self.store.save(request_id(platform, "s", "t", call), req, task_hash(platform, "s", f"task {call}"),
                        Advice(action, reason, "Light" if action == "advise" else None, .9 if action == "advise" else None, cands), "jev", self.now)

    def rows(self):
        with sqlite3.connect(self.db) as db:
            db.row_factory = sqlite3.Row
            return {r["call_id"]: r for r in db.execute("SELECT * FROM advice")}

    def test_role_is_kept_in_the_existing_json_field_and_candidates_still_read(self):
        self.explicit("w1", "gpt-6-luna", "max", "luna_worker")
        self.save("n1", "advise", "advice_given", cands=({"model": "gpt-6-luna", "effort": "high"},))
        self.save("e1", "preserve", "named_role", role="Explore", platform="claude")
        rows = self.rows()
        self.assertEqual(json.loads(rows["w1"]["candidates"])["role"], "luna_worker")
        self.assertIsNone(json.loads(rows["n1"]["candidates"])["role"])
        self.assertEqual(candidates(rows["n1"]), ({"model": "gpt-6-luna", "effort": "high"},))
        self.assertEqual(json.loads(rows["e1"]["candidates"])["role"], "Explore")

    def test_unsafe_role_text_is_not_stored(self):
        self.save("x1", "preserve", "named_role", role="bad role; DROP")
        self.assertEqual(json.loads(self.rows()["x1"]["candidates"])["role"], "other")

    def test_statistics_split_skill_roles_other_explicit_picks_and_older_rows(self):
        self.explicit("w1", "gpt-6-luna", "max", "luna_worker")
        self.explicit("w2", "gpt-6.1-sol", "high", "sol_worker")
        self.explicit("m1", "haiku", "high", platform="claude")          # explicit, but no skill role
        self.save("n1", "advise", "advice_given", cands=({"model": "gpt-6-luna", "effort": "high"},))
        req = AdvisoryRequest("codex", "s", "t", "old", "task old")      # an older row: plain list, no role key
        with sqlite3.connect(self.db) as db:
            db.execute("INSERT INTO advice VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       ("r-old", self.now, "codex", "s", "t", "old", task_hash("codex", "s", "task old"),
                        "preserve", "explicit_model", None, None, "jev", "[]"))
        self.store.record_child(Child("codex", "s", "inherit", None, None, None, "a-inherit"), self.now)
        data = self.store.stats(0)
        self.assertEqual(data["roles"], {"luna_worker": 1, "sol_worker": 1})
        self.assertEqual(stats_view.skill_roles(data), {"luna_worker": 1, "sol_worker": 1})
        self.assertEqual(data["explicit_without_role"], 1)
        self.assertEqual(data["role_recorded"], 4)
        self.assertEqual(data["children_inherited"], 1)
        self.assertEqual(stats_view.rerouted(data), (2, 5))               # 2 skill picks of 5 delegations; the advice was not followed
        self.assertAlmostEqual(data["confidence"]["total"]["avg"], .9); self.assertEqual(data["confidence"]["total"]["n"], 1)
        self.assertEqual(data["confidence"]["last_24h"], data["confidence"]["total"])
        self.assertEqual(data["children_models"], {"codex": {"gpt-6-luna": 1, "gpt-6.1-sol": 1}, "claude": {"haiku": 1}})
        policy = settings()["policy"]                                     # tiers: haiku, gpt-5.6-luna, sonnet
        self.assertEqual(stats_view.tier_model_children(data, policy), (1, 4))
        notes = " ".join(stats_view.skill_notes(data))
        self.assertIn("另有 1 次主模型自選", notes)
        self.assertNotIn("未記錄角色", notes)

    def test_status_card_shows_both_bars_and_keeps_its_width(self):
        self.explicit("w1", "gpt-6-luna", "max", "luna_worker")
        self.save("n1", "advise", "advice_given", cands=({"model": "gpt-6-luna", "effort": "high"},))
        data = self.store.stats(0)
        for width in (80, 100, 120):
            for color in (False, True):
                with self.subTest(width=width, color=color):
                    text = ANSI.sub("", dashboard.render(settings(), data, "過去 7 天", width, color, today="2026-10-15"))
                    for expected in ("有改派（MRH＋skill）", "skill 自選 1 次", "luna_worker 1", "由 Router skill 自己選模型派工", "子代理用了分級表的模型", "平均信心度 · 24 小時內", "平均信心度 · 總平均", "0.90"):
                        self.assertIn(expected, text)
                    card = [l for l in text.splitlines() if l[:1] in "│╭╰" and cell_width(l) > 40]
                    self.assertEqual({cell_width(l) for l in card}, {width})
        text = stats_view.render(data, "全部紀錄", 0.65, False, settings()["policy"])
        for expected in ("Router skill 自己選模型派工", "■ 改派的效果", "skill 自選 1 次（luna_worker 1）", "■ 子代理實際用的模型"):
            self.assertIn(expected, text)


if __name__ == "__main__":
    unittest.main()
