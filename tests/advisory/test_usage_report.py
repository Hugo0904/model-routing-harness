import json
import re
import sqlite3
import tempfile
import unittest
from pathlib import Path

from mrh.advisory import usage_report
from mrh.advisory.request import Advice, AdvisoryRequest, Child
from mrh.advisory.store import AdviceStore, request_id, task_hash
from mrh.presentation import dashboard, stats_view
from mrh.presentation.terminal import cell_width
from tests.presentation.test_dashboard import settings

ANSI = re.compile(r"\x1b\[[0-9;]*m")
M = 1_000_000


def entry(inp=0, read=0, out=None, write5=0):
    return {"observation": {"version": 1, "semantics": "settled_snapshot", "collected_at": 1,
                            "sources": [{"name": "fixture.jsonl", "device": 1, "inode": 1, "size": 1, "mtime_ns": 1}]},
            "max_request_input": 1000, "requests": 2, "output": out, "reasoning": None if out is None else 10,
            "small": {"input": inp, "cache_write_5m": write5, "cache_write_1h": 0, "cache_write": 0, "cache_read": read},
            "large": {f: 0 for f in ("input", "cache_write_5m", "cache_write_1h", "cache_write", "cache_read")}}


class Env(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.store = AdviceStore(Path(tmp.name) / "advice.sqlite3")
        self.now = 1_800_000_000
        self.n = 0

    def advised_child(self, platform, advised, requested, effort, actual_models, usage, parent, ts=None, collect=True):
        """A delegation MRH redirected (advice + the model-carrying re-issue) whose sub-agent has finished."""
        self.n += 1; n = self.n; ts = ts or self.now - 600
        req = AdvisoryRequest(platform, f"s{n}", "t", f"c{n}", f"task {n}")
        self.store.save(request_id(platform, f"s{n}", "t", f"c{n}"), req, task_hash(platform, f"s{n}", f"task {n}"),
                        Advice("advise", "advice_given", "Light", .9, tuple(advised)), "jev", ts - 5)
        reissue = AdvisoryRequest(platform, f"s{n}", "t", f"k{n}", f"task {n}", requested, effort)
        self.store.preserve_explicit(request_id(platform, f"s{n}", "t", f"k{n}"), reissue, task_hash(platform, f"s{n}", f"task {n}"), "jev", ts)
        self.store.record_child(Child(platform, f"s{n}", f"k{n}", requested, effort, None, f"agent{n}"), ts)
        if collect:
            self.store.save_usage({"platform": platform, "session_id": f"s{n}", "call_id": f"k{n}", "ts": ts, "source_file": f"a{n}.jsonl",
                                   "models": actual_models, "usage": usage, "parent_model": parent, "collected_at": ts})


class SummaryTests(Env):
    def test_tokens_are_summed_per_platform_and_model_and_claude_output_stays_unknown(self):
        self.advised_child("claude", [{"model": "haiku", "effort": "medium"}], "haiku", "medium", [{"model": "claude-haiku-5-5", "effort": "medium"}],
                           {"claude-haiku-5-5": entry(inp=M, read=2 * M)}, "claude-opus-5-5")
        self.advised_child("claude", [{"model": "haiku", "effort": "medium"}], "haiku", "medium", [{"model": "claude-haiku-5-5", "effort": "medium"}],
                           {"claude-haiku-5-5": entry(inp=M, read=M)}, "claude-opus-5-5")
        data = self.store.stats(0)["usage"]
        self.assertEqual((data["recorded"], data["collected"], data["uncollected"]), (2, 2, 0))
        slot = data["by_model"]["claude|claude-haiku-5-5"]
        self.assertEqual((slot["children"], slot["input"], slot["cache_read"], slot["requests"]), (2, 2 * M, 3 * M, 4))
        self.assertIsNone(slot["output"])
        cost = data["cost"]["claude"]
        self.assertAlmostEqual(cost["input_side_usd"], 2 * 0.10 + 3 * 0.01); self.assertIsNone(cost["output_usd"])
        saving = data["saving"]["claude"]
        self.assertEqual((saving["children"], saving["scope"]), (2, "輸入端"))
        self.assertAlmostEqual(saving["usd"], (2 * 4 + 3 * 0.20) - (2 * 0.10 + 3 * 0.01))

    def test_codex_output_is_exact_and_the_saving_includes_it(self):
        self.advised_child("codex", [{"model": "gpt-6-luna", "effort": "high"}], "gpt-6-luna", "high", [{"model": "gpt-6-luna", "effort": "high"}],
                           {"gpt-6-luna": entry(inp=M, read=M, out=M)}, "gpt-6.1-sol")
        data = self.store.stats(0)["usage"]
        self.assertEqual(data["by_model"]["codex|gpt-6-luna"]["output"], M); self.assertEqual(data["by_model"]["codex|gpt-6-luna"]["reasoning"], 10)
        self.assertAlmostEqual(data["cost"]["codex"]["output_usd"], 0.50)
        self.assertAlmostEqual(data["saving"]["codex"]["usd"], (2 + 0.10 + 10) - (0.10 + 0.01 + 0.50)); self.assertEqual(data["saving"]["codex"]["scope"], "輸入＋輸出")

    def test_uncollected_children_are_counted_and_an_unknown_parent_never_becomes_a_number(self):
        self.advised_child("claude", [{"model": "haiku"}], "haiku", None, [{"model": "claude-haiku-5-5"}], {"claude-haiku-5-5": entry(inp=M)}, None)
        self.advised_child("claude", [{"model": "haiku"}], "haiku", None, [], {}, None, collect=False)
        data = self.store.stats(0)["usage"]
        self.assertEqual((data["recorded"], data["collected"], data["uncollected"]), (2, 1, 1))
        self.assertEqual((data["saving"]["claude"]["children"], data["saving"]["claude"]["unknown"]), (0, 1))
        self.assertEqual(data["saving_unknown_reasons"], {"不知道主模型": 1})

    def test_what_actually_ran_is_compared_with_the_advice_not_with_the_request(self):
        advised = [{"model": "haiku", "effort": "medium"}]
        self.advised_child("claude", advised, "haiku", "medium", [{"model": "claude-haiku-5-5", "effort": "medium"}], {"claude-haiku-5-5": entry(inp=1)}, None)   # fine
        self.advised_child("claude", advised, "haiku", "medium", [{"model": "claude-sonnet-5-5", "effort": "medium"}], {"claude-sonnet-5-5": entry(inp=1)}, None) # model differs
        self.advised_child("claude", advised, "haiku", "medium", [{"model": "claude-haiku-5-5", "effort": "high"}], {"claude-haiku-5-5": entry(inp=1)}, None)   # effort differs
        data = self.store.stats(0)["usage"]
        self.assertEqual({k: data["verified"][k] for k in ("checked", "matching")}, {"checked": 3, "matching": 2})
        self.assertEqual([(m["kind"], m["actual"]) for m in data["mismatch"]], [("model", ["claude-sonnet-5-5:medium"]), ("effort", ["claude-haiku-5-5:high"])])
        self.assertEqual(data["mismatch"][0]["advised"], ["haiku:medium"])

    def test_the_period_limits_usage_and_reset_clears_it(self):
        self.advised_child("claude", [{"model": "haiku"}], "haiku", None, [{"model": "claude-haiku-5-5"}], {"claude-haiku-5-5": entry(inp=1)}, None, ts=self.now - 40 * 86400)
        self.assertEqual(self.store.stats(self.now - 7 * 86400)["usage"]["collected"], 0)
        self.assertEqual(self.store.stats(0)["usage"]["collected"], 1)
        self.store.delete_since(0)
        with sqlite3.connect(self.store.path) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM child_usage").fetchone()[0], 0)

    def test_an_older_database_without_the_table_still_reads(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "old.sqlite3"
        AdviceStore(path)
        with sqlite3.connect(path) as db:
            db.execute("DROP TABLE child_usage")
        data = AdviceStore.read_stats(path, 0)
        self.assertEqual(data["usage"]["collected"], 0); self.assertEqual(AdviceStore.read_usage(path, 0), [])


class ScreenTests(Env):
    def seed(self):
        self.advised_child("claude", [{"model": "haiku"}], "haiku", None, [{"model": "claude-sonnet-5-5"}], {"claude-sonnet-5-5": entry(inp=M, read=M)}, "claude-opus-5-5")
        self.advised_child("codex", [{"model": "gpt-6-luna"}], "gpt-6-luna", None, [{"model": "gpt-6-luna"}], {"gpt-6-luna": entry(inp=M, out=1234)}, "gpt-6.1-sol")
        self.advised_child("claude", [{"model": "haiku"}], "haiku", None, [], {}, None, collect=False)
        return self.store.stats(0)

    def test_stats_text_labels_measured_converted_and_unknown_numbers(self):
        text = stats_view.render(self.seed(), "全部紀錄", 0.65, False, settings()["policy"])
        for expected in ("■ 子代理實際用量（已收集 2／3 個；1 個還沒收集，請執行 mrh usage collect）", "輸出 未知", "輸出 1,234（含推理 10）",
                         "依官方 API 定價換算，不是你的實際帳單（價格查於 2026-10-16）", "輸入端 $", "（輸出量未知，不是總額）",
                         "節省（換算）", "假設主模型處理同樣內容用的 token 數相同", "輸入＋輸出約省", "實際執行的模型也符合建議：1／2 個",
                         "建議 haiku，實際 claude-sonnet-5-5（模型不同）"):
            self.assertIn(expected, text)

    def test_status_gets_exactly_one_usage_bar_and_never_overflows(self):
        data = self.seed()
        for width in (80, 100, 120):
            for color in (False, True):
                with self.subTest(width=width, color=color):
                    text = ANSI.sub("", dashboard.render(settings(), data, "全部紀錄", width, color, today="x"))
                    card = [l for l in text.splitlines() if l[:1] in "│╭╰" and cell_width(l) > 40]
                    self.assertEqual({cell_width(l) for l in card}, {width})
                    self.assertEqual(text.count("子代理用量已收集"), 1)
                    self.assertIn("2 / 3 個子代理", text)
        plain = ANSI.sub("", dashboard.render(settings(), self.seed(), "全部紀錄", 120, False, today="x"))
        self.assertIn("節省（換算）", plain)

    def test_nothing_recorded_means_no_section_and_no_bar(self):
        text = stats_view.render(self.store.stats(0), "全部紀錄", 0.65, False)
        self.assertNotIn("子代理實際用量", text)
        self.assertNotIn("子代理用量已收集", ANSI.sub("", dashboard.render(settings(), self.store.stats(0), "全部紀錄", 100, False, today="x")))

    def test_the_json_export_only_gains_a_usage_object(self):
        data = self.seed()
        self.assertTrue({"recorded", "collected", "uncollected", "by_model", "cost", "saving", "mismatch", "verified", "pricing"} <= set(data["usage"]))
        json.dumps(data)                                                   # everything serialisable (no tuples of unknown shape)
        self.assertEqual(data["usage"]["pricing"]["checked"], "2026-10-16")


class SnapshotReportTests(Env):
    def test_every_actual_model_must_match_and_effort_is_independent(self):
        cases = [
            ([{"model": "claude-haiku-5-5"}], 1, [], 1),
            ([{"model": "claude-haiku-5-5", "effort": "high"}, {"model": "claude-sonnet-5-5", "effort": "low"}], 0, ["claude-sonnet-5-5"], 1),
            ([{"model": "claude-opus-5-5", "effort": "low"}], 0, ["claude-opus-5-5"], 1),
            ([], 0, [], 1),
        ]
        for profiles, matching, mismatched, unknown_effort in cases:
            with self.subTest(profiles=profiles):
                result = usage_report.empty()
                usage_report._compare(result, {"advice_request_id": "a", "platform": "claude", "models": json.dumps(profiles)}, {},
                                      {"a": {"candidates": json.dumps([{"model": "haiku", "effort": "high"}])}})
                self.assertEqual(result["verified"]["matching"], matching)
                actual = [name.split(":")[0] for m in result["mismatch"] if m["kind"] == "model" for name in m["actual"]]
                self.assertEqual(actual, mismatched)
                self.assertEqual(result["verified"]["effort_unknown"], unknown_effort)
                if not profiles:
                    self.assertEqual((result["verified"]["checked"], result["verified"]["unknown"]), (0, 1))
        for candidate, actual in (("haiku", "custom-haiku-model"), ("sol", "gpt-6.1-sol"), ("haiku", "claude-haiku-unknown")):
            self.assertFalse(usage_report._matches(candidate, actual))
        self.assertTrue(usage_report._matches("haiku", "claude-haiku-5-5"))
        result = usage_report.empty()
        usage_report._compare(result, {"advice_request_id": "a", "platform": "codex", "models": json.dumps([{"model": "gpt-6-luna", "effort": "low"}])}, {},
                              {"a": {"candidates": json.dumps([{"model": "gpt-6-luna", "effort": "high"}])}})
        self.assertEqual((result["verified"]["matching"], result["verified"]["effort_matching"]), (1, 0))
        self.assertEqual(result["mismatch"][0]["kind"], "effort")

    def seed_unknown_partial_legacy(self):
        self.advised_child("codex", [{"model": "gpt-6-luna", "effort": "high"}], "gpt-6-luna", "high",
                           [{"model": "gpt-6-luna"}], {"gpt-6-luna": entry(inp=1000, out=10)}, "gpt-6.1-sol")
        unknown = entry(inp=2000, out=20); unknown["max_request_input"] = None; unknown["requests"] = None
        self.advised_child("codex", [{"model": "gpt-6-luna"}], "gpt-6-luna", None,
                           [{"model": "gpt-6-luna"}], {"gpt-6-luna": unknown}, "gpt-6.1-sol")
        legacy = entry(inp=123); legacy.pop("observation")
        self.advised_child("claude", [{"model": "haiku"}], "haiku", None,
                           [{"model": "claude-haiku-5-5"}], {"claude-haiku-5-5": legacy}, "claude-opus-5-5")
        return self.store.stats(0)

    def test_unknown_totals_keep_labelled_subtotals_and_legacy_is_not_verified(self):
        data = self.seed_unknown_partial_legacy(); usage = data["usage"]
        self.assertEqual(usage["legacy"], 1)
        self.assertEqual((usage["verified"]["checked"], usage["verified"]["matching"], usage["verified"]["unknown"]), (2, 2, 1))
        c = usage["cost"]["codex"]
        self.assertIsNone(c["input_side_usd"]); self.assertIsNone(c["output_usd"])
        self.assertGreater(c["input_side_known_usd"], 0)
        sv = usage["saving"]["codex"]
        self.assertIsNone(sv["usd"]); self.assertGreater(sv["known_usd"], 0)
        self.assertIsNone(usage["by_model"]["codex|gpt-6-luna"]["requests"])
        self.assertIsNone(usage["by_model"]["claude|claude-haiku-5-5"]["input"])
        text = "\n".join(stats_view.usage_lines(data))
        for phrase in ("總額未知", "小計", "已知部分", "舊版快照未重新驗證", "長度未知", "推理強度未驗證", "不代表子代理已結束"):
            self.assertIn(phrase, text)

    def test_changed_unknown_partial_legacy_terminal_states_fit_selected_widths_and_are_readonly(self):
        from unittest.mock import patch
        from mrh.advisory import usage_collect
        self.seed_unknown_partial_legacy()
        old_rows = AdviceStore.read_usage(self.store.path, 0)
        with patch.object(usage_collect, "_lines", side_effect=AssertionError("transcript read")), patch.object(AdviceStore, "save_usage", side_effect=AssertionError("DB write")):
            for width in (80, 100, 120):
                data = AdviceStore.read_stats(self.store.path, 0)
                text = ANSI.sub("", dashboard.render(settings(), data, "全部紀錄", width, False, today="x"))
                card = [l for l in text.splitlines() if l[:1] in "│╭╰" and cell_width(l) > 40]
                self.assertEqual({cell_width(l) for l in card}, {width})
                self.assertEqual(text.count("子代理用量已收集"), 1)
                self.assertIn("已知部分", text)
                stats_view.render(data, "全部紀錄", 0.65, False, settings()["policy"])
        self.assertEqual(AdviceStore.read_usage(self.store.path, 0), old_rows)
        json.dumps(data)


class SnapshotCompatibilityTests(Env):
    def test_old_json_remains_raw_readable_and_new_metadata_does_not_change_columns_or_retention(self):
        self.advised_child("claude", [{"model": "haiku"}], "haiku", None, [{"model": "claude-haiku-5-5"}],
                           {"claude-haiku-5-5": entry(inp=4)}, None, ts=self.now - 40 * 86400)
        with self.store.connect() as db:
            self.assertEqual(len(db.execute("PRAGMA table_info(child_usage)").fetchall()), 9)
            raw = db.execute("SELECT usage FROM child_usage").fetchone()[0]
            legacy = json.loads(raw)
            for e in legacy.values():
                e.pop("observation")
            db.execute("UPDATE child_usage SET usage=?", (json.dumps(legacy),))
        rows = AdviceStore.read_usage(self.store.path, 0)
        self.assertEqual(json.loads(rows[0]["usage"]), legacy)
        self.assertEqual(self.store.stats(0)["usage"]["legacy"], 1)
        self.assertEqual(json.loads(AdviceStore.read_usage(self.store.path, 0)[0]["usage"]), legacy)
        self.store.prune_before(self.now - 30 * 86400)
        self.assertEqual(AdviceStore.read_usage(self.store.path, 0), [])


if __name__ == "__main__":
    unittest.main()
