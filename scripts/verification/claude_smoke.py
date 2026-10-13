#!/usr/bin/env python3
"""Claude Code regression check. Run after ANY change to shared MRH code; costs about $0.3 and needs a Jev key and a Claude login.

  python3 scripts/verification/claude_smoke.py

Uses an isolated scratch artifact + settings + database (never the daily ones), through the *installed* `mrh`
(~/.local/bin/mrh), so rebuild and `install_local.py` first if you changed code. Also statically checks the real
hook entry in ~/.claude/settings.json.  Exit code 0 only when every check passes.
"""
import json, os, shlex, shutil, sqlite3, subprocess, sys, tempfile, time
from pathlib import Path

MRH = shutil.which("mrh") or str(Path.home() / ".local/bin/mrh")
APP = Path.home() / ".local/share/model-routing-harness/app"
results = []
evidence = {"started_at": time.time(), "checks": [], "scenarios": []}


def save_evidence():
    target = os.environ.get("MRH_SMOKE_EVIDENCE_DIR")
    if target:
        path = Path(target).resolve()
        path.mkdir(parents=True, exist_ok=True)
        (path / "smoke-results.json").write_text(json.dumps(evidence, indent=2) + "\n")


def check(name, ok, detail=""):
    results.append(bool(ok))
    evidence["checks"].append({"name": name, "passed": bool(ok), "detail": detail})
    save_evidence()
    print(("PASS  " if ok else "FAIL  ") + name + (f"   {detail}" if detail else ""))


def mrh(*args):
    r = subprocess.run([MRH, *args], capture_output=True, text=True)
    if r.returncode:
        evidence["helper_failure"] = {"command": list(args[:2]), "returncode": r.returncode}
        save_evidence()
        raise SystemExit(f"mrh {' '.join(args[:2])} failed (exit {r.returncode}); raw stderr not retained")
    return r.stdout


def static_install_check():
    path = Path.home() / ".claude/settings.json"
    hooks = json.loads(path.read_text()).get("hooks", {}) if path.exists() else {}
    for event in ("PreToolUse", "PostToolUse"):
        entries = [h for e in hooks.get(event, []) for h in e.get("hooks", []) if "model-routing-harness" in h.get("command", "")]
        ok = len(entries) == 1
        check(f"~/.claude/settings.json has exactly one MRH {event} hook", ok)
        if ok:
            parts = shlex.split(entries[0]["command"])
            check(f"{event} hook files exist and it passes the 'claude' platform argument",
                  Path(parts[0]).exists() and Path(parts[-2]).exists() and parts[-1] == "claude", entries[0]["command"][:110])


def scenario(work, settings_json, db, prompt, model="opus", env=None):
    e = dict(os.environ, **(env or {})); e.pop("CLAUDE_CODE_SIMPLE", None)
    before = 0
    if Path(db).exists():
        with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as con:
            before = con.execute("select count(*) from advice").fetchone()[0]
    record = {"index": len(evidence["scenarios"]) + 1, "requested_parent_model": model, "returncode": None}
    started = time.monotonic()
    try:
        r = subprocess.run(["claude", "-p", "--model", model, "--settings", settings_json, "--setting-sources", "", "--no-session-persistence",
                            "--permission-mode", "bypassPermissions", "--max-budget-usd", "1.0", "--output-format", "json", prompt],
                           capture_output=True, text=True, timeout=420, cwd=work, env=e)
        record["returncode"] = r.returncode
        try:
            output = json.loads(r.stdout)
            record["is_error"] = output.get("is_error")
            record["usage"] = {k: v for k, v in output.get("usage", {}).items() if type(v) in (int, float)}
            record["total_cost_usd"] = output.get("total_cost_usd")
        except (ValueError, AttributeError):
            record["output_format_error"] = "not_expected_json"
    except subprocess.TimeoutExpired:
        record["failure_reason"] = "claude_process_timeout"
        raise
    finally:
        record["elapsed_seconds"] = time.monotonic() - started
        try:
            with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as con:
                con.row_factory = sqlite3.Row
                record["advice"] = [dict(row) for row in con.execute("select * from advice order by ts limit -1 offset ?", (before,))]
                record["children"] = [dict(row) for row in con.execute("select * from children order by ts")]
                record["attempts"] = [dict(row) for row in con.execute("select * from attempts order by ts")]
        except sqlite3.Error as exc:
            record["capture_error"] = type(exc).__name__
        evidence["scenarios"].append(record)
        save_evidence()
    if "capture_error" in record:
        raise RuntimeError("smoke_database_unavailable")
    decisions = [(row["action"], row["reason"]) for row in record["advice"]]
    kids = [(row["requested_model"], row["requested_effort"], row["resolved_model"], row["followed"]) for row in record["children"]]
    return r.returncode, decisions, kids


def run_scenarios(tmp):
    work, art, settings = tmp / "work", tmp / "art", tmp / "profile" / "settings.json"
    work.mkdir()
    (work / "utils.py").write_text("def total(items):\n    cnt = 0\n    for i in items:\n        cnt += i\n    return cnt\n")
    mrh("plugin", "prepare", "--advisory", "--root", str(art), "--settings", str(settings), "--python", str(APP / "runtime/bin/python3.11"))
    for k, v in (("classifier.provider", "jev"), ("tiers.Light.claude", "haiku:medium"), ("allowed_workspaces", str(work)), ("task_export", "on"), ("enabled", "on")):
        mrh("ctrl", "--settings", str(settings), "set", k, v)
    launcher = shlex.quote(str(art / "plugins/model-routing-harness/launcher.py"))
    command = f"{shlex.quote(str(APP / 'runtime/bin/python3.11'))} -I -B {launcher} claude"
    cs = tmp / "claude-settings.json"
    cs.write_text(json.dumps({"hooks": {ev: [{"matcher": "Agent|Task", "hooks": [{"type": "command", "command": command, "timeout": 50}]}] for ev in ("PreToolUse", "PostToolUse")}}))
    db = str(settings.parent / "advice.sqlite3")

    code, dec, kids = scenario(work, str(cs), db, "Use the Agent tool (subagent_type general-purpose) to rename the variable cnt to count in utils.py. Reply DONE.")
    check("A. light task: advised, then the parent re-issued it with the suggested model",
          code == 0 and ("advise", "advice_given") in dec and kids and kids[-1][3] == 1, f"{dec} {kids[-1:]}")
    check("A. the child really ran on Haiku 5.5 with the advised effort", bool(kids) and kids[-1][2] == "claude-haiku-5-5" and kids[-1][1] == "medium")

    code, dec, _ = scenario(work, str(cs), db, "Use the Explore subagent to list the python files here. Reply with the list.")
    check("B. built-in Explore subagent is left alone", code == 0 and dec == [("preserve", "named_role")], str(dec))

    code, dec, _ = scenario(work, str(cs), db, "Standing rule: every subagent must use model sonnet and effort medium. Use the Agent tool (subagent_type general-purpose) once to answer PONG. Reply DONE.")
    check("C. a model chosen by the user/parent is respected without calling the classifier", code == 0 and dec == [("preserve", "explicit_model")], str(dec))

    code, dec, _ = scenario(work, str(cs), db, "Use the Agent tool (subagent_type general-purpose) to answer PONG. Reply DONE.", env={"TYPESAFE_API_KEY": "invalid-key"})
    check("D. a rejected Jev key never blocks the delegation", code == 0 and dec == [("preserve", "typesafe_http_401")], str(dec))

def main():
    tmp = None
    try:
        static_install_check()
        if not all(results):
            raise RuntimeError("static_hook_prerequisite_failed")
        tmp = Path(tempfile.mkdtemp(prefix="mrh-smoke-")).resolve()
        (tmp / "OWNED.json").write_text(json.dumps({"owner": "MRH Claude smoke", "pid": os.getpid()}) + "\n")
        evidence["scratch_path"] = str(tmp)
        save_evidence()
        run_scenarios(tmp)
    except BaseException as exc:
        evidence["failure_type"] = type(exc).__name__
        if isinstance(exc, RuntimeError):
            evidence["failure_reason"] = str(exc)
        raise
    finally:
        passed = len(results) == 9 and all(results) and "failure_type" not in evidence
        if tmp and passed:
            shutil.rmtree(tmp)
        evidence.update(completed_at=time.time(), passed=sum(results), total=len(results),
                        all_nine_passed=passed, scratch_removed=bool(tmp and not tmp.exists()),
                        scratch_preserved_for_failure=bool(tmp and tmp.exists()))
        save_evidence()
    print(f"\n{sum(results)}/{len(results)} checks passed")
    sys.exit(0 if evidence["all_nine_passed"] else 1)


if __name__ == "__main__":
    main()
