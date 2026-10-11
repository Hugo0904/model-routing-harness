"""Idempotent dispatch boundary; a determined operator stop survives write faults."""
import sys
from mrh.routing.core import route, cached_effect_blocker, cached_operator_stop
from mrh.routing.types import Decision


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
                stopped = cached_operator_stop(proposal, policy, capabilities, cached)
                if stopped:
                    if cached.action != 'operator_update_required':
                        try:
                            store.record_stop(proposal.identity, stopped)
                        except Exception:
                            print('mrh: store_error stage=operator_stop; delegation remains denied', file=sys.stderr)
                    return stopped
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
            if decision.action == 'operator_update_required':
                print('mrh: store_error stage=complete; delegation remains denied', file=sys.stderr)
                return decision
            return failure("complete")
    return decision
