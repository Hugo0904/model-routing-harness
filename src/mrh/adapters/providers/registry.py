"""Settings v2 `classifier` block -> provider instance. No fallback between providers."""
from mrh.adapters.providers.claude_subscription import ClaudeSubscriptionClassifier
from mrh.adapters.providers.codex_subscription import CodexSubscriptionClassifier
from mrh.adapters.providers.typesafe import TypesafeClassifier
from mrh.infrastructure import secrets
from mrh.routing.core import ClassifierFailure

# Provider -> (human label, needs a stored key). Models are listed by the tool catalogs.
LABELS = {"jev": "Jev（TypeSafe API）", "codex_subscription": "Codex 訂閱", "claude_subscription": "Claude 訂閱"}
NEEDS_KEY = {"jev": True, "codex_subscription": False, "claude_subscription": False}
DEFAULT_TIMEOUT = {"jev": 10, "codex_subscription": 20, "claude_subscription": 25}


def build(settings, *, credential_resolver=None, transport=None):
    """`settings` is a validated v2 document; gates are copied from it, never inferred."""
    classifier = settings["classifier"]
    provider, flags = classifier["provider"], {"enabled": settings["enabled"],
                                               "task_export_permitted": settings["task_export_permitted"]}
    if provider == "jev":
        return TypesafeClassifier(**flags, credential_resolver=credential_resolver or secrets.credential_resolver("jev"),
                                  transport=transport, model=classifier["model"])
    if provider == "codex_subscription":
        return CodexSubscriptionClassifier(**flags, model=classifier["model"], standalone=True)
    if provider == "claude_subscription":
        return ClaudeSubscriptionClassifier(**flags, model=classifier["model"])
    raise ClassifierFailure("invalid_policy")
