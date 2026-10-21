import io
import json
import os
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch
from argparse import Namespace
from pathlib import Path

from mrh.advisory import usage_collect as uc
from mrh.advisory.request import Child
from mrh.advisory.store import AdviceStore
from mrh.infrastructure import settings_v2 as v2
from mrh.presentation import cli, usage_cli

NOW = 1_800_000_000
SECRET = "SECRET-TASK-TEXT-DO-NOT-STORE"


def claude_line(mid, model, inp=10, w5=0, w1=0, read=0, out=7, total_cc=None, cc=True):
    usage = {"input_tokens": inp, "cache_read_input_tokens": read, "output_tokens": out,
             "cache_creation_input_tokens": (w5 + w1) if total_cc is None else total_cc}
    if cc:
        usage["cache_creation"] = {"ephemeral_5m_input_tokens": w5, "ephemeral_1h_input_tokens": w1}
    return json.dumps({"type": "assistant", "message": {"id": mid, "model": model, "usage": usage,
                                                         "content": [{"type": "text", "text": SECRET}]}})


class Env(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.claude, self.codex = self.root / "claude", self.root / "codex"
        self.store = AdviceStore(self.root / "advice.sqlite3")

    def child(self, platform, call, agent, session="s1", ts=NOW - 3600, model="haiku", effort="high"):
        self.store.record_child(Child(platform, session, call, model, effort, None, agent), ts)

    def claude_agent(self, agent, call, lines, session="s1", effort="high", age=3600, tool_use_id=None):
        folder = self.claude / "-proj" / session / "subagents"; folder.mkdir(parents=True, exist_ok=True)
        meta = folder / f"agent-{agent}.meta.json"
        meta.write_text(json.dumps({"agentType": "general-purpose", "description": SECRET, "toolUseId": tool_use_id or call,
                                    "model": "haiku", "effort": effort}))
        transcript = folder / f"agent-{agent}.jsonl"; transcript.write_text("\n".join(lines) + "\n")
        for path in (meta, transcript):
            os.utime(path, (NOW - age, NOW - age))
        return transcript

    def claude_parent(self, session, mapping):
        folder = self.claude / "-proj"; folder.mkdir(parents=True, exist_ok=True)
        lines = [json.dumps({"type": "assistant", "message": {"model": model, "content": [{"type": "tool_use", "id": call, "name": "Agent"}]}})
                 for call, model in mapping.items()]
        (folder / f"{session}.jsonl").write_text("\n".join(lines) + "\n")

    def codex_agent(self, parent, path_name, call_models=("gpt-6-luna",), total=None, age=3600, day=None, start=NOW - 3600):
        t = time.localtime(start)
        folder = self.codex / f"{t.tm_year:04d}" / f"{t.tm_mon:02d}" / f"{t.tm_mday:02d}"; folder.mkdir(parents=True, exist_ok=True)
        file = folder / f"rollout-x-{path_name.strip('/').replace('/', '_')}-{parent[:6]}.jsonl"
        first = {"type": "session_meta", "payload": {"timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(start)),
                 "source": {"subagent": {"thread_spawn": {"parent_thread_id": parent, "agent_path": path_name, "agent_role": "worker"}}}}}
        lines = [json.dumps(first)]
        for model, effort in (m if isinstance(m, tuple) else (m, "max") for m in call_models):
            lines.append(json.dumps({"type": "turn_context", "payload": {"model": model, "effort": effort, "instructions": SECRET}}))
        total = total or {"input_tokens": 1000, "cached_input_tokens": 600, "cache_write_input_tokens": 0, "output_tokens": 50,
                          "reasoning_output_tokens": 20, "total_tokens": 1050}
        lines.append(json.dumps({"type": "event_msg", "payload": {"type": "token_count", "info": {"total_token_usage": total}}}))
        file.write_text("\n".join(lines) + "\n"); os.utime(file, (NOW - age, NOW - age))
        return file

    def collect(self, **kw):
        return uc.collect(self.store, NOW, claude_root=self.claude, codex_root=self.codex, **kw)

    def rows(self):
        with sqlite3.connect(self.store.path) as db:
            db.row_factory = sqlite3.Row
            return [dict(r) for r in db.execute("SELECT * FROM child_usage ORDER BY call_id")]


class ClaudeTests(Env):
    def test_messages_repeat_once_per_content_block_and_are_counted_once_with_output_always_unknown(self):
        self.child("claude", "toolu_1", "a1")
        self.claude_agent("a1", "toolu_1", [claude_line("m1", "claude-haiku-5-5", inp=10, w5=500, read=100)] * 3
                          + [claude_line("m2", "claude-haiku-5-5", inp=20, w1=200, read=300, out=999)])
        self.claude_parent("s1", {"toolu_1": "claude-opus-5-5"})
        summary = self.collect()
        self.assertEqual((summary["candidates"], summary["collected"]), (1, 1))
        (row,) = self.rows()
        usage = json.loads(row["usage"])["claude-haiku-5-5"]
        self.assertEqual(usage["requests"], 2)
        self.assertEqual(usage["small"], {"input": 30, "cache_write_5m": 500, "cache_write_1h": 200, "cache_write": 0, "cache_read": 400})
        self.assertIsNone(usage["output"]); self.assertIsNone(usage["reasoning"])                       # never an estimate
        self.assertEqual(json.loads(row["models"]), [{"model": "claude-haiku-5-5", "effort": "high"}])
        self.assertEqual((row["parent_model"], row["source_file"], row["ts"]), ("claude-opus-5-5", "agent-a1.jsonl", NOW - 3600))

    def test_large_prompts_are_separate_and_missing_ttl_split_cannot_publish_partial_total(self):
        self.child("claude", "toolu_2", "a2")
        path = self.claude_agent("a2", "toolu_2", [claude_line("big", "claude-haiku-5-5", inp=50, read=120_000)])
        self.collect()
        original = self.rows()
        usage = json.loads(original[0]["usage"])["claude-haiku-5-5"]
        self.assertEqual(usage["large"]["cache_read"], 120_000); self.assertEqual(usage["small"]["cache_read"], 0)
        path.write_text(path.read_text() + claude_line("old", "claude-haiku-5-5", inp=5, total_cc=700, cc=False) + "\n")
        os.utime(path, (NOW - 1800, NOW - 1800))
        result = self.collect()
        self.assertEqual(result["collected"], 0)
        self.assertEqual(result["details"][0]["reason"], "invalid_usage:cache_creation_ttl_split")
        self.assertEqual(self.rows(), original)

    def test_synthetic_malformed_and_other_roles_are_ignored(self):
        self.child("claude", "toolu_3", "a3")
        self.claude_agent("a3", "toolu_3", ["not json {", json.dumps({"type": "user", "message": {"usage": {"input_tokens": 9}}}),
                                            claude_line("s", "<synthetic>", inp=1000), claude_line("ok", "claude-sonnet-5-5", inp=3)])
        self.collect()
        self.assertEqual(list(json.loads(self.rows()[0]["usage"])), ["claude-sonnet-5-5"])

    def test_a_transcript_that_belongs_to_another_tool_call_is_not_used(self):
        self.child("claude", "toolu_4", "a4")
        self.claude_agent("a4", "toolu_4", [claude_line("m", "claude-haiku-5-5")], tool_use_id="toolu_OTHER")
        summary = self.collect()
        self.assertEqual((summary["collected"], summary["not_found"]), (0, 1)); self.assertEqual(self.rows(), [])

    def test_a_transcript_still_changing_is_skipped_and_picked_up_by_a_later_run(self):
        self.child("claude", "toolu_5", "a5")
        path = self.claude_agent("a5", "toolu_5", [claude_line("m", "claude-haiku-5-5")], age=60)
        summary = self.collect()
        self.assertEqual((summary["collected"], summary["running"]), (0, 1)); self.assertEqual(self.rows(), [])
        for p in (path, path.with_name("agent-a5.meta.json")):
            os.utime(p, (NOW - 3600, NOW - 3600))
        self.assertEqual(self.collect()["collected"], 1)

    def test_unchanged_sources_do_not_read_bodies_and_changed_sources_replace_same_child(self):
        self.child("claude", "toolu_6", "a6")
        path = self.claude_agent("a6", "toolu_6", [claude_line("m", "claude-haiku-5-5", inp=5)])
        self.assertEqual(self.collect()["collected"], 1)
        original = self.rows()[0]
        with patch.object(uc, "_lines", side_effect=AssertionError("body reread")), patch.object(uc, "find_claude_child", side_effect=AssertionError("meta reread")):
            again = self.collect()
        self.assertEqual((again["candidates"], again["unchanged"], again["collected"]), (1, 1, 0))
        path.write_text(path.read_text() + claude_line("m2", "claude-haiku-5-5", inp=13) + "\n")
        os.utime(path, (NOW - 1800, NOW - 1800))
        again = self.collect()
        self.assertEqual((again["collected"], again["updated"]), (1, 1))
        (row,) = self.rows()
        self.assertEqual(json.loads(row["usage"])["claude-haiku-5-5"]["small"]["input"], 18)
        self.assertEqual((row["platform"], row["session_id"], row["call_id"]), (original["platform"], original["session_id"], original["call_id"]))
        self.assertEqual(self.collect()["unchanged"], 1)

    def test_unknown_parent_model_stays_unknown(self):
        self.child("claude", "toolu_7", "a7")
        self.claude_agent("a7", "toolu_7", [claude_line("m", "claude-haiku-5-5")])
        self.collect(); self.assertIsNone(self.rows()[0]["parent_model"])


class CodexTests(Env):
    def test_the_child_is_found_by_parent_thread_and_agent_path_and_totals_are_a_snapshot(self):
        self.child("codex", "call_1", "/root/map_ui", session="parent-1", model="gpt-6-luna")
        self.codex_agent("parent-1", "/root/map_ui", call_models=[("gpt-6-luna", "max")])
        self.codex_agent("parent-1", "/root/other_task")                                                  # a different child: ignored
        summary = self.collect()
        self.assertEqual((summary["candidates"], summary["collected"]), (1, 1))
        (row,) = self.rows()
        usage = json.loads(row["usage"])["gpt-6-luna"]
        self.assertEqual(usage["small"], {"input": 400, "cache_write_5m": 0, "cache_write_1h": 0, "cache_write": 0, "cache_read": 600})  # input includes cached
        self.assertEqual((usage["output"], usage["reasoning"], usage["requests"]), (50, 20, None))
        self.assertIsNone(usage["max_request_input"])                                                   # no per-request record in this fixture
        self.assertEqual(json.loads(row["models"]), [{"model": "gpt-6-luna", "effort": "max"}])

    def test_the_largest_single_request_is_recorded_for_the_long_context_price_tier(self):
        self.child("codex", "call_7", "/root/big", session="parent-7")
        file = self.codex_agent("parent-7", "/root/big")
        lines = file.read_text().splitlines()[:-1]
        inp = out = 0
        for n in (1000, 310_000, 5000):
            inp += n; out += 10
            lines.append(json.dumps({"type": "event_msg", "payload": {"type": "token_count", "info": {
                "total_token_usage": {"input_tokens": inp, "cached_input_tokens": 0, "cache_write_input_tokens": 0, "output_tokens": out, "total_tokens": inp + out},
                "last_token_usage": {"input_tokens": n, "output_tokens": 10}}}}))
        file.write_text("\n".join(lines) + "\n"); os.utime(file, (NOW - 3600, NOW - 3600))
        self.collect()
        self.assertEqual(json.loads(self.rows()[0]["usage"])["gpt-6-luna"]["max_request_input"], 310_000)

    def test_several_models_in_one_thread_are_kept_but_the_total_is_not_split_between_them(self):
        self.child("codex", "call_2", "/root/two", session="parent-2")
        self.codex_agent("parent-2", "/root/two", call_models=[("gpt-6-luna", "high"), ("gpt-6.1-sol", "xhigh")])
        self.collect()
        row = self.rows()[0]
        self.assertEqual([m["model"] for m in json.loads(row["models"])], ["gpt-6-luna", "gpt-6.1-sol"])
        self.assertEqual(list(json.loads(row["usage"])), [uc.MIXED])

    def test_codex_builtin_reviewers_and_unrelated_threads_do_not_match(self):
        self.child("codex", "call_3", "/root/real", session="parent-3")
        folder = self.codex / time.strftime("%Y/%m/%d", time.localtime(NOW - 3600)); folder.mkdir(parents=True, exist_ok=True)
        (folder / "rollout-guardian.jsonl").write_text(json.dumps({"type": "session_meta", "payload": {"source": {"subagent": {"other": "guardian"}}}}) + "\n")
        summary = self.collect()
        self.assertEqual((summary["collected"], summary["not_found"]), (0, 1))

    def test_a_running_thread_is_skipped_and_a_thread_without_token_counts_is_unreadable(self):
        self.child("codex", "call_4", "/root/live", session="parent-4"); self.child("codex", "call_5", "/root/empty", session="parent-5")
        self.codex_agent("parent-4", "/root/live", age=30)
        file = self.codex_agent("parent-5", "/root/empty")
        file.write_text(file.read_text().splitlines()[0] + "\n"); os.utime(file, (NOW - 3600, NOW - 3600))
        summary = self.collect()
        self.assertEqual((summary["running"], summary["unreadable"], summary["collected"]), (1, 1, 0))

    def test_the_parent_model_is_the_one_in_effect_when_the_call_was_made(self):
        self.child("codex", "call_6", "/root/p", session="parent-6")
        self.codex_agent("parent-6", "/root/p")
        folder = self.codex / time.strftime("%Y/%m/%d", time.localtime(NOW - 7200)); folder.mkdir(parents=True, exist_ok=True)
        (folder / "rollout-parent-parent-6.jsonl").write_text("\n".join([
            json.dumps({"type": "turn_context", "payload": {"model": "gpt-6.1-sol"}}),
            json.dumps({"type": "response_item", "payload": {"type": "function_call", "name": "spawn_agent", "call_id": "call_6"}}),
            json.dumps({"type": "turn_context", "payload": {"model": "gpt-6-astra"}}),
            json.dumps({"type": "response_item", "payload": {"type": "function_call_output", "call_id": "call_6"}})]) + "\n")
        self.collect(); self.assertEqual(self.rows()[0]["parent_model"], "gpt-6.1-sol")


class PrivacyAndCliTests(Env):
    def test_no_task_text_reaches_the_database_and_the_period_limits_the_candidates(self):
        self.child("claude", "toolu_8", "a8"); self.child("claude", "toolu_old", "aold", ts=NOW - 40 * 86400)
        self.claude_agent("a8", "toolu_8", [claude_line("m", "claude-haiku-5-5")])
        self.claude_agent("aold", "toolu_old", [claude_line("m", "claude-haiku-5-5")])
        summary = self.collect(days=30)
        self.assertEqual((summary["candidates"], summary["collected"]), (1, 1))
        with sqlite3.connect(self.store.path) as db:
            dump = "".join(str(r) for t in ("child_usage", "children", "advice") for r in db.execute(f"SELECT * FROM {t}"))
        self.assertNotIn(SECRET, dump)

    def test_the_command_prints_chinese_counts_and_json_and_refuses_bad_input(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        path = Path(tmp.name).resolve() / "owned" / "settings.json"; v2.init(path)
        store = AdviceStore(path.parent / "advice.sqlite3")
        store.record_child(Child("claude", "s1", "toolu_9", "haiku", "high", None, "a9"), NOW - 3600)
        args = Namespace(days=None, json=False, settings=path)
        out, err = io.StringIO(), io.StringIO()
        code = usage_cli.main(args, stdin=io.StringIO(), stdout=out, stderr=err, now=NOW, claude_root=self.claude, codex_root=self.codex)
        text = out.getvalue()
        self.assertEqual(code, 0)
        for expected in ("只讀本機紀錄檔，不連網、不花錢", "共 1 個", "找不到紀錄檔", "找不到 Claude 的子代理紀錄檔", "mrh stats"):
            self.assertIn(expected, text)
        args.json = True; out = io.StringIO()
        usage_cli.main(args, stdin=io.StringIO(), stdout=out, stderr=err, now=NOW, claude_root=self.claude, codex_root=self.codex)
        self.assertEqual(json.loads(out.getvalue())["not_found"], 1)
        args.days = 0
        self.assertEqual(usage_cli.main(args, stdin=io.StringIO(), stdout=io.StringIO(), stderr=err, now=NOW), 2)
        self.assertIn("mrh usage collect", cli.COMMAND_LIST)
        parsed = cli.build_parser().parse_args(["usage", "collect", "--days", "7", "--json"])
        self.assertEqual((parsed.usage_action, parsed.days, parsed.json), ("collect", 7.0, True))

    def test_roots_come_from_the_environment_for_tests_and_default_to_the_vendor_folders(self):
        self.assertEqual(uc.roots({uc.CLAUDE_ENV: "/x/claude", uc.CODEX_ENV: "/x/codex"}), (Path("/x/claude"), Path("/x/codex")))
        claude, codex = uc.roots({})
        self.assertTrue(str(claude).endswith(".claude/projects") and str(codex).endswith(".codex/sessions"))


class SnapshotValidityTests(Env):
    def test_required_values_are_not_zero_filled_and_real_zero_is_valid(self):
        path = self.claude_agent("invalid", "c", [claude_line("m", "claude-haiku-5-5", inp=0)])
        base = json.loads(path.read_text())
        for field in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
            for invalid in (None, True, -1, "0", 0.5):
                with self.subTest(field=field, invalid=invalid):
                    record = json.loads(json.dumps(base)); record["message"]["usage"][field] = invalid
                    path.write_text(json.dumps(record) + "\n")
                    with self.assertRaisesRegex(ValueError, "invalid_usage:"):
                        uc.parse_claude(path)
        path.write_text(json.dumps(base) + "\n")
        self.assertEqual(uc.parse_claude(path)["claude-haiku-5-5"]["small"]["input"], 0)
        base["message"]["usage"]["cache_creation"]["ephemeral_5m_input_tokens"] = 1
        path.write_text(json.dumps(base) + "\n")
        with self.assertRaisesRegex(ValueError, "inconsistent_usage:"):
            uc.parse_claude(path)

    def test_invalid_later_record_does_not_publish_partial_claude_total(self):
        self.child("claude", "c", "invalid")
        path = self.claude_agent("invalid", "c", [claude_line("m", "claude-haiku-5-5")])
        self.collect(); original = self.rows()
        invalid = json.loads(claude_line("m2", "claude-haiku-5-5")); invalid["message"]["usage"].pop("input_tokens")
        path.write_text(path.read_text() + json.dumps(invalid) + "\n"); os.utime(path, (NOW - 1800, NOW - 1800))
        result = uc.collect(self.store, NOW + 1, claude_root=self.claude, codex_root=self.codex)
        self.assertEqual(result["collected"], 0); self.assertEqual(self.rows(), original)
        self.assertEqual(result["details"][0]["reason"], "invalid_usage:input_tokens")

    def test_codex_required_missing_invalid_and_inconsistent_counts(self):
        base = {"input_tokens": 5, "cached_input_tokens": 1, "cache_write_input_tokens": 0, "output_tokens": 2, "total_tokens": 7}
        for field in ("input_tokens", "cached_input_tokens", "cache_write_input_tokens", "output_tokens"):
            for invalid in (None, True, -1, "0"):
                with self.subTest(field=field, invalid=invalid):
                    counts = {**base, field: invalid}
                    path = self.codex_agent("p", "/root/x", total=counts)
                    with self.assertRaisesRegex(ValueError, "invalid_usage:"):
                        uc.parse_codex(path)
        for counts in ({**base, "cached_input_tokens": 6}, {**base, "total_tokens": 0}, {**base, "reasoning_output_tokens": 3}):
            with self.assertRaisesRegex(ValueError, "inconsistent_usage:"):
                uc.parse_codex(self.codex_agent("p", "/root/x", total=counts))
        zero = {k: 0 for k in base}
        _, entries = uc.parse_codex(self.codex_agent("p", "/root/x", total=zero))
        e = entries["gpt-6-luna"]
        self.assertEqual(e["output"], 0); self.assertIsNone(e["reasoning"]); self.assertIsNone(e["max_request_input"])

    def test_codex_refresh_replaces_cumulative_total_and_unchanged_does_not_index_or_read(self):
        self.child("codex", "c", "/root/x", session="p")
        path = self.codex_agent("p", "/root/x")
        self.collect()
        with patch.object(uc, "index_codex", side_effect=AssertionError("indexed")), patch.object(uc, "_lines", side_effect=AssertionError("body reread")):
            self.assertEqual(self.collect()["unchanged"], 1)
        payload = {"type": "event_msg", "payload": {"type": "token_count", "info": {"total_token_usage": {
            "input_tokens": 2000, "cached_input_tokens": 600, "cache_write_input_tokens": 0, "output_tokens": 70, "total_tokens": 2070}}}}
        path.write_text(path.read_text() + json.dumps(payload) + "\n"); os.utime(path, (NOW - 1800, NOW - 1800))
        self.assertEqual(self.collect()["updated"], 1)
        (row,) = self.rows()
        self.assertEqual(json.loads(row["usage"])["gpt-6-luna"]["small"]["input"], 1400)

    def test_changes_during_read_preserve_snapshot_and_collected_at(self):
        self.child("claude", "c", "race")
        path = self.claude_agent("race", "c", [claude_line("m", "claude-haiku-5-5")])
        self.collect(); old = self.rows()
        path.write_text(path.read_text() + claude_line("m2", "claude-haiku-5-5") + "\n")
        os.utime(path, (NOW - 1800, NOW - 1800))
        parse = uc.parse_claude
        def racing(p):
            value = parse(p)
            with p.open("a") as f:
                f.write("\n")
            return value
        with patch.object(uc, "parse_claude", side_effect=racing):
            result = uc.collect(self.store, NOW + 5, claude_root=self.claude, codex_root=self.codex)
        self.assertEqual(self.rows(), old)
        self.assertEqual(result["details"][0]["reason"], "source_changed_during_read")

    def test_metadata_change_refreshes_and_legacy_revalidates_once(self):
        self.child("claude", "c", "legacy")
        path = self.claude_agent("legacy", "c", [claude_line("m", "claude-haiku-5-5")])
        self.collect()
        row = self.rows()[0]; legacy = json.loads(row["usage"])
        for entry in legacy.values():
            entry.pop("observation")
        with self.store.connect() as db:
            db.execute("UPDATE child_usage SET usage=?", (json.dumps(legacy),))
        self.assertEqual(self.collect()["updated"], 1); self.assertEqual(self.collect()["unchanged"], 1)
        meta = path.with_suffix(".meta.json"); data = json.loads(meta.read_text()); data["effort"] = "low"
        meta.write_text(json.dumps(data)); os.utime(meta, (NOW - 1200, NOW - 1200))
        self.assertEqual(self.collect()["updated"], 1)
        self.assertEqual(json.loads(self.rows()[0]["models"])[0]["effort"], "low")


class SnapshotBoundaryTests(Env):
    def test_codex_unknown_profile_and_incomplete_request_lengths_are_not_verified(self):
        path = self.codex_agent("p", "/root/x")
        records = [json.loads(line) for line in path.read_text().splitlines()]
        records.insert(2, {"type": "turn_context", "payload": {"effort": "high"}})
        path.write_text("\n".join(map(json.dumps, records)) + "\n")
        models, usage = uc.parse_codex(path)
        self.assertIn({}, models); self.assertIn(uc.MIXED, usage)
        self.assertIsNone(usage[uc.MIXED]["max_request_input"])
        records[-1]["payload"]["info"]["last_token_usage"] = {"input_tokens": 1000, "output_tokens": 50}
        records.pop(2)
        path.write_text("\n".join(map(json.dumps, records + [records[-1]])) + "\n")
        _, usage = uc.parse_codex(path)
        self.assertEqual(usage["gpt-6-luna"]["requests"], 1)  # repeated cumulative report is not another request
        self.assertEqual(usage["gpt-6-luna"]["max_request_input"], 1000)
        records[-1]["payload"]["info"]["last_token_usage"]["input_tokens"] = 999
        path.write_text("\n".join(map(json.dumps, records)) + "\n")
        _, usage = uc.parse_codex(path)
        self.assertIsNone(usage["gpt-6-luna"]["max_request_input"])
        for record in (["token_count"], {"type": "event_msg", "payload": "token_count"},
                       {"type": "event_msg", "payload": {"type": "token_count", "info": {"last_token_usage": {"input_tokens": 1}}}}):
            path.write_text(json.dumps(record) + "\n")
            with self.assertRaisesRegex(ValueError, "invalid_usage:"):
                uc.parse_codex(path)

    def test_replaced_file_with_same_size_and_mtime_is_not_unchanged(self):
        self.child("claude", "c", "identity")
        path = self.claude_agent("identity", "c", [claude_line("m", "claude-haiku-5-5", inp=1)])
        self.collect(); stat = path.stat()
        replacement = path.with_suffix(".replacement")
        replacement.write_text(path.read_text().replace('"input_tokens": 1', '"input_tokens": 9'))
        os.utime(replacement, ns=(stat.st_atime_ns, stat.st_mtime_ns)); replacement.replace(path)
        self.assertEqual(self.collect()["updated"], 1)
        self.assertEqual(json.loads(self.rows()[0]["usage"])["claude-haiku-5-5"]["small"]["input"], 9)


class ParentReaderTests(Env):
    def parent(self, records, parent="parent-cross-day"):
        folder = self.codex / "2026/09/24"; folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"rollout-parent-{parent}.jsonl"
        path.write_text("\n".join(json.dumps(r) for r in records) + "\n")
        return path

    @staticmethod
    def context(model="gpt-6.1-sol"):
        return {"type": "turn_context", "payload": {"model": model}}

    @staticmethod
    def call(call_id, name="spawn_agent", **extra):
        return {"type": "response_item", "payload": {"type": "function_call", "name": name, "call_id": call_id, **extra}}

    def test_parent_exceeds_child_total_limit_but_streams_both_exact_calls_across_days(self):
        path = self.parent([self.context(), self.call("call_a", "collaborationspawn_agent"), self.call("call_b", "another_native_alias")])
        with patch.object(uc, "MAX_FILE_BYTES", 32):
            self.assertGreater(path.stat().st_size, uc.MAX_FILE_BYTES)
            self.assertEqual(uc.codex_parent_models(self.codex, "parent-cross-day", ["call_a", "call_b"]),
                             {"call_a": "gpt-6.1-sol", "call_b": "gpt-6.1-sol"})
            with self.assertRaisesRegex(ValueError, "too_large"):
                uc.parse_codex(path)  # child usage retains the original whole-file gate

    def test_only_real_events_and_exact_ids_count_not_quoted_arguments_or_outputs(self):
        self.parent([self.context(),
                     self.call("different", arguments=json.dumps({"call_id": "wanted"})),
                     {"type": "event_msg", "payload": {"type": "function_call", "call_id": "wanted"}},
                     {"type": "response_item", "payload": {"type": "function_call_output", "call_id": "wanted"}},
                     self.call("wanted_suffix"),
                     {"type": "response_item", "payload": {"type": "message", "text": json.dumps(self.call("wanted"))}}])
        self.assertEqual(uc.codex_parent_models(self.codex, "parent-cross-day", ["wanted"]), {})

    def test_missing_or_invalid_new_context_clears_model_and_quoted_context_does_not(self):
        for payload in ({}, {"model": None}, {"model": False}, {"model": "invalid model"}, "not a payload"):
            with self.subTest(payload=payload):
                self.parent([self.context(), {"type": "turn_context", "payload": payload}, self.call("wanted")])
                self.assertEqual(uc.codex_parent_models(self.codex, "parent-cross-day", ["wanted"]), {})
        self.parent([self.context(), {"type": "response_item", "payload": {"type": "message", "text": json.dumps(self.context("gpt-6-astra"))}}, self.call("wanted")])
        self.assertEqual(uc.codex_parent_models(self.codex, "parent-cross-day", ["wanted"]), {"wanted": "gpt-6.1-sol"})

    def test_oversized_line_stops_parent_without_parsing_tail_or_losing_prior_evidence(self):
        path = self.parent([self.context(), self.call("before")])
        with path.open("ab") as f:
            f.write(b' ' * 257 + b'\n')
            f.write((json.dumps(self.call("after")) + "\n").encode())
        with patch.object(uc, "MAX_PARENT_LINE_BYTES", 256):
            self.assertEqual(uc.codex_parent_models(self.codex, "parent-cross-day", ["before", "after"]), {"before": "gpt-6.1-sol"})

    def test_stops_reading_immediately_after_all_wanted_calls(self):
        path = self.parent([])
        def lines(p):
            self.assertEqual(p, path)
            yield json.dumps(self.context()).encode()
            yield json.dumps(self.call("wanted")).encode()
            raise AssertionError("read beyond complete mapping")
        with patch.object(uc, "_parent_lines", side_effect=lines):
            self.assertEqual(uc.codex_parent_models(self.codex, "parent-cross-day", ["wanted"]), {"wanted": "gpt-6.1-sol"})

    def test_legacy_two_children_refresh_same_primary_keys_with_new_parent_mapping(self):
        for call, agent in (("call_a", "/root/a"), ("call_b", "/root/b")):
            self.child("codex", call, agent, session="parent-cross-day")
            self.codex_agent("parent-cross-day", agent)
        self.collect(); before = self.rows()
        self.assertEqual(len(before), 2); self.assertTrue(all(row["parent_model"] is None for row in before))
        with self.store.connect() as db:
            for row in before:
                legacy = json.loads(row["usage"])
                for entry in legacy.values():
                    entry.pop("observation")
                db.execute("UPDATE child_usage SET usage=? WHERE platform=? AND session_id=? AND call_id=?",
                           (json.dumps(legacy), row["platform"], row["session_id"], row["call_id"]))
        self.parent([self.context(), self.call("call_a"), self.call("call_b")])
        result = self.collect(); after = self.rows()
        self.assertEqual((result["collected"], result["updated"]), (2, 2))
        self.assertEqual([(r["platform"], r["session_id"], r["call_id"]) for r in after],
                         [(r["platform"], r["session_id"], r["call_id"]) for r in before])
        self.assertEqual([r["parent_model"] for r in after], ["gpt-6.1-sol"] * 2)
        with patch.object(uc, "codex_parent_models", side_effect=AssertionError("unchanged parent reread")):
            self.assertEqual(self.collect()["unchanged"], 2)


if __name__ == "__main__":
    unittest.main()
