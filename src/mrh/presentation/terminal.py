"""Terminal helpers for the control center: width, text sanitising, framed choice screens."""
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


_BG = "\x1b[48;2;35;38;45m"


_FG = "\x1b[38;2;239;240;246m"


_LAVENDER = "\x1b[38;2;173;178;250m"


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


def _cell_chunks(value: Any, width: int) -> list[str]:
    chunks, current = [], ""
    for char in sanitize_text(value):
        if cell_width(current + char) > width:
            chunks.append(current); current = ""
        current += char
    return chunks + [current]


def _policy_frame(title: str, contents: list[str], *, width: int | None, color: bool, heading: str = "MODEL POLICY", trail: list | None = None) -> str:
    columns = min(140, _width(width))
    inner = columns - 4
    head = ["", _fit("MRH  /  " + heading, inner)]
    if trail:
        head.append(_fit("路徑：" + " > ".join(str(t) for t in trail), inner))
    lines = head + ["", _fit(title, inner), ""] + contents + [""]
    accent = set(range(1, len(head))) | {len(head) + 1}
    fitted = ["  " + line + " " * max(0, inner - cell_width(line)) + "  " for line in lines]
    if color:
        return "\n".join(_BG + (_LAVENDER if index in accent else _FG) + line + _RESET
                         for index, line in enumerate(fitted)) + "\n"
    return "\n".join(fitted) + "\n"


def render_choices(title: str, entries: list[str], *, width: int, color: bool = False, heading: str = "MODEL POLICY", trail: list | None = None) -> str:
    """Numbered catalog choices share the current-policy frame and cell geometry."""
    inner = min(140, _width(width)) - 4
    contents = []
    for entry in entries:
        contents.extend(_cell_chunks(entry, inner))
    return _policy_frame(title, contents, width=width, color=color, heading=heading, trail=trail)
