"""Turning measured tokens into dollars, with the source of every price and an honest "unknown".

Prices are the vendors' published list prices per million tokens, copied from the pages named below on the date shown. They are
list prices, not the user's bill (a subscription is billed differently). A price that is not here is `None`, and any amount that
needs it is unknown, never zero and never estimated.

Savings compare what the sub-agent's tokens cost on the model it actually used with what the same tokens would cost on the
parent (main) model. That rests on one stated assumption: the parent would have used the same number of tokens for the same work.
"""
from __future__ import annotations

import re

from mrh.advisory.usage_collect import MIXED, _n

CHECKED = "2026-10-16"
CLAUDE_URL = "https://platform.claude.com/docs/en/about-claude/pricing"
OPENAI_URL = "https://developers.openai.com/api/docs/pricing"
CODEX_LONG_CONTEXT = 272_000      # OpenAI prices requests above this many input tokens separately; that tier is not recorded here
INPUT_SIDE = ("input", "cache_write_5m", "cache_write_1h", "cache_write", "cache_read")


def _claude(inp, w5, w1, read, out):
    return {"input": inp, "cache_write_5m": w5, "cache_write_1h": w1, "cache_write": None, "cache_read": read, "output": out}


def _openai(inp, read, write, out):
    return {"input": inp, "cache_write_5m": None, "cache_write_1h": None, "cache_write": write, "cache_read": read, "output": out}


# USD per million tokens. A Claude cache write without a recorded 5-minute/1-hour split has no price (None): the TTL decides it.
PRICES = {
    "claude-opus-5-5": {"source": CLAUDE_URL, "small": _claude(4, 5, 8, 0.20, 20)},
    "claude-sonnet-5-5": {"source": CLAUDE_URL, "small": _claude(2, 2.5, 4, 0.10, 10)},
    "claude-fable-5-1": {"source": CLAUDE_URL, "small": _claude(10, 12.5, 20, 0.25, 50)},
    # Haiku 5.5 is priced per request by prompt length (input + cache writes + cache reads): <= 100K or > 100K.
    "claude-haiku-5-5": {"source": CLAUDE_URL, "small": _claude(0.10, 0.125, 0.20, 0.01, 0.50),
                         "large": _claude(0.50, 0.625, 1.0, 0.05, 2.50)},
    "gpt-6-luna": {"source": OPENAI_URL, "small": _openai(0.10, 0.01, 0.125, 0.50)},
    "gpt-6.1-sol": {"source": OPENAI_URL, "small": _openai(2.00, 0.10, 2.50, 10.00)},
    "gpt-6-astra": {"source": OPENAI_URL, "small": _openai(10.00, 1.00, 12.50, 50.00)},
}


def key(model):
    """The price-table key of a model id: a trailing context suffix such as `[1m]` is not part of the identity."""
    return re.sub(r"\[[^\]]*\]$", "", model) if isinstance(model, str) else None


def known(model):
    return key(model) in PRICES


def _rate(model, field, bucket):
    table = PRICES[key(model)]
    return (table.get(bucket) or table["small"]).get(field)


def price_entry(model, entry):
    """Cost of one model's tokens: {"input_side": usd|None, "output": usd|None, "unknown": [reasons]}.

    A zero token count costs zero whatever the price; a non-zero count with no price makes that part unknown."""
    if model == MIXED:
        return {"input_side": None, "output": None, "unknown": ["同一個子代理用了多個模型，無法分開計價"]}
    if not known(model):
        return {"input_side": None, "output": None, "unknown": [f"沒有官方價格：{model}"]}
    length = _n(entry.get("max_request_input"))
    if key(model).startswith("gpt-") and length is None:
        return {"input_side": None, "output": None, "unknown": ["單次請求輸入長度未知，無法確認價格分檔"]}
    if key(model).startswith("gpt-") and length > CODEX_LONG_CONTEXT:
        return {"input_side": None, "output": None, "unknown": [f"單次請求超過 {CODEX_LONG_CONTEXT // 1000}K 輸入，長上下文價格未收錄"]}
    unknown, side = [], 0.0
    for bucket in ("small", "large"):
        for field in INPUT_SIDE:
            tokens = _n((entry.get(bucket) or {}).get(field))
            if tokens is None:
                unknown.append(f"用量未知：{bucket}.{field}")
                continue
            if tokens == 0:
                continue
            rate = _rate(model, field, bucket)
            if rate is None:
                unknown.append(f"沒有價格：{field}（{tokens:,} tokens）")
            else:
                side += tokens * rate / 1_000_000
    output = _n(entry.get("output"))
    out_usd = None if output is None else output * PRICES[key(model)]["small"]["output"] / 1_000_000
    output_reason = "輸出 token 未知" + ("（Claude 紀錄不含最終輸出量）" if key(model).startswith("claude-") else "")
    return {"input_side": None if unknown else side, "output": out_usd,
            "unknown": unknown + ([output_reason] if output is None else [])}


def price_child(usage):
    """Sum over the models a sub-agent used. input_side is None if any part is unknown; output likewise; total needs both."""
    if not usage:
        return {"input_side": None, "output": None, "total": None, "unknown": ["沒有用量快照"]}
    side = out = 0.0
    side_ok = out_ok = True
    reasons = []
    for model, entry in usage.items():
        part = price_entry(model, entry)
        reasons += part["unknown"]
        side_ok &= part["input_side"] is not None
        out_ok &= part["output"] is not None
        side += part["input_side"] or 0.0
        out += part["output"] or 0.0
    return {"input_side": side if side_ok else None, "output": out if out_ok else None,
            "total": side + out if side_ok and out_ok else None, "unknown": sorted(set(reasons))}


def saving(usage, parent_model):
    """What the same tokens would have cost on the parent model minus what they cost, or why it cannot be said.

    Claude: input side only (its output is unknown). Codex: input and output, since Codex reports the final output."""
    if not parent_model:
        return {"usd": None, "scope": None, "reason": "不知道主模型"}
    if not known(parent_model):
        return {"usd": None, "scope": None, "reason": f"主模型沒有官方價格：{parent_model}"}
    if any(known(m) and key(m).startswith("claude-") != key(parent_model).startswith("claude-") for m in usage):
        return {"usd": None, "scope": None, "reason": "主模型與子代理不是同一個平台，不比較"}
    actual = price_child(usage)
    include_output = all(entry.get("output") is not None for entry in usage.values())
    swapped = {parent_model: _merge(usage)}
    baseline = price_child(swapped)
    if actual["input_side"] is None or baseline["input_side"] is None:
        return {"usd": None, "scope": None, "reason": (actual["unknown"] + baseline["unknown"] or ["價格不完整"])[0]}
    if include_output and (actual["output"] is None or baseline["output"] is None):
        return {"usd": None, "scope": None, "reason": "輸出價格不完整"}
    spent = actual["input_side"] + (actual["output"] if include_output else 0.0)
    would = baseline["input_side"] + (baseline["output"] if include_output else 0.0)
    return {"usd": would - spent, "scope": "輸入＋輸出" if include_output else "輸入端", "reason": None}


def _merge(usage):
    """All of a sub-agent's tokens as one entry, to price them at a single (parent) model's rates."""
    entries = list(usage.values())
    def add(values):
        return None if not values or any(_n(v) is None for v in values) else sum(values)
    lengths = [e.get("max_request_input") for e in entries]
    return {"requests": add([e.get("requests") for e in entries]),
            "output": add([e.get("output") for e in entries]),
            "reasoning": add([e.get("reasoning") for e in entries]),
            "max_request_input": max(lengths) if lengths and all(_n(n) is not None for n in lengths) else None,
            **{bucket: {f: add([(e.get(bucket) or {}).get(f) for e in entries]) for f in INPUT_SIDE}
               for bucket in ("small", "large")}}
