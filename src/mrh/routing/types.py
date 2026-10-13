"""Our internal protocol; these shapes are not a Jev wire API."""
from dataclasses import dataclass
import re

TIERS = ("Light", "Small", "Mid", "Top")
REASONS = {"classifier_unavailable", "unrelated_event", "explicit_model", "fixed_role_model",
           "unresolved_host_configuration", "invalid_policy", "evidence_partition_mismatch",
           "classifier_timeout", "classifier_error", "malformed_classification", "low_confidence",
           "top_main_requested", "unsupported_effort", "unsupported_model", "unsupported_role",
           "cost_unknown", "top_fixed_requested", "cheaper_child_requested", "store_error",
           "proposal_pending", "proposal_conflict"}
REASONS.update({'explicit_effort','scope_unsupported','scope_changed','scope_host_unverified'})
REASONS.update({'scope_fresh_start_missing','scope_fresh_lifecycle',
                'scope_fresh_sources_changed','scope_fresh_sources_not_predated'})
REASONS.update({"typesafe_disabled", "typesafe_export_denied", "typesafe_missing_credentials", "typesafe_unverified_transport",
                "typesafe_invalid_task", "typesafe_malformed_response", "typesafe_model_mismatch",
                "typesafe_http_401", "typesafe_http_402", "typesafe_http_422", "typesafe_http_429", "typesafe_http_529",
                "typesafe_http_5xx", "typesafe_http_error", "typesafe_network_error",
                "typesafe_timeout", "typesafe_oversized_response", "typesafe_redirect_rejected"})
REASONS.update({"invalid_host_facts", "host_fact_scope_mismatch", "missing_role_protection", "fixed_role_effort",
                "missing_deny_capability", "unsupported_deny_capability", "missing_rewrite_capability",
                "missing_target_model", "missing_target_effort", "missing_effective_effort", "missing_original_baseline",
                "cached_effect_mismatch"})
REASONS.update({'catalog_model_unavailable', 'catalog_model_retired'})
REASONS.update({'named_role', 'no_candidates_for_platform', 'advice_already_given', 'advice_given', 'advice_reissue'})
REASONS.add('operator_stop_unavailable')
REASONS.update({'claude_subscription_'+reason for reason in (
    'disabled','export_denied','recursion','malformed_response','process_failed','timeout','cli_not_found')})
REASONS.update({'codex_subscription_'+reason for reason in (
    'disabled','export_denied','recursion','invalid_task','malformed_response',
    'oversized_response','tool_activity','process_failed','timeout',
    'chatgpt_login_required','home_instructions','isolation_unsupported','unverified_process',
    'auth_source_unconfirmed','auth_source_invalid','auth_reference_invalid','auth_lock_unavailable')})
UNAVAILABLE_REASONS = {'unsupported_model', 'unsupported_effort', 'catalog_model_unavailable', 'catalog_model_retired'}


def safe_id(value, limit=128):
    return isinstance(value, str) and 0 < len(value) <= limit and bool(re.fullmatch(r"[A-Za-z0-9_.:/-]+", value)) and not value.lower().startswith(("sk-", "bearer", "password", "secret"))


def safe_model_id(value, limit=128):
    """Model request IDs may carry a balanced context suffix; identities may not."""
    return (isinstance(value, str) and 0 < len(value) <= limit and
            bool(re.fullmatch(r"[A-Za-z0-9_.:/-]+(?:\[[A-Za-z0-9_.:-]+\])?", value)) and
            not value.lower().startswith(("sk-", "bearer", "password", "secret")))

@dataclass(frozen=True)
class Classification:
    tier: str
    confidence: float
    reason_code: str = "classified"

@dataclass(frozen=True)
class ContextSummary:
    summary: str
    source_ref: str
    permitted_export: bool = False
