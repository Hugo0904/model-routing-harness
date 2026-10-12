"""Our internal protocol; these shapes are not a Jev wire API."""
from dataclasses import dataclass, field
import hashlib
import json
import math
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
                "typesafe_http_401", "typesafe_http_422", "typesafe_http_429", "typesafe_http_529",
                "typesafe_http_5xx", "typesafe_http_error", "typesafe_network_error",
                "typesafe_timeout", "typesafe_oversized_response", "typesafe_redirect_rejected"})
REASONS.update({"invalid_host_facts", "host_fact_scope_mismatch", "missing_role_protection", "fixed_role_effort",
                "missing_deny_capability", "unsupported_deny_capability", "missing_rewrite_capability",
                "missing_target_model", "missing_target_effort", "missing_effective_effort", "missing_original_baseline",
                "cached_effect_mismatch"})
REASONS.update({'catalog_model_unavailable', 'catalog_model_retired'})
REASONS.add('operator_stop_unavailable')
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
class Proposal:
    platform: str
    surface: str
    session_id: str
    turn_id: str
    tool_call_id: str
    tool_input: dict
    synthetic: bool = False
    tool_name: str = "spawn_agent"

    @property
    def identity(self):
        ids = [self.platform, self.surface, self.session_id, self.turn_id, self.tool_call_id]
        if not all(safe_id(x) for x in ids):
            raise ValueError("invalid_identity")
        return hashlib.sha256(json.dumps(ids, separators=(",", ":")).encode()).hexdigest()

    @property
    def task(self):
        value = self.tool_input.get("message", "")
        return value if isinstance(value, str) else ""


@dataclass(frozen=True)
class Decision:
    action: str = "preserve"
    reason: str = "classifier_unavailable"
    tier: str | None = None
    confidence: float | None = None
    patch: dict = field(default_factory=dict)
    synthetic: bool = False
    context_status: str = "absent"
    target_model: str | None = None

    def validate(self):
        if self.action not in ("preserve", "request_child", "return_to_main", "operator_update_required") or self.reason not in REASONS or type(self.synthetic) is not bool:
            raise ValueError("invalid_decision")
        if self.context_status not in ("absent", "export_denied", "oversized", "sensitive", "permitted", "timeout", "error"):
            raise ValueError("invalid_decision")
        if self.tier is None:
            if self.confidence is not None:
                raise ValueError("invalid_decision")
        elif self.tier not in TIERS or isinstance(self.confidence, bool) or not isinstance(self.confidence, (int, float)) or not math.isfinite(self.confidence) or not 0 <= self.confidence <= 1:
            raise ValueError("invalid_decision")
        if not isinstance(self.patch, dict) or set(self.patch) - {"model", "reasoning_effort"}:
            raise ValueError("invalid_decision")
        if self.action == "request_child":
            if not safe_model_id(self.patch.get("model")) or ("reasoning_effort" in self.patch and not safe_id(self.patch["reasoning_effort"])):
                raise ValueError("invalid_decision")
            if self.tier is None or self.confidence < 0.5:
                raise ValueError("invalid_decision")
        elif self.patch:
            raise ValueError("invalid_decision")
        if self.action == "return_to_main" and (self.tier != "Top" or self.confidence < 0.5 or self.reason != "top_main_requested"):
            raise ValueError("invalid_decision")
        if self.action == "operator_update_required":
            if self.tier is None or self.confidence < 0.5 or not safe_model_id(self.target_model) or self.reason not in UNAVAILABLE_REASONS:
                raise ValueError("invalid_decision")
        elif self.target_model is not None:
            raise ValueError("invalid_decision")
        return self

    def as_dict(self):
        value = {"schema_version": 1, "action": self.action, "reason": self.reason,
                "tier": self.tier, "confidence": self.confidence, "patch": self.patch,
                "synthetic": self.synthetic, "context_status": self.context_status}
        if self.target_model is not None:
            value['target_model'] = self.target_model
        return value

    @classmethod
    def from_dict(cls, value):
        return cls(**{k: v for k, v in value.items() if k != "schema_version"}).validate()


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
