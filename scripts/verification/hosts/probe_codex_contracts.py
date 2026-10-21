#!/usr/bin/env python3
"""E1 only: credential-free installed schema/config discovery, never start a turn.

All host data written by these subprocesses lives in a TemporaryDirectory.
The output is a curated inventory, not raw config, private state, or a model
execution receipt. No hook is trusted, enabled in the real home, or executed.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
import argparse
import datetime
import json
import os
import queue
import subprocess
import tempfile
import threading
import time


def rpc_inventory(binary, home, cwd, effort=None):
    env = {k: os.environ[k] for k in ("PATH", "HOME", "TMPDIR", "LANG") if k in os.environ}
    env["PATH"] = str(Path(binary).parent) + os.pathsep + env.get("PATH", "")
    # Official child-process config-home selector, never modify the caller's env.
    env["CODEX_HOME"] = str(home)
    command = [binary, "app-server", "--listen", "stdio://", "-c", 'model="mrh-cli-override"']
    if effort is not None:
        command.extend(["-c", "model_reasoning_effort=" + json.dumps(effort)])
    proc = subprocess.Popen(
        command,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, cwd=cwd, env=env,
    )
    inbox = queue.Queue()

    def collect():
        for line in proc.stdout:
            try:
                inbox.put(json.loads(line))
            except json.JSONDecodeError:
                pass

    reader = threading.Thread(target=collect, daemon=True)
    reader.start()
    next_id = 0

    def request(method, params):
        nonlocal next_id
        next_id += 1
        proc.stdin.write(json.dumps({"id": next_id, "method": method, "params": params}) + "\n")
        proc.stdin.flush()
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            item = inbox.get(timeout=max(0.01, deadline - time.monotonic()))
            if item.get("id") == next_id:
                return item
        raise TimeoutError(method)

    try:
        init = request("initialize", {"clientInfo": {"name": "mrh-e1", "version": "1"},
                                      "capabilities": {"experimentalApi": True}})
        if "error" in init:
            return {"initialize_error": init["error"]}
        proc.stdin.write('{"method":"initialized"}\n')
        proc.stdin.flush()
        config = request("config/read", {"cwd": str(cwd), "includeLayers": False})
        hooks = request("hooks/list", {"cwd": str(cwd)})
        c = config.get("result", {}).get("config", {})
        h = hooks.get("result", {})
        # Output only synthetic values and hook discovery metadata, never source text.
        return {"configured_model": c.get("model"),
                "configured_effort": c.get("model_reasoning_effort"),
                "config_error": config.get("error"),
                "hooks_error": hooks.get("error"),
                "hooks_result": h}
    except (queue.Empty, TimeoutError, BrokenPipeError) as exc:
        return {"probe_error": type(exc).__name__}
    finally:
        proc.stdin.close()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.terminate()
            proc.wait(timeout=3)
        proc.stdout.close()
        proc.stderr.close()


def inspect(binary):
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="mrh-e1-") as scratch:
        scratch = Path(scratch)
        home, cwd = scratch / "home", scratch / "workspace"
        home.mkdir()
        cwd.mkdir()
        # No credentials, provider request, hook execution, or global config write.
        (home / "config.toml").write_text('model = "mrh-home-synthetic"\nmodel_reasoning_effort = "high"\n')
        (home / "hooks.json").write_text(json.dumps({"hooks": {"PreToolUse": [
            {"matcher": "^spawn_agent$", "hooks": [{"type": "command", "command": "false", "timeout": 1}]}]}}))
        env = {k: os.environ[k] for k in ("PATH", "HOME", "TMPDIR", "LANG") if k in os.environ}
        env["PATH"] = str(Path(binary).parent) + os.pathsep + env.get("PATH", "")
        env["CODEX_HOME"] = str(home)
        version = subprocess.run([binary, "--version"], cwd=cwd, env=env,
                                 capture_output=True, text=True, timeout=10)
        output = scratch / "schema"
        generated = subprocess.run([binary, "app-server", "generate-json-schema", "--experimental", "--out", str(output)],
                                   cwd=cwd, env=env, capture_output=True, text=True, timeout=10)
        facts = {}
        if generated.returncode == 0:
            for filename in ("HookCompletedNotification", "ThreadStartParams", "TurnStartParams", "ThreadReadResponse"):
                obj = json.loads((output / "v2" / (filename + ".json")).read_text())
                facts[filename] = {"fields": list(obj.get("properties", {}))}
                defs = obj.get("definitions", {})
                if "HookEventName" in defs:
                    facts[filename]["events"] = defs["HookEventName"]["enum"]
                if "Thread" in defs:
                    facts[filename]["model_fields"] = {k: defs["Thread"]["properties"][k]
                                                         for k in ("model", "reasoningEffort")}
                if "ReasoningEffort" in defs:
                    facts[filename]["effort_schema"] = defs["ReasoningEffort"]
        rpc = rpc_inventory(binary, home, cwd)
        arbitrary_effort = rpc_inventory(binary, home, cwd, effort="mrh-invalid")
        return {"binary": binary, "version": version.stdout.strip(),
                "version_exit": version.returncode,
                "schema_generation_exit": generated.returncode, "schemas": facts,
                "arbitrary_effort_rpc": arbitrary_effort, "rpc": rpc,
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "limitations": ["No turn or agent was started", "No real model/provider execution",
                                "Hook discovered only; not trusted or executed", "No Top Main handback proof"]}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--binary", action="append", required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    start = time.monotonic()
    evidence = {"schema_version": 1, "evidence_kind": "installed-host-contract-probe",
                "recorded_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "platforms": [inspect(b) for b in args.binary]}
    evidence["elapsed_seconds"] = round(time.monotonic() - start, 3)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"output": str(args.output), "elapsed_seconds": evidence["elapsed_seconds"],
                      "versions": [x["version"] for x in evidence["platforms"]]}))


if __name__ == "__main__":
    main()
