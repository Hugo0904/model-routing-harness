import copy
import math
import time
import unittest
from mrh.core import Classification, ScriptedClassifier, UnavailableClassifier, route
from mrh.codex import handle_event
from mrh.simulation import demo_capabilities, demo_policy
from mrh.types import ContextSummary, Proposal


class CoreTests(unittest.TestCase):
    def proposal(self, **changes):
        values = dict(platform="codex", surface="simulation", session_id="s", turn_id="t",
                      tool_call_id="c", tool_input={"message": "PRIVATE_CANARY", "unknown": {"keep": True}}, synthetic=True)
        values.update(changes)
        return Proposal(**values)

    def decide(self, result=Classification("Top", 0.9), *, proposal=None, policy=None, caps=None, context=None):
        classifier = ScriptedClassifier([result])
        d = route(proposal or self.proposal(), policy or demo_policy(), caps or demo_capabilities(), classifier, context)
        return d, classifier

    def test_explicit_fixed_role_and_unrelated_skip(self):
        for change, expected in [({"tool_input": {"model": "explicit-model"}}, "explicit_model"),
                                 ({"tool_input": {"agent_type": "fixed"}}, "fixed_role_model"),
                                 ({"tool_name": "exec_command"}, "unrelated_event")]:
            d, c = self.decide(proposal=self.proposal(**change))
            self.assertEqual(d.reason, expected)
            self.assertEqual(c.calls, 0)

    def test_confidence_threshold_and_malformed_values(self):
        self.assertEqual(self.decide(Classification("Top", 0.49))[0].reason, "low_confidence")
        self.assertEqual(self.decide(Classification("Top", 0.5))[0].action, "return_to_main")
        for v in [True, False, math.nan, math.inf, -1, 1.01, "0.8"]:
            self.assertEqual(self.decide(Classification("Top", v))[0].reason, "malformed_classification")
        for v in [{"tier": "bad", "confidence": 0.9}, {"extra": "CANARY"}, None]:
            self.assertEqual(self.decide(v)[0].reason, "malformed_classification")

    def test_failure_unavailable_timeout_fail_open(self):
        p = self.proposal()
        class UnavailableFixture(UnavailableClassifier): synthetic = True
        self.assertEqual(route(p, demo_policy(), demo_capabilities(), UnavailableFixture()).reason, "classifier_unavailable")
        for result, reason in [(RuntimeError("SECRET_ERROR_CANARY"), "classifier_error"),
                               (TimeoutError("SECRET_ERROR_CANARY"), "classifier_timeout")]:
            self.assertEqual(self.decide(result)[0].reason, reason)

        class Slow:
            synthetic = True
            def classify(self, *_):
                time.sleep(0.1)
                return Classification("Top", 1)
        pol = demo_policy(); pol["timeout_seconds"] = 0.005
        self.assertEqual(route(self.proposal(), pol, demo_capabilities(), Slow()).reason, "classifier_timeout")

    def test_fixed_parent_unchanged_and_guards(self):
        p, caps, pol = self.proposal(), demo_capabilities(), demo_policy()
        before = copy.deepcopy((p.tool_input, caps, pol))
        pol["top_mode"] = "Fixed"
        d, _ = self.decide(policy=pol, caps=caps)
        self.assertEqual(d.patch, {"model": "gpt-6-astra", "reasoning_effort": "high"})
        self.assertEqual(caps, before[1]); self.assertEqual(p.tool_input, before[0])
        self.assertEqual(self.decide(Classification("Top", 0.49), policy=pol)[0].reason, "low_confidence")
        explicit, classifier = self.decide(proposal=self.proposal(tool_input={"model": "explicit", "unknown": True}), policy=pol)
        self.assertEqual(explicit.reason, "explicit_model"); self.assertEqual(classifier.calls, 0)
        role_caps = demo_capabilities(); role_caps["roles"]["default"]["rewrite_allowed"] = False
        self.assertEqual(self.decide(policy=pol, caps=role_caps)[0].reason, "unsupported_role")
        self.assertEqual(self.decide(proposal=self.proposal(tool_input={"reasoning_effort": "ultra"}), policy=pol)[0].reason, "unsupported_effort")
        pol["fixed"]["model"] = "unsupported"
        self.assertEqual(self.decide(policy=pol)[0].reason, "missing_target_model")
        pol["fixed"] = {"model": "gpt-6-astra", "effort": "unsupported"}
        self.assertEqual(self.decide(policy=pol)[0].reason, "unsupported_effort")
        self.assertEqual(self.decide(policy=demo_policy(), caps={"configuration_known": False})[0].reason, "missing_role_protection")
        malformed_caps = demo_capabilities(); malformed_caps["roles"] = ["bad"]
        self.assertEqual(self.decide(caps=malformed_caps)[0].reason, "missing_role_protection")
        invalid_policy = demo_policy(); invalid_policy["top_mode"] = "bad"
        self.assertEqual(self.decide(policy=invalid_policy)[0].reason, "invalid_policy")

    def test_cost_vector_requires_all_components_and_source(self):
        pol, caps = demo_policy(), demo_capabilities()
        pol["tiers"]["Small"] = {"model": "gpt-6.1-sol", "effort": "high"}
        self.assertEqual(self.decide(Classification("Small", 0.8), policy=pol)[0].reason, "cost_unknown")
        rates = {"gpt-6-luna": {"currency": "USD", "unit": "per-million", "service": "synthetic",
                  "source_ref": "fixture-v1", "components": {"input": 3, "output": 5, "cached": 1}},
                 "gpt-6.1-sol": {"currency": "USD", "unit": "per-million", "service": "synthetic",
                  "source_ref": "fixture-v1", "components": {"input": 2, "output": 5, "cached": 1}}}
        pol["rates"] = rates
        self.assertEqual(self.decide(Classification("Small", 0.8), policy=pol)[0].action, "request_child")
        rates["gpt-6.1-sol"]["components"]["cached"] = 2
        self.assertEqual(self.decide(Classification("Small", 0.8), policy=pol)[0].reason, "cost_unknown")
        rates["gpt-6.1-sol"]["currency"] = "EUR"
        self.assertEqual(self.decide(Classification("Small", 0.8), policy=pol)[0].reason, "cost_unknown")

    def test_context_contract_never_boosts_confidence(self):
        for context, status in [(None, "absent"), (lambda: ContextSummary("private", "source", False), "export_denied"),
                                (lambda: ContextSummary("x" * 2049, "source", True), "oversized"),
                                (lambda: ContextSummary("summary", "source", True), "permitted")]:
            d, _ = self.decide(Classification("Top", 0.49), context=context)
            self.assertEqual(d.context_status, status); self.assertEqual(d.reason, "low_confidence")
        def fail(): raise RuntimeError("SECRET_CONTEXT_ERROR")
        self.assertEqual(self.decide(context=fail)[0].context_status, "error")
        pol = demo_policy(); pol["timeout_seconds"] = 0.005
        self.assertEqual(self.decide(policy=pol, context=lambda: (time.sleep(0.05), None)[1])[0].context_status, "timeout")

    def test_candidate_translates_only_explicit_simulation(self):
        event = {"hook_event_name": "PreToolUse", "tool_name": "spawn_agent", "session_id": "s",
                 "turn_id": "goal-later-turn", "tool_use_id": "c", "tool_input": {"message": "task", "unknown": 42}}
        original = copy.deepcopy(event)
        self.assertEqual(handle_event(event), {})
        self.assertEqual(handle_event(event, candidate=True), {})
        denied = handle_event(event, candidate=True, simulation={"tier": "Top", "confidence": 0.8})
        self.assertEqual(denied["hookSpecificOutput"]["permissionDecision"], "deny")
        pol = demo_policy(); pol["top_mode"] = "Fixed"
        rewrite = handle_event(event, candidate=True, simulation={"tier": "Top", "policy": pol})
        args = rewrite["hookSpecificOutput"]["updatedInput"]
        self.assertEqual(args["message"], "task"); self.assertEqual(args["unknown"], 42)
        self.assertEqual(args["model"], "gpt-6-astra"); self.assertEqual(event, original)


if __name__ == "__main__": unittest.main()
