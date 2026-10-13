import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from mrh.adapters.hosts.advisory_hosts import HOSTS
from mrh.adapters.providers.typesafe import HttpResponse, TypesafeClassifier
from mrh.application import advisory_runtime as rt
from mrh.infrastructure import settings_v2 as v2
from mrh.routing.types import Classification

FIXTURE = json.loads((Path(__file__).parent.parent / "fixtures" / "claude_agent_events.json").read_text())
SECRET = "tsk_SECRET_do_not_leak_0123456789"
LISTS = {"tiers": {"Light": {"codex": [{"model": "gpt-5.6-luna", "effort": "low"}], "claude": [{"model": "haiku"}]}}}


def codex_pre(**tool_input):
    return {"hook_event_name": "PreToolUse", "tool_name": "spawn_agent", "session_id": "s1", "turn_id": "t1",
            "tool_use_id": "call1", "cwd": "/work/project", "model": "gpt-6.1-sol",
            "tool_input": {"message": "Rename cnt to count in utils.py", **tool_input}}


class Fixed:
    def __init__(self, tier="Light", confidence=0.9):
        self.result, self.calls = Classification(tier, confidence), 0
    def classify(self, task, context, recorder):
        self.calls += 1
        return self.result


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name).resolve() / "owned"
        self.path = self.dir / "settings.json"
        v2.init(self.path)

    def configure(self, **changes):
        base = dict(enabled=True, task_export_permitted=True, allowed_workspaces=["/"], policy=LISTS)
        return v2.update(self.path, **{**base, **changes})

    def handle(self, event, platform="codex", fake=None):
        fake = fake or Fixed()
        return rt.handle(event, platform, self.path, classifier_factory=lambda: fake), fake

    def test_disabled_unlisted_and_unrelated_events_do_nothing_at_all(self):
        out, fake = self.handle(codex_pre())                         # disabled by default
        self.assertEqual((out, fake.calls), ({}, 0))
        self.configure(allowed_workspaces=["/elsewhere"])
        out, fake = self.handle(codex_pre())
        self.assertEqual((out, fake.calls), ({}, 0))
        self.configure(allowed_workspaces=["/"])
        out, fake = self.handle({"hook_event_name": "PreToolUse", "tool_name": "shell", "tool_input": {}})
        self.assertEqual((out, fake.calls), ({}, 0))
        self.assertFalse((self.dir / "advice.sqlite3").exists())    # not even a database was created

    def test_codex_advice_is_a_deny_that_names_model_and_effort(self):
        self.configure()
        out, fake = self.handle(codex_pre())
        decision = out["hookSpecificOutput"]
        self.assertEqual((decision["permissionDecision"], fake.calls), ("deny", 1))
        self.assertIn("model=gpt-5.6-luna reasoning_effort=low", decision["permissionDecisionReason"])
        self.assertNotIn("Rename cnt", decision["permissionDecisionReason"])   # task text is never echoed

    def test_reissued_call_with_a_model_passes_and_is_recorded_as_following_advice(self):
        self.configure()
        self.handle(codex_pre())
        reissue = codex_pre(model="gpt-5.6-luna", reasoning_effort="low"); reissue["tool_use_id"] = "call2"
        out, fake = self.handle(reissue)
        self.assertEqual((out, fake.calls), ({}, 0))
        post = {**reissue, "hook_event_name": "PostToolUse", "tool_response": json.dumps({"agent_id": "a-1"})}
        self.handle(post)
        with sqlite3.connect(self.dir / "advice.sqlite3") as db:
            self.assertEqual(db.execute("SELECT followed FROM children").fetchall(), [(1,)])

    def test_codex_encrypted_message_falls_back_to_the_readable_task_name(self):
        token = "gAAAAABqzc6Q" + "A1b2C3d4_-" * 12
        host = HOSTS["codex"]
        seen = host.request(codex_pre(message=token, task_name="rename_variable"))
        self.assertEqual(seen.task, "rename variable")                  # never send ciphertext to a classifier
        self.assertIsNone(host.request(codex_pre(message=token)))        # nothing readable: leave the delegation alone
        self.assertEqual(host.request(codex_pre(task_name="ignored")).task, "Rename cnt to count in utils.py")  # plain text wins

    def test_claude_code_real_event_shape(self):
        self.configure()
        pre = FIXTURE["PreToolUse"]
        self.assertEqual(pre["tool_name"], "Agent")
        out, _ = self.handle(pre, "claude")
        reason = out["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("model=haiku", reason)
        self.assertNotIn("reasoning_effort", reason)                 # the Agent tool has no such parameter
        post = FIXTURE["PostToolUse"]
        child = HOSTS["claude"].child(post)
        self.assertEqual((child.agent_id, child.resolved_model), (post["tool_response"]["agentId"], "claude-haiku-4-5-20251001"))

    def test_claude_default_agent_is_classified_but_a_named_one_is_respected(self):
        self.configure()
        named = json.loads(json.dumps(FIXTURE["PreToolUse"])); named["tool_input"]["subagent_type"] = "code-reviewer"
        self.assertEqual(HOSTS["claude"].request(named).role, "code-reviewer")
        self.assertIsNone(HOSTS["claude"].request(FIXTURE["PreToolUse"]).role)
        out, fake = self.handle(named, "claude")
        self.assertEqual((out, fake.calls), ({}, 0))

    def test_credential_never_reaches_output_database_or_stderr(self):
        self.configure(classifier={"provider": "jev", "model": "jev-1.13.0", "timeout_seconds": 5})
        answer = {"model": "jev-1.13.0", "usage": {"input_tokens": 300, "output_tokens": 30}, "answers": {"tier": {
            "type": "choice", "choice": "light", "confidence": 0.9, "probabilities": {"light": 0.9, "small": 0.1, "mid": 0.0, "top": 0.0}}}}
        seen = {}
        class Transport:
            synthetic = True
            def request(self, body, headers, deadline, enter):
                enter(); seen["auth"] = headers["Authorization"]
                return HttpResponse(200, json.dumps(answer).encode())
        errors = io.StringIO()
        factory = lambda: TypesafeClassifier(enabled=True, task_export_permitted=True, transport=Transport(), credential_resolver=lambda: SECRET)
        out = rt.handle(codex_pre(), "codex", self.path, classifier_factory=factory, stderr=errors)
        self.assertEqual(seen["auth"], "Bearer " + SECRET)           # the key did reach the provider call...
        blob = json.dumps(out) + errors.getvalue() + b"".join(p.read_bytes() for p in self.dir.glob("advice.sqlite3*")).decode("latin1")
        self.assertNotIn(SECRET, blob)                               # ...and nowhere else
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_symlinked_cwd_is_resolved_before_the_allowlist_check(self):
        real = self.dir.parent / "project"; real.mkdir()
        link = self.dir.parent / "link"; link.symlink_to(real)
        self.configure(allowed_workspaces=[str(real)])
        event = codex_pre(); event["cwd"] = str(link)
        out, fake = self.handle(event)
        self.assertEqual((out["hookSpecificOutput"]["permissionDecision"], fake.calls), ("deny", 1))

    def test_unreadable_event_or_settings_fails_open_with_a_fixed_reason(self):
        out, err = io.StringIO(), io.StringIO()
        rt.run("codex", self.path, io.StringIO("{not json"), out, err)
        self.assertEqual((out.getvalue().strip(), err.getvalue().strip()), ("{}", "mrh: advisory_hook_error"))
        self.assertEqual(rt.handle(codex_pre(), "codex", self.dir / "missing" / "settings.json", classifier_factory=lambda: Fixed()), {})


if __name__ == "__main__":
    unittest.main()

