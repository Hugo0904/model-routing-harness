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

from mrh.presentation.terminal import render_report, render_stats, terminal_width


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
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--db", type=Path, default=None, help="event database path")
    source.add_argument("--settings", type=Path, help="owned settings and associated event store")
    parser.add_argument("--synthetic", action="store_true", help="read the isolated synthetic partition")
    parser.add_argument("--json", action="store_true", help="print the unmodified statistics object")
    parser.add_argument("--details", action="store_true", help="show full statistics and telemetry")
    _add_display_options(parser)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mrh",
        description="Inspect local model-routing candidate statistics and integration status.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    model = commands.add_parser('model', help='choose a tier model from a bound tool catalog')
    model.add_argument('tier', nargs='?', type=str.lower, choices=('light','small','mid','top'),
                       help='tier to configure (omit for a picker)')
    model.add_argument('--root', type=Path, help='explicit MRH binding-state root for isolation')
    model.add_argument('--bind', action='store_true', help='confirm association of another detected tool/profile')
    model.add_argument('--associate-settings', type=Path, help='explicit known owned settings to associate (with --bind)')
    _add_display_options(model)

    for name, help_text in (
        ("stats", "show event statistics"),
        ("status", "show current local routing status and statistics"),
    ):
        command = commands.add_parser(name, help=help_text)
        _add_stats_options(command)

    ctrl = commands.add_parser("ctrl", help="control center: every MRH setting in one place")
    ctrl.add_argument("--settings", type=Path, help="settings.json (default: MRH_SETTINGS or the installed pointer)")
    ctrl_actions = ctrl.add_subparsers(dest="ctrl_action")
    ctrl_show = ctrl_actions.add_parser("show", help="print the current configuration")
    ctrl_show.add_argument("--json", action="store_true")
    ctrl_set = ctrl_actions.add_parser("set", help="change one setting (see `mrh ctrl keys`)")
    ctrl_set.add_argument("key"); ctrl_set.add_argument("value")
    ctrl_actions.add_parser("keys", help="list the settable keys")
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

    doctor = commands.add_parser("doctor", help="show capability boundaries without probing services")
    _add_display_options(doctor)

    config = commands.add_parser("config", help="preview or explicitly apply a Codex hook configuration change")
    config.add_argument("--home", type=Path, required=True, help="explicit Codex home to inspect")
    config.add_argument("--command", dest="hook_command", required=True, help="explicit MRH executable command for the hook")
    config.add_argument("--action", choices=("apply", "disable"), default="apply")
    config.add_argument("--apply", dest="write", action="store_true", help="write the prepared change")
    _add_display_options(config)

    settings = commands.add_parser("settings", help="manage an explicit MRH-owned settings file")
    actions = settings.add_subparsers(dest="settings_action", required=True)
    for action in ("init", "show", "configure", "enable", "disable", "edit", "view"):
        item = actions.add_parser(action)
        item.add_argument("--path", required=True, type=Path, help="canonical absolute settings.json path")
        if action in ("edit", "view"):
            _add_display_options(item)
        elif action not in ("init", "show"):
            item.add_argument("--expected-revision", type=int)
        if action == "configure":
            item.add_argument("--provider", choices=("codex_subscription", "typesafe"),
                              help="classifier source; separate from routed child models")
            item.add_argument("--policy", type=Path, help="explicit policy JSON file; does not enable routing/export")
            item.add_argument("--allow-workspace", action="append", default=None)
            item.add_argument("--clear-workspaces", action="store_true")
            allowlist = item.add_mutually_exclusive_group()
            allowlist.add_argument("--workspace-allowlist-file", type=Path)
            allowlist.add_argument("--clear-workspace-allowlist-file", action="store_true")
            export = item.add_mutually_exclusive_group()
            export.add_argument("--permit-task-export", dest="export_permission", action="store_true", default=None)
            export.add_argument("--deny-task-export", dest="export_permission", action="store_false")

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

    demo = commands.add_parser("demo", help="show isolated synthetic examples (temporary database by default)")
    demo.add_argument("--db", type=Path, default=None, help="event database path")
    demo.add_argument("--json", action="store_true", help="print the synthetic statistics object")
    demo.add_argument("--details", action="store_true", help="show full statistics and telemetry")
    _add_display_options(demo)

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


def _cmd_stats(args: argparse.Namespace) -> int:
    configuration = None
    database = args.db
    if args.settings is not None:
        from mrh.infrastructure import settings
        from mrh.infrastructure.settings_schema import SettingsError
        try:
            configuration = settings.read(args.settings)
        except SettingsError as exc:
            sys.stderr.write("mrh: " + exc.reason + "\n")
            return 2
        database = args.settings.parent / "events.sqlite3"
    stats = _store(database).stats(synthetic=args.synthetic)
    if args.json:
        _write_json(stats)
    else:
        width = args.width or terminal_width()
        sys.stdout.write(render_stats(stats, width=width, color=_wants_color(args), details=args.details,
                                     configuration=configuration))
    return 0


def _cmd_doctor(args: argparse.Namespace) -> int:
    report = render_report(
        "MRH  /  local capability check",
        {
            "Live classification": [
                "Codex subscription classifier: default-disabled; existing ChatGPT login, no API key; isolation required",
                "TypeSafe Jev adapter: retained for explicitly selected legacy profiles",
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
        from mrh.infrastructure.installer import apply, prepare

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
    from mrh.application.simulation import demo_policy, run_demo

    if args.db is None:
        with tempfile.TemporaryDirectory(prefix="mrh-demo-") as temporary:
            stats = run_demo(_store(Path(temporary) / "events.sqlite3"))
    else:
        stats = run_demo(_store(args.db))
    if args.json:
        _write_json(stats)
    else:
        sys.stdout.write(render_stats(stats, width=args.width or terminal_width(),
                                      color=_wants_color(args), details=args.details,
                                      demo_policy=demo_policy()))
    return 0


def _cmd_settings(args, stdin):
    from mrh.infrastructure import settings
    from mrh.infrastructure.settings_schema import SettingsError
    try:
        action = args.settings_action
        if action == "edit":
            from mrh.presentation.settings_editor import edit
            return edit(args.path, stdin=stdin, stdout=sys.stdout, width=args.width or terminal_width(), color=_wants_color(args))
        if action == "view":
            from mrh.presentation.terminal import render_configuration
            sys.stdout.write(render_configuration(settings.read(args.path), width=args.width or terminal_width(), color=_wants_color(args)))
            return 0
        if action == "init":
            value = settings.init(args.path)
        elif action == "show":
            value = settings.read(args.path)
        else:
            changes = {}
            if action in ("enable", "disable"):
                changes["enabled"] = action == "enable"
            else:
                if args.provider is not None:
                    changes["provider"] = args.provider
                    from mrh.application.classifier import PROVIDERS
                    changes['classifier_model'] = PROVIDERS[args.provider]
                if args.export_permission is not None:
                    changes["task_export_permitted"] = args.export_permission
                if args.clear_workspaces and args.allow_workspace is not None:
                    raise SettingsError("settings_conflict")
                if args.allow_workspace is not None or args.clear_workspaces:
                    changes["allowed_workspaces"] = args.allow_workspace or []
                if args.workspace_allowlist_file is not None or args.clear_workspace_allowlist_file:
                    changes["workspace_allowlist_file"] = args.workspace_allowlist_file
                if args.policy is not None:
                    from mrh.infrastructure.owned import read_regular
                    from mrh.adapters.providers.typesafe import _no_duplicate_keys
                    changes["policy"] = json.loads(read_regular(args.policy), object_pairs_hook=_no_duplicate_keys,
                                                  parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            value = settings.update(args.path, expected_revision=args.expected_revision, **changes)
        _write_json({"settings": value, "routing_enabled": value["enabled"],
                     "live_routing_ready": False, "readiness_reason": "missing_role_protection",
                     "installation_status": "not_inferred_from_settings", "credentials_probed": False})
        return 0
    except SettingsError as exc:
        sys.stderr.write("mrh: " + exc.reason + "\n")
    except Exception:
        sys.stderr.write("mrh: settings_invalid\n")
    return 2


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
    parser = build_parser()
    args = parser.parse_args(argv)
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
        if args.command == 'model':
            from mrh.infrastructure.bindings import default_root
            from mrh.presentation.model_selector import select
            if args.associate_settings is not None and not args.bind:
                stderr.write('mrh: --associate-settings requires --bind\n');return 2
            return select(args.root or default_root(), args.tier.title() if args.tier else None,
                          stdin=stdin, stdout=stdout, width=args.width or terminal_width(), color=_wants_color(args),
                          bind=args.bind, associate=args.associate_settings, **(model_dependencies or {}))
        if args.command in {"stats", "status"}:
            return _cmd_stats(args)
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
        if args.command == "doctor":
            return _cmd_doctor(args)
        if args.command == "config":
            return _cmd_config(args)
        if args.command == "settings":
            return _cmd_settings(args, stdin)
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
        if args.command == "demo":
            return _cmd_demo(args)
        parser.error("unknown command")
    except Exception:
        stderr.write("mrh: cli_error\n")
        return 2
    finally:
        sys.stdout, sys.stderr = old_stdout, old_stderr
    return 2
