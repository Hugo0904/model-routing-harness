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
    raise CtrlError("請填 on 或 off")


def parse_candidates(text):
    """'gpt-5.6-luna:low, gpt-6-luna' -> [{'model':..,'effort':..}, {'model':..}]"""
    result = []
    for part in [p.strip() for p in str(text).split(",") if p.strip()]:
        model, _, effort = part.partition(":")
        if not safe_model_id(model) or (effort and not safe_id(effort)):
            raise CtrlError(f"不是有效的模型寫法：{part[:40]}（格式：模型 或 模型:推理強度）")
        result.append({"model": model, **({"effort": effort} if effort else {})})
    if len(result) > v2.MAX_CANDIDATES:
        raise CtrlError(f"每份清單最多 {v2.MAX_CANDIDATES} 個候選模型")
    return result


def format_candidates(items):
    return ", ".join(c["model"] + (":" + c["effort"] if c.get("effort") else "") for c in items) or "(none)"


def _number(value, low, high, label):
    try:
        number = float(value)
    except ValueError:
        raise CtrlError(f"{label}必須是數字") from None
    if not low <= number <= high:
        raise CtrlError(f"{label}必須介於 {low} 到 {high}")
    return number


def changes_for(settings, key, value):
    """Return kwargs for settings_v2.update. Raises CtrlError on unknown key or bad value."""
    policy, classifier = settings["policy"], settings["classifier"]
    if key == "enabled":
        return {"enabled": parse_bool(value)}
    if key == "task_export":
        return {"task_export_permitted": parse_bool(value)}
    if key == "stats.retention_days":
        try:
            days = int(str(value).strip())
        except ValueError:
            raise CtrlError("保留天數必須是整數（0 代表永久保留）") from None
        if not 0 <= days <= v2.MAX_RETENTION_DAYS:
            raise CtrlError(f"保留天數必須介於 0 到 {v2.MAX_RETENTION_DAYS}（0 代表永久保留）")
        return {"retention_days": days}
    if key == "classifier.provider":
        provider = str(value).strip().lower()
        if provider not in v2.PROVIDERS:
            raise CtrlError("分級器只能是：" + "、".join(v2.PROVIDERS))
        from mrh.adapters.providers.registry import DEFAULT_TIMEOUT
        return {"classifier": {"provider": provider, "model": v2.PROVIDERS[provider], "timeout_seconds": DEFAULT_TIMEOUT[provider]}}
    if key == "classifier.model":
        return {"classifier": {**classifier, "model": str(value).strip()}}
    if key == "classifier.rich_input":
        if parse_bool(value):
            return {"classifier": {**classifier, "rich_input": True}}
        return {"classifier": {k: v for k, v in classifier.items() if k != "rich_input"}}
    if key == "classifier.timeout":
        return {"classifier": {**classifier, "timeout_seconds": _number(value, 1, 30, "逾時秒數")}}
    if key == "threshold":
        return {"policy": {**policy, "threshold": _number(value, *v2.THRESHOLD_RANGE, "信心門檻")}}
    if key == "top_mode":
        mode = str(value).strip().title()
        if mode not in ("Main", "Fixed"):
            raise CtrlError("top_mode 只能是 Main 或 Fixed")
        if mode == "Fixed" and not any(policy["fixed"].values()):
            raise CtrlError("請先設定 Top 清單再改成 Fixed，例如：mrh ctrl set fixed.codex gpt-6.1-sol:high")
        return {"policy": {**policy, "top_mode": mode}}
    if key == "allowed_workspaces":
        raw = [p.strip() for p in str(value).split(",") if p.strip()]
        roots = [str(Path(p).resolve()) for p in raw if os.path.isabs(p)]
        if not raw or len(roots) != len(raw):
            raise CtrlError("請填一個或多個絕對路徑，用逗號分隔（/ 代表全部）")
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
            raise CtrlError("請填角色名稱，用逗號分隔（最多 8 個）")
        return {"policy": {**policy, "generic_roles": {**policy.get("generic_roles", v2.DEFAULT_GENERIC_ROLES), parts[1]: names}}}
    raise CtrlError("沒有這個設定項目：" + key[:60] + "（可用 mrh ctrl keys 列出）")


def key_names():
    return ["enabled", "task_export", "stats.retention_days", "classifier.provider", "classifier.model", "classifier.timeout", "classifier.rich_input", "threshold",
            "top_mode", "allowed_workspaces", *[f"tiers.{t}.{p}" for t in v2.TIERS for p in v2.PLATFORMS],
            *[f"fixed.{p}" for p in v2.PLATFORMS], *[f"generic_roles.{p}" for p in v2.PLATFORMS]]
