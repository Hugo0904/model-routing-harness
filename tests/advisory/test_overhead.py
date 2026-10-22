import io
import json
import tempfile
import unittest
from pathlib import Path

from mrh.advisory import engine, overhead
from mrh.advisory.request import AdvisoryRequest, Child
from mrh.advisory.store import AdviceStore, request_id
from mrh.infrastructure import settings_v2 as v2
from mrh.presentation import usage_cli
from mrh.routing.types import Classification
from tests.advisory.test_engine import Fake, LISTS, settings

DAY = 86400
BLANK = {"input": 0, "cache_write_5m": 0, "cache_write_1h": 0, "cache_write": 0, "cache_read": 0}


class OverheadTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name).resolve()
        self.path = self.base / "owned" / "settings.json"; v2.init(self.path)
        self.store = AdviceStore(self.path.parent / "advice.sqlite3")
        self.claude = self.base / "projects"; (self.claude / "proj").mkdir(parents=True)
        self.now = 1_000_000

    def request(self, platform, call, **changes):
        values = dict(platform=platform, session_id="s", turn_id="t", call_id=call, task="sort three words")
        values.update(changes)
        return AdvisoryRequest(**values)

    def advise(self, platform, call, *, wait=1.5, tokens=300):
        self.now += 10
        rid = request_id(platform, "s", "t", call)
        self.store.attempt(rid, "jev", "started", self.now)
        self.store.attempt(rid, "jev", "returned", self.now + wait, input_tokens=tokens)
        result = engine.decide(self.request(platform, call), settings(**LISTS), self.store,
                               lambda: Fake(Classification("Light", .9)), clock=lambda: self.now)
        self.assertEqual(result.reason, "advice_given")
        return rid

    def reissue(self, platform, call, model, *, effort=None, after=4):
        self.now += after
        result = engine.decide(self.request(platform, call, explicit_model=model, explicit_effort=effort), settings(**LISTS), self.store,
                               lambda: Fake(Classification("Light", .9)), clock=lambda: self.now)
        self.assertEqual(result.reason, "advice_reissue")

    def transcript(self, call, usage, model="claude-opus-5-5", session="s"):
        line = {"type": "assistant", "message": {"id": "m-" + call, "model": model, "usage": usage,
                                                 "content": [{"type": "tool_use", "id": call}]}}
        with open(self.claude / "proj" / f"{session}.jsonl", "a") as handle:
            handle.write(json.dumps(line) + "\n")

    def observed(self, entry):
        """What the collector adds to every entry of a settled snapshot; without it `mrh stats` treats the row as legacy."""
        return {**entry, "observation": {"version": 1, "semantics": "settled_snapshot", "collected_at": self.now, "sources": [
            {"name": "x.jsonl", "device": 1, "inode": 2, "size": 3, "mtime_ns": 4}]}}

    def child_usage(self, platform, call, model, requested, usage_entry, parent):
        usage_entry = self.observed(usage_entry)
        self.assertTrue(self.store.record_child(Child(platform, "s", call, requested, None, model, "agent-" + call), self.now))
        self.store.save_usage({"platform": platform, "session_id": "s", "call_id": call, "ts": self.now, "source_file": "x",
                               "models": [model], "usage": {model: usage_entry}, "parent_model": parent, "collected_at": self.now})

    def build(self):
        return overhead.build(self.store.path, 0, claude_root=self.claude)

    def test_claude_pair_counts_wait_fee_extra_request_and_the_saving_that_followed(self):
        self.advise("claude", "orig", wait=1.5, tokens=300)
        self.transcript("redo", {"input_tokens": 10, "cache_read_input_tokens": 50_000, "cache_creation_input_tokens": 0,
                                 "output_tokens": 7})
        self.reissue("claude", "redo", "haiku")
        usage = {"small": {**BLANK, "input": 100, "cache_read": 1000}, "large": dict(BLANK), "requests": 1,
                 "output": None, "reasoning": None}
        self.child_usage("claude", "redo", "claude-haiku-5-5", "haiku", usage, "claude-opus-5-5")
        report = self.build()
        self.assertEqual((report["delegations"], report["advised"], report["reissues"]), (1, 1, 1))
        pair = report["pairs"][0]
        self.assertAlmostEqual(pair["classifier_seconds"], 1.5)
        self.assertAlmostEqual(pair["classifier_usd"], 300 * 0.042 / 1_000_000)
        self.assertAlmostEqual(pair["deny_to_reissue_seconds"], 4.0, delta=0.5)
        self.assertEqual(pair["main_model"], "claude-opus-5-5")
        # opus 5.5: $4/M input, $0.20/M cache read
        self.assertAlmostEqual(pair["main_extra_input_usd"], 10 * 4 / 1e6 + 50_000 * 0.20 / 1e6)
        # same tokens on opus minus on haiku (input side)
        self.assertAlmostEqual(pair["saving_usd"], (100 * 4 + 1000 * 0.20) / 1e6 - (100 * 0.10 + 1000 * 0.01) / 1e6)
        self.assertEqual(pair["saving_scope"], "輸入端")
        self.assertEqual(pair["main_context_tokens"], 50_010)
        self.assertEqual(report["main_context_tokens_median"], 50_010)
        # the figure `mrh stats` shows counts every collected child, here the one that followed the advice
        self.assertAlmostEqual(report["all_children_saving_usd"], pair["saving_usd"])
        self.assertEqual(report["all_children_saving_children"], 1)
        self.assertEqual(report["compared"], 1)
        self.assertEqual(report["compared_net_positive"], 0)          # one small child cannot pay for a 50K-token extra turn
        self.assertAlmostEqual(report["compared_saving_usd"], pair["saving_usd"])

    def test_a_legacy_snapshot_without_observation_is_not_priced(self):
        self.advise("claude", "orig")
        self.reissue("claude", "redo", "haiku")
        usage = {"small": {**BLANK, "input": 100}, "large": dict(BLANK), "requests": 1, "output": None, "reasoning": None}
        self.assertTrue(self.store.record_child(Child("claude", "s", "redo", "haiku", None, "claude-haiku-5-5", "agent"), self.now))
        self.store.save_usage({"platform": "claude", "session_id": "s", "call_id": "redo", "ts": self.now, "source_file": "x",
                               "models": ["claude-haiku-5-5"], "usage": {"claude-haiku-5-5": usage}, "parent_model": "claude-opus-5-5",
                               "collected_at": self.now})
        report = self.build()
        self.assertIsNone(report["pairs"][0]["saving_usd"]); self.assertIn("舊格式", report["pairs"][0]["saving_unknown"])
        self.assertEqual(report["all_children_saving_children"], 0)

    def test_codex_pair_reports_the_parent_request_as_unknown_not_zero(self):
        self.advise("codex", "orig")
        self.reissue("codex", "redo", "luna", effort="low")
        report = self.build()
        pair = report["pairs"][0]
        self.assertIsNone(pair["main_extra_input_usd"]); self.assertIn("Codex", pair["main_extra_unknown"])
        self.assertIsNone(report["main_extra_input_usd_total"]); self.assertEqual(report["main_extra_known"], 0)
        self.assertEqual(report["compared"], 0)
        self.assertIsNone(pair["saving_usd"]); self.assertIn("mrh usage collect", pair["saving_unknown"])

    def test_cache_write_without_a_ttl_split_and_missing_transcript_stay_unknown(self):
        self.advise("claude", "orig")
        self.transcript("redo", {"input_tokens": 1, "cache_read_input_tokens": 1, "cache_creation_input_tokens": 500})
        self.reissue("claude", "redo", "haiku")
        pair = self.build()["pairs"][0]
        self.assertIsNone(pair["main_extra_input_usd"]); self.assertIn("未知", pair["main_extra_unknown"])
        (self.claude / "proj" / "s.jsonl").unlink()
        self.assertIn("找不到", self.build()["pairs"][0]["main_extra_unknown"])

    def test_advised_but_not_reissued_and_ordinary_delegations_are_counted_separately(self):
        self.advise("codex", "a")
        self.now += 5
        engine.decide(self.request("codex", "b", turn_id="u", explicit_model="sol"), settings(**LISTS), self.store,
                      lambda: Fake(Classification("Light", .9)), clock=lambda: self.now)
        report = self.build()
        self.assertEqual((report["delegations"], report["advised"], report["reissues"], report["advised_not_reissued"]), (2, 1, 0, 1))
        self.assertAlmostEqual(report["advised_share"], .5)
        self.assertIsNone(report["classifier_seconds_median"])

    def test_cli_text_and_json_are_read_only(self):
        self.advise("claude", "orig")
        self.transcript("redo", {"input_tokens": 10, "cache_read_input_tokens": 50_000, "cache_creation_input_tokens": 0})
        self.reissue("claude", "redo", "haiku")
        db = self.path.parent / "advice.sqlite3"
        before = db.read_bytes()
        args = type("A", (), {"settings": self.path, "days": 30, "json": False, "usage_action": "overhead"})()
        out = io.StringIO()
        self.assertEqual(usage_cli.main(args, stdin=None, stdout=out, stderr=io.StringIO(), now=self.now + 60, claude_root=self.claude), 0)
        for text in ("攔下重派的開銷", "MRH 給了建議", "主模型多跑的那一輪", "上下文大小", "和 mrh stats 的差別", "不量品質", "不能判斷划不划算"):
            self.assertIn(text, out.getvalue())
        args.json = True
        out = io.StringIO()
        self.assertEqual(usage_cli.main(args, stdin=None, stdout=out, stderr=io.StringIO(), now=self.now + 60, claude_root=self.claude), 0)
        self.assertEqual(json.loads(out.getvalue())["reissues"], 1)
        self.assertEqual(db.read_bytes(), before)

    def test_the_subcommand_is_wired_into_the_cli(self):
        from mrh.presentation import cli
        self.advise("codex", "a")
        out = io.StringIO()
        self.assertEqual(cli.main(["usage", "overhead", "--settings", str(self.path), "--days", "36500", "--json"],
                                  stdout=out, stderr=io.StringIO()), 0)
        self.assertEqual(json.loads(out.getvalue())["advised"], 1)

    def test_status_card_shows_a_summary_and_the_json_export_is_unchanged(self):
        from mrh.presentation import ctrl
        self.advise("claude", "orig")
        self.transcript("redo", {"input_tokens": 10, "cache_read_input_tokens": 50_000, "cache_creation_input_tokens": 0})
        self.reissue("claude", "redo", "haiku")
        import os
        from unittest.mock import patch
        with patch.dict(os.environ, {"MRH_CLAUDE_PROJECTS": str(self.claude)}):
            card = ctrl.dashboard_text(self.path, None, 100, False)
            exported = ctrl.status_data(self.path, None)
        for text in ("MRH 攔截的淨收益", "1 次重派，還算不出淨值"):
            self.assertIn(text, card)
        self.assertNotIn("overhead", exported)

    def test_status_card_shows_a_negative_net_with_its_sign(self):
        from mrh.presentation import ctrl
        import os
        from unittest.mock import patch
        self.advise("claude", "orig")
        self.transcript("redo", {"input_tokens": 10, "cache_read_input_tokens": 420_000, "cache_creation_input_tokens": 0})
        self.reissue("claude", "redo", "haiku")
        usage = {"small": {**BLANK, "input": 100, "cache_read": 1000}, "large": dict(BLANK), "requests": 1, "output": None, "reasoning": None}
        self.child_usage("claude", "redo", "claude-haiku-5-5", "haiku", usage, "claude-opus-5-5")
        with patch.dict(os.environ, {"MRH_CLAUDE_PROJECTS": str(self.claude)}):
            card = ctrl.dashboard_text(self.path, None, 100, False)
        self.assertIn("淨 －$", card); self.assertIn("（1 次重派）", card)

    def test_status_card_omits_the_block_without_data(self):
        from mrh.presentation import ctrl
        self.assertNotIn("MRH 攔截的淨收益", ctrl.dashboard_text(self.path, None, 100, False))

    def test_empty_database_and_bad_days(self):
        args = type("A", (), {"settings": self.path, "days": 0, "json": False, "usage_action": "overhead"})()
        err = io.StringIO()
        self.assertEqual(usage_cli.main(args, stdin=None, stdout=io.StringIO(), stderr=err), 2)
        args.days = 30
        out = io.StringIO()
        self.assertEqual(usage_cli.main(args, stdin=None, stdout=out, stderr=io.StringIO(), now=self.now), 0)


if __name__ == "__main__":
    unittest.main()
