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
from mrh.presentation.terminal import sanitize_text


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

    def test_terminal_controls_are_removed(self) -> None:
        self.assertEqual(sanitize_text("\x1b[31mTop\x1b[0m\n\x00x\u202e"), "Top x")




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
