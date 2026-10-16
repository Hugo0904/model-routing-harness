"""Advisory classification on demand (`mrh classify`): ask the classifier about a task without delegating anything.

It records only classifier attempts, under a `manual-` request id, so the call costs what it costs and shows in the usage
numbers, but is not a delegation: nothing is written to `advice`, and the task text is never stored.
"""
from __future__ import annotations

import time
import uuid

from mrh.adapters.providers.registry import build
from mrh.advisory.engine import route
from mrh.advisory.store import AdviceStore
from mrh.routing.attempts import GuardedAttempts
from mrh.routing.core import ClassifierFailure, bounded_call
from mrh.routing.types import REASONS, TIERS, Classification

MANUAL_PREFIX = "manual-"
JEV_USD_PER_INPUT_TOKEN = 0.042 / 1_000_000


class ClassifyError(Exception):
    """`reason` is a stable code; the CLI turns it into a Chinese sentence."""
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def recommend(policy, tier, confidence, platforms):
    """Per platform, what the hook would do with this classification right now."""
    result = {}
    for platform in platforms:
        action, reason, chosen = route(policy, tier, confidence, platform)
        result[platform] = {"action": action, "reason": reason, "candidates": [dict(c) for c in chosen]}
    return result


def run(settings, task, *, store, platforms=("claude", "codex"), extras=None, classifier_factory=None,
        clock=time.time, request_hex=None):
    """Classify `task` once. Raises ClassifyError. Never retries."""
    if not isinstance(task, str) or not task.strip():
        raise ClassifyError("empty_task")
    if settings["task_export_permitted"] is not True:
        raise ClassifyError("export_not_permitted")
    provider = settings["classifier"]["provider"]
    # The route switch is not consulted: this is a question, not a delegation. Sending the task out is still gated by
    # the user's explicit export permission above.
    asking = {**settings, "enabled": True}
    rid = MANUAL_PREFIX + (request_hex or uuid.uuid4().hex)
    timeout = settings["classifier"]["timeout_seconds"]
    events = []

    def emit(attempt_id, kind, outcome, **meta):
        now = clock()
        events.append((outcome, now, meta))
        try:
            store.attempt(rid, kind, outcome, now, **meta)
        except Exception:
            pass   # statistics never block an answer

    attempts = GuardedAttempts(timeout, emit)
    emit(rid, provider, "classification_requested")
    fault, result = None, None
    try:
        classifier = (classifier_factory or (lambda: build(asking)))()
        extra = {"extras": extras} if extras and provider == "jev" else {}
        result = bounded_call(lambda: classifier.classify(task, None, attempts, **extra), timeout)
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
        raise ClassifyError(fault)
    if not isinstance(result, Classification) or result.tier not in TIERS:
        emit(rid, provider, "classification_error", error_reason="malformed_classification")
        raise ClassifyError("malformed_classification")

    started = next((ts for outcome, ts, _ in events if outcome == "started"), None)
    answered = next(((ts, meta) for outcome, ts, meta in events if outcome in ("returned", "late_returned")), (None, {}))
    seconds = answered[0] - started if started is not None and answered[0] is not None else None
    tokens = answered[1].get("input_tokens")
    return {
        "request_id": rid, "provider": provider, "model": result.model or answered[1].get("response_model"),
        "tier": result.tier, "confidence": float(result.confidence),
        "probabilities": dict(result.probabilities) if result.probabilities else None,
        "threshold": settings["policy"]["threshold"],
        "recommended": recommend(settings["policy"], result.tier, float(result.confidence), platforms),
        "latency_seconds": seconds, "input_tokens": tokens, "output_tokens": answered[1].get("output_tokens"),
        "estimated_usd": tokens * JEV_USD_PER_INPUT_TOKEN if provider == "jev" and isinstance(tokens, int) else None,
    }
