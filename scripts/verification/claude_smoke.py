#!/usr/bin/env python3
"""Claude Code regression check. Run after ANY change to shared MRH code; costs about $0.3 and needs a Jev key and a Claude login.

  python3 scripts/verification/claude_smoke.py

Uses an isolated scratch artifact + settings + database (never the daily ones), through the *installed* `mrh`
(~/.local/bin/mrh), so rebuild and `install_local.py` first if you changed code. Also statically checks the real
hook entry in ~/.claude/settings.json.  Exit code 0 only when every check passes.
"""
import json, os, shlex, shutil, sqlite3, subprocess, sys, tempfile
from pathlib import Path

MRH = shutil.which("mrh") or str(Path.home() / ".local/bin/mrh")
APP = Path.home() / ".local/share/model-routing-harness/app"
results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(("PASS  " if ok else "FAIL  ") + name + (f"   {detail}" if detail else ""))


def mrh(*args):
    r = subprocess.run([MRH, *args], capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"mrh {' '.join(args)} failed: {r.stderr.strip()}")
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
    before = len(sqlite3.connect(db).execute("select 1 from advice").fetchall()) if Path(db).exists() else 0
    r = subprocess.run(["claude", "-p", "--model", model, "--settings", settings_json, "--setting-sources", "", "--no-session-persistence",
                        "--permission-mode", "bypassPermissions", "--max-budget-usd", "1.0", "--output-format", "json", prompt],
                       capture_output=True, text=True, timeout=420, cwd=work, env=e)
    con = sqlite3.connect(db)
    decisions = con.execute(f"select action,reason from advice order by ts limit -1 offset {before}").fetchall()
    kids = con.execute("select requested_model,requested_effort,resolved_model,followed from children order by ts").fetchall()
    return r.returncode, decisions, kids


def main():
    static_install_check()
    tmp = Path(tempfile.mkdtemp(prefix="mrh-smoke-")).resolve()
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

    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{sum(results)}/{len(results)} checks passed")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
