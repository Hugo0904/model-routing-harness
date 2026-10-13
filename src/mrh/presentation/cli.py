"""Command line entry point for the local MRH candidate."""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Sequence

from mrh.presentation.terminal import terminal_width


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
    parser.add_argument("--settings", type=Path, help="settings.json (default: MRH_SETTINGS or the installed pointer)")
    parser.add_argument("--json", action="store_true", help="print the statistics as JSON")
    parser.add_argument("--days", type=float, default=None, help="period in days (0 = all records)")
    _add_display_options(parser)


COMMAND_LIST = """MRH 指令（用法：mrh <指令>）

日常使用
  mrh ctrl               控制中心（互動選單：模型、分級器、信心門檻、適用範圍…）
  mrh status             儀表板（流程、難度表、分段比例條）
  mrh stats              文字統計（可加 --days N；0 = 全部）
  mrh ctrl show          目前設定一覽
  mrh ctrl set 項目 值   修改單一設定（mrh ctrl keys 列出所有項目）
  mrh key status jev     金鑰狀態（set 存入、delete 刪除）

安裝與維護
  mrh plugin prepare --advisory …   準備 Codex／Claude Code 共用外掛
  mrh install claude --artifact …   套用 Claude Code hook（預設只顯示差異，加 --apply 才寫入）

說明
  mrh <指令> --help      該指令的參數說明
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mrh",
        description="Inspect local model-routing candidate statistics and integration status.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    for name, help_text in (("status", "card dashboard"), ("stats", "statistics in plain language")):
        _add_stats_options(commands.add_parser(name, help=help_text))

    ctrl = commands.add_parser("ctrl", help="control center: every MRH setting in one place")
    ctrl.add_argument("--settings", type=Path, help="settings.json (default: MRH_SETTINGS or the installed pointer)")
    ctrl_actions = ctrl.add_subparsers(dest="ctrl_action")
    ctrl_show = ctrl_actions.add_parser("show", help="print the current configuration")
    ctrl_show.add_argument("--json", action="store_true")
    ctrl_set = ctrl_actions.add_parser("set", help="change one setting (see `mrh ctrl keys`)")
    ctrl_set.add_argument("key"); ctrl_set.add_argument("value")
    ctrl_actions.add_parser("keys", help="list the settable keys")
    ctrl_dash = ctrl_actions.add_parser("dashboard", help="card-style dashboard: routing flow, tier table, proportion bars")
    ctrl_dash.add_argument("--days", type=float, default=7, help="period in days (0 = all records; default 7)")
    ctrl_report = ctrl_actions.add_parser("report", help="write an HTML dashboard (tier table + proportion bars)")
    ctrl_report.add_argument("--days", type=float, default=7, help="period in days (0 = all records; default 7)")
    ctrl_report.add_argument("--out", help="output file (default ~/.local/state/model-routing-harness/report.html)")
    ctrl_report.add_argument("--open", action="store_true", help="open it in the browser")
    ctrl_stats = ctrl_actions.add_parser("stats", help="statistics in plain language")
    ctrl_stats.add_argument("--days", type=float, default=1, help="period in days (0 = all records; default 1)")
    ctrl_stats.add_argument("--json", action="store_true")
    _add_display_options(ctrl)

    install = commands.add_parser("install", help="show (default) or apply the Claude Code hook")
    install.add_argument("host", choices=("claude",))
    install.add_argument("--artifact", type=Path, required=True, help="prepared advisory artifact root (mrh plugin prepare --advisory)")
    install.add_argument("--claude-settings", type=Path, default=None, help="default: ~/.claude/settings.json")
    install.add_argument("--remove", action="store_true", help="take MRH's hook out again")
    install.add_argument("--apply", action="store_true", help="write the change (a timestamped backup is kept)")

    key = commands.add_parser("key", help="manage the classifier API key (stored in the macOS Keychain)")
    key.add_argument("action", choices=("status", "set", "delete"))
    key.add_argument("name", choices=("jev",))

    plugin = commands.add_parser("plugin", help="prepare owned plugin files; native install and trust remain explicit")
    plugin_actions = plugin.add_subparsers(dest="plugin_action", required=True)
    prepare = plugin_actions.add_parser("prepare")
    prepare.add_argument("--root", required=True, type=Path, help="fresh or verified MRH-owned bundle root")
    prepare.add_argument("--settings", required=True, type=Path, help="separate absolute MRH settings.json path")
    prepare.add_argument("--python", type=Path, help="installed Python 3.11+ interpreter")
    prepare.add_argument('--scope-workspace',type=Path,help='inspect a finite official CLI generic-routing scope; preserves default-off')
    prepare.add_argument('--codex-binary',type=Path,help='optional exact official native CLI; default uses installed discovery')
    prepare.add_argument('--scope-contract',choices=['fresh-root-cli'],help='explicit fresh root native CLI contract; requires --scope-workspace')
    prepare.add_argument('--advisory',action='store_true',help='advisory routing (settings v2): no scope binding; serves Codex and Claude Code')
    show = plugin_actions.add_parser("show")
    show.add_argument("--root", required=True, type=Path)

    hook = commands.add_parser("hook", help="read one Codex hook JSON event from stdin")
    hook.add_argument("--settings", type=Path, help="explicit registered MRH-owned settings.json; default off")
    hook.add_argument("--platform", choices=("codex", "claude"), help="advisory routing for this host (settings v2)")
    hook.add_argument('--scope-binding',type=Path,help=argparse.SUPPRESS)
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
    from mrh.infrastructure.store import Store

    return Store(str(path or _default_db()))


def _write_json(value: Any, stream: Any = None) -> None:
    if stream is None:
        stream = sys.stdout
    stream.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False, default=str))
    stream.write("\n")


def _hook_failure(event, admitted):
    if (admitted and isinstance(event, dict) and event.get('hook_event_name') == 'PreToolUse' and
            event.get('tool_name') in ('spawn_agent','collaborationspawn_agent') and isinstance(event.get('tool_input'), dict)):
        from mrh.routing.faults import warning
        return warning('runtime_error')
    return {}


def _cmd_hook(args: argparse.Namespace, stdin: Any, stdout: Any, stderr: Any, runtime_dependencies=None) -> int:
    event, exit_code = None, 0
    if args.settings is not None:
        if args.candidate or args.simulate_tier is not None or args.simulate_confidence is not None or args.db is not None:
            stderr.write("mrh: settings_candidate_conflict\n")
            stdout.write("{}\n")
            return 0
        try:
            payload = stdin.read(2_000_001)
            if len(payload.encode()) > 2_000_000:
                raise ValueError()
            event = json.loads(payload)
            from mrh.application.runtime import configured_event
            dependencies=dict(runtime_dependencies or {})
            if args.scope_binding is not None:dependencies['scope_binding']=args.scope_binding
            response = configured_event(event, args.settings, **dependencies)
            encoded = json.dumps(response, separators=(",", ":"), allow_nan=False)
        except Exception:
            stderr.write("mrh: configured_hook_error\n")
            try:
                encoded = json.dumps(_hook_failure(event, True), separators=(',', ':'))
            except Exception:
                # The independent launcher must be able to detect that even
                # the shared warning module could not load. Never mask it with
                # a successful empty response or forward an import traceback.
                encoded, exit_code = '{}', 1
        stdout.write(encoded + "\n")
        return exit_code
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
        from mrh.adapters.hosts.codex import handle_event

        store = _store(args.db) if args.candidate else None
        response = handle_event(event, store=store, candidate=args.candidate, simulation=simulation)
        if not isinstance(response, dict):
            raise TypeError("hook adapter response must be an object")
        encoded = json.dumps(response, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    except Exception:
        stderr.write("mrh: hook_error\n")
        try:
            encoded = json.dumps(_hook_failure(event, args.candidate), separators=(',', ':'))
        except Exception:
            encoded, exit_code = '{}', 1
    stdout.write(encoded + "\n")
    return exit_code


def main(
    argv: Sequence[str] | None = None,
    *,
    stdin: Any = None,
    stdout: Any = None,
    stderr: Any = None,
    runtime_dependencies: dict | None = None,
    model_dependencies: dict | None = None,
) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments or arguments[0] in ("-h", "--help", "help"):
        (stdout or sys.stdout).write(COMMAND_LIST)
        return 0
    parser = build_parser()
    args = parser.parse_args(arguments)
    if stdin is None:
        stdin = sys.stdin
    if stdout is None:
        stdout = sys.stdout
    if stderr is None:
        stderr = sys.stderr

    # The hook path owns explicit streams because Codex consumes stdout as protocol.
    if args.command == "hook" and args.platform:
        from mrh.application import advisory_runtime
        from mrh.infrastructure.settings_v2 import resolve_settings_path
        try:
            path = resolve_settings_path(args.settings)
        except Exception:
            stderr.write("mrh: settings_path_invalid\n"); stdout.write("{}\n"); return 0
        return advisory_runtime.run(args.platform, path, stdin, stdout, stderr)
    if args.command == "hook":
        return _cmd_hook(args, stdin, stdout, stderr, runtime_dependencies)

    # Keep command output directed through the caller-provided streams as well.
    old_stdout, old_stderr = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = stdout, stderr
    try:
        if args.command in {"stats", "status"}:
            from mrh.presentation import ctrl
            args.ctrl_action = "dashboard" if args.command == "status" else "stats"
            if args.days is None:
                args.days = 7 if args.command == "status" else 1
            return ctrl.main(args, stdin=stdin, stdout=stdout, stderr=stderr, color=_wants_color(args))
        if args.command == "install":
            from mrh.infrastructure import claude_hook as ch
            target = args.claude_settings or Path.home() / ".claude" / "settings.json"
            try:
                before = target.read_text() if target.exists() else ""
                after = ch.plan(before, ch.command_for(args.artifact), remove=args.remove)
            except (ch.ClaudeHookError, OSError, ValueError) as exc:
                stderr.write("mrh: " + str(exc) + "\n"); return 2
            if after == before:
                stdout.write("Nothing to change.\n"); return 0
            stdout.write(ch.diff(before, after, str(target)))
            if not args.apply:
                stdout.write("\nDry run. Add --apply to write this change.\n"); return 0
            backup = ch.apply(target, after)
            stdout.write(f"\nApplied. Backup: {backup}\n" if backup else "\nApplied (new file).\n"); return 0
        if args.command == "ctrl":
            from mrh.presentation import ctrl
            return ctrl.main(args, stdin=stdin, stdout=stdout, stderr=stderr, color=_wants_color(args))
        if args.command == "key":
            from mrh.presentation import key_cli
            return key_cli.run(args.action, args.name, stdout=stdout, stderr=stderr)
        if args.command == "plugin":
            from mrh.infrastructure import plugin
            from mrh.infrastructure.owned import OwnedError
            from mrh.adapters.hosts.codex_scope import ScopeError
            try:
                _write_json(plugin.prepare(args.root, args.settings, args.python,scope_workspace=args.scope_workspace,
                                         codex_binary=args.codex_binary,scope_contract=args.scope_contract,advisory=args.advisory) if args.plugin_action == "prepare" else plugin.show(args.root))
                return 0
            except (OwnedError,ScopeError) as exc:
                stderr.write("mrh: " + getattr(exc,'reason',str(exc)) + "\n")
                return 2
        parser.error("unknown command")
    except KeyboardInterrupt:
        stdout.write("\n")
        return 130                                     # the usual exit status for Ctrl-C; no traceback
    except Exception:
        stderr.write("mrh: cli_error\n")
        return 2
    finally:
        sys.stdout, sys.stderr = old_stdout, old_stderr
    return 2
