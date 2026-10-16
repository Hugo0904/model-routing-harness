import io
import json
import os
import sqlite3
import tempfile
import time
import unittest
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

    def test_large_prompts_are_kept_apart_for_the_higher_price_tier_and_cache_without_a_ttl_split_is_not_guessed(self):
        self.child("claude", "toolu_2", "a2")
        self.claude_agent("a2", "toolu_2", [claude_line("big", "claude-haiku-5-5", inp=50, read=120_000),                    # 120,050 > 100K
                                            claude_line("old", "claude-haiku-5-5", inp=5, total_cc=700, cc=False)])             # no TTL breakdown
        self.collect()
        usage = json.loads(self.rows()[0]["usage"])["claude-haiku-5-5"]
        self.assertEqual(usage["large"]["cache_read"], 120_000); self.assertEqual(usage["small"]["cache_read"], 0)
        self.assertEqual((usage["small"]["cache_write"], usage["small"]["cache_write_5m"]), (700, 0))

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

    def test_rerunning_never_duplicates_or_rereads(self):
        self.child("claude", "toolu_6", "a6")
        path = self.claude_agent("a6", "toolu_6", [claude_line("m", "claude-haiku-5-5", inp=5)])
        self.assertEqual(self.collect()["collected"], 1)
        path.write_text("")                                                                             # a re-read would now find nothing
        again = self.collect()
        self.assertEqual((again["candidates"], again["collected"]), (0, 0)); self.assertEqual(len(self.rows()), 1)

    def test_unknown_parent_model_stays_unknown(self):
        self.child("claude", "toolu_7", "a7")
        self.claude_agent("a7", "toolu_7", [claude_line("m", "claude-haiku-5-5")])
        self.collect(); self.assertIsNone(self.rows()[0]["parent_model"])


class CodexTests(Env):
    def test_the_child_is_found_by_parent_thread_and_agent_path_and_totals_are_taken_as_final(self):
        self.child("codex", "call_1", "/root/map_ui", session="parent-1", model="gpt-6-luna")
        self.codex_agent("parent-1", "/root/map_ui", call_models=[("gpt-6-luna", "max")])
        self.codex_agent("parent-1", "/root/other_task")                                                  # a different child: ignored
        summary = self.collect()
        self.assertEqual((summary["candidates"], summary["collected"]), (1, 1))
        (row,) = self.rows()
        usage = json.loads(row["usage"])["gpt-6-luna"]
        self.assertEqual(usage["small"], {"input": 400, "cache_write_5m": 0, "cache_write_1h": 0, "cache_write": 0, "cache_read": 600})  # input includes cached
        self.assertEqual((usage["output"], usage["reasoning"], usage["requests"]), (50, 20, 0))
        self.assertEqual(usage["max_request_input"], 0)                                                   # no per-request record in this fixture
        self.assertEqual(json.loads(row["models"]), [{"model": "gpt-6-luna", "effort": "max"}])

    def test_the_largest_single_request_is_recorded_for_the_long_context_price_tier(self):
        self.child("codex", "call_7", "/root/big", session="parent-7")
        file = self.codex_agent("parent-7", "/root/big")
        extra = [json.dumps({"type": "event_msg", "payload": {"type": "token_count", "info": {"last_token_usage": {"input_tokens": n}}}}) for n in (1000, 310_000, 5000)]
        file.write_text(file.read_text() + "\n".join(extra) + "\n"); os.utime(file, (NOW - 3600, NOW - 3600))
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


if __name__ == "__main__":
    unittest.main()
