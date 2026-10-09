"""Command line entry point for the local MRH candidate."""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path
from typing import Any, Sequence

from .terminal import render_report, render_stats, terminal_width


def _default_db() -> Path:
    return Path.home() / ".local" / "state" / "model-routing-harness" / "events.sqlite3"


def _wants_color(args: argparse.Namespace) -> bool:
    if getattr(args, "plain", False):
        return False
    if getattr(args, "color", None) is not None:
        return args.color
    return (
        hasattr(sys.stdout, "isatty")
        and sys.stdout.isatty()
        and os.environ.get("NO_COLOR", "") == ""
        and os.environ.get("TERM", "") != "dumb"
    )


def _add_display_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--plain", action="store_true", help="disable terminal colors")
    parser.add_argument("--color", dest="color", action="store_true", default=None, help="force terminal colors")
    parser.add_argument("--no-color", dest="color", action="store_false", help=argparse.SUPPRESS)
    parser.add_argument("--width", type=int, default=None, help="set display width")


def _add_stats_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--db", type=Path, default=None, help="event database path")
    parser.add_argument("--synthetic", action="store_true", help="read the isolated synthetic partition")
    parser.add_argument("--json", action="store_true", help="print the unmodified statistics object")
    _add_display_options(parser)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mrh",
        description="Inspect local model-routing candidate statistics and integration status.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    for name, help_text in (
        ("stats", "show event statistics"),
        ("status", "show current local routing status and statistics"),
    ):
        command = commands.add_parser(name, help=help_text)
        _add_stats_options(command)

    doctor = commands.add_parser("doctor", help="show capability boundaries without probing services")
    _add_display_options(doctor)

    config = commands.add_parser("config", help="preview or explicitly apply a Codex hook configuration change")
    config.add_argument("--home", type=Path, required=True, help="explicit Codex home to inspect")
    config.add_argument("--command", dest="hook_command", required=True, help="explicit MRH executable command for the hook")
    config.add_argument("--action", choices=("apply", "disable"), default="apply")
    config.add_argument("--apply", dest="write", action="store_true", help="write the prepared change")
    _add_display_options(config)

    demo = commands.add_parser("demo", help="write labeled synthetic examples to an explicit partition")
    demo.add_argument("--db", type=Path, default=None, help="event database path")
    demo.add_argument("--json", action="store_true", help="print the synthetic statistics object")
    _add_display_options(demo)

    hook = commands.add_parser("hook", help="read one Codex hook JSON event from stdin")
    hook.add_argument("--db", type=Path, default=None, help="event database path")
    hook.add_argument("--candidate", action="store_true", help="enable the isolated candidate adapter")
    hook.add_argument(
        "--simulate-tier",
        choices=("Light", "Small", "Mid", "Top"),
        help="inject a synthetic classification for an isolated candidate run",
    )
    hook.add_argument(
        "--simulate-confidence",
        type=float,
        default=None,
        help="synthetic confidence (default: 0.9 when --simulate-tier is set)",
    )
    return parser


def _store(path: Path | None) -> Any:
    # Importing the CLI, --help, doctor, and config preview must stay side-effect free.
    from .store import Store

    return Store(str(path or _default_db()))


def _write_json(value: Any, stream: Any = None) -> None:
    if stream is None:
        stream = sys.stdout
    stream.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False, default=str))
    stream.write("\n")


def _cmd_stats(args: argparse.Namespace) -> int:
    stats = _store(args.db).stats(synthetic=args.synthetic)
    if args.json:
        _write_json(stats)
    else:
        width = args.width or terminal_width()
        sys.stdout.write(render_stats(stats, width=width, color=_wants_color(args)))
    return 0


def _cmd_doctor(args: argparse.Namespace) -> int:
    report = render_report(
        "MRH  /  local capability check",
        {
            "Live classification": [
                "Jev provider: unavailable; live requests are not sent",
                "Credentials and network: not probed",
            ],
            "Codex": [
                "Candidate hook adapter: available for isolated use",
                "Desktop and CLI adoption: unverified",
                "Global hook activation: not checked",
            ],
            "Other CLIs": [
                "Claude Code: unsupported",
                "Gemini CLI: unsupported",
            ],
            "Data": [
                "Statistics are read from the local event store when requested",
                "Cost, token, quota, and actual model remain unavailable without evidence",
            ],
        },
        width=args.width or terminal_width(),
        color=_wants_color(args),
    )
    sys.stdout.write(report)
    return 0


def _public_plan(plan: Any) -> Any:
    public = getattr(plan, "public", None)
    if not callable(public):
        raise TypeError("installer returned an invalid plan")
    return public()


def _status_refused(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    status = value.get("status")
    return isinstance(status, str) and status.strip().casefold() == "refused"


def _cmd_config(args: argparse.Namespace) -> int:
    try:
        from .installer import apply, prepare

        plan = prepare(args.home, args.hook_command, action=args.action)
        public = _public_plan(plan)
        result: dict[str, Any] = {"plan": public}
        failure_code = "mrh: config_refused" if _status_refused(public) else None
        if args.write and failure_code is None:
            apply_result = apply(plan)
            result["apply_result"] = apply_result
            if isinstance(apply_result, dict) and apply_result.get("ok") is False:
                failure_code = "mrh: config_apply_refused"
        report = render_report(
            "MRH  /  Codex hook configuration",
            {"Preview and result": result},
            width=args.width or terminal_width(),
            color=_wants_color(args),
        )
        sys.stdout.write(report)
        if failure_code is not None:
            sys.stderr.write(f"{failure_code}\n")
            return 2
        return 0
    except Exception:
        sys.stderr.write("mrh: config_error\n")
        return 2


def _cmd_demo(args: argparse.Namespace) -> int:
    from .simulation import run_demo

    stats = run_demo(_store(args.db))
    if args.json:
        _write_json(stats)
    else:
        sys.stdout.write(
            render_report(
                "MRH  /  synthetic demo",
                {
                    "Synthetic statistics": [
                        "The following counts are synthetic examples, not live provider or host evidence."
                    ]
                },
                width=args.width or terminal_width(),
                color=_wants_color(args),
            )
        )
        sys.stdout.write(render_stats(stats, width=args.width or terminal_width(), color=_wants_color(args)))
    return 0


def _cmd_hook(args: argparse.Namespace, stdin: Any, stdout: Any, stderr: Any) -> int:
    simulation_requested = args.simulate_tier is not None or args.simulate_confidence is not None
    simulation = None
    if simulation_requested:
        if not args.candidate:
            stderr.write("mrh: simulation_requires_candidate\n")
            stdout.write("{}\n")
            return 0
        if args.db is None:
            stderr.write("mrh: simulation_requires_explicit_db\n")
            stdout.write("{}\n")
            return 0
        if args.simulate_tier is None:
            stderr.write("mrh: simulation_requires_tier\n")
            stdout.write("{}\n")
            return 0
        confidence = 0.9 if args.simulate_confidence is None else args.simulate_confidence
        if not math.isfinite(confidence) or not 0 <= confidence <= 1:
            stderr.write("mrh: invalid_simulation_confidence\n")
            stdout.write("{}\n")
            return 0
        simulation = {"tier": args.simulate_tier, "confidence": confidence}
    try:
        event = json.load(stdin)
        if not isinstance(event, dict):
            raise ValueError("hook event must be a JSON object")
        from .codex import handle_event

        store = _store(args.db) if args.candidate else None
        response = handle_event(event, store=store, candidate=args.candidate, simulation=simulation)
        if not isinstance(response, dict):
            raise TypeError("hook adapter response must be an object")
        encoded = json.dumps(response, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    except Exception:
        stderr.write("mrh: hook_error\n")
        encoded = "{}"
    stdout.write(encoded + "\n")
    return 0


def main(
    argv: Sequence[str] | None = None,
    *,
    stdin: Any = None,
    stdout: Any = None,
    stderr: Any = None,
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if stdin is None:
        stdin = sys.stdin
    if stdout is None:
        stdout = sys.stdout
    if stderr is None:
        stderr = sys.stderr

    # The hook path owns explicit streams because Codex consumes stdout as protocol.
    if args.command == "hook":
        return _cmd_hook(args, stdin, stdout, stderr)

    # Keep command output directed through the caller-provided streams as well.
    old_stdout, old_stderr = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = stdout, stderr
    try:
        if args.command in {"stats", "status"}:
            return _cmd_stats(args)
        if args.command == "doctor":
            return _cmd_doctor(args)
        if args.command == "config":
            return _cmd_config(args)
        if args.command == "demo":
            return _cmd_demo(args)
        parser.error("unknown command")
    except Exception:
        stderr.write("mrh: cli_error\n")
        return 2
    finally:
        sys.stdout, sys.stderr = old_stdout, old_stderr
    return 2
