"""Pure control-center logic: parse operator input into settings changes. No IO."""
from __future__ import annotations

import os
from pathlib import Path

from mrh.infrastructure import settings_v2 as v2
from mrh.routing.types import safe_id, safe_model_id

TRUE, FALSE = {"on", "true", "yes", "1", "enable", "enabled"}, {"off", "false", "no", "0", "disable", "disabled"}
DEFAULT_MODEL = v2.PROVIDERS
FALLBACK_MODELS = {"claude": ("haiku", "sonnet", "opus")}   # Agent-tool aliases when the CLI catalog is unsupported


class CtrlError(ValueError):
    pass


def parse_bool(value):
    text = str(value).strip().lower()
    if text in TRUE:
        return True
    if text in FALSE:
        return False
    raise CtrlError("expected on/off")


def parse_candidates(text):
    """'gpt-5.6-luna:low, gpt-6-luna' -> [{'model':..,'effort':..}, {'model':..}]"""
    result = []
    for part in [p.strip() for p in str(text).split(",") if p.strip()]:
        model, _, effort = part.partition(":")
        if not safe_model_id(model) or (effort and not safe_id(effort)):
            raise CtrlError(f"not a model entry: {part[:40]}")
        result.append({"model": model, **({"effort": effort} if effort else {})})
    if len(result) > v2.MAX_CANDIDATES:
        raise CtrlError(f"at most {v2.MAX_CANDIDATES} candidates per list")
    return result


def format_candidates(items):
    return ", ".join(c["model"] + (":" + c["effort"] if c.get("effort") else "") for c in items) or "(none)"


def _number(value, low, high, label):
    try:
        number = float(value)
    except ValueError:
        raise CtrlError(f"{label} must be a number") from None
    if not low <= number <= high:
        raise CtrlError(f"{label} must be between {low} and {high}")
    return number


def changes_for(settings, key, value):
    """Return kwargs for settings_v2.update. Raises CtrlError on unknown key or bad value."""
    policy, classifier = settings["policy"], settings["classifier"]
    if key == "enabled":
        return {"enabled": parse_bool(value)}
    if key == "task_export":
        return {"task_export_permitted": parse_bool(value)}
    if key == "classifier.provider":
        provider = str(value).strip().lower()
        if provider not in v2.PROVIDERS:
            raise CtrlError("provider must be one of: " + ", ".join(v2.PROVIDERS))
        from mrh.adapters.providers.registry import DEFAULT_TIMEOUT
        return {"classifier": {"provider": provider, "model": v2.PROVIDERS[provider], "timeout_seconds": DEFAULT_TIMEOUT[provider]}}
    if key == "classifier.model":
        return {"classifier": {**classifier, "model": str(value).strip()}}
    if key == "classifier.timeout":
        return {"classifier": {**classifier, "timeout_seconds": _number(value, 1, 30, "timeout")}}
    if key == "threshold":
        return {"policy": {**policy, "threshold": _number(value, *v2.THRESHOLD_RANGE, "threshold")}}
    if key == "top_mode":
        mode = str(value).strip().title()
        if mode not in ("Main", "Fixed"):
            raise CtrlError("top_mode must be Main or Fixed")
        if mode == "Fixed" and not any(policy["fixed"].values()):
            raise CtrlError("set a Top list first, e.g. mrh ctrl set fixed.codex gpt-6.1-sol:high")
        return {"policy": {**policy, "top_mode": mode}}
    if key == "allowed_workspaces":
        raw = [p.strip() for p in str(value).split(",") if p.strip()]
        roots = [str(Path(p).resolve()) for p in raw if os.path.isabs(p)]
        if not raw or len(roots) != len(raw):
            raise CtrlError("give one or more absolute paths, comma separated (/ means everywhere)")
        return {"allowed_workspaces": roots}
    parts = key.split(".")
    if len(parts) == 3 and parts[0] == "tiers" and parts[1].title() in v2.TIERS and parts[2] in v2.PLATFORMS:
        tiers = {t: dict(p) for t, p in policy["tiers"].items()}
        tiers.setdefault(parts[1].title(), {})[parts[2]] = parse_candidates(value)
        return {"policy": {**policy, "tiers": tiers}}
    if len(parts) == 2 and parts[0] == "fixed" and parts[1] in v2.PLATFORMS:
        return {"policy": {**policy, "fixed": {**policy["fixed"], parts[1]: parse_candidates(value)}}}
    if len(parts) == 2 and parts[0] == "generic_roles" and parts[1] in v2.PLATFORMS:
        names = [r.strip() for r in str(value).split(",") if r.strip()]
        if len(names) > 8 or not all(safe_id(r) for r in names):
            raise CtrlError("role names, comma separated (at most 8)")
        return {"policy": {**policy, "generic_roles": {**policy.get("generic_roles", v2.DEFAULT_GENERIC_ROLES), parts[1]: names}}}
    raise CtrlError("unknown key: " + key[:60])


def key_names():
    return ["enabled", "task_export", "classifier.provider", "classifier.model", "classifier.timeout", "threshold",
            "top_mode", "allowed_workspaces", *[f"tiers.{t}.{p}" for t in v2.TIERS for p in v2.PLATFORMS],
            *[f"fixed.{p}" for p in v2.PLATFORMS], *[f"generic_roles.{p}" for p in v2.PLATFORMS]]
