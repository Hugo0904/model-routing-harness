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
_TIER_GLYPH = {"Light": "·", "Small": "░", "Mid": "▒", "Top": "█"}
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
    active = [index for index, count in enumerate(counts) if count > 0]
    width = max(width, len(active))
    exact = [count * (width - len(active)) / total for count in counts]
    sizes = [math.floor(part) + (1 if counts[index] > 0 else 0) for index, part in enumerate(exact)]
    remainder = width - sum(sizes)
    order = sorted(range(len(counts)), key=lambda index: (exact[index] - math.floor(exact[index]), -index), reverse=True)
    for index in order[:remainder]:
        sizes[index] += 1
    return sizes


def _mapping_field(label: str, value: Any, width: int) -> list[str]:
    prefix = f"  {label}:"
    if not isinstance(value, Mapping):
        return _wrap(f"{prefix} Unavailable", width)
    if not value:
        return _wrap(f"{prefix} None recorded", width)
    lines = _wrap(prefix, width)
    for key in sorted(value, key=lambda item: sanitize_text(item).casefold()):
        lines.extend(_wrap(f"{sanitize_text(key)}: {_value(value[key])}", width, "    "))
    return lines


def _jev_telemetry_lines(jev: Any, width: int) -> list[str]:
    telemetry = jev if isinstance(jev, Mapping) else {}
    lines: list[str] = []
    lines.extend(_wrap(f"  Source: {_value(telemetry.get('source'))}", width))
    lines.extend(_mapping_field("Attempt states", telemetry.get("attempt_states"), width))
    lines.extend(_mapping_field("Requested Jev model versions", telemetry.get("requested_models"), width))
    lines.extend(_mapping_field("Returned Jev model versions", telemetry.get("response_models"), width))
    for key, label in (
        ("input_tokens", "Input token total"),
        ("output_tokens", "Output token total"),
        ("known_input_tokens", "Known input tokens"),
        ("known_output_tokens", "Known output tokens"),
        ("usage_unavailable_attempts", "Attempts with unavailable usage"),
    ):
        lines.extend(_wrap(f"  {label}: {_value(telemetry.get(key))}", width))

    cost = telemetry.get("estimated_cost")
    if not isinstance(cost, Mapping):
        lines.extend(_wrap("  Estimated Jev cost: Unavailable", width))
    else:
        amount = _value(cost.get("amount"))
        currency = _value(cost.get("currency"))
        unit = _value(cost.get("unit"))
        lines.extend(_wrap(f"  Estimated Jev cost: {amount} {currency} ({unit})", width))
        lines.extend(_wrap("  Cost type: Estimate", width))
        lines.extend(_wrap(f"  Estimate model: {_value(cost.get('model'))}", width))
        lines.extend(_wrap(f"  Price source: {_value(cost.get('price_source'))}", width))
        lines.extend(_wrap(f"  Price date: {_value(cost.get('price_date'))}", width))
    return lines


def _share(count: int, total: int) -> str:
    percentage = count * 100 / total
    if count > 0 and percentage < 0.05:
        return "<0.1%"
    return f"{percentage:.1f}%"


def render_details(
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
        ("JEV TELEMETRY", []),
        ("HANDBACK ANOMALIES", [f"Recorded anomaly count: {_value(stats.get('handback_anomalies'))}",
                               f"Evidence: {_value(stats.get('handback_anomaly_evidence'))}"]),
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
                    _color(_TIER_GLYPH[tier] * size, _TIER_ANSI[tier], color)
                    for tier, size in zip(_TIER_ORDER, sizes)
                    if size
                ]
                lines.append("  " + "|".join(bar_parts))
                lines.extend(_wrap(f"{total} classified tasks", columns, "  "))
                for tier, count in zip(_TIER_ORDER, counts):
                    lines.extend(_wrap(f"{tier} {count} ({_share(count, total)})", columns, "  "))
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
        if heading == "JEV TELEMETRY":
            lines.extend(_jev_telemetry_lines(stats.get("jev"), columns))
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


# The dashboard owns presentation only. The detailed view and JSON retain every
# recorded field; absent quota/configuration is never inferred from event counts.
_BG = "\x1b[48;2;35;38;45m"
_FG = "\x1b[38;2;239;240;246m"
_DIM = "\x1b[38;2;155;158;171m"
_EDGE = "\x1b[38;2;76;80;94m"
_LAVENDER = "\x1b[38;2;173;178;250m"
_PALETTE = ("\x1b[38;2;142;150;198m", "\x1b[38;2;107;117;219m",
            "\x1b[38;2;173;178;250m", "\x1b[38;2;226;226;253m")


def cell_width(text: str) -> int:
    return sum(0 if unicodedata.combining(c) else
               2 if unicodedata.east_asian_width(c) in {"W", "F"} else 1
               for c in _ANSI.sub("", text))


def _fit(value: Any, size: int) -> str:
    text = sanitize_text(value)
    if cell_width(text) > size:
        clipped = ""
        for c in text:
            if cell_width(clipped + c) > size - 1:
                break
            clipped += c
        text = clipped + "…"
    return text + " " * max(0, size - cell_width(text))


def policy_rows(policy: Mapping[str, Any]) -> list[tuple[str, str]]:
    """Current targets; Top follows mode/fixed, never the legacy tiers.Top."""
    def target(mapping):
        return (f"{mapping['model']} / {mapping.get('effort', 'inherit')}" if mapping
                else "Unset / preserve original")
    rows = [(tier, target(policy.get("tiers", {}).get(tier))) for tier in _TIER_ORDER[:3]]
    rows.append(("Top", "Fixed / " + target(policy.get("fixed")) if policy.get("top_mode", "Main") == "Fixed"
                 else "Main / current main agent"))
    return rows


def _configuration_lines(configuration: Mapping[str, Any], width: int) -> list[str]:
    lines = _wrap("Jev chooses the tier. You choose the model and effort.", width)
    lines += [""]
    for tier, target in policy_rows(configuration["policy"]):
        lines += _wrap(f"{tier}: {target}", width)
    lines += [""] + _wrap(
        f"Routing requested: {'On' if configuration['enabled'] else 'Off'} / "
        f"Task export: {'Allowed' if configuration['task_export_permitted'] else 'Blocked'}", width)
    lines += _wrap("inherit uses the host's effort. Unset keeps the original delegation.", width)
    return lines


def _policy_frame(title: str, contents: list[str], *, width: int | None, color: bool) -> str:
    columns = min(140, _width(width))
    inner = columns - 4
    lines = ["", "MRH  /  MODEL POLICY", "", title, ""] + contents + [""]
    fitted = ["  " + _fit(line, inner) + "  " for line in lines]
    if color:
        return "\n".join(_BG + (_LAVENDER if index in (1, 3) else _FG) + line + _RESET
                         for index, line in enumerate(fitted)) + "\n"
    return "\n".join(fitted) + "\n"


def render_configuration(configuration: Mapping[str, Any], *, width: int | None = None, color: bool = False) -> str:
    inner = min(140, _width(width)) - 4
    contents = [f"Revision {configuration['revision']}", ""] + _configuration_lines(configuration, inner)
    contents += [""] + _wrap("Configured requests do not confirm model availability or execution.", inner)
    return _policy_frame("CURRENT CONFIGURATION", contents, width=width, color=color)


def render_policy_review(changes: list[str], *, width: int | None = None, color: bool = False) -> str:
    inner = min(140, _width(width)) - 4
    contents = ["BEFORE -> AFTER", ""]
    for change in changes or ["No policy changes."]:
        contents += _wrap(change, inner)
    contents += [""] + _wrap("Routing and task-sharing permissions stay as they are.", inner)
    return _policy_frame("REVIEW POLICY CHANGES", contents, width=width, color=color)


def render_stats(stats: Mapping[str, Any], *, width: int | None = None,
                 color: bool = False, details: bool = False,
                 demo_policy: Mapping[str, Any] | None = None,
                 configuration: Mapping[str, Any] | None = None) -> str:
    """Compact, width-aware dashboard over unchanged statistics.

    Current settings and historical events are separate observations. Demo
    examples cannot be combined with an operator's actual configuration.
    """
    if configuration is not None and demo_policy is not None:
        raise ValueError("conflicting_policy_sources")
    if details:
        return (render_configuration(configuration, width=width, color=color) if configuration is not None else "") + render_details(stats, width=width, color=color)
    columns = min(140, _width(width))
    inner = columns - 4
    synthetic = stats.get("partition") == "synthetic"
    policy = demo_policy if synthetic else None
    history_label = ("SYNTHETIC DEMO  ·  isolated examples / no live calls" if policy is not None else
                     "SYNTHETIC HISTORY  ·  isolated recorded events" if synthetic else
                     "LOCAL EVENTS  ·  all recorded history")

    def ink(text: str, tone: str = _FG, bold: bool = False) -> str:
        return (tone + ("\x1b[1m" if bold else "") + text +
                "\x1b[22m" + _FG) if color else text

    def row(text: str = "") -> str:
        # All variable text is sanitized before it reaches styled spans.
        padded = text + " " * max(0, inner - cell_width(text))
        return "  " + padded + "  "

    def box(title: str, contents: list[str], size: int) -> list[str]:
        label = _fit(title, size - 6).rstrip()
        top = ink("╭─ ", _EDGE) + ink(label, _DIM) + ink(" " + "─" * (size - 5 - cell_width(label)) + "╮", _EDGE)
        return [top] + [ink("│", _EDGE) + " " + item +
               " " * max(0, size - 3 - cell_width(item)) + ink("│", _EDGE)
               for item in contents] + [ink("╰" + "─" * (size - 2) + "╯", _EDGE)]

    lines = [row(), row(ink(_fit("MRH  /  DELEGATION ROUTER", inner), _LAVENDER, True)),
             row(), row(ink(_fit("Route each task. Keep the big picture.", inner), bold=True)),
             row(ink(_fit(history_label, inner), _DIM)),
             row(ink(_fit("Updated: " + _value(stats.get("updated_at")), inner), _DIM)), row()]
    lines.append(row(ink(_fit("01  HOW A DELEGATION IS ROUTED", inner), _LAVENDER)))
    lines.append(row())
    stages = [("Orchestrator", "Writes the task brief"), ("Jev", "Classifies complexity"),
              ("Tier", "Light Small Mid Top"), ("Model", "Selected by policy")]
    if inner >= 96:
        size = (inner - 9) // 4
        cards = [box(name, [ink(_fit(desc, size - 4), _DIM)], size) for name, desc in stages]
        for index in range(3):
            lines.append(row((" → " if index == 1 else "   ").join(card[index] for card in cards)))
    else:
        for index, (name, desc) in enumerate(stages, 1):
            lines.append(row(ink(_fit(f"{index}. {name}  /  {desc}", inner), _DIM)))
    lines.append(row())
    lines.append(row(ink(_fit("CURRENT CONFIGURATION" if configuration is not None else
                                    "TIER POLICY  /  demo examples" if policy else
                                    "TIER POLICY  /  configuration not loaded", inner), _DIM)))
    counts = [_count((stats.get("tiers") or {}).get(tier)) for tier in _TIER_ORDER]
    total = sum(counts)
    if configuration is not None:
        lines.extend(row(ink(line)) for line in _configuration_lines(configuration, inner))
    elif inner >= 70:
        model_size = inner - 39
        lines.append(row(ink("  " + _fit("TIER", 10) + _fit("MODEL / EFFORT", model_size) +
                            _fit("TASKS", 9) + _fit("SHARE", 9) + "SOURCE", _DIM)))
        lines.append(row(ink("─" * inner, _EDGE)))
        for i, tier in enumerate(_TIER_ORDER):
            mapping = policy.get("tiers", {}).get(tier, {}) if policy else {}
            model = f"{mapping.get('model')} / {mapping.get('effort')}" if mapping else "Unavailable"
            if policy and tier == "Top":
                model = "Main / Fixed (per example)"
            line = "▏ " if tier == "Top" else "  "
            line += _fit(tier, 10) + _fit(model, model_size) + _fit(counts[i], 9)
            line += _fit(_share(counts[i], total) if total else "—", 9) + ("Demo" if policy else "Unknown")
            lines.append(row(ink(line, _LAVENDER if tier == "Top" else _FG, tier == "Top")))
    else:
        for i, tier in enumerate(_TIER_ORDER):
            share = _share(counts[i], total) if total else "—"
            lines.append(row(ink(_fit(f"{tier:<6} {counts[i]:>4} tasks  {share}", inner),
                                 _LAVENDER if tier == "Top" else _FG)))
            mapping = policy.get("tiers", {}).get(tier, {}) if policy else {}
            model = f"{mapping.get('model')} / {mapping.get('effort')}" if mapping else "Unavailable"
            if policy and tier == "Top":
                model = "Main / Fixed (per example)"
            lines.append(row(ink(_fit("  " + model, inner), _DIM)))
    lines.append(row())
    lines.extend(row(ink(item, _DIM)) for item in _wrap(
        "Current targets are separate from historical counts and confirmed execution." if configuration is not None else
        "Policy selects a request; confirmed execution is recorded separately.", inner))
    lines.append(row())

    panel_size = (inner - 3) // 2 if inner >= 90 else inner
    content_size = panel_size - 4
    bar_width = content_size - 3
    sizes = _bar_segments(counts, bar_width)
    bar = "│".join(ink(("█" if color else _TIER_GLYPH[tier]) * n, _PALETTE[i]) for i, (tier, n) in
                    enumerate(zip(_TIER_ORDER, sizes))) if total else ink("░" * content_size, _EDGE)
    composition = [ink(_fit(f"{total} classified tasks", content_size), bold=True), "", bar, ""]
    for i, tier in enumerate(_TIER_ORDER):
        label = f"{tier} {counts[i]} ({_share(counts[i], total)})" if total else f"{tier} 0 (—)"
        composition.append(ink(_fit(label, content_size), _PALETTE[i]))
    quota = [ink(_fit("Quota: " + _value(stats.get("quota")), content_size), bold=True),
             ink(_fit("Reset: Unavailable", content_size), _DIM), "",
             ink(_fit("Cost: " + _value(stats.get("cost")), content_size)),
             ink(_fit("Tokens: " + _value(stats.get("tokens")), content_size)), "",
             ink(_fit(("No quota source is connected." if stats.get("quota") is None else "Quota as recorded in event data."), content_size), _DIM),
             ink(_fit("Unavailable does not mean zero.", content_size), _DIM)]
    left, right = box("TIER COMPOSITION", composition, panel_size), box("USAGE / QUOTA", quota, panel_size)
    if inner >= 90:
        lines.extend(row(a + "   " + b) for a, b in zip(left, right))
    else:
        lines.extend(row(a) for a in left)
        lines.append(row())
        lines.extend(row(b) for b in right)
    lines.append(row())
    activity = (f"Proposals {_value(stats.get('proposals'))}   ·   "
                f"Confirmed children {_value(stats.get('confirmed_children'))}   ·   "
                f"Low confidence {_value(stats.get('low_confidence_tasks'))}")
    for item in _wrap(activity, inner):
        lines.append(row(ink(item, _DIM)))
    lines.append(row(ink("─" * inner, _EDGE)))
    lines.extend(row(ink(item, _DIM)) for item in _wrap(
        "--details  full telemetry     --json  raw data     --plain  no color", inner))
    lines.append(row())
    if color:
        return "\n".join(_BG + _FG + line + _RESET for line in lines) + "\n"
    return "\n".join(lines) + "\n"
