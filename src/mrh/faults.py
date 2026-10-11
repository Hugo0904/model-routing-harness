"""Safe fault interpretation shared by Hook notices and canonical statistics.

Notification metadata never decides a route or supplies host capabilities.
All public notices are fixed text; caller data and exception text stay out.
"""

FAULTS = {
    "classifier_unavailable": "the classifier was unavailable",
    "classifier_timeout": "the classifier timed out",
    "classifier_error": "the classifier failed",
    "malformed_classification": "the classifier returned an invalid result",
    "invalid_policy": "routing evaluation failed",
    "store_error": "event persistence failed",
    "typesafe_malformed_response": "the classifier returned an invalid response",
    "typesafe_model_mismatch": "the classifier returned an unexpected model",
    "typesafe_http_401": "classifier authentication was rejected",
    "typesafe_http_422": "the classifier rejected the request",
    "typesafe_http_429": "the classifier rate limit was reached",
    "typesafe_http_529": "the classifier was overloaded",
    "typesafe_http_5xx": "the classifier service failed",
    "typesafe_http_error": "the classifier request failed",
    "typesafe_network_error": "the classifier connection failed",
    "typesafe_timeout": "the classifier timed out",
    "typesafe_oversized_response": "the classifier response exceeded its limit",
    "typesafe_redirect_rejected": "the classifier returned a disallowed redirect",
}
NORMAL = {"unrelated_event", "explicit_model", "fixed_role_model", "fixed_role_effort",
          "low_confidence", "cost_unknown"}
CATEGORIES = ("classified_child_request", "classified_main_request", "normal_retention",
              "fault_fallback", "operator_stop", "unavailable_readiness")


def category(decision):
    if decision.action == "operator_update_required":
        return "operator_stop"
    if decision.action == "request_child":
        return "classified_child_request"
    if decision.action == "return_to_main":
        return "classified_main_request"
    if decision.reason in FAULTS:
        return "fault_fallback"
    return "normal_retention" if decision.reason in NORMAL else "unavailable_readiness"


def warning(reason, *, recorded=False, action='preserve'):
    description = FAULTS.get(reason, {
        "settings_unavailable": "settings could not be loaded",
        "runtime_error": "the Hook runtime failed",
        "notification_error": "event or notification persistence could not be confirmed",
    }.get(reason, "routing evaluation failed"))
    effect = ('delegation remains denied' if action == 'operator_update_required' else
              'original tool call preserved' if action == 'preserve' else 'routing decision retained')
    notice = "MRH: " + description + "; " + effect + ". Use mrh stats --details with this profile's --settings or --db."
    if not recorded:
        notice += " Recording and warning deduplication are unavailable; this fault may be absent from history."
    return {"systemMessage": notice}


def notice_for(proposal, decision, store):
    """Observe only actual evaluations; persistence failure still warns.

    A claim is a warning emission request, never proof that a UI displayed it.
    """
    fault = category(decision) == "fault_fallback"
    if store is None or decision.reason == "store_error":
        return warning(decision.reason) if fault else {}
    try:
        emit = store.observe_notice(proposal, decision)
    except Exception:
        return warning(decision.reason) if fault else warning('notification_error', action=decision.action)
    return warning(decision.reason, recorded=True) if emit else {}
