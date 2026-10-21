"""Pure statistics over stored snapshots; never reads transcripts or writes the database."""
from __future__ import annotations

import json

from mrh.advisory import pricing
from mrh.advisory.usage_collect import _n, observation

PLATFORMS = ("claude", "codex")
# The Agent-tool aliases supported by this release, resolved only to explicit known IDs.
CLAUDE_ALIASES = {"haiku": "claude-haiku-5-5", "sonnet": "claude-sonnet-5-5", "opus": "claude-opus-5-5"}
LEGACY = "舊版快照未重新驗證，請執行 mrh usage collect"


def empty():
    return {"recorded": 0, "collected": 0, "uncollected": 0, "legacy": 0, "by_model": {}, "cost": {}, "saving": {},
            "mismatch": [], "verified": {"checked": 0, "matching": 0, "unknown": 0,
                                           "effort_checked": 0, "effort_matching": 0, "effort_unknown": 0},
            "pricing": {"checked": pricing.CHECKED, "sources": [pricing.CLAUDE_URL, pricing.OPENAI_URL]}}


def _add(values):
    values = list(values)
    return None if any(_n(v) is None for v in values) else sum(values)


def _sum(entries, bucket_field):
    return _add((e.get(bucket) or {}).get(bucket_field) for e in entries for bucket in ("small", "large"))


def _matches(candidate_model, actual_model):
    return (isinstance(candidate_model, str) and isinstance(actual_model, str) and
            (candidate_model == actual_model or CLAUDE_ALIASES.get(candidate_model) == actual_model))


def summarize(rows, recorded, advice):
    result = empty()
    result.update(recorded=recorded, collected=len(rows), uncollected=max(0, recorded - len(rows)))
    by_model, cost, savings, unknown = {}, {}, {}, {}
    for row in rows:
        usage = json.loads(row["usage"])
        trusted = observation(usage) is not None
        result["legacy"] += int(not trusted)
        platform = row["platform"]
        for model, entry in usage.items():
            slot = by_model.setdefault((platform, model), {"children": 0, "legacy_children": 0,
                **{k: [] for k in ("requests", "input", "cache_write", "cache_read", "output", "reasoning")}})
            slot["children"] += 1
            slot["legacy_children"] += int(not trusted)
            values = {"requests": entry.get("requests"), "input": _sum([entry], "input"),
                      "cache_write": _add(_sum([entry], f) for f in ("cache_write_5m", "cache_write_1h", "cache_write")),
                      "cache_read": _sum([entry], "cache_read"), "output": entry.get("output"), "reasoning": entry.get("reasoning")}
            for k, value in values.items():
                slot[k].append(value if trusted else None)
        child_cost = pricing.price_child(usage) if trusted else {"input_side": None, "output": None, "unknown": [LEGACY]}
        c = cost.setdefault(platform, {"children": 0, "input_side_usd": 0.0, "input_side_known_usd": 0.0,
                                     "input_side_unknown": 0, "output_usd": 0.0, "output_known_usd": 0.0, "output_unknown": 0, "unknown_reasons": {}})
        c["children"] += 1
        for field in ("input_side", "output"):
            if child_cost[field] is None:
                c[field + "_unknown"] += 1
            else:
                c[field + "_known_usd"] += child_cost[field]
        for reason in child_cost["unknown"]:
            c["unknown_reasons"][reason] = c["unknown_reasons"].get(reason, 0) + 1
        saved = pricing.saving(usage, row.get("parent_model")) if trusted else {"usd": None, "scope": None, "reason": LEGACY}
        sv = savings.setdefault(platform, {"children": 0, "usd": 0.0, "known_usd": 0.0, "scope": None, "unknown": 0})
        if saved["usd"] is None:
            sv["unknown"] += 1
            unknown[saved["reason"]] = unknown.get(saved["reason"], 0) + 1
        else:
            sv["children"] += 1; sv["known_usd"] += saved["usd"]; sv["scope"] = saved["scope"]
        _compare(result, row, usage, advice, trusted=trusted)
    result["by_model"] = {f"{p}|{m}": {k: (_add(v) if isinstance(v, list) else v) for k, v in slot.items()}
                          for (p, m), slot in sorted(by_model.items())}
    for c in cost.values():
        for field in ("input_side", "output"):
            c[field + "_usd"] = None if c[field + "_unknown"] else c[field + "_known_usd"]
    for sv in savings.values():
        sv["usd"] = None if sv["unknown"] else sv["known_usd"]
    result["cost"], result["saving"], result["saving_unknown_reasons"] = cost, savings, unknown
    return result


def _compare(result, row, usage, advice, *, trusted=True):
    original = advice.get(row.get("advice_request_id") or "")
    if not original:
        return
    try:
        offered = json.loads(original["candidates"])
        actual = json.loads(row["models"])
    except (TypeError, ValueError):
        return
    offered = offered.get("candidates", []) if isinstance(offered, dict) else offered
    if not isinstance(offered, list):
        return
    offered = [c for c in offered if isinstance(c, dict) and isinstance(c.get("model"), str)]
    if not offered:
        return
    actual = actual if isinstance(actual, list) else []
    profiles = [m for m in actual if isinstance(m, dict) and isinstance(m.get("model"), str) and m["model"]]
    verified = result["verified"]
    if not trusted or not profiles or len(profiles) != len(actual):
        verified["unknown"] += 1
        verified["effort_unknown"] += 1
        return
    verified["checked"] += 1
    bad_models = [m for m in profiles if not any(_matches(c["model"], m["model"]) for c in offered)]
    verified["matching"] += int(not bad_models)
    def mismatch(kind, mismatched):
        result["mismatch"].append({"platform": row["platform"], "agent_id": row.get("agent_id"),
            "advised": [c["model"] + (":" + c["effort"] if c.get("effort") else "") for c in offered],
            "actual": [m["model"] + (":" + m["effort"] if m.get("effort") else "") for m in mismatched], "kind": kind})
    if bad_models:
        mismatch("model", bad_models)
    effort_checked, effort_bad = 0, []
    for profile in profiles:
        candidates = [c for c in offered if _matches(c["model"], profile["model"])]
        expected = [c.get("effort") for c in candidates if c.get("effort")]
        if not profile.get("effort") or not expected:
            continue
        effort_checked += 1
        if profile["effort"] not in expected:
            effort_bad.append(profile)
    if effort_bad:
        mismatch("effort", effort_bad)
    if effort_checked == len(profiles):
        verified["effort_checked"] += 1
        verified["effort_matching"] += int(not effort_bad)
    else:
        verified["effort_unknown"] += 1
