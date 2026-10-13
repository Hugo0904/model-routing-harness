from __future__ import annotations

import contextlib
import builtins
import io
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from mrh.presentation import cli
from mrh.presentation.terminal import render_stats, sanitize_text


SAMPLE_STATS = {
    "schema_version": 1,
    "updated_at": None,
    "partition": "live",
    "proposals": 0,
    "jev_attempts": 0,
    "synthetic_attempts": 0,
    "classified_tasks": 0,
    "low_confidence_tasks": 0,
    "tiers": {"Light": 0, "Small": 0, "Mid": 0, "Top": 0},
    "outcomes": {},
    "requested_models": {},
    "confirmed_children": 0,
    "actual_models": {},
    "unknown_actual_model_children": 0,
    "cost": None,
    "tokens": None,
    "quota": None,
    "capabilities": {
        "jev": "unavailable",
        "codex": "candidate_unverified",
        "claude": "unsupported",
        "gemini": "unsupported",
    },
}


def fake_module(name: str, **attrs: object) -> types.ModuleType:
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    return module


def forbid_store_imports():
    original = builtins.__import__

    def guarded(name, *args, **kwargs):
        if name == "mrh.infrastructure.store":
            raise AssertionError("this command must not import the event store")
        return original(name, *args, **kwargs)

    return patch("builtins.__import__", side_effect=guarded)


class TerminalTests(unittest.TestCase):
    def test_dashboard_fits_wide_narrow_and_unicode_and_keeps_detail_view(self) -> None:
        from mrh.presentation.terminal import cell_width
        stats = dict(SAMPLE_STATS, updated_at="範例標籤" * 30)
        for width in (24, 28, 48, 80, 100, 120, 140):
            for color in (False, True):
                rendered = render_stats(stats, width=width, color=color)
                self.assertTrue(all(cell_width(line) <= width for line in rendered.splitlines()), width)
        details = render_stats(stats, width=80, details=True)
        self.assertIn("ACTUAL MODELS", details)
        self.assertIn("JEV TELEMETRY", details)
        self.assertIn("Quota: Unavailable", render_stats(stats, width=120))
        self.assertNotIn("0%", render_stats(stats, width=120))

    def test_terminal_controls_are_removed(self) -> None:
        self.assertEqual(sanitize_text("\x1b[31mTop\x1b[0m\n\x00x\u202e"), "Top x")

    def test_tier_bar_is_a_composition_and_unavailable_facts_stay_visible(self) -> None:
        stats = dict(SAMPLE_STATS)
        stats.update(
            classified_tasks=10,
            tiers={"Light": 5, "Small": 3, "Mid": 1, "Top": 1},
            cost=None,
            tokens=None,
            quota=None,
        )
        rendered = render_stats(stats, width=48, color=False)
        self.assertIn("TIER COMPOSITION", rendered)
        self.assertIn("10 classified tasks", rendered)
        self.assertIn("Cost: Unavailable", rendered)
        self.assertIn("Tokens: Unavailable", rendered)
        self.assertNotIn("progress", rendered.casefold())
        self.assertNotIn("\x1b[", rendered)

    def test_narrow_output_sanitizes_untrusted_labels_and_wraps(self) -> None:
        stats = dict(SAMPLE_STATS)
        stats["requested_models"] = {"\x1b[31mVeryLongModelName-" * 3: 1}
        rendered = render_stats(stats, width=32, color=False)
        self.assertNotIn("\x1b", rendered)
        self.assertTrue(all(len(line) <= 32 for line in rendered.splitlines()))


class CliTests(unittest.TestCase):

    def test_color_respects_tty_plain_and_no_color(self) -> None:
        class TTY:
            def isatty(self):
                return True

        with patch.object(cli.sys, "stdout", TTY()), patch.dict(os.environ, {"TERM": "xterm"}, clear=True):
            self.assertTrue(cli._wants_color(types.SimpleNamespace(plain=False, color=None)))
            self.assertFalse(cli._wants_color(types.SimpleNamespace(plain=True, color=True)))
        with patch.object(cli.sys, "stdout", TTY()), patch.dict(os.environ, {"TERM": "xterm", "NO_COLOR": "1"}, clear=True):
            self.assertFalse(cli._wants_color(types.SimpleNamespace(plain=False, color=None)))














if __name__ == "__main__":
    unittest.main()
