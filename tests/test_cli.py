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

from mrh import cli
from mrh.terminal import render_stats, sanitize_text


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
        if name == "mrh.store":
            raise AssertionError("this command must not import the event store")
        return original(name, *args, **kwargs)

    return patch("builtins.__import__", side_effect=guarded)


class TerminalTests(unittest.TestCase):
    def test_dashboard_fits_wide_narrow_and_unicode_and_keeps_detail_view(self) -> None:
        from mrh.terminal import cell_width
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
    def test_demo_without_db_is_temporary_and_json_remains_synthetic(self) -> None:
        output = io.StringIO()
        with patch.object(cli, "_default_db", side_effect=AssertionError("live DB touched")):
            self.assertEqual(cli.main(["demo", "--json"], stdout=output), 0)
        stats = json.loads(output.getvalue())
        self.assertEqual(stats["partition"], "synthetic")
        self.assertEqual(stats["proposals"], 5)
        self.assertEqual(stats["confirmed_children"], 0)

    def test_color_respects_tty_plain_and_no_color(self) -> None:
        class TTY:
            def isatty(self):
                return True

        with patch.object(cli.sys, "stdout", TTY()), patch.dict(os.environ, {"TERM": "xterm"}, clear=True):
            self.assertTrue(cli._wants_color(types.SimpleNamespace(plain=False, color=None)))
            self.assertFalse(cli._wants_color(types.SimpleNamespace(plain=True, color=True)))
        with patch.object(cli.sys, "stdout", TTY()), patch.dict(os.environ, {"TERM": "xterm", "NO_COLOR": "1"}, clear=True):
            self.assertFalse(cli._wants_color(types.SimpleNamespace(plain=False, color=None)))

    def test_help_does_not_import_store(self) -> None:
        output = io.StringIO()
        with forbid_store_imports(), contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as raised:
            cli.main(["--help"])
        self.assertEqual(raised.exception.code, 0)

    def test_doctor_does_not_import_store_or_touch_external_services(self) -> None:
        output, errors = io.StringIO(), io.StringIO()
        with forbid_store_imports(), contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            result = cli.main(["doctor", "--plain"])
        self.assertEqual(result, 0)
        self.assertIn("TypeSafe Jev adapter: default-disabled; real provider unverified", output.getvalue())
        self.assertIn("not probed", output.getvalue())
        self.assertIn("Global hook activation: not checked", output.getvalue())

    def test_stats_json_is_the_store_object_without_presentation_fields(self) -> None:
        class FakeStore:
            def __init__(self, path: str):
                self.path = path

            def stats(self, synthetic: bool = False):
                self.synthetic = synthetic
                return SAMPLE_STATS

        output = io.StringIO()
        with patch.dict(sys.modules, {"mrh.store": fake_module("mrh.store", Store=FakeStore)}):
            result = cli.main(["stats", "--db", "/tmp/mrh-test.sqlite", "--json"], stdout=output)
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(output.getvalue()), SAMPLE_STATS)
        self.assertNotIn("\x1b", output.getvalue())

    def test_synthetic_stats_are_requested_only_when_explicit(self) -> None:
        seen: list[bool] = []

        class FakeStore:
            def __init__(self, path: str):
                pass

            def stats(self, synthetic: bool = False):
                seen.append(synthetic)
                return SAMPLE_STATS

        output = io.StringIO()
        with patch.dict(sys.modules, {"mrh.store": fake_module("mrh.store", Store=FakeStore)}):
            cli.main(["stats", "--db", "/tmp/mrh-test.sqlite", "--json"], stdout=output)
            cli.main(["stats", "--db", "/tmp/mrh-test.sqlite", "--synthetic", "--json"], stdout=output)
        self.assertEqual(seen, [False, True])

    def test_config_preview_uses_explicit_home_and_never_applies_by_default(self) -> None:
        calls: list[tuple[Path, str, str]] = []
        applied: list[object] = []

        class Plan:
            def public(self):
                return {"action": "apply", "writes": []}

        def prepare(home: Path, command: str, action: str = "apply"):
            calls.append((home, command, action))
            return Plan()

        module = fake_module("mrh.installer", prepare=prepare, apply=lambda plan: applied.append(plan))
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, patch.dict(sys.modules, {"mrh.installer": module}):
            result = cli.main(["config", "--home", tmp, "--command", "mrh", "--plain"], stdout=output)
        self.assertEqual(result, 0)
        self.assertEqual(calls, [(Path(tmp), "mrh", "apply")])
        self.assertEqual(applied, [])
        self.assertIn("PREVIEW AND RESULT", output.getvalue())

    def test_config_apply_requires_explicit_flag(self) -> None:
        calls: list[str] = []

        class Plan:
            def public(self):
                return {"action": "disable"}

        module = fake_module(
            "mrh.installer",
            prepare=lambda home, command, action="apply": Plan(),
            apply=lambda plan: calls.append("apply") or {"ok": True},
        )
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, patch.dict(sys.modules, {"mrh.installer": module}):
            result = cli.main(["config", "--home", tmp, "--command", "mrh", "--action", "disable", "--apply", "--plain"], stdout=output)
        self.assertEqual(result, 0)
        self.assertEqual(calls, ["apply"])

    def test_config_refused_preview_returns_nonzero_and_skips_apply(self) -> None:
        calls: list[str] = []

        class Plan:
            def public(self):
                return {"status": "refused", "reason": "safe_reason"}

        module = fake_module(
            "mrh.installer",
            prepare=lambda home, command, action="apply": Plan(),
            apply=lambda plan: calls.append("apply") or {"ok": True},
        )
        output, errors = io.StringIO(), io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, patch.dict(sys.modules, {"mrh.installer": module}):
            result = cli.main(["config", "--home", tmp, "--command", "mrh", "--apply", "--plain"], stdout=output, stderr=errors)
        self.assertNotEqual(result, 0)
        self.assertEqual(errors.getvalue(), "mrh: config_refused\n")
        self.assertEqual(calls, [])

    def test_config_apply_refusal_returns_nonzero(self) -> None:
        class Plan:
            def public(self):
                return {"status": "ready"}

        module = fake_module(
            "mrh.installer",
            prepare=lambda home, command, action="apply": Plan(),
            apply=lambda plan: {"ok": False, "status": "refused"},
        )
        output, errors = io.StringIO(), io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, patch.dict(sys.modules, {"mrh.installer": module}):
            result = cli.main(["config", "--home", tmp, "--command", "mrh", "--apply", "--plain"], stdout=output, stderr=errors)
        self.assertNotEqual(result, 0)
        self.assertEqual(errors.getvalue(), "mrh: config_apply_refused\n")

    def test_hook_stdout_is_protocol_only_and_default_is_passthrough(self) -> None:
        seen: list[tuple[dict, object, bool, object]] = []

        def handle_event(event, store=None, candidate=False, simulation=None):
            seen.append((event, store, candidate, simulation))
            return {}

        module = fake_module("mrh.codex", handle_event=handle_event)
        stdin, stdout, stderr = io.StringIO('{"hook_event_name":"Other"}'), io.StringIO(), io.StringIO()
        with patch.dict(sys.modules, {"mrh.codex": module}):
            result = cli.main(["hook"], stdin=stdin, stdout=stdout, stderr=stderr)
        self.assertEqual(result, 0)
        self.assertEqual(stdout.getvalue(), "{}\n")
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(seen, [({"hook_event_name": "Other"}, None, False, None)])

    def test_hook_adapter_errors_return_empty_json_and_safe_error_code(self) -> None:
        def handle_event(*args, **kwargs):
            raise RuntimeError("private prompt and secret")

        stdin, stdout, stderr = io.StringIO("{}"), io.StringIO(), io.StringIO()
        with patch.dict(sys.modules, {"mrh.codex": fake_module("mrh.codex", handle_event=handle_event)}):
            result = cli.main(["hook", "--candidate"], stdin=stdin, stdout=stdout, stderr=stderr)
        self.assertEqual(result, 0)
        self.assertEqual(stdout.getvalue(), "{}\n")
        self.assertEqual(stderr.getvalue(), "mrh: hook_error\n")
        self.assertNotIn("secret", stderr.getvalue())

    def test_hook_simulation_requires_candidate_and_explicit_database(self) -> None:
        calls: list[object] = []
        codex = fake_module("mrh.codex", handle_event=lambda *args, **kwargs: calls.append(kwargs) or {})
        with tempfile.TemporaryDirectory() as tmp:
            cases = (
                (["hook", "--simulate-tier", "Top"], "mrh: simulation_requires_candidate\n"),
                (["hook", "--candidate", "--simulate-tier", "Top"], "mrh: simulation_requires_explicit_db\n"),
                (["hook", "--candidate", "--db", str(Path(tmp) / "events.sqlite3"), "--simulate-confidence", "0.8"], "mrh: simulation_requires_tier\n"),
            )
            for argv, expected_error in cases:
                stdout, stderr = io.StringIO(), io.StringIO()
                with patch.dict(sys.modules, {"mrh.codex": codex}):
                    result = cli.main(argv, stdin=io.StringIO("{}"), stdout=stdout, stderr=stderr)
                self.assertEqual(result, 0)
                self.assertEqual(stdout.getvalue(), "{}\n")
                self.assertEqual(stderr.getvalue(), expected_error)
        self.assertEqual(calls, [])

    def test_hook_simulation_passes_synthetic_tier_and_default_confidence(self) -> None:
        seen: list[dict] = []

        class FakeStore:
            def __init__(self, path: str):
                self.path = path

        def handle_event(event, store=None, candidate=False, simulation=None):
            seen.append({"event": event, "store": store, "candidate": candidate, "simulation": simulation})
            return {}

        modules = {
            "mrh.store": fake_module("mrh.store", Store=FakeStore),
            "mrh.codex": fake_module("mrh.codex", handle_event=handle_event),
        }
        with tempfile.TemporaryDirectory() as tmp, patch.dict(sys.modules, modules):
            db_path = str(Path(tmp) / "events.sqlite3")
            for confidence_args, confidence in (([], 0.9), (["--simulate-confidence", "0.62"], 0.62)):
                output, errors = io.StringIO(), io.StringIO()
                result = cli.main(
                    ["hook", "--candidate", "--db", db_path, "--simulate-tier", "Mid", *confidence_args],
                    stdin=io.StringIO('{"hook_event_name":"PreToolUse"}'),
                    stdout=output,
                    stderr=errors,
                )
                self.assertEqual(result, 0)
                self.assertEqual(output.getvalue(), "{}\n")
                self.assertEqual(errors.getvalue(), "")
                self.assertEqual(seen[-1]["simulation"], {"tier": "Mid", "confidence": confidence})
                self.assertTrue(seen[-1]["candidate"])
                self.assertEqual(seen[-1]["store"].path, db_path)
        self.assertEqual(len(seen), 2)


if __name__ == "__main__":
    unittest.main()
