"""Is a suggested sub-agent smaller than the main model? Smaller, not smaller, or unknown — never a guess.

Names only say whether two ids are the same model; which of two models is larger comes from the official list prices in
`pricing.PRICES` (input and output per million tokens), and within one model from the effort order. An unknown candidate is
kept: only a candidate that is known not to be smaller is dropped from the advice.
"""
from __future__ import annotations

import re

EFFORT_ORDER = ("low", "medium", "high", "xhigh", "max")
SMALLER, NOT_SMALLER, UNKNOWN = "smaller", "not_smaller", "unknown"
_CLAUDE_ID = re.compile(r"claude-([a-z]+)-(\d+(?:-\d+)*)")
_ALIAS = re.compile(r"[a-z]+")


def _key(model):
    from mrh.advisory import pricing     # deferred: pricing loads the usage collector, which only this path needs
    return pricing.key(model)


def _price(key):
    from mrh.advisory import pricing
    small = pricing.PRICES.get(key, {}).get("small") or {}
    inp, out = small.get("input"), small.get("output")
    return (inp, out) if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (inp, out)) else None


def _alias_price(alias):
    """The price of an alias such as `opus`: only when exactly one Claude entry of that family is listed."""
    from mrh.advisory import pricing
    keys = [k for k in pricing.PRICES if (m := _CLAUDE_ID.fullmatch(k)) and m.group(1) == alias]
    return _price(keys[0]) if len(keys) == 1 else None


def compare(candidate, main):
    """`candidate` is {"model", "effort"?}; `main` is (model id, effort) as read from the host."""
    main_key, main_effort = _key(main[0]), main[1]
    shape = _CLAUDE_ID.fullmatch(main_key or "")
    model = _key(candidate.get("model"))
    if shape is None or not model or main_effort not in EFFORT_ORDER:
        return UNKNOWN
    alias = _ALIAS.fullmatch(model) is not None
    if model == main_key or (alias and model == shape.group(1)):
        effort = candidate.get("effort")
        if effort not in EFFORT_ORDER:
            return UNKNOWN
        return SMALLER if EFFORT_ORDER.index(effort) < EFFORT_ORDER.index(main_effort) else NOT_SMALLER
    main_price = _price(main_key)                  # the exact id only: a sibling version's price is not borrowed
    mine = _alias_price(model) if alias else (_price(model) if _CLAUDE_ID.fullmatch(model) else None)
    if main_price is None or mine is None:
        return UNKNOWN
    (ci, co), (mi, mo) = mine, main_price
    if ci >= mi and co >= mo:
        return NOT_SMALLER
    if ci <= mi and co <= mo:
        return SMALLER
    return UNKNOWN


def below_main(candidates, main):
    """The candidates that are not known to be at or above the main model, in their original order."""
    return tuple(c for c in candidates if compare(c, main) != NOT_SMALLER)
