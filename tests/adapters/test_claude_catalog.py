"""Focused regressions for Claude's initialize-only model catalog."""
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from mrh.adapters.catalogs import catalog; from mrh.presentation import cli; from mrh.infrastructure import settings
from mrh.infrastructure.bindings import Registry
from mrh.adapters.catalogs.catalog import Catalog, CatalogError, CodexCatalog, Model, ToolCatalog, executable_hash
import mrh.adapters.catalogs.claude_catalog as claude_catalog
from mrh.adapters.catalogs.claude_catalog import ClaudeCatalog, parse_initialize
from mrh.routing.types import Proposal, safe_id, safe_model_id


REQUEST_ID = "mrh_initialize_0123456789abcdef"


def response_frame(models, *, request_id=REQUEST_ID, subtype="success", **extra):
    response = {"request_id": request_id, "subtype": subtype}
    if subtype == "success":
        response["response"] = {"models": models, **extra}
    return {"type": "control_response", "response": response}


def model_row(value="default", *, label="Default", **extra):
    return {"value": value, "displayName": label, **extra}


class ClaudeInitializeParserTests(unittest.TestCase):
    def test_uses_request_values_and_effort_levels_without_reading_extra_initialize_data(self):
        rows = [
            model_row(
                "default",
                label="Default (recommended)",
                resolvedModel="claude-opus-5[1m]",
                supportsEffort=True,
                supportedEffortLevels=["low", "medium", "high", "xhigh", "max"],
            ),
            model_row("haiku", label="Haiku"),
        ]

        models = parse_initialize(
            response_frame(rows, available_output_styles=[], analytics_disabled=True),
            REQUEST_ID,
        )

        self.assertEqual(tuple(model.id for model in models), ("default", "haiku"))
        self.assertEqual(models[0].resolved_model, "claude-opus-5[1m]")
        self.assertEqual(models[0].efforts, ("low", "medium", "high", "xhigh", "max"))
        self.assertIsNone(models[1].resolved_model)
        self.assertEqual(models[1].efforts, ())

    def test_rejects_wrong_envelope_request_id_and_initialize_error(self):
        valid = response_frame([model_row()])
        wrong_type = copy.deepcopy(valid)
        wrong_type["type"] = "system"
        missing_response_id = copy.deepcopy(valid)
        del missing_response_id["response"]["request_id"]
        wrong_response_id = response_frame([model_row()], request_id="different_request")
        initialize_error = response_frame([], subtype="error")

        for frame, request_id, expected in (
            (wrong_type, REQUEST_ID, "claude_catalog_protocol_incompatible"),
            (missing_response_id, REQUEST_ID, "claude_catalog_protocol_incompatible"),
            (wrong_response_id, REQUEST_ID, "claude_catalog_protocol_incompatible"),
            (initialize_error, REQUEST_ID, "claude_catalog_initialize_failed"),
        ):
            with self.subTest(expected=expected, frame=frame):
                with self.assertRaises(CatalogError) as raised:
                    parse_initialize(frame, request_id)
                self.assertEqual(str(raised.exception), expected)

    def test_rejects_malformed_duplicate_and_unknown_model_metadata(self):
        invalid_rows = (
            [model_row("bad id", label="Bad")],
            [model_row("opus", label=3)],
            [model_row("opus", resolvedModel="claude-opus[1m")],
            [model_row("opus", supportsEffort="yes")],
            [model_row("opus", supportsEffort=False, supportedEffortLevels=["low"])],
            [model_row("opus", supportsEffort=True, supportedEffortLevels=["ultra"])],
            [model_row("opus", supportsEffort=True, supportedEffortLevels=["high", "high"])],
            [model_row("opus"), model_row("opus", label="Duplicate request value")],
        )
        for rows in invalid_rows:
            with self.subTest(rows=rows):
                with self.assertRaises(CatalogError) as raised:
                    parse_initialize(response_frame(rows), REQUEST_ID)
                self.assertEqual(str(raised.exception), "claude_catalog_protocol_incompatible")

    def test_rejects_missing_or_oversized_model_lists(self):
        missing_models = response_frame([])
        del missing_models["response"]["response"]["models"]
        oversized = [model_row(f"model-{index}") for index in range(1025)]
        for frame in (missing_models, response_frame(oversized)):
            with self.assertRaises(CatalogError) as raised:
                parse_initialize(frame, REQUEST_ID)
            self.assertEqual(str(raised.exception), "claude_catalog_protocol_incompatible")


class ModelIdentifierTests(unittest.TestCase):
    def test_balanced_context_suffix_is_limited_to_model_ids(self):
        for value in ("opus[1m]", "claude-opus-5[1m]", "claude-sonnet-5", "default"):
            with self.subTest(value=value):
                self.assertTrue(safe_model_id(value))
        for value in ("opus[1m", "opus1m]", "opus[1m]tail", "opus[a][b]", "sk-secret[1m]"):
            with self.subTest(value=value):
                self.assertFalse(safe_model_id(value))

        self.assertFalse(safe_id("opus[1m]"))
        self.assertTrue(safe_id("session-012345"))
        proposal = Proposal("claude", "surface", "session[1m]", "turn", "call", {})
        with self.assertRaises(ValueError):
            _ = proposal.identity


class ToolCatalogDispatchTests(unittest.TestCase):
    def test_dispatches_catalog_refresh_without_starting_a_cli(self):
        codex_binding = {"tool": "codex"}
        claude_binding = {"tool": "claude"}
        codex_catalog = object()
        claude_catalog = object()
        with patch.object(CodexCatalog, "refresh", return_value=codex_catalog) as codex_refresh, \
                patch.object(ClaudeCatalog, "refresh", return_value=claude_catalog) as claude_refresh:
            self.assertIs(ToolCatalog().refresh(codex_binding), codex_catalog)
            self.assertIs(ToolCatalog().refresh(claude_binding), claude_catalog)

        codex_refresh.assert_called_once_with(codex_binding)
        claude_refresh.assert_called_once_with(claude_binding)
        with self.assertRaises(CatalogError) as raised:
            ToolCatalog().refresh({"tool": "gemini"})
        self.assertEqual(str(raised.exception), "tool_catalog_unsupported")

    def test_claude_description_uses_its_tool_specific_version_adapter(self):
        candidate = {"tool": "claude", "executable": "/synthetic/claude", "label": "Claude", "supported": True}
        described = {**candidate, "version": "2.1.267 (Claude Code)", "executable_sha256": "a" * 64}
        with patch.object(ClaudeCatalog, "describe", return_value=described) as describe:
            self.assertEqual(catalog.describe_tool(candidate), described)
        describe.assert_called_once_with(candidate)

    def test_discovery_marks_claude_supported_only_on_darwin(self):
        def which(tool):
            return "/usr/local/bin/claude" if tool == "claude" else None

        with patch.object(catalog.shutil, "which", side_effect=which), \
                patch.object(catalog.sys, "platform", "darwin"):
            darwin = next(candidate for candidate in catalog.discover() if candidate["tool"] == "claude")
        with patch.object(catalog.shutil, "which", side_effect=which), \
                patch.object(catalog.sys, "platform", "linux"):
            linux = next(candidate for candidate in catalog.discover() if candidate["tool"] == "claude")

        self.assertTrue(darwin["supported"])
        self.assertFalse(linux["supported"])

    def test_only_the_tested_claude_version_is_accepted_without_running_a_cli(self):
        candidate = {"tool": "claude", "executable": "/synthetic/claude", "label": "Claude", "supported": True}

        def describe_output(output):
            isolated = MagicMock()
            isolated.__enter__.return_value = (Path("/private/tmp"), {}, ["/synthetic/claude"], None, None)
            with patch("mrh.adapters.catalogs.claude_catalog.executable_hash", return_value="a" * 64), \
                    patch("mrh.adapters.catalogs.claude_catalog.isolated_cli", return_value=isolated), \
                    patch("mrh.adapters.catalogs.claude_catalog.subprocess.run",
                          return_value=subprocess.CompletedProcess(["claude"], 0, output, "")):
                return ClaudeCatalog().describe(candidate)

        accepted = describe_output("2.1.267 (Claude Code)\n")
        self.assertEqual(accepted["version"], "2.1.267 (Claude Code)")
        self.assertEqual(accepted["executable_sha256"], "a" * 64)
        with self.assertRaises(CatalogError) as raised:
            describe_output("2.1.268 (Claude Code)\n")
        self.assertEqual(str(raised.exception), "claude_catalog_version_unsupported")


class ClaudeTransportTests(unittest.TestCase):
    """Exercise the parser's real pipe/selector boundary with an inert child."""

    def run_responder(self, mode, *, timeout=False):
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name).resolve()
        trace_path = root / "request-trace.json"
        real_popen = subprocess.Popen
        launched = []
        child = r'''import json, pathlib, sys
trace_path = pathlib.Path(sys.argv[1])
mode = sys.argv[2]
line = sys.stdin.readline()
try:
    request = json.loads(line)
except Exception:
    request = None
valid = (type(request) is dict and request.get("type") == "control_request"
         and type(request.get("request_id")) is str
         and request.get("request", {}).get("subtype") == "initialize")
if not valid:
    sys.stdout.write(json.dumps({"type": "system", "subtype": "refused"}) + "\n")
    sys.stdout.flush()
    extra = sys.stdin.read()
    trace_path.write_text(json.dumps({"request": request, "extra": extra, "accepted": False}))
    raise SystemExit(17)
request_id = request["request_id"]
if mode == "eof":
    trace_path.write_text(json.dumps({"request": request, "extra": "", "accepted": True}))
    raise SystemExit(0)
if mode == "malformed":
    sys.stdout.write('{"type":"control_response",\n')
elif mode == "duplicate":
    quoted = json.dumps(request_id)
    sys.stdout.write('{"type":"control_response","response":{"request_id":' + quoted
                     + ',"request_id":' + quoted
                     + ',"subtype":"success","response":{"models":[]}}}\n')
elif mode == "oversized":
    sys.stdout.write("x" * 262145 + "\n")
elif mode == "unrelated_then_matching":
    unrelated = {"type": "control_response", "response": {"request_id": "mrh_unrelated",
                 "subtype": "success", "response": {"models": []}}}
    matching = {"type": "control_response", "response": {"request_id": request_id,
                "subtype": "success", "response": {"models": [{"value": "opus[1m]",
                "displayName": "Opus 1M", "resolvedModel": "claude-opus-5[1m]"}]}}}
    sys.stdout.write(json.dumps(unrelated) + "\n" + json.dumps(matching) + "\n")
elif mode in ("user", "assistant", "result", "control_request"):
    sys.stdout.write(json.dumps({"type": mode, "request_id": request_id}) + "\n")
elif mode == "timeout":
    pass
sys.stdout.flush()
extra = sys.stdin.read()
trace_path.write_text(json.dumps({"request": request, "extra": extra, "accepted": True}))
'''

        def launch(_args, **kwargs):
            proc = real_popen(
                [sys.executable, "-c", child, str(trace_path), mode],
                **kwargs,
            )
            launched.append(proc)
            return proc

        try:
            with patch.object(claude_catalog.subprocess, "Popen", side_effect=launch):
                if timeout:
                    ticks = iter((100.0, 116.0))
                    fake_clock = SimpleNamespace(monotonic=lambda: next(ticks))
                    with patch.object(claude_catalog, "time", fake_clock):
                        try:
                            outcome = claude_catalog._models(
                                ["/synthetic/claude"], root, {"PATH": os.defpath},
                                root / "settings.json", root / "mcp.json",
                            )
                        except CatalogError as exc:
                            outcome = str(exc)
                else:
                    try:
                        outcome = claude_catalog._models(
                            ["/synthetic/claude"], root, {"PATH": os.defpath},
                            root / "settings.json", root / "mcp.json",
                        )
                    except CatalogError as exc:
                        outcome = str(exc)

            self.assertEqual(len(launched), 1)
            self.assertIsNotNone(launched[0].returncode, "_models must reap its owned child")
            trace = json.loads(trace_path.read_text())
            self.assertTrue(trace["accepted"], "the responder accepts initialize only")
            self.assertEqual(trace["request"]["type"], "control_request")
            self.assertEqual(trace["request"]["request"]["subtype"], "initialize")
            self.assertEqual(trace["extra"], "", "_models must send exactly one frame")
            return outcome
        finally:
            temp.cleanup()
            self.assertFalse(root.exists(), "the test-owned responder directory must be removed")

    def test_skips_unrelated_response_and_accepts_only_matching_initialize_id(self):
        models = self.run_responder("unrelated_then_matching")

        self.assertIsInstance(models, tuple)
        self.assertEqual(len(models), 1)
        self.assertEqual(models[0].id, "opus[1m]")
        self.assertEqual(models[0].resolved_model, "claude-opus-5[1m]")

    def test_rejects_malformed_duplicate_key_and_oversized_responses(self):
        for mode in ("malformed", "duplicate", "oversized"):
            with self.subTest(mode=mode):
                outcome = self.run_responder(mode)
                self.assertEqual(outcome, "claude_catalog_protocol_incompatible")

    def test_rejects_unsolicited_non_control_response_frames(self):
        for mode in ("user", "assistant", "result", "control_request"):
            with self.subTest(mode=mode):
                outcome = self.run_responder(mode)
                self.assertEqual(outcome, "claude_catalog_protocol_incompatible")

    def test_maps_eof_before_response_to_initialize_failed(self):
        self.assertEqual(self.run_responder("eof"), "claude_catalog_initialize_failed")

    def test_maps_expired_deadline_to_timeout(self):
        self.assertEqual(self.run_responder("timeout", timeout=True), "claude_catalog_timeout")


class Tty(io.StringIO):
    def isatty(self):
        return True


class SyntheticClaudeProvider:
    def __init__(self, rows):
        self.rows = tuple(rows)
        self.calls = 0

    def refresh(self, binding):
        self.calls += 1
        return Catalog(
            binding["id"],
            "claude",
            binding["executable_sha256"],
            binding["version"],
            "synthetic:claude-selector-fixture",
            time.time(),
            self.rows,
            assurance="synthetic",
        ).validate()


class ClaudeSelectorRoundTripTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / "registry"
        self.registry = Registry(self.root)
        executable = str(Path("/usr/bin/true").resolve())
        self.candidate = {
            "tool": "claude",
            "label": "Synthetic Claude fixture",
            "executable": executable,
            "supported": True,
            "version": "2.1.267 (Claude Code)",
            "executable_sha256": executable_hash(executable),
        }
        self.binding = self.registry.associate(self.candidate, expected_revision=0)
        row = Model("opus[1m]", "Opus 1M", (), resolved_model="claude-opus-5[1m]")
        self.provider = SyntheticClaudeProvider((row,))
        self.settings_path = Path(self.binding["settings_path"])
        self.dependencies = {
            "provider": self.provider,
            "discovery": lambda: [self.candidate],
            "describe": lambda candidate: candidate,
        }

    def run_selector(self, text):
        stdout, stderr = io.StringIO(), io.StringIO()
        code = cli.main(
            ["model", "light", "--root", str(self.root), "--plain", "--width", "120"],
            stdin=Tty(text),
            stdout=stdout,
            stderr=stderr,
            model_dependencies=self.dependencies,
        )
        return code, stdout.getvalue(), stderr.getvalue()




if __name__ == "__main__":
    unittest.main()
