"""Shared routing policy with no filesystem, host, or provider transport."""
import math
import queue
import threading
from .types import Classification, ContextSummary, Decision, REASONS, TIERS, safe_id
from .attempts import GuardedAttempts
from .facts import snapshot_for


class ClassifierUnavailable(Exception):
    pass


class ClassifierFailure(Exception):
    """Safe typed provider failure; telemetry may contain only validated scalars."""
    def __init__(self, reason, telemetry=None):
        self.reason = reason
        self.telemetry = telemetry or {}
        super().__init__(reason)


class UnavailableClassifier:
    synthetic = False

    def classify(self, task, context, record_attempt):
        raise ClassifierUnavailable()


class ScriptedClassifier:
    """Explicit simulation only; each scripted entry models one transport attempt."""
    synthetic = True

    def __init__(self, entries):
        self.entries = entries
        self.calls = 0

    def classify(self, task, context, record_attempt):
        self.calls += 1
        for number, item in enumerate(self.entries):
            record_attempt(str(number), "synthetic", "error" if isinstance(item, Exception) else "returned")
            if isinstance(item, Exception):
                if number == len(self.entries) - 1:
                    raise item
                continue
            return item
        raise ClassifierUnavailable()


def bounded_call(fn, timeout):
    results = queue.Queue(maxsize=1)

    def work():
        try:
            results.put((True, fn()))
        except Exception as exc:
            # Exception stays in memory only; caller exposes a fixed reason code.
            results.put((False, exc))

    thread = threading.Thread(target=work, daemon=True)
    thread.start()
    try:
        ok, result = results.get(timeout=timeout)
    except queue.Empty:
        raise TimeoutError() from None
    if not ok:
        raise result
    return result


def cheaper(source, target):
    if not isinstance(source, dict) or not isinstance(target, dict):
        return False
    for key in ("currency", "unit", "service"):
        if not source.get(key) or source.get(key) != target.get(key):
            return False
    if not all(safe_id(x.get("source_ref", "")) for x in (source, target)):
        return False
    a, b = source.get("components"), target.get("components")
    if not isinstance(a, dict) or not isinstance(b, dict) or not a or a.keys() != b.keys():
        return False
    values = list(a.values()) + list(b.values())
    if any(isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) or v < 0 for v in values):
        return False
    return all(b[k] <= a[k] for k in a) and any(b[k] < a[k] for k in a)


def validated_facts(proposal, value):
    """One validation/role gate for fresh decisions and cached effect replay."""
    try:
        facts = snapshot_for(proposal, value)
        invalid = facts.validation_reason(proposal)
    except (ValueError, TypeError, AttributeError):
        return None, "invalid_host_facts"
    if invalid:
        return None, invalid
    protection = facts.role_protection
    if not protection.known:
        return None, "missing_role_protection"
    if protection.value != "unprotected":
        return None, "fixed_role_effort" if protection.value == "effort" else "fixed_role_model"
    return facts, None


def action_eligibility(proposal, policy, facts, tier):
    original = proposal.tool_input
    # Return a precise blocker and a model/effort-only patch. Each field
    # used here was validated for this exact call and evidence partition.
    if tier == "Top" and policy.get("top_mode", "Main") == "Main":
        if not facts.deny_supported.known:
            return "missing_deny_capability", None
        return (None, {}) if facts.deny_supported.value else ("unsupported_deny_capability", None)
    control = facts.rewrite_supported
    if not control.known:
        return "missing_rewrite_capability", None
    if not control.value:
        return "unsupported_role", None
    tiers = policy.get("tiers", {})
    mapping = policy.get("fixed") if tier == "Top" else tiers.get(tier) if isinstance(tiers, dict) else None
    if not isinstance(mapping, dict) or not safe_id(mapping.get("model")):
        return "invalid_policy", None
    model = mapping["model"]
    target = facts.target(model)
    if target is None or not target.available.known:
        return "missing_target_model", None
    if not target.available.value:
        return "unsupported_model", None
    requested = original.get("reasoning_effort", mapping.get("effort"))
    explicit_effort = requested is not None
    if explicit_effort and not safe_id(requested):
        return "unsupported_effort", None
    if explicit_effort:
        effective = requested
    elif not target.inherited_effort.known:
        return "missing_effective_effort", None
    else:
        effective = target.inherited_effort.value
    if not target.efforts.known:
        return "missing_target_effort", None
    if effective not in target.efforts.value:
        return "unsupported_effort", None
    if tier != "Top":
        if not facts.original_model.known or not facts.original_effort.known:
            return "missing_original_baseline", None
        rates = policy.get("rates", {})
        if not isinstance(rates, dict):
            return "invalid_policy", None
        if not cheaper(rates.get(facts.original_model.value), rates.get(model)):
            return "cost_unknown", None
    patch = {"model": model}
    if explicit_effort:
        patch["reasoning_effort"] = requested
    # A verified inherited effort is checked, never silently forced.
    return None, patch


def cached_effect_blocker(proposal, policy, value, decision):
    """Revalidate an effect without classification or changing saved facts."""
    if decision.action == "preserve":
        return None
    if proposal.tool_input.get("model") is not None:
        return "explicit_model"
    facts, reason = validated_facts(proposal, value)
    if reason:
        return reason
    if not isinstance(policy, dict) or policy.get("top_mode", "Main") not in ("Main", "Fixed"):
        return "invalid_policy"
    reason, patch = action_eligibility(proposal, policy, facts, decision.tier)
    if reason:
        return reason
    expected = "return_to_main" if decision.tier == "Top" and policy.get("top_mode", "Main") == "Main" else "request_child"
    if expected != decision.action or patch != decision.patch:
        return "cached_effect_mismatch"
    return None


def route(proposal, policy, host_capabilities, classifier=None, optional_context=None, record_attempt=lambda *_, **__: None):
    synthetic = proposal.synthetic
    classification = None
    context_status = "absent"

    def preserve(reason):
        return Decision(reason=reason, synthetic=synthetic, context_status=context_status,
                        tier=classification.tier if classification else None,
                        confidence=classification.confidence if classification else None)

    if proposal.tool_name != "spawn_agent":
        return preserve("unrelated_event")
    original = proposal.tool_input
    if original.get("model") is not None:
        return preserve("explicit_model")
    facts, blocker = validated_facts(proposal, host_capabilities)
    if blocker:
        return preserve(blocker)
    if not isinstance(policy, dict) or policy.get("top_mode", "Main") not in ("Main", "Fixed"):
        return preserve("invalid_policy")
    timeout = policy.get("timeout_seconds", 1.0)
    if isinstance(timeout, bool) or not isinstance(timeout, (float, int)) or not math.isfinite(timeout) or not 0 < timeout <= 30:
        return preserve("invalid_policy")
    classifier = classifier or UnavailableClassifier()
    if bool(getattr(classifier, "synthetic", False)) != synthetic:
        return preserve("evidence_partition_mismatch")
    configured = ["Top"] + [tier for tier in TIERS[:-1] if isinstance(policy.get("tiers"), dict) and tier in policy["tiers"]]
    eligibility = {tier: action_eligibility(proposal, policy, facts, tier) for tier in configured}
    if not any(reason is None for reason, _ in eligibility.values()):
        return preserve(eligibility["Top"][0])
    # Only a legally possible effect permits context/Jev/key/HTTP work.
    context = None
    if optional_context is not None:
        try:
            candidate = bounded_call(optional_context, min(timeout, 1.0))
            if not isinstance(candidate, ContextSummary) or candidate.permitted_export is not True or not safe_id(candidate.source_ref):
                context_status = "export_denied"
            elif not isinstance(candidate.summary, str) or len(candidate.summary.encode()) > 2048:
                context_status = "oversized"
            elif any(x in candidate.summary.lower() for x in ("bearer ", "sk-proj-", "begin private key")):
                context_status = "sensitive"
            else:
                context = candidate.summary
                context_status = "permitted"
        except TimeoutError:
            context_status = "timeout"
        except Exception:
            context_status = "error"
    attempts = GuardedAttempts(timeout, record_attempt)
    try:
        result = bounded_call(lambda: classifier.classify(proposal.task, context, attempts), timeout)
        attempts.check()
    except ClassifierUnavailable:
        return preserve("classifier_unavailable")
    except ClassifierFailure as exc:
        return preserve(exc.reason if isinstance(exc.reason, str) and exc.reason in REASONS else "classifier_error")
    except TimeoutError:
        return preserve("classifier_timeout")
    except Exception:
        return preserve("classifier_error")
    finally:
        attempts.cancel()
    if isinstance(result, dict):
        try:
            result = Classification(**result)
        except (TypeError, ValueError):
            return preserve("malformed_classification")
    if not isinstance(result, Classification) or result.tier not in TIERS or isinstance(result.confidence, bool) or not isinstance(result.confidence, (int, float)) or not math.isfinite(result.confidence) or not 0 <= result.confidence <= 1 or not safe_id(result.reason_code):
        return preserve("malformed_classification")
    classification = result
    if result.confidence < 0.5:
        return preserve("low_confidence")
    reason, patch = action_eligibility(proposal, policy, facts, result.tier)
    if reason is not None:
        return preserve(reason)
    if result.tier == "Top" and policy.get("top_mode", "Main") == "Main":
        return Decision("return_to_main", "top_main_requested", result.tier, result.confidence,
                        synthetic=synthetic, context_status=context_status)
    return Decision("request_child", "top_fixed_requested" if result.tier == "Top" else "cheaper_child_requested",
                    result.tier, result.confidence, patch, synthetic, context_status)
