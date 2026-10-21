"""Advisory decision. Rules run in a fixed order; every failure keeps the original call.

Nothing here imports a host, a vendor adapter, or the legacy rewrite/facts core.
"""
from __future__ import annotations

import json
import math
import time
from typing import NamedTuple

from mrh.advisory import advice_text
from mrh.advisory.request import Advice, AdvisoryRequest
from mrh.advisory.store import AdviceStore, candidates, request_id, task_hash
from mrh.infrastructure import settings_v2 as v2
from mrh.routing.attempts import GuardedAttempts
from mrh.routing.core import ClassifierFailure, bounded_call
from mrh.routing.types import REASONS, TIERS, Classification, safe_model_id

QUIET = {"explicit_model", "explicit_effort", "named_role", "low_confidence",
         "no_candidates_for_platform", "advice_already_given"}


def _from_row(row):
    return Advice(row["action"], row["reason"], row["tier"], row["confidence"],
                  candidates(row), row["request_id"], extra={"replayed": row.get("_replayed", True)})


class Route(NamedTuple):
    """What the hook does with a classification. `gear`/`score` are set only in gears mode."""
    action: str
    reason: str
    candidates: tuple = ()
    gear: int | None = None
    score: float | None = None


def route(policy, tier, confidence, platform, probabilities=None):
    """Shared by the hook and `mrh classify`. The confidence threshold is the same in both modes."""
    if confidence < policy["threshold"]:
        return Route("preserve", "low_confidence")
    if v2.mode(policy) == "gears":
        score = v2.difficulty_score(tier, probabilities)
        number, gear = v2.gear_for(policy["gears"], score)
        if gear.get("main"):
            return Route("continue_main", "gear_main", (), number, score)
        chosen = tuple(gear["candidates"].get(platform, []))
        if not chosen:
            return Route("preserve", "no_candidates_for_platform", (), number, score)
        return Route("advise", "advice_given", chosen, number, score)
    if tier == "Top" and policy["top_mode"] == "Main":
        return Route("continue_main", "top_main_requested")
    pool = policy["fixed"] if tier == "Top" else policy["tiers"].get(tier, {})
    chosen = tuple(pool.get(platform, []))
    if not chosen:
        return Route("preserve", "no_candidates_for_platform")
    return Route("advise", "advice_given", chosen)


def _meta(result):
    """Classifier facts worth keeping next to the decision: the four per-tier probabilities and the model that answered."""
    meta = {}
    probabilities = getattr(result, "probabilities", None)
    if isinstance(probabilities, dict) and set(probabilities) == set(TIERS) and all(
            isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and 0 <= v <= 1 for v in probabilities.values()):
        meta["probabilities"] = {tier: round(float(probabilities[tier]), 4) for tier in TIERS}
    model = getattr(result, "model", None)
    if safe_model_id(model):
        meta["classifier_model"] = model
    return meta


def decide(req: AdvisoryRequest, settings, store: AdviceStore, classifier_factory, clock=time.time, *, context_provider=None) -> Advice:
    rid = request_id(req.platform, req.session_id, req.turn_id, req.call_id)
    thash = task_hash(req.platform, req.session_id, req.task)
    provider = settings["classifier"]["provider"]
    budget = getattr(store, "hook_budget", None)
    now = clock()

    def finish(advice, notice_reason=None):
        store.save(rid, req, thash, advice, provider, now)
        if notice_reason and store.first_notice(req.session_id, notice_reason, now):
            return Advice(advice.action, advice.reason, advice.tier, advice.confidence, advice.candidates, rid,
                          notice=advice_text.fault_notice(notice_reason))
        return advice

    def keep(reason, **fields):
        return Advice("preserve", reason, request_id=rid, **fields)

    stored = store.call(rid)
    if stored:
        if budget is not None:
            budget.local()
        return _from_row(stored)
    if req.explicit_model is not None:
        if budget is not None:
            budget.local()
        return _from_row(store.preserve_explicit(rid, req, thash, provider, now))
    if req.explicit_effort is not None:
        if budget is not None:
            budget.local()
        return finish(keep("explicit_effort"))
    if req.role is not None and req.role not in v2.generic_roles(settings["policy"], req.platform):
        if budget is not None:
            budget.local()
        return finish(keep("named_role"))
    if store.recent_advice(req.platform, req.session_id, thash, now):
        if budget is not None:
            budget.local()
        return finish(keep("advice_already_given"))

    timeout = settings["classifier"]["timeout_seconds"]
    if budget is not None:
        timeout = budget.classification_timeout(timeout, provider)

    def emit(attempt_id, kind, outcome, **meta):
        try:
            store.attempt(rid, kind, outcome, clock(), **meta)
        except Exception:
            pass  # statistics must never block the delegation

    attempts = GuardedAttempts(timeout, emit)
    fault = None
    result = None
    try:
        emit(rid, provider, "classification_requested")
        if budget is not None:
            budget.check()
        context = None
        if context_provider is not None:
            from mrh.advisory.context import resolve
            context = resolve(req.task, settings, attempts, context_provider, hook_budget=budget)
        classifier = classifier_factory()
        attempts.check()
        if budget is not None:
            budget.check()
        # Only Jev takes the extra data, and only when the user turned `classifier.rich_input` on.
        extra = ({"extras": {"title": req.title, "role": req.role}}
                 if provider == "jev" and v2.rich_input(settings) else {})
        result = bounded_call(lambda: classifier.classify(req.task, context, attempts, **extra), attempts.remaining())
        attempts.check()
    except ClassifierFailure as exc:
        fault = exc.reason if isinstance(exc.reason, str) and exc.reason in REASONS else "classifier_error"
    except TimeoutError:
        fault = "classifier_timeout"
    except Exception:
        fault = "classifier_error"
    finally:
        attempts.cancel()
    if budget is not None:
        budget.check()
    if fault:
        emit(rid, provider, "classification_error", error_reason=fault)
        return finish(keep(fault), notice_reason=fault)
    if (not isinstance(result, Classification) or result.tier not in TIERS or isinstance(result.confidence, bool)
            or not isinstance(result.confidence, (int, float)) or not math.isfinite(result.confidence)
            or not 0 <= result.confidence <= 1):
        return finish(keep("malformed_classification"), notice_reason="malformed_classification")
    tier, confidence = result.tier, float(result.confidence)
    decision = route(settings["policy"], tier, confidence, req.platform, getattr(result, "probabilities", None))
    meta = _meta(result)
    if decision.gear is not None:
        meta = {**meta, "gear": decision.gear, "score": round(decision.score, 2)}
    return finish(Advice(decision.action, decision.reason, tier, confidence, decision.candidates, rid, extra=meta))
