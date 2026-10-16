import io
import json
import sqlite3
import tempfile
import time
import unittest
from argparse import Namespace
from pathlib import Path

from mrh.advisory.request import Advice, AdvisoryRequest, Child
from mrh.advisory.store import AdviceStore
from mrh.infrastructure import settings_v2 as v2
from mrh.presentation import ctrl, stats_reset

NOW = 1_800_000_000          # a fixed "now" so day boundaries are exact
DAY = 86400


class Tty(io.StringIO):
    def isatty(self): return True
    def fileno(self): raise OSError          # numbered fallback menu, not raw key reads


class ResetTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name).resolve() / "owned" / "settings.json"; v2.init(self.path)
        self.store = AdviceStore(self.path.parent / "advice.sqlite3")
        # one delegation (+ classifier call + child + notice) at 0.5, 3, 10 and 40 days ago
        for n, age in enumerate((0.5, 3, 10, 40)):
            ts = NOW - age * DAY
            req = AdvisoryRequest("claude", f"s{n}", "t", f"c{n}", "task")
            self.store.save(f"r{n}", req, f"h{n}", Advice("advise", "advice_given", "Light", .9, ({"model": "haiku"},)), "jev", ts)
            self.store.attempt(f"r{n}", "jev", "returned", ts, input_tokens=400, output_tokens=40)
            self.store.record_child(Child("claude", f"s{n}", f"c{n}", "haiku", None, "claude-haiku-5-5", f"a{n}"), ts)
            self.store.first_notice(f"s{n}", "typesafe_http_401", ts)

    def rows(self):
        with sqlite3.connect(self.store.path) as db:
            return {t: db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in AdviceStore.TABLES}

    def test_a_range_removes_exactly_the_newer_rows_from_every_table_and_the_database_keeps_working(self):
        cutoff = stats_reset.cutoff_for("days", 7, NOW)
        preview = self.store.preview_since(cutoff)
        self.assertEqual(preview["delete"], {t: 2 for t in AdviceStore.TABLES})       # 0.5 and 3 days ago
        self.assertEqual(preview["keep"], {t: 2 for t in AdviceStore.TABLES})
        self.assertEqual(self.rows(), {t: 4 for t in AdviceStore.TABLES})            # preview wrote nothing
        self.assertEqual(sum(self.store.delete_since(cutoff).values()), 8)
        self.assertEqual(self.rows(), {t: 2 for t in AdviceStore.TABLES})
        self.store.save("again", AdvisoryRequest("claude", "s", "t", "x", "task"), "h", Advice("preserve", "named_role"), "jev", NOW)
        self.assertEqual(self.rows()["advice"], 3)

    def test_last_24_hours_removes_only_the_newest_delegation_and_is_described_in_hours(self):
        cutoff = stats_reset.cutoff_for("hours", 24, NOW)
        self.assertEqual(cutoff, NOW - DAY)
        self.assertEqual(stats_reset.describe("hours", 24), "最近 24 小時內")
        self.assertEqual(self.store.preview_since(cutoff)["delete"], {t: 1 for t in AdviceStore.TABLES})   # only the 0.5-day-old one
        out, err = io.StringIO(), io.StringIO()
        code = ctrl.main(Namespace(settings=self.path, width=100, json=False, ctrl_action="reset", all=False, today=False,
                                   reset_hours=24, reset_days=None, yes=False), stdin=io.StringIO(), stdout=out, stderr=err)
        self.assertEqual(code, 0, err.getvalue())
        self.assertIn("最近 24 小時內", out.getvalue())
        self.assertEqual(self.rows(), {t: 4 for t in AdviceStore.TABLES})              # no --yes: preview only

    def test_today_starts_at_local_midnight_and_all_removes_everything(self):
        midnight = stats_reset.cutoff_for("today", None, NOW)
        local = time.localtime(NOW)
        self.assertEqual(time.localtime(midnight)[3:6], (0, 0, 0))
        self.assertEqual(time.localtime(midnight)[:3], local[:3])
        self.assertLessEqual(NOW - midnight, DAY + 3700)                              # at most a day (DST aside)
        self.store.delete_since(stats_reset.cutoff_for("all", None, NOW))
        self.assertEqual(self.rows(), {t: 0 for t in AdviceStore.TABLES})

    def test_confirmation_must_be_typed_exactly_and_scripts_need_yes(self):
        def attempt(**kw):
            out = io.StringIO()
            stats_reset.run(self.store, "all", None, out=out, now=NOW, **kw)
            return out.getvalue()
        total = sum(self.rows().values())
        self.assertIn("沒有刪除", attempt(yes=False, interactive=True, ask=lambda p: "yes"))
        self.assertIn("沒有刪除", attempt(yes=False, interactive=True, ask=lambda p: f"刪除 {total - 1}"))
        self.assertIn("加上 --yes", attempt(yes=False, interactive=False, ask=lambda p: self.fail("must not prompt")))
        self.assertEqual(sum(self.rows().values()), total)                           # nothing deleted so far
        self.assertIn(f"已刪除 {total} 筆", attempt(yes=False, interactive=True, ask=lambda p: f"  刪除   {total} "))
        self.assertEqual(sum(self.rows().values()), 0)
        self.assertIn("沒有資料", attempt(yes=True, interactive=False, ask=None))

    def test_reset_never_touches_settings_and_menu_flow_deletes_after_typed_confirmation(self):
        before = self.path.read_bytes()
        total = sum(self.rows().values())
        out, err = io.StringIO(), io.StringIO()
        script = "\n".join(["10", "6", f"刪除 {total}", "14"]) + "\n"                # menu: clear stats -> all -> confirm -> quit
        code = ctrl.main(Namespace(settings=self.path, width=100, json=False, ctrl_action=None), stdin=Tty(script), stdout=out, stderr=err)
        self.assertEqual(code, 0, err.getvalue())
        self.assertEqual(sum(self.rows().values()), 0)
        self.assertEqual(self.path.read_bytes(), before)                             # settings untouched

    def test_retention_prunes_only_older_rows_and_only_once_a_day(self):
        self.assertEqual(self.store.maintain(0, NOW), 0)                              # 0 = keep forever
        self.assertEqual(self.rows()["advice"], 4)
        self.assertEqual(self.store.maintain(30, NOW), 4)                             # the 40-day-old delegation, its call, child, notice
        self.assertEqual(self.rows(), {t: 3 for t in AdviceStore.TABLES})
        self.store.save("old", AdvisoryRequest("claude", "z", "t", "z", "task"), "h", Advice("preserve", "named_role"), "jev", NOW - 60 * DAY)
        self.assertEqual(self.store.maintain(30, NOW + 3600), 0)                      # same day: no second sweep
        self.assertEqual(self.store.maintain(30, NOW + DAY), 1)                       # next day: swept

    def test_retention_setting_defaults_to_a_year_and_is_validated(self):
        self.assertEqual(v2.retention_days(v2.read(self.path)), 365)
        def cli(*argv):
            return ctrl.main(Namespace(settings=self.path, width=100, json=False, ctrl_action="set", key=argv[0], value=argv[1]),
                             stdin=io.StringIO(), stdout=io.StringIO(), stderr=io.StringIO())
        self.assertEqual(cli("stats.retention_days", "90"), 0)
        self.assertEqual(v2.retention_days(v2.read(self.path)), 90)
        self.assertEqual(cli("stats.retention_days", "0"), 0)
        self.assertEqual(v2.retention_days(v2.read(self.path)), 0)
        for bad in ("-1", "3651", "abc", "1.5"):
            self.assertEqual(cli("stats.retention_days", bad), 2, bad)
        self.assertEqual(v2.retention_days(v2.read(self.path)), 0)                   # rejected values changed nothing


if __name__ == "__main__":
    unittest.main()
