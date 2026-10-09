"""Small, dependency-free terminal presentation helpers for MRH."""

from __future__ import annotations

import json
import math
import re
import shutil
import textwrap
import unicodedata
from collections.abc import Mapping
from typing import Any


_ANSI = re.compile(
    r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\)|"
    r"[P^_].*?\x1b\\|[@-_])",
    re.DOTALL,
)
_TIER_ORDER = ("Light", "Small", "Mid", "Top")
_TIER_ANSI = {
    "Light": "\x1b[38;5;110m",
    "Small": "\x1b[38;5;75m",
    "Mid": "\x1b[38;5;177m",
    "Top": "\x1b[38;5;220m",
}
_ACCENT = "\x1b[38;5;81m"
_MUTED = "\x1b[38;5;245m"
_BOLD = "\x1b[1m"
_RESET = "\x1b[0m"


def terminal_width(fallback: int = 80) -> int:
    """Return a useful width even when stdout is redirected."""
    return shutil.get_terminal_size(fallback=(fallback, 24)).columns


def sanitize_text(value: Any) -> str:
    """Remove terminal escapes and control/format characters from display text."""
    raw = _ANSI.sub("", str(value))
    cleaned: list[str] = []
    for char in raw:
        category = unicodedata.category(char)
        if category in {"Cc", "Cf", "Cs"}:
            if char in "\n\r\t":
                cleaned.append(" ")
            continue
        if category in {"Zl", "Zp"}:
            cleaned.append(" ")
            continue
        cleaned.append(char)
    return "".join(cleaned)


def _width(width: int | None) -> int:
    if width is None:
        width = terminal_width()
    try:
        return max(24, int(width))
    except (TypeError, ValueError):
        return 80


def _wrap(value: Any, width: int, indent: str = "") -> list[str]:
    text = sanitize_text(value)
    if not text:
        text = "—"
    return textwrap.wrap(
        text,
        width=max(8, width - len(indent)),
        initial_indent=indent,
        subsequent_indent=indent,
        break_long_words=True,
        break_on_hyphens=False,
        replace_whitespace=True,
        drop_whitespace=True,
    ) or [indent]


def _value(value: Any) -> str:
    if value is None:
        return "Unavailable"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, Mapping):
        if not value:
            return "None recorded"
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    if isinstance(value, (list, tuple)):
        if not value:
            return "None recorded"
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
    return str(value)


def _count(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    if not math.isfinite(value) or value < 0:
        return 0
    return int(value)


def _color(text: str, code: str, enabled: bool) -> str:
    return f"{code}{text}{_RESET}" if enabled else text


def _mapping_lines(value: Any, width: int) -> list[str]:
    if not isinstance(value, Mapping) or not value:
        return ["  None recorded"]
    lines: list[str] = []
    for key in sorted(value, key=lambda item: sanitize_text(item).casefold()):
        label = sanitize_text(key)
        lines.extend(_wrap(f"{label}: {_value(value[key])}", width, "  "))
    return lines


def _bar_segments(counts: list[int], width: int) -> list[int]:
    total = sum(counts)
    if total <= 0 or width <= 0:
        return [0] * len(counts)
    exact = [count * width / total for count in counts]
    sizes = [math.floor(part) for part in exact]
    remainder = width - sum(sizes)
    order = sorted(range(len(counts)), key=lambda index: (exact[index] - sizes[index], -index), reverse=True)
    for index in order[:remainder]:
        sizes[index] += 1
    return sizes


def render_stats(
    stats: Mapping[str, Any],
    *,
    width: int | None = None,
    color: bool = False,
) -> str:
    """Render the Store.stats object without adding or changing statistics."""
    columns = _width(width)
    partition = sanitize_text(stats.get("partition", "live")).upper() or "LIVE"
    title = f"MRH  /  {partition} event statistics"
    lines: list[str] = []
    lines.extend(_wrap(title, columns))
    lines.extend(_wrap(f"Updated: {_value(stats.get('updated_at'))}", columns))
    lines.append(_color("━" * columns, _MUTED, color))

    sections: list[tuple[str, list[str]]] = [
        (
            "ACTIVITY",
            [
                f"Proposals: {_value(stats.get('proposals'))}",
                f"Jev request attempts: {_value(stats.get('jev_attempts'))}",
                f"Synthetic attempts: {_value(stats.get('synthetic_attempts'))}",
                f"Classified tasks: {_value(stats.get('classified_tasks'))}",
                f"Low-confidence tasks: {_value(stats.get('low_confidence_tasks'))}",
            ],
        ),
        (
            "TIER COMPOSITION",
            [],
        ),
        ("POLICY OUTCOMES", []),
        ("REQUESTED MODELS", []),
        (
            "CHILD EXECUTION",
            [
                f"Confirmed children: {_value(stats.get('confirmed_children'))}",
                f"Simulated children: {_value(stats.get('simulated_children'))}",
                f"Reported children: {_value(stats.get('reported_children'))}",
                f"Children with unknown actual model: {_value(stats.get('unknown_actual_model_children'))}",
            ],
        ),
        ("ACTUAL MODELS", []),
        (
            "COST / USAGE",
            [
                f"Cost: {_value(stats.get('cost'))}",
                f"Tokens: {_value(stats.get('tokens'))}",
                f"Quota: {_value(stats.get('quota'))}",
            ],
        ),
        ("CAPABILITIES", []),
    ]

    for heading, entries in sections:
        lines.append("")
        lines.append(_color(heading, _ACCENT, color))
        if heading == "TIER COMPOSITION":
            tiers = stats.get("tiers")
            tiers = tiers if isinstance(tiers, Mapping) else {}
            counts = [_count(tiers.get(tier, 0)) for tier in _TIER_ORDER]
            total = sum(counts)
            if total == 0:
                lines.append("  No tier classifications yet")
            else:
                bar_width = max(8, min(28, columns - 10))
                sizes = _bar_segments(counts, bar_width)
                bar_parts = [
                    _color("█" * size, _TIER_ANSI[tier], color)
                    for tier, size in zip(_TIER_ORDER, sizes)
                    if size
                ]
                lines.append("  " + "".join(bar_parts))
                labels = "   ".join(f"{tier} {count}" for tier, count in zip(_TIER_ORDER, counts))
                lines.extend(_wrap(f"{total} classified tasks · {labels}", columns, "  "))
            continue
        if heading == "POLICY OUTCOMES":
            lines.extend(_mapping_lines(stats.get("outcomes"), columns))
            continue
        if heading == "REQUESTED MODELS":
            lines.extend(_mapping_lines(stats.get("requested_models"), columns))
            continue
        if heading == "ACTUAL MODELS":
            lines.extend(_mapping_lines(stats.get("actual_models"), columns))
            continue
        if heading == "CAPABILITIES":
            lines.extend(_mapping_lines(stats.get("capabilities"), columns))
            continue
        for entry in entries:
            lines.extend(_wrap(entry, columns, "  "))

    lines.append("")
    return "\n".join(lines)


def render_report(
    title: str,
    sections: Mapping[str, Any],
    *,
    width: int | None = None,
    color: bool = False,
) -> str:
    """Render a sanitized, sectioned report for doctor and config preview."""
    columns = _width(width)
    lines = _wrap(title, columns)
    lines.append(_color("━" * columns, _MUTED, color))
    for heading, body in sections.items():
        lines.append("")
        lines.append(_color(sanitize_text(heading).upper(), _ACCENT, color))
        if isinstance(body, Mapping):
            lines.extend(_mapping_lines(body, columns))
        elif isinstance(body, (list, tuple)):
            for item in body:
                lines.extend(_wrap(item, columns, "  "))
        else:
            lines.extend(_wrap(body, columns, "  "))
    lines.append("")
    return "\n".join(lines)
