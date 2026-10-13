"""Advisory decision. Rules run in a fixed order; every failure keeps the original call.

Nothing here imports a host, a vendor adapter, or the legacy rewrite/facts core.
"""
from __future__ import annotations

import json
import math
import time

from mrh.advisory import advice_text
from mrh.advisory.request import Advice, AdvisoryRequest
from mrh.advisory.store import AdviceStore, candidates, request_id, task_hash
from mrh.infrastructure import settings_v2 as v2
from mrh.routing.attempts import GuardedAttempts
from mrh.routing.core import ClassifierFailure, bounded_call
from mrh.routing.types import REASONS, TIERS, Classification

QUIET = {"explicit_model", "explicit_effort", "named_role", "low_confidence",
         "no_candidates_for_platform", "advice_already_given"}


def _from_row(row):
    return Advice(row["action"], row["reason"], row["tier"], row["confidence"],
                  candidates(row), row["request_id"], extra={"replayed": row.get("_replayed", True)})


def decide(req: AdvisoryRequest, settings, store: AdviceStore, classifier_factory, clock=time.time) -> Advice:
    rid = request_id(req.platform, req.session_id, req.turn_id, req.call_id)
    thash = task_hash(req.platform, req.session_id, req.task)
    provider = settings["classifier"]["provider"]
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
        return _from_row(stored)
    if req.explicit_model is not None:
        return _from_row(store.preserve_explicit(rid, req, thash, provider, now))
    if req.explicit_effort is not None:
        return finish(keep("explicit_effort"))
    if req.role is not None and req.role not in v2.generic_roles(settings["policy"], req.platform):
        return finish(keep("named_role"))
    if store.recent_advice(req.platform, req.session_id, thash, now):
        return finish(keep("advice_already_given"))

    timeout = settings["classifier"]["timeout_seconds"]

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
        classifier = classifier_factory()
        result = bounded_call(lambda: classifier.classify(req.task, None, attempts), timeout)
        attempts.check()
    except ClassifierFailure as exc:
        fault = exc.reason if isinstance(exc.reason, str) and exc.reason in REASONS else "classifier_error"
    except TimeoutError:
        fault = "classifier_timeout"
    except Exception:
        fault = "classifier_error"
    finally:
        attempts.cancel()
    if fault:
        emit(rid, provider, "classification_error", error_reason=fault)
        return finish(keep(fault), notice_reason=fault)
    if (not isinstance(result, Classification) or result.tier not in TIERS or isinstance(result.confidence, bool)
            or not isinstance(result.confidence, (int, float)) or not math.isfinite(result.confidence)
            or not 0 <= result.confidence <= 1):
        return finish(keep("malformed_classification"), notice_reason="malformed_classification")
    tier, confidence, policy = result.tier, float(result.confidence), settings["policy"]
    if confidence < policy["threshold"]:
        return finish(keep("low_confidence", tier=tier, confidence=confidence))
    if tier == "Top" and policy["top_mode"] == "Main":
        return finish(Advice("continue_main", "top_main_requested", tier, confidence, request_id=rid))
    pool = policy["fixed"] if tier == "Top" else policy["tiers"].get(tier, {})
    candidates = tuple(pool.get(req.platform, []))
    if not candidates:
        return finish(keep("no_candidates_for_platform", tier=tier, confidence=confidence))
    return finish(Advice("advise", "advice_given", tier, confidence, candidates, rid))
