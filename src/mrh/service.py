"""Idempotent dispatch boundary. Persistence faults fail open with safe diagnostics."""
import sys
from .core import route, cached_effect_blocker
from .types import Decision


def process(proposal, policy, capabilities, store=None, classifier=None, optional_context=None):
    def failure(stage):
        print("mrh: store_error stage=" + stage, file=sys.stderr)
        return Decision(reason="store_error", synthetic=proposal.synthetic)

    if proposal.tool_name != "spawn_agent":
        return Decision(reason="unrelated_event", synthetic=proposal.synthetic)
    if store is not None:
        try:
            state, cached = store.claim(proposal)
        except Exception:
            return failure("claim")
        if state == "cached":
            try:
                blocker = cached_effect_blocker(proposal, policy, capabilities, cached)
            except Exception:
                blocker = "invalid_host_facts"
            if blocker:
                # Historical classification/decision remains frozen. Current
                # facts may prevent emitting its effect, without a new attempt.
                print("mrh: cached_effect_preserved reason=" + blocker, file=sys.stderr)
                return Decision(reason=blocker, synthetic=proposal.synthetic)
            return cached
        if state in ("pending", "conflict"):
            return Decision(reason="proposal_" + state, synthetic=proposal.synthetic)
    persistence_failed = []

    def attempt(attempt_id, kind, outcome, **metadata):
        if store is None:
            return
        try:
            store.attempt(proposal.identity, attempt_id, kind, outcome, **metadata)
        except Exception:
            persistence_failed.append(True)
            raise RuntimeError("store_error") from None

    try:
        decision = route(proposal, policy, capabilities, classifier, optional_context, attempt)
    except Exception:
        decision = Decision(reason="invalid_policy", synthetic=proposal.synthetic)
    if persistence_failed:
        return failure("attempt")
    if store is not None:
        try:
            store.complete(proposal.identity, decision)
        except Exception:
            return failure("complete")
    return decision
