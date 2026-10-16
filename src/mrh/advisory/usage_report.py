"""Statistics over collected sub-agent usage. Pure: it reads rows already in the database and never touches transcript files."""
from __future__ import annotations

import json

from mrh.advisory import pricing

PLATFORMS = ("claude", "codex")


def empty():
    return {"recorded": 0, "collected": 0, "uncollected": 0, "by_model": {}, "cost": {}, "saving": {}, "mismatch": [], "verified": {"checked": 0, "matching": 0},
            "pricing": {"checked": pricing.CHECKED, "sources": [pricing.CLAUDE_URL, pricing.OPENAI_URL]}}


def _sum(entries, bucket_field):
    return sum((e.get(bucket) or {}).get(bucket_field, 0) for e in entries for bucket in ("small", "large"))


def _matches(candidate_model, actual_model):
    """A tier-table name such as `haiku` matches the full id `claude-haiku-5-5`; a full id matches itself."""
    return candidate_model == actual_model or (candidate_model.isalpha() and candidate_model in actual_model)


def summarize(rows, recorded, advice):
    """rows: child_usage joined with children (see AdviceStore.read_usage); recorded: children with an agent id in the period;
    advice: {request_id: advice row dict} for the advice that sub-agents were redirected by."""
    result = empty()
    result.update(recorded=recorded, collected=len(rows), uncollected=max(0, recorded - len(rows)))
    by_model, cost, saving, unknown = {}, {}, {}, {}
    for row in rows:
        usage = json.loads(row["usage"])
        platform = row["platform"]
        for model, entry in usage.items():
            slot = by_model.setdefault((platform, model), {"children": 0, "requests": 0, "input": 0, "cache_write": 0, "cache_read": 0,
                                                            "outputs": [], "reasoning": []})
            slot["children"] += 1
            slot["requests"] += entry.get("requests") or 0
            slot["input"] += _sum([entry], "input")
            slot["cache_write"] += sum(_sum([entry], f) for f in ("cache_write_5m", "cache_write_1h", "cache_write"))
            slot["cache_read"] += _sum([entry], "cache_read")
            slot["outputs"].append(entry.get("output")); slot["reasoning"].append(entry.get("reasoning"))
        child_cost = pricing.price_child(usage)
        c = cost.setdefault(platform, {"children": 0, "input_side_usd": 0.0, "input_side_unknown": 0, "output_usd": 0.0, "output_unknown": 0})
        c["children"] += 1
        if child_cost["input_side"] is None:
            c["input_side_unknown"] += 1
        else:
            c["input_side_usd"] += child_cost["input_side"]
        if child_cost["output"] is None:
            c["output_unknown"] += 1
        else:
            c["output_usd"] += child_cost["output"]
        s = pricing.saving(usage, row.get("parent_model"))
        sv = saving.setdefault(platform, {"children": 0, "usd": 0.0, "scope": None, "unknown": 0})
        if s["usd"] is None:
            sv["unknown"] += 1
            unknown[s["reason"]] = unknown.get(s["reason"], 0) + 1
        else:
            sv["children"] += 1; sv["usd"] += s["usd"]; sv["scope"] = s["scope"]
        _compare(result, row, usage, advice)
    result["by_model"] = {f"{p}|{m}": {**{k: v for k, v in slot.items() if k not in ("outputs", "reasoning")},
                                       "output": None if any(o is None for o in slot["outputs"]) else sum(slot["outputs"]),
                                       "reasoning": None if any(o is None for o in slot["reasoning"]) else sum(slot["reasoning"])}
                          for (p, m), slot in sorted(by_model.items())}
    for c in cost.values():
        c["output_usd"] = c["output_usd"] if not c["output_unknown"] else None
    result["cost"], result["saving"] = cost, saving
    result["saving_unknown_reasons"] = unknown
    return result


def _compare(result, row, usage, advice):
    """For a sub-agent MRH redirected: did what actually ran match the advice? Compares the real model, not the request."""
    original = advice.get(row.get("advice_request_id") or "")
    if not original:
        return
    try:
        offered = json.loads(original["candidates"])
    except (TypeError, ValueError):
        return
    offered = offered.get("candidates", []) if isinstance(offered, dict) else offered
    if not offered:
        return
    actual = json.loads(row["models"])
    names = [m["model"] for m in actual]
    result["verified"]["checked"] += 1
    model_ok = any(_matches(c["model"], n) for c in offered for n in names)
    result["verified"]["matching"] += int(model_ok)
    if not model_ok:
        result["mismatch"].append({"platform": row["platform"], "agent_id": row.get("agent_id"), "advised": [c["model"] + (":" + c["effort"] if c.get("effort") else "") for c in offered],
                                   "actual": [m["model"] + (":" + m["effort"] if m.get("effort") else "") for m in actual], "kind": "model"})
        return
    efforts = {(c["model"], c.get("effort")) for c in offered if c.get("effort")}
    for m in actual:
        if m.get("effort") and efforts and not any(_matches(cm, m["model"]) and ce == m["effort"] for cm, ce in efforts):
            result["mismatch"].append({"platform": row["platform"], "agent_id": row.get("agent_id"),
                                       "advised": [c["model"] + (":" + c["effort"] if c.get("effort") else "") for c in offered],
                                       "actual": [m["model"] + ":" + m["effort"]], "kind": "effort"})
            break
