"""What advising costs, next to what it saves (`mrh usage overhead`). Read-only: local database and transcripts, no network.

MRH stops a delegation and asks the main model to issue it again. For each such pair this measures:
- the classifier wait (the Pre hook held the delegation for this long) and its fee;
- the extra main-model request the re-issue needed (Claude only: the parent transcript records its input side;
  Codex does not record per-request parent usage, so it stays unknown);
- the sub-agent saving that followed (the same figure `mrh stats` shows), so the two can be set against each other.

Anything that cannot be known is reported as unknown, never as zero.
"""
from __future__ import annotations

import json
import statistics
from pathlib import Path

from mrh.advisory import pricing, usage_collect
from mrh.advisory.store import AdviceStore, _links
from mrh.application.classify import JEV_USD_PER_INPUT_TOKEN

_ANSWERED = ("returned", "late_returned")


def _classifier(attempts):
    """{request_id: {"seconds", "input_tokens"}} from the first start and first answer of each request."""
    started, answered = {}, {}
    for row in attempts:
        if row["outcome"] == "started":
            started.setdefault(row["request_id"], row["ts"])
        elif row["outcome"] in _ANSWERED:
            answered.setdefault(row["request_id"], row)
    result = {}
    for rid, row in answered.items():
        begin = started.get(rid)
        result[rid] = {"seconds": row["ts"] - begin if begin is not None and row["ts"] >= begin else None,
                       "input_tokens": row.get("input_tokens")}
    return result


def _entry(usage):
    """One assistant message's request as a price-table entry. Claude's transcript has no final output, so output is unknown."""
    inp = usage.get("input_tokens")
    read = usage.get("cache_read_input_tokens")
    written = usage.get("cache_creation_input_tokens")
    split = usage.get("cache_creation")
    if not all(usage_collect._n(v) is not None for v in (inp, read, written)):
        return None
    if written == 0:
        w5 = w1 = 0
    elif isinstance(split, dict) and all(usage_collect._n(split.get(k)) is not None for k in ("ephemeral_5m_input_tokens", "ephemeral_1h_input_tokens")):
        w5, w1 = split["ephemeral_5m_input_tokens"], split["ephemeral_1h_input_tokens"]
        if w5 + w1 > written:
            return None
    else:
        w5 = w1 = None      # a cache write without a TTL split has no price
    parts = {"input": inp, "cache_write_5m": w5, "cache_write_1h": w1,
             "cache_write": None if w5 is None else written - w5 - w1, "cache_read": read}
    bucket = "large" if inp + read + written > usage_collect.LARGE_PROMPT else "small"
    other = "small" if bucket == "large" else "large"
    blank = {name: 0 for name in usage_collect._FIELDS}
    return {"requests": 1, "output": None, "reasoning": None, bucket: parts, other: blank,
            "max_request_input": inp + read + written}


def parent_requests(root, session_id, call_ids):
    """{call_id: (model, entry)}: the parent message that made each call, taken from the Claude transcript."""
    wanted, found = set(call_ids), {}
    if not usage_collect._ID.fullmatch(session_id or ""):
        return found
    for path in sorted(Path(root).glob(f"*/{session_id}.jsonl")):
        try:
            for line in usage_collect._lines(path):
                if "tool_use" not in line or not any(c in line for c in wanted):
                    continue
                try:
                    message = (json.loads(line) or {}).get("message") or {}
                except ValueError:
                    continue
                model, usage = message.get("model"), message.get("usage")
                if not isinstance(model, str) or model.startswith("<") or not isinstance(usage, dict):
                    continue
                for block in message.get("content") or []:
                    if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("id") in wanted:
                        entry = _entry(usage)
                        if entry is not None:
                            found.setdefault(block["id"], (model, entry))
        except (OSError, ValueError):
            continue
        if wanted <= set(found):
            break
    return found


def _median(values):
    values = [v for v in values if v is not None]
    return statistics.median(values) if values else None


def build(path, since, *, claude_root=None, now=None):
    """The overhead report for everything recorded since `since`."""
    advice, attempts, children, usage_rows = AdviceStore.read_overhead(path, since)
    claude_root = Path(claude_root) if claude_root else usage_collect.roots()[0]
    links = _links(advice)
    classifier = _classifier(attempts)
    by_id = {r["request_id"]: r for r in advice}
    saved = {}
    for row in usage_rows:
        if row["advice_request_id"] and row["followed"]:
            try:
                usage = json.loads(row["usage"])
            except ValueError:
                continue
            saved[row["advice_request_id"]] = pricing.saving(usage, row.get("parent_model"))
    claude_calls = {}
    for replacement_id, (original, _) in links.items():
        reissue = by_id[replacement_id]
        if reissue["platform"] == "claude":
            claude_calls.setdefault(reissue["session_id"], []).append(reissue["call_id"])
    requests = {}
    for session_id, call_ids in claude_calls.items():
        requests.update({(session_id, k): v for k, v in parent_requests(claude_root, session_id, call_ids).items()})

    pairs = []
    for replacement_id, (original, _) in sorted(links.items(), key=lambda item: item[1][0]["ts"]):
        reissue = by_id[replacement_id]
        wait = classifier.get(original["request_id"], {})
        tokens = wait.get("input_tokens")
        item = {"platform": original["platform"], "tier": original["tier"], "ts": original["ts"],
                "classifier_seconds": wait.get("seconds"),
                "classifier_usd": tokens * JEV_USD_PER_INPUT_TOKEN if isinstance(tokens, int) else None,
                "deny_to_reissue_seconds": reissue["ts"] - original["ts"],
                "main_model": None, "main_extra_input_usd": None, "main_extra_unknown": None,
                "saving_usd": None, "saving_scope": None, "saving_unknown": None}
        if original["platform"] == "claude":
            found = requests.get((reissue["session_id"], reissue["call_id"]))
            if found:
                model, entry = found
                priced = pricing.price_entry(model, entry)
                item["main_model"] = model
                item["main_extra_input_usd"] = priced["input_side"]
                if priced["input_side"] is None:
                    item["main_extra_unknown"] = (priced["unknown"] or ["價格不完整"])[0]
            else:
                item["main_extra_unknown"] = "在父對話紀錄找不到這次重派的請求"
        else:
            item["main_extra_unknown"] = "Codex 的父層紀錄沒有逐請求用量"
        gain = saved.get(original["request_id"])
        if gain is not None:
            item["saving_usd"], item["saving_scope"], item["saving_unknown"] = gain["usd"], gain["scope"], gain["reason"]
        else:
            item["saving_unknown"] = "這次重派的子代理還沒收集用量（mrh usage collect）"
        pairs.append(item)

    def known(key):
        return [p[key] for p in pairs if p[key] is not None]

    both = [p for p in pairs if p["main_extra_input_usd"] is not None and p["saving_usd"] is not None and p["saving_scope"] == "輸入端"]
    reasons = {}
    for row in advice:
        reasons[row["reason"]] = reasons.get(row["reason"], 0) + 1
    advised = reasons.get("advice_given", 0)
    delegations = sum(1 for r in advice if r["reason"] != "advice_reissue")
    return {
        "since": since, "delegations": delegations, "advised": advised,
        "advised_share": advised / delegations if delegations else None,
        "reissues": len(pairs), "advised_not_reissued": max(advised - len(pairs), 0),
        "classifier_seconds_total": sum(known("classifier_seconds")) if known("classifier_seconds") else None,
        "classifier_seconds_median": _median(known("classifier_seconds")),
        "classifier_usd_total": sum(known("classifier_usd")) if known("classifier_usd") else None,
        "deny_to_reissue_seconds_median": _median(known("deny_to_reissue_seconds")),
        "main_extra_known": len(known("main_extra_input_usd")),
        "main_extra_input_usd_total": sum(known("main_extra_input_usd")) if known("main_extra_input_usd") else None,
        "saving_known": len(known("saving_usd")),
        "saving_usd_total": sum(known("saving_usd")) if known("saving_usd") else None,
        "compared": len(both),
        "compared_saving_usd": sum(p["saving_usd"] for p in both),
        "compared_overhead_usd": sum(p["main_extra_input_usd"] + (p["classifier_usd"] or 0.0) for p in both),
        "compared_net_positive": sum(p["saving_usd"] > p["main_extra_input_usd"] + (p["classifier_usd"] or 0.0) for p in both),
        "reasons": reasons, "pairs": pairs,
    }
