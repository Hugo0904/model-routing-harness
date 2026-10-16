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


DEFAULT_GEAR_STARTS = (0, 0.75, 1.5, 2.25, 2.75)


def default_gears(policy):
    """A five-gear starting ladder built from the current tier table: gears 1-3 copy Light/Small/Mid; the two hardest
    go back to the main model (or to the Top list when Top is set to Fixed). The user then edits it."""
    top = {p: list(c) for p, c in policy["fixed"].items() if c} if policy["top_mode"] == "Fixed" else {}
    gears = []
    for start, tier in zip(DEFAULT_GEAR_STARTS, ("Light", "Small", "Mid", "Top", "Top")):
        if tier == "Top":
            gears.append({"from": start, "candidates": top} if top else {"from": start, "main": True})
        else:
            gears.append({"from": start, "candidates": {p: list(c) for p, c in policy["tiers"].get(tier, {}).items() if c}})
    return gears


def _gear_number(policy, text, *, allow_new=False):
    gears = policy.get("gears") or []
    try:
        number = int(str(text).strip())
    except ValueError:
        raise CtrlError("檔位編號必須是整數（第 1 檔最容易）") from None
    if not 1 <= number <= len(gears) + (1 if allow_new else 0):
        raise CtrlError(f"目前只有 {len(gears)} 檔")
    return number


def _checked(gears):
    """User-facing reasons before the generic settings validation."""
    if not 1 <= len(gears) <= v2.MAX_GEARS:
        raise CtrlError(f"檔位最少 1 檔、最多 {v2.MAX_GEARS} 檔")
    if gears[0]["from"] != 0:
        raise CtrlError("第 1 檔的分數下限固定是 0")
    for before, after in zip(gears, gears[1:]):
        if after["from"] <= before["from"]:
            raise CtrlError("每一檔的分數下限要比前一檔大（難度分數 0～3，越高越難）")
    return gears


def _gear_changes(policy, key, parts, value):
    gears = [dict(g) for g in (policy.get("gears") or [])]
    if key == "gears.default":
        return {"policy": {**policy, "gears": default_gears(policy)}}
    if key == "gears.add":
        start = _number(value, 0, v2.SCORE_MAX, "分數下限")
        if any(abs(g["from"] - start) < 1e-9 for g in gears):
            raise CtrlError("已經有一檔從這個分數開始")
        gears = sorted([*gears, {"from": start, "candidates": {}}], key=lambda g: g["from"])
        return {"policy": {**policy, "gears": _checked(gears)}}
    if key == "gears.remove":
        number = _gear_number(policy, value)
        if len(gears) == 1:
            raise CtrlError("至少要保留 1 檔")
        del gears[number - 1]
        gears[0] = {**gears[0], "from": 0}                       # the first gear always starts at 0
        return {"policy": {**policy, "gears": _checked(gears)}}
    number = _gear_number(policy, parts[1])
    gear = gears[number - 1]
    field = parts[2]
    if field == "from":
        if number == 1:
            raise CtrlError("第 1 檔的分數下限固定是 0")
        gear["from"] = _number(value, 0, v2.SCORE_MAX, "分數下限")
    elif field == "main":
        gears[number - 1] = {"from": gear["from"], "main": True} if parse_bool(value) else {"from": gear["from"], "candidates": {}}
        return {"policy": {**policy, "gears": _checked(gears)}}
    elif field in v2.PLATFORMS:
        candidates = dict(gear.get("candidates", {}))
        candidates[field] = parse_candidates(value)
        gears[number - 1] = {"from": gear["from"], "candidates": candidates}
        return {"policy": {**policy, "gears": _checked(gears)}}
    else:
        raise CtrlError("檔位可以設：from（分數下限）、main（交回主模型）、" + "／".join(v2.PLATFORMS) + "（候選模型）")
    gears[number - 1] = gear
    return {"policy": {**policy, "gears": _checked(gears)}}


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
    if key == "mode":
        chosen = str(value).strip().lower()
        if chosen not in ("tiers", "gears"):
            raise CtrlError("模式只能是 tiers（難度表）或 gears（檔位）")
        if chosen == "gears" and not policy.get("gears"):
            raise CtrlError("還沒有檔位。請先建立：mrh ctrl set gears.default yes（再用 gears.<編號>.… 調整）")
        return {"policy": {**{k: v for k, v in policy.items() if k != "mode"}, **({"mode": "gears"} if chosen == "gears" else {})}}
    if key.startswith("gears."):
        parts = key.split(".")
        if key in ("gears.default", "gears.add", "gears.remove") or len(parts) == 3:
            return _gear_changes(policy, key, parts, value)
        raise CtrlError("檔位的設定項目：gears.default／gears.add／gears.remove／gears.<編號>.from／main／claude／codex")
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
    return ["enabled", "task_export", "stats.retention_days", "classifier.provider", "classifier.model", "classifier.timeout", "classifier.rich_input", "threshold", "mode", "gears.default", "gears.add", "gears.remove",
            "top_mode", "allowed_workspaces", *[f"tiers.{t}.{p}" for t in v2.TIERS for p in v2.PLATFORMS],
            *[f"fixed.{p}" for p in v2.PLATFORMS], *[f"generic_roles.{p}" for p in v2.PLATFORMS]]
