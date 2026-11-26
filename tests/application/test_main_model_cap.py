"""Claude Code: advice that is not smaller than the main model is dropped; whatever cannot be read leaves the hook as before."""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from mrh.adapters.hosts import claude_transcript
from mrh.advisory import advice_text, engine
from mrh.advisory.hook_budget import HookBudget
from mrh.application import advisory_runtime as rt
from mrh.infrastructure import settings_v2 as v2
from mrh.presentation import ctrl, dashboard, report_html, stats_view
from mrh.routing.types import REASONS, Classification

SESSION, CALL = "0a1b2c3d-0000-4000-8000-000000000001", "toolu_01SyntheticCallAaaaaaaaa"
OPUS_HIGH, SONNET, HAIKU = {"model": "opus", "effort": "high"}, {"model": "sonnet", "effort": "medium"}, {"model": "haiku", "effort": "medium"}
LADDER = [OPUS_HIGH, SONNET, HAIKU]


class Fixed:
    def __init__(self, tier="Light", confidence=0.9, probabilities=None):
        self.result, self.calls = Classification(tier, confidence, probabilities=probabilities), 0

    def classify(self, task, context, recorder):
        self.calls += 1
        return self.result


def record(call=CALL, **over):
    """One assistant line of a synthetic main transcript, holding the Agent call `call`."""
    line = {"type": "assistant", "sessionId": SESSION, "isSidechain": False, "effort": "high", "uuid": "u-1",
            "message": {"model": "claude-opus-5-5", "id": "msg_synthetic", "role": "assistant",
                        "content": [{"type": "tool_use", "id": call, "name": "Agent",
                                     "input": {"description": "synthetic", "prompt": "synthetic task"}}]}}
    for key, value in over.items():
        if key == "model":
            line["message"]["model"] = value
        elif value is None:
            line.pop(key, None)
        else:
            line[key] = value
    return json.dumps(line)


NEIGHBOURS = [json.dumps({"type": "user", "sessionId": SESSION, "message": {"role": "user", "content": "synthetic"}}),
              json.dumps({"type": "attachment", "sessionId": SESSION, "toolUseID": CALL}),
              json.dumps({"type": "queue-operation", "sessionId": SESSION, "content": CALL})]


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.runs = 0

    def transcript(self, *lines, name="main.jsonl", end="\n"):
        path = self.root / name
        path.write_bytes(("\n".join(lines) + end).encode())
        return str(path)

    def event(self, transcript=None, **tool_input):
        event = {"hook_event_name": "PreToolUse", "tool_name": "Agent", "session_id": SESSION, "prompt_id": "p-1",
                 "tool_use_id": CALL, "cwd": "/work/project", "permission_mode": "default",
                 "tool_input": {"description": "Rename a variable", "prompt": "Rename cnt to count in utils.py", **tool_input}}
        if transcript is not None:
            event["transcript_path"] = transcript
        return event

    def fresh(self, policy=None):
        """A new settings folder and database for every run, so no replay or same-task de-duplication can fake a match."""
        self.runs += 1
        path = self.root / f"owned-{self.runs}" / "settings.json"
        v2.init(path)
        v2.update(path, enabled=True, task_export_permitted=True, allowed_workspaces=["/"],
                  policy=policy or {"tiers": {"Light": {"claude": LADDER}}})
        return path

    def handle(self, event, policy=None, fake=None, platform="claude", **kw):
        path, fake = self.fresh(policy), fake or Fixed()
        out = rt.handle(event, platform, path, classifier_factory=lambda: fake, **kw)
        self.assertEqual(fake.calls, 1)
        return out, path

    def row(self, path):
        with sqlite3.connect(path.parent / "advice.sqlite3") as db:
            db.row_factory = sqlite3.Row
            return dict(db.execute("SELECT * FROM advice").fetchone())

    def without_feature(self, event, policy=None, **kw):
        with patch.object(engine, "_below_main", lambda decision, *a: decision):
            return self.handle(event, policy, **kw)


class UnreadableMainModelTests(Base):
    """Every way the main model can be missing gives byte-for-byte the hook output MRH gave before this feature."""

    def assertUnchanged(self, event):
        before, _ = self.without_feature(event)
        self.assertEqual(before["hookSpecificOutput"]["permissionDecisionReason"],
                         advice_text.advise("claude", "Light", 0.9, tuple(LADDER)))
        after, path = self.handle(event)
        self.assertEqual(json.dumps(after, sort_keys=True), json.dumps(before, sort_keys=True))
        row = self.row(path)
        self.assertEqual((row["action"], row["reason"], json.loads(row["candidates"])["candidates"]), ("advise", "advice_given", LADDER))

    def test_no_transcript_path_or_one_that_is_not_an_absolute_regular_file(self):
        self.assertUnchanged(self.event())
        self.assertUnchanged(self.event("relative/main.jsonl"))
        self.assertUnchanged(self.event(str(self.root / "missing.jsonl")))
        self.assertUnchanged(self.event(str(self.root)))                       # a directory
        self.assertUnchanged({**self.event(), "transcript_path": ["not", "a", "path"]})

    @unittest.skipUnless(hasattr(os, "mkfifo"), "POSIX FIFO")
    def test_a_fifo_is_never_opened_so_it_cannot_block_the_hook(self):
        fifo = self.root / "pipe.jsonl"; os.mkfifo(fifo)
        started = time.monotonic()
        self.assertUnchanged(self.event(str(fifo)))
        self.assertLess(time.monotonic() - started, 2.0)

    def test_the_call_is_not_in_the_transcript(self):
        self.assertUnchanged(self.event(self.transcript(*NEIGHBOURS, record(call="toolu_01OtherCallBbbbbbbbbbbbbb"))))  # no "last line" fallback
        self.assertUnchanged(self.event(self.transcript(*NEIGHBOURS)))          # lines that only mention the id do not count
        self.assertUnchanged(self.event(self.transcript("")))

    def test_the_line_of_the_call_does_not_match_exactly(self):
        for over in ({"sessionId": "0a1b2c3d-0000-4000-8000-000000000002"}, {"sessionId": None}, {"isSidechain": True},
                     {"model": "<synthetic>"}, {"model": None}, {"model": "claude opus"}, {"effort": None},
                     {"effort": "turbo"}, {"effort": ["high"]}, {"type": "user"}):
            with self.subTest(over=over):
                self.assertUnchanged(self.event(self.transcript(*NEIGHBOURS, record(**over))))

    def test_the_line_of_the_call_is_not_valid_json(self):
        self.assertUnchanged(self.event(self.transcript(*NEIGHBOURS, record()[:-1])))
        self.assertUnchanged(self.event(self.transcript(*NEIGHBOURS, record()[:-40], end="")))   # still being written

    def test_two_lines_holding_the_same_call_are_ambiguous(self):
        self.assertUnchanged(self.event(self.transcript(record(), *NEIGHBOURS, record())))

    def test_a_line_cut_or_left_out_by_the_tail_window(self):
        filler = json.dumps({"type": "user", "sessionId": SESSION, "message": {"content": "x" * 3000}})
        with patch.object(claude_transcript, "TAIL_BYTES", 4096):
            self.assertUnchanged(self.event(self.transcript(record(), filler, filler)))           # left out entirely
            target = record()
            cut = self.transcript(target, "x" * (4096 - len(target) // 2))                       # the window starts inside it
            self.assertLess(os.path.getsize(cut) - 4096, len(target))
            self.assertUnchanged(self.event(cut))
            padded = self.transcript(" " * 4096 + target)        # what is left after the cut would even parse: still dropped
            self.assertUnchanged(self.event(padded))
            whole = self.transcript(filler, filler, record())
            self.assertGreater(os.path.getsize(whole), 4096)
            out, _ = self.handle(self.event(whole))                                                # inside the window: read
            self.assertIn("model=sonnet", out["hookSpecificOutput"]["permissionDecisionReason"])
            self.assertNotIn("model=opus", out["hookSpecificOutput"]["permissionDecisionReason"])

    def test_a_reader_that_raises_or_hangs_changes_nothing(self):
        event = self.event(self.transcript(record()))
        with patch.object(claude_transcript, "main_model", side_effect=RuntimeError("synthetic")):
            self.assertUnchanged(event)
        with patch("mrh.advisory.main_cap.below_main", side_effect=KeyError("synthetic")):
            self.assertUnchanged(event)
        slow = lambda e: time.sleep(engine.MAIN_READ_SECONDS + 0.3) or ("claude-opus-5-5", "high")
        with patch.object(claude_transcript, "main_model", side_effect=slow):
            self.assertUnchanged(event)
        with patch.object(claude_transcript, "main_model", return_value=("claude-opus-5-5",)):     # malformed result
            self.assertUnchanged(event)

    def test_too_little_hook_time_left_skips_the_read(self):
        event = self.event(self.transcript(record()))
        with patch.object(claude_transcript, "main_model", side_effect=AssertionError("must not read")) as reader:
            budget = HookBudget(time.monotonic() - 2.0)        # 0.5 s left of the 2.5 s Jev window: enough to save, not to read
            out, path = self.handle(event, hook_budget=budget)
        reader.assert_not_called()
        self.assertEqual(out["hookSpecificOutput"]["permissionDecisionReason"], advice_text.advise("claude", "Light", 0.9, tuple(LADDER)))


class FilteredAdviceTests(Base):
    def test_only_the_candidates_below_the_main_model_remain_in_the_same_words(self):
        out, path = self.handle(self.event(self.transcript(*NEIGHBOURS, record(), NEIGHBOURS[1])))
        self.assertEqual(out, {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                               "permissionDecisionReason": advice_text.advise("claude", "Light", 0.9, (SONNET, HAIKU))}})
        row = self.row(path)
        self.assertEqual((row["action"], row["reason"], json.loads(row["candidates"])["candidates"]), ("advise", "advice_given", [SONNET, HAIKU]))

    def test_a_higher_main_effort_keeps_the_same_model(self):
        out, _ = self.handle(self.event(self.transcript(record(effort="xhigh"))))
        self.assertEqual(out["hookSpecificOutput"]["permissionDecisionReason"], advice_text.advise("claude", "Light", 0.9, tuple(LADDER)))

    def test_a_main_model_without_a_price_keeps_the_full_advice(self):
        out, _ = self.handle(self.event(self.transcript(record(model="claude-fable-5-2"))))
        self.assertEqual(out["hookSpecificOutput"]["permissionDecisionReason"], advice_text.advise("claude", "Light", 0.9, tuple(LADDER)))

    def test_nothing_left_lets_the_call_run_unchanged_and_records_where_it_landed(self):
        out, path = self.handle(self.event(self.transcript(record())), {"tiers": {"Light": {"claude": [OPUS_HIGH]}}})
        self.assertEqual(out, {})
        row = self.row(path)
        self.assertEqual((row["action"], row["reason"], row["tier"], row["confidence"], json.loads(row["candidates"])["candidates"]),
                         ("preserve", "at_or_above_main", "Light", 0.9, []))
        self.assertIn("at_or_above_main", REASONS); self.assertIn("at_or_above_main", engine.QUIET)
        self.assertViewsWork(path, "建議的模型都不比主模型小")

    def test_gears_mode_keeps_the_gear_and_score_of_a_call_it_lets_through(self):
        gears = {"mode": "gears", "threshold": 0.65, "gears": [
            {"from": 0, "candidates": {"claude": [HAIKU]}}, {"from": 1.5, "candidates": {"claude": [OPUS_HIGH]}}, {"from": 2.5, "main": True}]}
        fake = Fixed("Mid", 0.8, {"Light": 0.0, "Small": 0.2, "Mid": 0.8, "Top": 0.0})            # score 1.8 -> gear 2
        out, path = self.handle(self.event(self.transcript(record())), gears, fake)
        self.assertEqual(out, {})
        row = self.row(path)
        meta = json.loads(row["candidates"])
        self.assertEqual((row["action"], row["reason"], row["tier"]), ("preserve", "at_or_above_main", "Mid"))
        self.assertEqual((meta["gear"], meta["score"], meta["candidates"]), (2, 1.8, []))
        self.assertViewsWork(path, "建議的模型都不比主模型小")
        data, _ = ctrl.statistics(path, None)
        policy = v2.read(path)["policy"]
        parts, _ = stats_view.gear_parts(data, policy)
        self.assertIn(("Pass", 1), parts)                                                      # counted as passed through

    def assertViewsWork(self, path, label):
        data, period = ctrl.statistics(path, None)
        self.assertEqual(data["decisions"], {"preserve": 1}); self.assertEqual(data["kept_unchanged"], {"at_or_above_main": 1})
        settings = v2.read(path)
        self.assertIn(label, stats_view.render(data, period, settings["policy"]["threshold"], False, settings["policy"]))
        self.assertIn("1 次原樣放行", report_html.render(settings, data, period))
        status = ctrl.status_data(path, None, include_events=True)
        dashboard.render(status["status"], status, status["status"]["period_label"], 100, False)
        [item] = [e for e in status["events"]["items"] if e["kind"] == "decision"]
        self.assertEqual((item["action"], item["reason"]), ("preserve", "at_or_above_main"))


class UntouchedPathTests(Base):
    def test_other_outcomes_never_read_the_transcript(self):
        transcript = self.transcript(record())
        cases = [(self.event(transcript), {"tiers": {"Light": {"claude": LADDER}}, "threshold": 0.95}, Fixed()),      # low confidence
                 (self.event(transcript), {"tiers": {}}, Fixed("Top")),                                               # Top -> main
                 (self.event(transcript), {"tiers": {"Small": {"claude": LADDER}}}, Fixed())]                         # no candidates
        with patch.object(claude_transcript, "main_model", side_effect=AssertionError("must not read")) as reader:
            for event, policy, fake in cases:
                before, _ = self.without_feature(event, policy, fake=Fixed(fake.result.tier, fake.result.confidence))
                after, _ = self.handle(event, policy, fake)
                self.assertEqual(after, before)
            for explicit in ({"model": "opus"}, {"effort": "high"}, {"subagent_type": "Explore"}):
                path = self.fresh()
                out = rt.handle(self.event(transcript, **explicit), "claude", path, classifier_factory=lambda: Fixed())
                self.assertEqual(out, {})
        reader.assert_not_called()

    def test_codex_is_not_filtered(self):
        event = {"hook_event_name": "PreToolUse", "tool_name": "spawn_agent", "session_id": "s1", "turn_id": "t1",
                 "tool_use_id": "call1", "cwd": "/work/project", "transcript_path": self.transcript(record()),
                 "tool_input": {"message": "Rename cnt to count in utils.py"}}
        policy = {"tiers": {"Light": {"codex": [{"model": "gpt-6.1-sol", "effort": "high"}]}}}
        with patch.object(engine, "_below_main", side_effect=AssertionError("codex must not be filtered")):
            out, _ = self.handle(event, policy, platform="codex")
        self.assertIn("model=gpt-6.1-sol", out["hookSpecificOutput"]["permissionDecisionReason"])

    def test_paths_that_do_not_advise_do_not_load_the_reader_or_the_price_table(self):
        path = self.fresh({"tiers": {"Light": {"claude": LADDER}}, "threshold": 0.95})
        script = ("import json,sys\nfrom mrh.application import advisory_runtime as rt\nfrom mrh.routing.types import Classification\n"
                  "class F:\n  def classify(self,*a): return Classification('Light',0.9)\n"
                  f"event=json.loads({json.dumps(json.dumps(self.event(self.transcript(record()))))})\n"
                  f"out=rt.handle(event,'claude',{str(path)!r},classifier_factory=F)\n"
                  "print(json.dumps([out, [m in sys.modules for m in ('mrh.adapters.hosts.claude_transcript','mrh.advisory.main_cap','mrh.advisory.pricing','mrh.advisory.usage_collect')]]))\n")
        env = {**os.environ, "PYTHONPATH": str(Path(rt.__file__).resolve().parents[2]), "PYTHONDONTWRITEBYTECODE": "1"}
        result = subprocess.run([sys.executable, "-B", "-c", script], capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), [{}, [False, False, False, False]])


if __name__ == "__main__":
    unittest.main()
