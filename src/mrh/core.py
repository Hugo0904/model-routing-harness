"""Shared routing policy with no filesystem, host, or provider transport."""
import math
import queue
import threading
from .types import Classification, ContextSummary, Decision, TIERS, safe_id


class ClassifierUnavailable(Exception):
    pass


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


def route(proposal, policy, host_capabilities, classifier=None, optional_context=None, record_attempt=lambda *_: None):
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
    role = original.get("agent_type", "default")
    roles = host_capabilities.get("roles", {}) if isinstance(host_capabilities, dict) else {}
    role_config = roles.get(role) if isinstance(roles, dict) else None
    if not isinstance(role_config, dict):
        role_config = None
    if role_config and role_config.get("fixed_model"):
        return preserve("fixed_role_model")
    if not isinstance(host_capabilities, dict) or not host_capabilities.get("configuration_known") or not role_config or not role_config.get("known"):
        return preserve("unresolved_host_configuration")
    if not isinstance(policy, dict) or policy.get("top_mode", "Main") not in ("Main", "Fixed"):
        return preserve("invalid_policy")
    timeout = policy.get("timeout_seconds", 1.0)
    if isinstance(timeout, bool) or not isinstance(timeout, (float, int)) or not math.isfinite(timeout) or not 0 < timeout <= 30:
        return preserve("invalid_policy")
    classifier = classifier or UnavailableClassifier()
    if bool(getattr(classifier, "synthetic", False)) != synthetic:
        return preserve("evidence_partition_mismatch")
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
    try:
        result = bounded_call(lambda: classifier.classify(proposal.task, context, record_attempt), timeout)
    except ClassifierUnavailable:
        return preserve("classifier_unavailable")
    except TimeoutError:
        return preserve("classifier_timeout")
    except Exception:
        return preserve("classifier_error")
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
    if result.tier == "Top" and policy.get("top_mode", "Main") == "Main":
        return Decision("return_to_main", "top_main_requested", result.tier, result.confidence,
                        synthetic=synthetic, context_status=context_status)
    tiers = policy.get("tiers", {})
    mapping = policy.get("fixed") if result.tier == "Top" else tiers.get(result.tier) if isinstance(tiers, dict) else None
    if not isinstance(mapping, dict) or not safe_id(mapping.get("model", "")):
        return preserve("invalid_policy")
    model = mapping["model"]
    effort = original.get("reasoning_effort", mapping.get("effort"))
    if effort is not None and not safe_id(effort):
        return preserve("unsupported_effort")
    catalog = host_capabilities.get("models", {})
    selected = catalog.get(model) if isinstance(catalog, dict) else None
    if not isinstance(selected, dict) or selected.get("available") is not True:
        return preserve("unsupported_model")
    if effort is not None and effort not in selected.get("efforts", []):
        return preserve("unsupported_effort")
    if not role_config.get("rewrite_allowed"):
        return preserve("unsupported_role")
    if result.tier != "Top":
        rates = policy.get("rates", {})
        if not isinstance(rates, dict):
            return preserve("invalid_policy")
        source_model = host_capabilities.get("main_model")
        if not cheaper(rates.get(source_model), rates.get(model)):
            return preserve("cost_unknown")
    patch = {"model": model}
    if effort is not None:
        patch["reasoning_effort"] = effort
    return Decision("request_child", "top_fixed_requested" if result.tier == "Top" else "cheaper_child_requested",
                    result.tier, result.confidence, patch, synthetic, context_status)
