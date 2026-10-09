"""All fixtures in this module are synthetic; never a provider implementation."""
from .core import Classification, ScriptedClassifier
from .service import process
from .types import Proposal


def demo_capabilities():
    return {"configuration_known": True, "main_model": "gpt-6-luna", "main_effort": "max",
            "roles": {"default": {"known": True, "rewrite_allowed": True},
                      "fixed": {"known": True, "rewrite_allowed": False, "fixed_model": "gpt-6-astra"}},
            "models": {"gpt-6-luna": {"available": True, "efforts": ["max"]},
                       "gpt-6.1-sol": {"available": True, "efforts": ["high", "xhigh", "max"]},
                       "gpt-6-astra": {"available": True, "efforts": ["high", "xhigh", "max"]}}}


def demo_policy():
    # Example price vectors are invented, explicitly synthetic, not product prices.
    return {"top_mode": "Main", "fixed": {"model": "gpt-6-astra", "effort": "high"},
            "tiers": {t: {"model": "gpt-6-luna", "effort": "max"} for t in ("Light", "Small", "Mid")},
            "rates": {}}


def run_demo(store):
    for index, (tier, confidence, mode) in enumerate([
            ("Light", 0.9, "Main"), ("Small", 0.49, "Main"), ("Mid", 0.5, "Main"),
            ("Top", 0.9, "Main"), ("Top", 0.9, "Fixed")]):
        policy = demo_policy()
        policy["top_mode"] = mode
        proposal = Proposal("codex", "simulation", "demo-v1", "turn-1", f"call-{index}",
                            {"message": "Synthetic fixture only", "agent_type": "default"}, True)
        process(proposal, policy, demo_capabilities(), store, ScriptedClassifier([Classification(tier, confidence)]))
    return store.stats(synthetic=True)
