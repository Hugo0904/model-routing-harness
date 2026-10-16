"""Plain-language statistics for the control center. Product terms stay in English; explanations in Chinese."""
from __future__ import annotations

import time

from mrh.presentation.terminal import cell_width

PLATFORM = {"claude": "Claude Code", "codex": "Codex", "gemini": "Gemini"}
REASON = {
    "advice_reissue": "舊重派紀錄（關聯未確認，按獨立呼叫計數）",
    "explicit_model": "主模型自己指定了模型（不干預）",
    "explicit_effort": "主模型已自己指定推理強度（effort）",
    "named_role": "專門角色、fork 或自訂子代理（不干預）",
    "advice_already_given": "同一任務 10 分鐘內已建議過（不重複攔）",
    "low_confidence": "分級信心低於門檻",
    "no_candidates_for_platform": "該等級沒有設定這個平台的模型",
    "classifier_timeout": "分級器逾時",
    "classifier_error": "分級器錯誤",
    "malformed_classification": "分級器回覆格式不對",
    "typesafe_http_402": "Jev 餘額不足",
    "typesafe_http_401": "Jev 金鑰無效",
    "typesafe_missing_credentials": "找不到 Jev 金鑰",
    "typesafe_http_429": "Jev 呼叫太頻繁（被限流）",
}
PROVIDER = {"jev": "Jev", "codex_subscription": "Codex 訂閱", "claude_subscription": "Claude 訂閱", "synthetic": "測試資料"}
JEV_USD_PER_INPUT_TOKEN = 0.042 / 1_000_000
# Codex roles installed by the engineering-workflow-router skill (~/.codex/agents/*.toml). Only that skill spawns them,
# so a delegation with one of these roles is the skill choosing its own model. Claude has no equivalent marker.
ROUTER_SKILL_ROLES = ("luna_worker", "sol_worker", "lean_explorer", "risk_reviewer", "architecture_analyst",
                      "principal_analyst", "expert_council")
# Official list prices per million tokens (input, output), checked 2026-10. Display only; nothing is billed from this table.
CLAUDE_PRICES = (("haiku", (0.10, 0.50)), ("sonnet", (2, 10)), ("opus", (4, 20)), ("fable", (10, 50)))


def claude_price(model):
    for name, (low, high) in CLAUDE_PRICES:
        if name in str(model).lower():
            fmt = lambda v: f"{v:.2f}" if v < 1 else f"{v:g}"
            return f"{fmt(low)} / {fmt(high)}"
    return "—"


# ---- terminal bars
TIER_RGB = {"Light": (75, 80, 168), "Small": (100, 105, 201), "Mid": (169, 174, 245), "Top": (232, 234, 252),
            "Skill": (94, 196, 182)}
TIER_GLYPH = {"Light": "░", "Small": "▒", "Mid": "▓", "Top": "█", "Skill": "▚"}


def stacked_bar(parts, width, color):
    """parts: [(tier, count)]. Each segment's length is proportional; the percentage sits in the caption."""
    total = sum(n for _, n in parts) or 1
    cells, used = [], 0
    for i, (tier, n) in enumerate(parts):
        size = width - used if i == len(parts) - 1 else max(1 if n else 0, round(n * width / total))
        size = max(0, min(size, width - used)); used += size
        if color:
            r, g, b = TIER_RGB[tier]
            cells.append(f"\x1b[38;2;{r};{g};{b}m" + "█" * size + "\x1b[0m")
        else:
            cells.append(TIER_GLYPH[tier] * size)
    return "".join(cells)


def _swatch(tier, color):
    r, g, b = TIER_RGB[tier]
    return f"\x1b[38;2;{r};{g};{b}m■\x1b[0m" if color else TIER_GLYPH[tier]


def progress_bar(percent, width, color):
    filled = round(width * percent / 100)
    if color:
        return "\x1b[38;2;169;174;245m" + "█" * filled + "\x1b[38;2;70;74;99m" + "█" * (width - filled) + "\x1b[0m"
    return "█" * filled + "░" * (width - filled)


def _pad(text, width):
    """Pad by terminal cells: a CJK character takes two."""
    return text + " " * max(1, width - cell_width(text))


def _usd(amount):
    return "$0" if amount == 0 else ("< $0.0001" if amount < 0.0001 else f"${amount:.4f}")


def _pct(part, whole):
    return f"{part * 100 // whole}%" if whole else "—"


CHANGE_NOTICE_DAYS = 7


def version_change_note(data, now=None):
    """A reminder for a week after the answering model changed, or None."""
    change = data.get("classifier_change")
    now = time.time() if now is None else now
    if not change or now - change["at"] > CHANGE_NOTICE_DAYS * 86400:
        return None
    return (f"分級器版本已從 {change['from']} 變為 {change['to']}（{time.strftime('%m/%d', time.localtime(change['at']))}），"
            "信心門檻建議重算")


def main_version(data):
    """The classifier model that answered most often in the period, or None."""
    versions = data.get("classifier_versions") or {}
    return max(versions, key=versions.get) if versions else None


def latency_text(data):
    """'平均 0.8 秒、最慢 2.1 秒（12 次）' or None when no call returned."""
    latency = data.get("classifier_latency") or {}
    if not latency.get("n"):
        return None
    return f"平均 {latency['avg']:.1f} 秒、最慢 {latency['max']:.1f} 秒（{latency['n']} 次）"


def skill_roles(data):
    """{role: count} of delegations the Router skill made with its own roles."""
    return {r: n for r, n in data.get("roles", {}).items() if r in ROUTER_SKILL_ROLES}


def skill_reasons(data):
    """{reason: count} behind the skill's delegations, so they are not listed again as "kept unchanged"."""
    out = {}
    for role, reasons in data.get("role_reasons", {}).items():
        if role in ROUTER_SKILL_ROLES:
            for reason, n in reasons.items():
                out[reason] = out.get(reason, 0) + n
    return out


def kept_without_skill(data):
    skill = skill_reasons(data)
    return {r: n - skill.get(r, 0) for r, n in data["kept_unchanged"].items() if n - skill.get(r, 0) > 0}


def rerouted(data):
    """(re-routed, all delegations): MRH advice the parent followed plus every skill delegation, over every delegation counted.
    A skill delegation is a re-route by definition: the skill picked the model itself. The rest is "not re-routed", and the
    reasons for it are the unchanged-reasons list."""
    d = data["decisions"]
    total = d.get("advise", 0) + d.get("continue_main", 0) + d.get("preserve", 0)
    return data["children_following_advice"] + sum(skill_roles(data).values()), total


def confidence_text(data, threshold=None):
    c = data.get("confidence") or {}
    parts = [f"{label} {c[key]['avg']:.2f}（{c[key]['n']} 次）" for key, label in (("last_24h", "24 小時內"), ("total", "總平均"))
             if c.get(key, {}).get("avg") is not None]
    return "、".join(parts) + (f"；門檻 {threshold:.2f}" if parts and threshold is not None else "") if parts else None


def _alias_match(candidate, model):
    return model == candidate or (candidate.isalpha() and candidate in model)   # "haiku" ~ "claude-haiku-5-5"


def tier_model_children(data, policy):
    """How many started subagents ran on a model from your Light/Small/Mid table, and how many reported a model at all."""
    matched = 0
    for platform, models in data.get("children_models", {}).items():
        table = {c["model"] for tier in ("Light", "Small", "Mid") for c in policy["tiers"].get(tier, {}).get(platform, [])}
        matched += sum(n for m, n in models.items() if any(_alias_match(c, m) for c in table))
    return matched, data.get("children_started", 0)


def skill_notes(data):
    """Caveats shared by every consumer of the skill bar."""
    notes = []
    if data.get("explicit_without_role"):
        notes.append(f"另有 {data['explicit_without_role']} 次主模型自選（非 skill 角色）")
    return notes


def accounting_notes(data):
    """One explanation of evidence limits for every statistics consumer."""
    notes = []
    if data.get('packet_classifications') or data.get('packet_releases'):
        notes.append(f"完整任務：已分級 {data.get('packet_classifications',0)} 次、已確認派工 {data.get('packet_children_started',0)} 次；其中請求設定符合建議 {data.get('packet_children_following_advice',0)} 次。")
    if data.get("children_following_prior_advice"):
        notes.append(f"本期 {data['children_following_prior_advice']} 次採用較早的建議，另列，不混入本期建議比例。")
    if data.get("inferred_links"):
        notes.append(f"其中 {data['inferred_links']} 筆是較早的紀錄，依「同一回合、模型與推理強度相符」推定")
    if data.get("unverified_reissues") or data.get("unverified_followed_children"):
        notes.append(f"舊紀錄關聯未確認：重派 {data.get('unverified_reissues', 0)}、跟隨 {data.get('unverified_followed_children', 0)}；不推定成功。")
    if data.get("followed_requested_models"):
        notes.append("採用模型僅有請求值，實際模型未回報：" + "、".join(f"{m} {n} 次" for m, n in sorted(data["followed_requested_models"].items())))
    if data.get("classifier_failed_requests") or any(u.get("usage_unknown_calls") for u in data["classifier_usage"].values()):
        notes.append(f"分級嘗試 {data.get('classifier_requests', 0)} 次，失敗 {data.get('classifier_failed_requests', 0)} 次；成本只估已回報 tokens，缺少用量仍未知。")
    return notes


def render(data, period_label, threshold=None, color=False, policy=None):
    d = data["decisions"]
    advised, main, kept = d.get("advise", 0), d.get("continue_main", 0), d.get("preserve", 0)
    total = advised + main + kept
    lines = [f"MRH 統計 ─ {period_label}", ""] + ([f"！{version_change_note(data)}", ""] if version_change_note(data) else [])
    if not total:
        return "\n".join(lines + ["  這段期間沒有任何子代理委派經過 MRH。",
                                  "  （路由關閉、不在生效範圍，或主模型沒有派子代理時都不會有紀錄。）", *accounting_notes(data), ""])
    platforms = "、".join(f"{PLATFORM.get(p, p)} {sum(v.values())}" for p, v in sorted(data["per_platform"].items()))
    handled = advised + main
    skill_total = sum(skill_roles(data).values())
    lines += [f"■ 子代理委派：共 {total} 次（{platforms}）",
              f"    路由器有出手的比例  {progress_bar(handled * 100 // total, 24, color)}  {handled} / {total} 次（{_pct(handled, total)}）",
              "    " + _pad("給建議，請主模型改用你設定的模型", 40) + f"{advised:>4} 次",
              "    " + _pad("判定為 Top，請主模型自己做", 40) + f"{main:>4} 次",
              "    " + _pad("Router skill 自己選模型派工", 40) + f"{skill_total:>4} 次",
              "    " + _pad("沒有介入，原樣放行", 40) + f"{kept - skill_total:>4} 次", ""]
    if data.get("reissues"):
        lines += [f"    （另有 {data['reissues']} 次是主模型照建議重派的後續呼叫，已排除，不重複計算）", ""]
    if kept_without_skill(data):
        lines.append("■ 沒有介入的原因")
        for reason, n in sorted(kept_without_skill(data).items(), key=lambda x: -x[1]):
            label = REASON.get(reason, f"其他（{reason}）")
            if reason == "low_confidence" and threshold is not None:
                label += f"（門檻 {threshold:.2f}）"
            lines.append("    " + _pad(label, 52) + f"{n:>4} 次")
        lines.append("")
    if policy is not None and data.get("children_started"):
        matched, started = tier_model_children(data, policy)
        lines += ["■ 子代理實際用的模型",
                  f"    用了分級表的模型  {progress_bar(matched * 100 // started, 24, color)}  {matched} / {started} 個子代理（{_pct(matched, started)}）"]
        for platform, models in sorted(data.get("children_models", {}).items()):
            lines.append(f"    {PLATFORM.get(platform, platform)}：" + "、".join(f"{m} {n}" for m, n in sorted(models.items(), key=lambda x: -x[1])))
        if data.get("children_inherited"):
            lines.append(f"    沿用主模型（沒指定模型）：{data['children_inherited']} 個")
        lines.append("")
    followed = data["children_following_advice"]
    moved, decided = rerouted(data)
    lines += ["■ 改派的效果",
              f"    有改派（MRH＋skill）  {progress_bar(moved * 100 // decided if decided else 0, 24, color)}  {moved} / {decided} 次委派（{_pct(moved, decided)}）",
              f"    其中照 MRH 建議 {followed} / {advised} 次；skill 自選 {skill_total} 次" +
              ("（" + "、".join(f"{r} {n}" for r, n in sorted(skill_roles(data).items(), key=lambda x: -x[1])) + "）" if skill_total else "")]
    if data["followed_models"]:
        lines.append("    已回報的執行模型：" + "、".join(f"{m} {n} 次" for m, n in sorted(data["followed_models"].items())))
    if advised > followed:
        lines.append("    尚未確認採用的部分：可能自己完成、改派其他模型，或缺少可證明的關聯。")
    lines.append("")
    if data["tiers"]:
        order = ("Light", "Small", "Mid", "Top")
        parts = [(t, data["tiers"][t]) for t in order if t in data["tiers"]]
        tsum = sum(n for _, n in parts)
        lines += ["■ 分級結果（分級器判定的難度）",
                  "    " + stacked_bar(parts, 48, color),
                  "    " + "   ".join(f"{_swatch(t, color)} {t.lower()} {n}（{_pct(n, tsum)}）" for t, n in parts)]
        if confidence_text(data, threshold):
            lines.append("    分級信心：" + confidence_text(data, threshold))
        lines.append("")
    lines.append("■ 分級器用量")
    if not data["classifier_usage"]:
        lines.append("    沒有呼叫分級器。")
    for kind, u in sorted(data["classifier_usage"].items()):
        cost = (("用量未回報，成本未知" if not u["input_tokens"] and (u.get("usage_unknown_calls") or u.get("failed"))
                 else "估計 " + _usd(u["input_tokens"] * JEV_USD_PER_INPUT_TOKEN)) if kind == "jev" else "使用訂閱額度")
        lines.append(f"    {PROVIDER.get(kind, kind)}：呼叫 {u['calls']} 次，輸入 {u['input_tokens']:,} tokens，{cost}")
    if data.get("manual_classifications"):
        lines.append(f"    其中手動查詢（mrh classify）{data['manual_classifications']} 次，不算委派")
    if latency_text(data):
        lines.append("    耗時：" + latency_text(data))
    if data.get("classifier_versions"):
        lines.append("    實際版本：" + "、".join(f"{m} {n} 次" for m, n in sorted(data["classifier_versions"].items(), key=lambda x: -x[1])))
    return "\n".join(lines + accounting_notes(data) + [""])
