"""Confidence-threshold suggestion. Pure and cheap: it runs once, when the user opens the threshold setting, and never in the hook.

There is no ground truth for "this delegation should have been routed elsewhere", so this is a suggestion built from the
confidence distribution and one behavioural signal (the parent replacing advice with a stronger model), not a verdict.
"""
from __future__ import annotations

import math

WINDOW_DAYS = 30
MIN_SAMPLES = 30
COVERAGE = 0.80               # the threshold sits where about this share of classifications passes
LOW, HIGH, STEP = 0.50, 0.90, 0.05
RAISE_MIN_OVERRIDES = 5
RAISE_MIN_SHARE = 0.20
FOLLOW_SECONDS = 600
TIER_ORDER = ("Light", "Small", "Mid", "Top")


def _round_step(value):
    return round(round(value / STEP) * STEP, 2)


def _percentile_low(values, share):
    """Nearest-rank value with about `share` of the samples at or above it."""
    ordered = sorted(values)
    rank = max(1, math.ceil((1 - share) * len(ordered)))
    return ordered[rank - 1]


def _tier_models(policy, platform):
    """{tier: set of models} for one platform, from the user's tier table."""
    table = {tier: {c["model"] for c in policy["tiers"].get(tier, {}).get(platform, [])} for tier in TIER_ORDER if tier != "Top"}
    table["Top"] = {c["model"] for c in policy.get("fixed", {}).get(platform, [])}
    return table


def _override(advice, child, policy):
    """True when the model the parent actually used is stronger than the advised tier, or is outside the tier table
    (including inheriting the main model), i.e. the parent did not accept the advised level."""
    advised = TIER_ORDER.index(advice["tier"]) if advice["tier"] in TIER_ORDER else None
    if advised is None:
        return False
    model = child["requested_model"]
    if not model:
        return True                                   # inherited the main model
    table = _tier_models(policy, advice["platform"])
    levels = [i for i, tier in enumerate(TIER_ORDER) if any(model == m or (m.isalpha() and m in model) for m in table[tier])]
    if not levels:
        return True                                   # not a table model: effectively the main model or the user's own pick
    return max(levels) > advised


def suggest_threshold(advice_rows, child_rows, policy, now, *, since=None, days=WINDOW_DAYS):
    """advice_rows/child_rows: dicts straight from advice.sqlite3 (advice needs request_id, ts, platform, session_id, turn_id,
    call_id, action, tier, confidence). `since` (epoch) further limits the data, e.g. to the current classifier version."""
    start = max(now - days * 86400, since or 0)
    rows = [r for r in advice_rows if r["ts"] >= start and r["confidence"] is not None]
    n = len(rows)
    if n < MIN_SAMPLES:
        return {"status": "insufficient", "n": n, "need": MIN_SAMPLES, "days": days}
    base = _percentile_low([r["confidence"] for r in rows], COVERAGE)

    pre_by_call = {(r["platform"], r["session_id"], r["call_id"]): r for r in advice_rows}
    followups = overrides = 0
    for advice in rows:
        if advice["action"] != "advise":
            continue
        later = []
        for child in child_rows:
            pre = pre_by_call.get((child["platform"], child["session_id"], child["call_id"]))
            if (pre and pre["session_id"] == advice["session_id"] and pre["turn_id"] == advice["turn_id"]
                    and pre["request_id"] != advice["request_id"] and 0 <= pre["ts"] - advice["ts"] <= FOLLOW_SECONDS):
                later.append((pre["ts"], child))
        if not later:
            continue
        followups += 1
        overrides += int(_override(advice, min(later, key=lambda x: x[0])[1], policy))
    raised = overrides >= RAISE_MIN_OVERRIDES and followups and overrides / followups >= RAISE_MIN_SHARE
    suggested = min(HIGH, max(LOW, _round_step(base + (STEP if raised else 0))))
    passing = sum(1 for r in rows if r["confidence"] >= suggested)
    return {"status": "ok", "suggested": suggested, "base": round(base, 4), "n": n, "days": days,
            "pass_share": passing / n, "raised": bool(raised), "overrides": overrides, "followups": followups}


def describe(result, change=None):
    """The one or two lines shown above the threshold prompt. `change` is the latest classifier-version switch, if any."""
    note = [f"　只計算分級器版本變更（{change['from']} → {change['to']}）之後的資料。"] if change else []
    if result["status"] == "insufficient":
        return [f"建議：樣本不足（最近 {result['days']} 天只有 {result['n']} 次分級，需要 {result['need']} 次），"
                "之後可以請 Claude 依資料判斷。", *note]
    lines = [f"建議：{result['suggested']:.2f}（依最近 {result['days']} 天 {result['n']} 次分級，約 {result['pass_share'] * 100:.0f}% 會通過）"]
    if result["raised"]:
        lines.append(f"　已 +{STEP:.2f}：主模型常改用更強的模型（{result['overrides']}／{result['followups']} 次）")
    return lines + note
