import contextlib
from dataclasses import replace
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from mrh import cli, settings
from mrh.core import route, ScriptedClassifier, Classification
from mrh.facts import CallScope, Fact, HostSnapshot, TargetFacts
from mrh.runtime import SupportedHostResolver
from mrh.store import Store
from mrh.types import Proposal, ContextSummary
from test_typesafe import FakeTransport
from test_configured_accounting import saved_events


class ActionFactTests(unittest.TestCase):
    def proposal(self, call="call", original=None):
        return Proposal("codex", "simulation", "session", "turn", call, original or {"message": "fixture"}, True)

    def facts(self, proposal, **changes):
        scope = CallScope.for_proposal(proposal)
        known = lambda value: Fact.observed(scope, value, "synthetic-action-fixture")
        return replace(HostSnapshot(scope, True, role_protection=known("unprotected")), **changes)

    def known(self, proposal, value):
        return Fact.observed(CallScope.for_proposal(proposal), value, "synthetic-action-fixture")

    def target(self, proposal, inherited=Fact()):
        return TargetFacts("target", self.known(proposal, True), self.known(proposal, ("high", "low")), inherited)

    def decide(self, facts, policy, tier="Top", confidence=.9, proposal=None):
        proposal = proposal or self.proposal()
        classifier = ScriptedClassifier([Classification(tier, confidence)])
        contexts, attempts = [], []
        def context():
            contexts.append(1); return ContextSummary("summary", "synthetic", True)
        result = route(proposal, policy, facts, classifier, context, lambda *args, **kwargs: attempts.append(args))
        return result, classifier.calls, len(contexts), len(attempts)

    def test_main_needs_role_and_deny_only_and_keeps_confidence_threshold(self):
        p = self.proposal(); facts = self.facts(p, deny_supported=self.known(p, True))
        for confidence, action in ((.49, "preserve"), (.5, "return_to_main")):
            result, calls, contexts, _ = self.decide(facts, {"top_mode": "Main"}, confidence=confidence)
            self.assertEqual(result.action, action); self.assertEqual(calls, 1); self.assertEqual(contexts, 1)
        self.assertFalse(facts.original_model.known); self.assertFalse(facts.original_effort.known)
        self.assertFalse(facts.parent_model.known); self.assertFalse(facts.rewrite_supported.known)

    def test_fixed_explicit_effort_needs_no_cost_or_parent_fields(self):
        p = self.proposal(); facts = self.facts(p, rewrite_supported=self.known(p, True), targets=(self.target(p),))
        policy = {"top_mode": "Fixed", "fixed": {"model": "target", "effort": "high"}}
        result, calls, _, _ = self.decide(facts, policy)
        self.assertEqual(result.patch, {"model": "target", "reasoning_effort": "high"}); self.assertEqual(calls, 1)
        explicit = self.proposal(original={"message": "fixture", "reasoning_effort": "low"})
        result, _, _, _ = self.decide(facts, policy, proposal=explicit)
        self.assertEqual(result.patch["reasoning_effort"], "low")
        inherited_policy = {"top_mode": "Fixed", "fixed": {"model": "target"}}
        result, calls, contexts, _ = self.decide(facts, inherited_policy)
        self.assertEqual(result.reason, "missing_effective_effort"); self.assertEqual((calls, contexts), (0, 0))
        inherited = replace(facts, targets=(self.target(p, self.known(p, "high")),))
        result, calls, _, _ = self.decide(inherited, inherited_policy)
        self.assertEqual(result.patch, {"model": "target"}); self.assertEqual(calls, 1)

    def test_unknown_protected_role_and_missing_controls_skip_all_work(self):
        p = self.proposal(); valid = self.facts(p, deny_supported=self.known(p, True))
        cases = [(replace(valid, role_protection=Fact()), "missing_role_protection"),
                 (replace(valid, role_protection=self.known(p, "model")), "fixed_role_model"),
                 (replace(valid, role_protection=self.known(p, "effort")), "fixed_role_effort"),
                 (replace(valid, deny_supported=Fact()), "missing_deny_capability"),
                 (replace(valid, deny_supported=self.known(p, False)), "unsupported_deny_capability")]
        for facts, reason in cases:
            result, calls, contexts, attempts = self.decide(facts, {"top_mode": "Main"})
            self.assertEqual(result.reason, reason); self.assertEqual((calls, contexts, attempts), (0, 0, 0))
        # Even the isolated legacy fixture shim does not invent deny support.
        legacy = {"roles": {"default": {"known": True, "rewrite_allowed": True}}}
        result, calls, contexts, attempts = self.decide(legacy, {"top_mode": "Main"})
        self.assertEqual(result.reason, "missing_deny_capability"); self.assertEqual((calls, contexts, attempts), (0, 0, 0))
        fixed = {"top_mode": "Fixed", "fixed": {"model": "target", "effort": "high"}}
        for facts, reason in [(self.facts(p), "missing_rewrite_capability"),
                (self.facts(p, rewrite_supported=self.known(p, True)), "missing_target_model"),
                (self.facts(p, rewrite_supported=self.known(p, True), targets=(replace(self.target(p), efforts=Fact()),)), "missing_target_effort")]:
            result, calls, contexts, attempts = self.decide(facts, fixed)
            self.assertEqual(result.reason, reason); self.assertEqual((calls, contexts, attempts), (0, 0, 0))

    def test_top_viable_but_ordinary_unknown_baseline_or_cost_cannot_rewrite(self):
        p = self.proposal()
        facts = self.facts(p, deny_supported=self.known(p, True), rewrite_supported=self.known(p, True), targets=(self.target(p),))
        policy = {"top_mode": "Main", "tiers": {"Mid": {"model": "target", "effort": "high"}}}
        result, calls, _, _ = self.decide(facts, policy, "Mid")
        self.assertEqual(result.reason, "missing_original_baseline"); self.assertEqual(calls, 1)
        baseline = replace(facts, original_model=self.known(p, "original"), original_effort=self.known(p, "low"))
        result, calls, _, _ = self.decide(baseline, policy, "Mid")
        self.assertEqual(result.reason, "cost_unknown"); self.assertEqual(calls, 1)
        policy["rates"] = {name: {"currency": "USD", "unit": "token", "service": "fixture", "source_ref": "synthetic",
                                  "components": {"input": amount}} for name, amount in (("original", 2), ("target", 1))}
        result, calls, _, _ = self.decide(baseline, policy, "Mid")
        self.assertEqual(result.action, "request_child"); self.assertEqual(calls, 1)
        # Main unavailable but this ordinary branch remains viable independently.
        result, calls, _, _ = self.decide(replace(baseline, deny_supported=self.known(p, False)), policy, "Mid")
        self.assertEqual(result.action, "request_child"); self.assertEqual(calls, 1)

    def test_foreign_scope_malformed_or_unlabelled_production_dict_never_routes(self):
        p = self.proposal(); facts = self.facts(p, deny_supported=self.known(p, True))
        foreign = CallScope("codex", "session", "other-turn", "call")
        for bad, reason in [(replace(facts, scope=foreign), "host_fact_scope_mismatch"),
            (replace(facts, deny_supported=Fact.observed(foreign, True, "synthetic")), "host_fact_scope_mismatch"),
            (replace(facts, role_protection=self.known(p, False)), "invalid_host_facts"),
            (replace(facts, synthetic=False), "evidence_partition_mismatch")]:
            result, calls, contexts, attempts = self.decide(bad, {"top_mode": "Main"})
            self.assertEqual(result.reason, reason); self.assertEqual((calls, contexts, attempts), (0, 0, 0))
        production = replace(p, synthetic=False, surface="unknown")
        result = route(production, {"top_mode": "Main"}, {"configuration_known": True, "roles": {"default": {"known": True}}})
        self.assertEqual(result.reason, "invalid_host_facts")

    def test_saved_hook_partial_snapshot_and_public_runtime_zero_provider(self):
        for surface in ("shell", "bundled"):
            pre, _ = saved_events(surface)
            pre["tool_input"].pop("model")
            snapshot = SupportedHostResolver().resolve(pre)
            self.assertEqual(snapshot.parent_model.value, pre["model"])
            self.assertEqual(snapshot.parent_model.source, "canonical-hook-model")
            self.assertEqual(snapshot.workspace.value, pre["cwd"])
            self.assertFalse(snapshot.role_protection.known); self.assertFalse(snapshot.original_model.known)
            self.assertFalse(snapshot.deny_supported.known); self.assertEqual(snapshot.targets, ())
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp).resolve()/"state/settings.json"; settings.init(path)
                settings.update(path, enabled=True, task_export_permitted=True, allowed_workspaces=[pre["cwd"]])
                out = io.StringIO()
                with patch("mrh.typesafe.environment_credential", side_effect=AssertionError("key")), \
                     patch("mrh.typesafe.HttpTransport.request", side_effect=AssertionError("network")):
                    self.assertEqual(cli.main(["hook", "--settings", str(path)], stdin=io.StringIO(json.dumps(pre)), stdout=out), 0)
                self.assertEqual(json.loads(out.getvalue()), {})
                self.assertEqual(Store(path.parent/"events.sqlite3").stats()["outcomes"], {"missing_role_protection": 1})

    def test_public_runtime_minimal_action_facts_and_foreign_replay(self):
        p = self.proposal()
        main = self.facts(p, deny_supported=self.known(p, True))
        fixed = self.facts(p, rewrite_supported=self.known(p, True), targets=(self.target(p),))
        main_policy = {"top_mode": "Main"}
        fixed_policy = {"top_mode": "Fixed", "fixed": {"model": "target", "effort": "high"}}
        cases = [(main, main_policy, "top_main_requested", True),
                 (fixed, fixed_policy, "top_fixed_requested", True),
                 (replace(main, role_protection=Fact()), main_policy, "missing_role_protection", False),
                 (replace(main, role_protection=self.known(p, "effort")), main_policy, "fixed_role_effort", False),
                 (replace(main, deny_supported=Fact()), main_policy, "missing_deny_capability", False),
                 (replace(fixed, rewrite_supported=Fact()), fixed_policy, "missing_rewrite_capability", False),
                 (replace(fixed, targets=()), fixed_policy, "missing_target_model", False),
                 (fixed, {"top_mode": "Fixed", "fixed": {"model": "target"}}, "missing_effective_effort", False),
                 (replace(main, scope=replace(main.scope, tool_call_id="foreign-call")), main_policy, "host_fact_scope_mismatch", False)]
        class Host:
            synthetic = True
            def __init__(self, snapshot): self.snapshot = snapshot
            def resolve(self, event): return self.snapshot
        for snapshot, policy, reason, eligible in cases:
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve(); path = root/"state/settings.json"
                settings.init(path)
                settings.update(path, enabled=True, task_export_permitted=True, allowed_workspaces=[str(root)], policy=policy)
                event = {"hook_event_name": "PreToolUse", "tool_name": "spawn_agent", "session_id": p.session_id,
                         "turn_id": p.turn_id, "tool_use_id": p.tool_call_id, "cwd": str(root), "tool_input": p.tool_input}
                keys = []; http = FakeTransport()
                def key(): keys.append(1); return "synthetic-unused-outside-fixture"
                outputs = []
                for _ in range(2):
                    out = io.StringIO()
                    self.assertEqual(cli.main(["hook", "--settings", str(path)], stdin=io.StringIO(json.dumps(event)), stdout=out,
                        runtime_dependencies={"host_resolver": Host(snapshot), "transport": http, "credential_resolver": key}), 0)
                    outputs.append(json.loads(out.getvalue()))
                self.assertEqual(outputs[0], outputs[1])
                stats = Store(path.parent/"events.sqlite3").stats(True)
                self.assertEqual(stats["outcomes"], {reason: 1}); self.assertEqual(stats["proposals"], 1)
                self.assertEqual((len(keys), len(http.calls), stats["synthetic_attempts"]), (int(eligible),)*3)
                self.assertEqual(Store(path.parent/"events.sqlite3").stats()["proposals"], 0)
                if reason == "top_main_requested":
                    self.assertEqual(outputs[0]["hookSpecificOutput"]["permissionDecision"], "deny")
                elif reason == "top_fixed_requested":
                    updated = outputs[0]["hookSpecificOutput"]["updatedInput"]
                    self.assertEqual(updated, dict(p.tool_input, model="target", reasoning_effort="high"))
                else:
                    self.assertEqual(outputs[0], {})
                if eligible:
                    # A cached effect must still respect this invocation's
                    # protected role, scope and action-specific capability.
                    invalid = [(replace(snapshot, role_protection=self.known(p, "effort")), "fixed_role_effort"),
                               (replace(snapshot, scope=replace(snapshot.scope, turn_id="foreign-turn")), "host_fact_scope_mismatch")]
                    if reason == "top_main_requested":
                        invalid.append((replace(snapshot, deny_supported=Fact()), "missing_deny_capability"))
                    else:
                        # D23: confirmed unavailable effort with no verified
                        # deny must identify the unsupported stop guarantee.
                        invalid.append((replace(snapshot, targets=(replace(self.target(p), efforts=self.known(p, ("low",))),)), "operator_stop_unavailable"))
                    for replay_facts, blocker in invalid:
                        out, err = io.StringIO(), io.StringIO()
                        with contextlib.redirect_stderr(err):
                            self.assertEqual(cli.main(["hook", "--settings", str(path)], stdin=io.StringIO(json.dumps(event)), stdout=out,
                                runtime_dependencies={"host_resolver": Host(replay_facts), "transport": http, "credential_resolver": key}), 0)
                        self.assertEqual(json.loads(out.getvalue()), {})
                        self.assertIn("cached_effect_preserved reason="+blocker, err.getvalue())
                        self.assertEqual((len(keys), len(http.calls)), (1, 1))
                        self.assertEqual(Store(path.parent/"events.sqlite3").stats(True), stats)
                    if reason == "top_fixed_requested":
                        settings.update(path, policy={"top_mode": "Fixed", "fixed": {"model": "target", "effort": "low"}})
                        out, err = io.StringIO(), io.StringIO()
                        with contextlib.redirect_stderr(err):
                            self.assertEqual(cli.main(["hook", "--settings", str(path)], stdin=io.StringIO(json.dumps(event)), stdout=out,
                                runtime_dependencies={"host_resolver": Host(snapshot), "transport": http, "credential_resolver": key}), 0)
                        self.assertEqual(json.loads(out.getvalue()), {})
                        self.assertIn("cached_effect_mismatch", err.getvalue())
                        self.assertEqual((len(keys), len(http.calls)), (1, 1))
                        self.assertEqual(Store(path.parent/"events.sqlite3").stats(True), stats)


if __name__ == "__main__": unittest.main()
