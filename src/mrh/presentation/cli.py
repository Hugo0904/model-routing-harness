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
  mrh stats reset        清除統計（--hours 24／--today／--days N／--all；會先預覽並要你輸入確認）
  mrh usage collect      收集子代理實際用了多少 token（只讀本機紀錄檔；之後 mrh stats 才有用量與換算）
  mrh classify "任務"    顧問分級：問分級器這件事算哪一級（不派工；--stdin／--json／--platform／--title／--role）
  mrh ctrl show          目前設定一覽
  mrh ctrl set 項目 值   修改單一設定（mrh ctrl keys 列出所有項目）
  mrh key status jev     金鑰狀態（set 存入、delete 刪除）

安裝與維護
  mrh plugin prepare --advisory …   準備 Codex／Claude Code 共用外掛
  mrh install claude --artifact …   套用 Claude Code hook（預設只顯示差異，加 --apply 才寫入）
  mrh models --host codex --json    CLI 宣告的模型／effort／來源；不代表帳號可用性

說明
  mrh <指令> --help      該指令的參數說明
"""


def build_parser() -> argparse.ArgumentParser:
    from mrh.adapters.hosts.registry import REGISTRATIONS
    parser = argparse.ArgumentParser(
        prog="mrh",
        description="Inspect local model-routing candidate statistics and integration status.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    models = commands.add_parser('models', help='current host-advertised model declarations; no paid account probe')
    models.add_argument('--host',choices=tuple(REGISTRATIONS),required=True)
    models.add_argument('--json',action='store_true')

    for name, help_text in (("status", "card dashboard"), ("stats", "statistics in plain language")):
        parser_for = commands.add_parser(name, help=help_text)
        _add_stats_options(parser_for)
        if name == "stats":
            reset = parser_for.add_subparsers(dest="stats_action").add_parser("reset", help="delete statistics (preview first; needs a typed confirmation or --yes)")
            scope = reset.add_mutually_exclusive_group()
            scope.add_argument("--today", action="store_true", help="records since 00:00 today")
            scope.add_argument("--hours", dest="reset_hours", type=int, help="records within the last N hours (--hours 24 = the last 24 hours)")
            scope.add_argument("--days", dest="reset_days", type=int, help="records within the last N days")
            scope.add_argument("--all", action="store_true", help="every record")
            reset.add_argument("--settings", type=Path, default=argparse.SUPPRESS, help="settings.json (default: MRH_SETTINGS or the installed pointer)")
            reset.add_argument("--yes", action="store_true", help="really delete (without it: preview, or a typed confirmation when interactive)")

    ask = commands.add_parser("classify", help="ask the classifier about one task (advisory; nothing is delegated or stored)")
    ask.add_argument("task", nargs="?", help="the task text (or use --stdin)")
    ask.add_argument("--stdin", action="store_true", help="read the task text from standard input")
    ask.add_argument("--title", help="the delegation's short description (sent to Jev as extra data)")
    ask.add_argument("--role", help="a named sub-agent role (sent to Jev as extra data)")
    ask.add_argument("--platform", choices=("claude", "codex"), help="show only this platform's suggestion")
    ask.add_argument("--json", action="store_true", help="print the result as JSON")
    ask.add_argument("--settings", type=Path, help="settings.json (default: MRH_SETTINGS or the installed pointer)")

    usage = commands.add_parser("usage", help="what each recorded sub-agent actually used (read-only, local files)")
    usage_actions = usage.add_subparsers(dest="usage_action", required=True)
    collect = usage_actions.add_parser("collect", help="refresh settled sub-agent token snapshots from local transcripts")
    collect.add_argument("--days", type=float, default=None, help="only sub-agents from the last N days (default 30)")
    collect.add_argument("--json", action="store_true", help="print the result as JSON")
    collect.add_argument("--settings", type=Path, help="settings.json (default: MRH_SETTINGS or the installed pointer)")

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
    prepare.add_argument('--advisory',action='store_true',required=True,help='advisory routing (settings v2): no scope binding; serves Codex and Claude Code')
    prepare.add_argument('--codex-packets', action='store_true', help='Codex-only full-task packet artifact; use a separate root, never replace an active Claude artifact')
    show = plugin_actions.add_parser("show")
    show.add_argument("--root", required=True, type=Path)

    hook = commands.add_parser("hook", help="read one Codex hook JSON event from stdin")
    hook.add_argument("--settings", type=Path, help="explicit registered MRH-owned settings.json; default off")
    hook.add_argument("--platform", choices=tuple(REGISTRATIONS), required=True, help="advisory routing for this host (settings v2)")
    hook.add_argument("--codex-packets", action="store_true", help=argparse.SUPPRESS)
    packet = commands.add_parser("codex-task", help="opt-in Codex full-task packet preparation and receipt")
    packet.add_argument("--settings", type=Path, required=True)
    actions = packet.add_subparsers(dest="packet_action", required=True)
    prep = actions.add_parser("prepare")
    prep.add_argument("--body-file", type=Path, required=True)
    prep.add_argument("--workspace", type=Path, required=True)
    prep.add_argument("--user-model", help="only an explicit human choice, not the skill baseline")
    prep.add_argument("--user-effort", help="only an explicit human choice, not the skill baseline")
    for action in ("status", "finish"):
        p = actions.add_parser(action)
        p.add_argument("--id", required=True)
    actions.add_parser('import-history', help='explicit idempotent import of owned legacy packet history into the shared statistics DB')
    return parser




def _write_json(value: Any, stream: Any = None) -> None:
    if stream is None:
        stream = sys.stdout
    stream.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False, default=str))
    stream.write("\n")






def main(
    argv: Sequence[str] | None = None,
    *,
    stdin: Any = None,
    stdout: Any = None,
    stderr: Any = None,
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
    if args.command == "hook":
        from mrh.application import advisory_runtime
        from mrh.infrastructure.settings_v2 import resolve_settings_path
        try:
            path = resolve_settings_path(args.settings)
        except Exception:
            stderr.write("mrh: settings_path_invalid\n")
            response = {}
            if args.platform == "codex" and args.codex_packets:
                from mrh.adapters.hosts import codex_packets as packets
                try:
                    event = json.loads(stdin.read(advisory_runtime.MAX_EVENT_BYTES + 1))
                    if packets.marked(event) and event.get("hook_event_name") == "PreToolUse":
                        response = packets._deny("packet_settings_path_invalid")
                except Exception:
                    pass
            stdout.write(json.dumps(response) + "\n"); return 0
        if args.codex_packets and args.platform != "codex":
            stderr.write("mrh: codex_packets_platform_invalid\n"); stdout.write("{}\n"); return 2
        return advisory_runtime.run(args.platform, path, stdin, stdout, stderr, codex_packets=args.codex_packets)

    # Keep command output directed through the caller-provided streams as well.
    old_stdout, old_stderr = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = stdout, stderr
    try:
        if args.command == 'models':
            from mrh.adapters.catalogs.catalog import public_models, CatalogError
            try:
                data=public_models(args.host).public()
                if args.json:_write_json(data)
                else:
                    stdout.write(f"{data['tool']} · {data['version']} · {data['source']} ({data['assurance']})\n")
                    for m in data['models']:stdout.write(m['id']+' · '+m['label']+' · '+', '.join(m['efforts'])+' · '+m['state']+'\n')
                return 0
            except CatalogError as exc:
                _write_json({'host':args.host,'models':[],'assurance':'unknown','error':str(exc)})
                return 2
        if args.command in {"stats", "status"}:
            from mrh.presentation import ctrl
            args.ctrl_action = "reset" if getattr(args, "stats_action", None) == "reset" else "dashboard" if args.command == "status" else "stats"
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
        if args.command == "usage":
            from mrh.presentation import usage_cli
            return usage_cli.main(args, stdin=stdin, stdout=stdout, stderr=stderr)
        if args.command == "classify":
            from mrh.presentation import classify_cli
            return classify_cli.main(args, stdin=stdin, stdout=stdout, stderr=stderr)
        if args.command == "ctrl":
            from mrh.presentation import ctrl
            return ctrl.main(args, stdin=stdin, stdout=stdout, stderr=stderr, color=_wants_color(args))
        if args.command == "key":
            from mrh.presentation import key_cli
            return key_cli.run(args.action, args.name, stdout=stdout, stderr=stderr)
        if args.command == "plugin":
            from mrh.infrastructure import plugin
            from mrh.infrastructure.owned import OwnedError
            try:
                _write_json(plugin.prepare(args.root, args.settings, args.python,advisory=args.advisory,codex_packets=args.codex_packets) if args.plugin_action == "prepare" else plugin.show(args.root))
                return 0
            except OwnedError as exc:
                stderr.write("mrh: " + getattr(exc,'reason',str(exc)) + "\n")
                return 2
        if args.command == "codex-task":
            from mrh.adapters.hosts import codex_packets as packets
            from mrh.infrastructure import owned
            try:
                if args.packet_action == "prepare":
                    task = owned.read_regular(args.body_file, packets.MAX_TASK_BYTES).decode("utf-8")
                    result = packets.prepare(args.settings, task, args.workspace,
                                             user_model=args.user_model, user_effort=args.user_effort)
                elif args.packet_action == 'import-history':
                    from mrh.adapters.hosts.codex_packet_import import import_history
                    result = import_history(args.settings)
                else:
                    result = packets.status(args.settings, args.id, finish=args.packet_action == "finish")
                _write_json(result)
                return 0
            except (packets.PacketError, owned.OwnedError) as exc:
                stderr.write("mrh: " + exc.reason + "\n")
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
