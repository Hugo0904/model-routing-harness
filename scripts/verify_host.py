#!/usr/bin/env python3
"""Owned temporary installed-host fixture; loopback scripted provider only."""
import argparse
import copy
import datetime
import hashlib
import fcntl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import pty
import queue
import re
import select
import signal
import shutil
import shlex
import struct
import subprocess
import sys
import tempfile
import termios
import threading
import time

CATALOG_HASHES = {"0.159.3": "fd219bd9f061278275f528939f82f54d2eb97df4b25c23b022adbe48813d920b",
                  "0.162.0-alpha.17.2": "943ca7fe1d19ed019054158303f0dbbd80b3bef43b3aa425a71aa7cb3fb52c2b"}


class OwnedScratch:
    def __init__(self):
        self.path = Path(tempfile.mkdtemp(prefix="mrh-e4-"))
        self.processes = []

    def __enter__(self):
        return self.path

    def __exit__(self, *_):
        if any(proc.poll() is None for proc in self.processes):
            raise RuntimeError("cleanup_failed_temporary_home_preserved:" + str(self.path))
        shutil.rmtree(self.path)


def stop_owned(proc, pump=None, seconds=3):
    """Reap only a process created as its own fresh session/group leader."""
    def wait():
        deadline = time.monotonic() + seconds
        while proc.poll() is None and time.monotonic() < deadline:
            if pump is not None:
                pump()
            else:
                time.sleep(.01)
        if proc.poll() is None:
            raise subprocess.TimeoutExpired("owned_fixture", seconds)
        return proc.wait(timeout=seconds)
    try:
        return wait()
    except subprocess.TimeoutExpired:
        pass
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            if os.getpgid(proc.pid) != proc.pid:
                raise RuntimeError("owned_process_group_changed")
            os.killpg(proc.pid, sig)
        except ProcessLookupError:
            pass  # Exit can race with the signal; wait still confirms reaping.
        try:
            return wait()
        except subprocess.TimeoutExpired:
            continue
    raise RuntimeError("owned_process_reap_failed")


class Fixture:
    def __init__(self, scenario):
        self.requests = []
        self.root_id = None
        self.step = 0
        self.scenario = scenario

    def response(self, body, headers):
        tools = body.get("tools", [])
        namespaces = {x["name"]: [t["name"] for t in x["tools"]] for x in tools if x.get("type") == "namespace"}
        is_parent = "MRH_PARENT_" in json.dumps(body.get("input", []))
        self.requests.append({"model": body.get("model"), "reasoning": body.get("reasoning"),
                              "native_namespace_tools": namespaces, "is_parent": is_parent,
                              "function_outputs": [x for x in body.get("input", []) if x.get("type") == "function_call_output"]})
        if is_parent and self.step < (2 if self.scenario in ("double", "goal") else 1):
            self.step += 1
            ns = next((name for name, functions in namespaces.items() if "spawn_agent" in functions), None)
            if not ns:
                raise ValueError("native_spawn_tool_absent")
            arguments = {"message": "MRH_CHILD_" + self.scenario, "fork_context": False}
            if self.scenario == "explicit":
                arguments.update(model="mrh-synthetic-explicit", reasoning_effort="high")
            return [{"id": "fc-fixture-" + str(len(self.requests)), "type": "function_call", "name": "spawn_agent",
                     "namespace": ns, "call_id": "call-fixture-" + str(len(self.requests)),
                     "arguments": json.dumps(arguments), "status": "completed"}]
        output = {"id": "message-fixture", "type": "message", "role": "assistant",
                  "content": [{"type": "output_text", "text": "MRH scripted fixture complete."}]}
        return [output]


class Rpc:
    def __init__(self, binary, env, work, scope):
        self.proc = subprocess.Popen([binary, "app-server", "--listen", "stdio://"], cwd=work, env=env,
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                         start_new_session=True)
        scope.processes.append(self.proc)
        self.inbox = queue.Queue()
        self.events = []
        self.errors = []
        self.methods = []
        self.counter = 0
        def collect():
            for line in self.proc.stdout:
                try:
                    self.inbox.put(json.loads(line))
                except ValueError:
                    self.errors.append("non_json_stdout")
        def drain():
            for line in self.proc.stderr:
                self.errors.append(line.rstrip())
        threading.Thread(target=collect, daemon=True).start()
        threading.Thread(target=drain, daemon=True).start()

    def write(self, obj):
        self.proc.stdin.write(json.dumps(obj) + "\n"); self.proc.stdin.flush()

    def request(self, method, params):
        self.methods.append(method)
        self.counter += 1
        identity = self.counter
        self.write({"id": identity, "method": method, "params": params})
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            item = self.inbox.get(timeout=max(.01, deadline-time.monotonic()))
            if item.get("id") == identity:
                return item
            self.events.append(item)
        raise TimeoutError("rpc_timeout")

    def turn(self, parent, prompt):
        result = self.request("turn/start", {"threadId": parent, "input": [{"type": "text", "text": prompt}], "effort": "low"})
        if "error" in result:
            return result
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            item = self.inbox.get(timeout=max(.01, deadline-time.monotonic()))
            self.events.append(item)
            if item.get("method") == "turn/completed" and item.get("params", {}).get("threadId") == parent:
                return item
        raise TimeoutError("turn_timeout")

    def close(self):
        try:
            self.proc.stdin.close()
            stop_owned(self.proc)
        finally:
            self.proc.stdout.close(); self.proc.stderr.close()
        return self.proc.returncode

    def await_children(self, children):
        deadline = time.monotonic() + 10
        while True:
            done = {e.get("params", {}).get("threadId") for e in self.events if e.get("method") == "turn/completed"}
            if set(children).issubset(done):
                return
            item = self.inbox.get(timeout=max(.01, deadline-time.monotonic()))
            self.events.append(item)
            if time.monotonic() >= deadline:
                raise TimeoutError("child_completion_timeout")


def trust_fixture(binary, env, work, scope):
    """Use the actual CLI startup trust review, never edit its trust state."""
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 100, 0, 0))
    proc = subprocess.Popen([binary, "--no-daemon", "--no-alt-screen", "-C", str(work)],
                            stdin=slave, stdout=slave, stderr=slave, env=env, cwd=work, start_new_session=True,
                            preexec_fn=lambda: fcntl.ioctl(0, termios.TIOCSCTTY, 0))
    scope.processes.append(proc)
    os.close(slave)
    transcript = bytearray()
    def read_until(needle, seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if select.select([master], [], [], .1)[0]:
                try:
                    chunk = os.read(master, 65536)
                except OSError:
                    break
                transcript.extend(chunk)
                if b"\x1b[6n" in chunk: os.write(master, b"\x1b[1;1R")
                if b"\x1b[c" in chunk: os.write(master, b"\x1b[?1;2c")
                plain = re.sub(rb"\x1b\[[0-?]*[ -/]*[@-~]", b"", transcript)
                needles = needle if isinstance(needle, tuple) else (needle,)
                if any(n in plain or re.sub(rb"\s+", b"", n) in re.sub(rb"\s+", b"", plain) for n in needles):
                    return True
        return False
    try:
        folder_trust = False
        if not read_until((b"Trustallandcontinue", b"Trustthisfolder?"), 5):
            plain = re.sub(rb"\x1b\[[0-?]*[ -/]*[@-~]", b"", transcript)
            raise ValueError("supported_trust_review_not_found:" + plain.decode(errors="replace")[-1600:])
        compact = re.sub(rb"\s+", b"", re.sub(rb"\x1b\[[0-?]*[ -/]*[@-~]", b"", transcript))
        if b"Trustthisfolder?" in compact and b"Trustallandcontinue" not in compact:
            # Older CLI also asks to trust the empty, freshly owned workspace.
            # This official decision is saved only in the fixture CODEX_HOME.
            time.sleep(.25); os.write(master, b"\r")
            folder_trust = True
            if not read_until(b"Trustallandcontinue", 5):
                raise ValueError("hook_review_after_folder_trust_unavailable")
        # The caller creates and vets the exact fixture command before opening
        # this official review. Trust applies only to its fresh owned CODEX_HOME.
        time.sleep(.25)
        os.write(master, b"\x1b[B")
        time.sleep(.15)
        os.write(master, b"\r")
        if not read_until((b"To get started", b"MRH synthetic parent", b"mrh-synthetic-parent"), 5):
            plain = re.sub(rb"\x1b\[[0-?]*[ -/]*[@-~]", b"", transcript)
            raise ValueError("trust_review_completion_unverified:" + plain.decode(errors="replace")[-1800:])
        return {"method": "official CLI startup review Trust all and continue", "bypass_flag": False,
                "temporary_home_only": True, "official_temporary_folder_trust": folder_trust}
    finally:
        def pump():
            if select.select([master], [], [], .1)[0]:
                try: os.read(master, 65536)
                except OSError: pass
        try:
            os.write(master, b"\x03"); time.sleep(.15); os.write(master, b"\x03")
            stop_owned(proc, pump)
        finally:
            os.close(master)


def curate_events(events):
    curated = []
    for e in events:
        method, params = e.get("method"), e.get("params", {})
        if method in ("hook/started", "hook/completed"):
            run = params.get("run", {})
            curated.append({"method": method, "threadId": params.get("threadId"), "turnId": params.get("turnId"),
                            "run": {k: run.get(k) for k in ("id", "eventName", "status", "durationMs", "entries")}})
        elif method in ("item/started", "item/completed") and params.get("item", {}).get("type") == "collabAgentToolCall":
            curated.append({"method": method, "params": params})
        elif method == "turn/completed":
            curated.append({"method": method, "threadId": params.get("threadId"), "turn": params.get("turn")})
        elif method == "thread/goal/updated":
            curated.append({"method": method, "params": params})
    return curated


def check_case(scenario, parent, completed, requests, events, logs):
    pre = [x for x in logs if x["event"]["hook_event_name"] == "PreToolUse"]
    assert len(pre) == (2 if scenario in ("double", "goal") else 1), "pre_hook_count"
    assert all(x["event"]["session_id"] == parent for x in pre), "parent_correlation"
    assert sum(x["classifier_calls"] for x in pre) == (0 if scenario == "explicit" else len(pre)), "classification_count"
    assert completed["params"]["turn"]["status"] == "completed", "parent_not_completed"
    parents = [x for x in requests if x["is_parent"]]
    children = [x for x in requests if not x["is_parent"]]
    assert parents and all(x["model"] == "mrh-synthetic-parent" and x["reasoning"]["effort"] == "low" for x in parents), "parent_changed"
    ids = sorted({i for e in events if e.get("method") == "item/completed"
                  for i in e.get("params", {}).get("item", {}).get("receiverThreadIds", [])})
    if scenario in ("main", "double", "goal"):
        assert not ids and not children, "unexpected_child_after_main"
        assert all(x["output"]["hookSpecificOutput"]["permissionDecision"] == "deny" for x in pre), "main_not_denied"
        assert any("blocked by PreToolUse hook" in str(x["function_outputs"]) for x in parents), "host_denial_missing"
    else:
        assert len(ids) == 1 and len(children) == 1, "child_missing_or_duplicated"
        expected = "mrh-synthetic-fixed" if scenario == "fixed" else "mrh-synthetic-explicit" if scenario == "explicit" else "mrh-synthetic-parent"
        assert children[0]["model"] == expected, "child_request_model_mismatch"
        assert children[0]["reasoning"]["effort"] == ("high" if scenario in ("fixed", "explicit") else "low"), "child_effort_mismatch"
        if scenario == "fixed":
            assert pre[0]["output"]["hookSpecificOutput"]["updatedInput"]["model"] == expected, "fixed_rewrite_missing"
        else:
            assert pre[0]["output"] == {}, "passthrough_changed"
    return {"status": "passed", "classified_events": sum(x["classifier_calls"] for x in pre),
            "host_created_child_ids": ids, "parent_model_unchanged": True, "parent_effort_unchanged": True,
            "requested_synthetic_child_models": [x["model"] for x in children], "autonomous_main_handback": False}


def inspect(binary, scenario, catalog_path=None):
    started = time.monotonic()
    fixture = Fixture(scenario)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_): pass
        def do_POST(self):
            size = int(self.headers.get("Content-Length", "0"))
            if not self.path.endswith("/responses") or size > 2_000_000:
                self.send_error(400); return
            body = json.loads(self.rfile.read(size))
            assert self.headers.get("Authorization") is None, "unexpected_provider_credentials"
            output = fixture.response(body, self.headers)
            response = {"id": "resp-fixture-" + str(len(fixture.requests)), "status": "completed", "output": output,
                        "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2,
                                  "input_tokens_details": {"cached_tokens": 0}}}
            events = [{"type": "response.created", "response": {"id": response["id"], "status": "in_progress", "output": []}}]
            for index, item in enumerate(output):
                events.extend([{"type": "response.output_item.added", "output_index": index, "item": item},
                               {"type": "response.output_item.done", "output_index": index, "item": item}])
            events.append({"type": "response.completed", "response": response})
            payload = "".join("data: " + json.dumps(event) + "\n\n" for event in events).encode()
            self.send_response(200); self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(payload))); self.end_headers(); self.wfile.write(payload)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    serving = threading.Thread(target=server.serve_forever, daemon=True); serving.start()
    try:
        scope = OwnedScratch()
        with scope as scratch:
            scratch = Path(scratch); home, work = scratch/"home", scratch/"workspace"
            home.mkdir(); work.mkdir()
            env = {"PATH": str(Path(binary).parent)+":/usr/bin:/bin:/usr/sbin:/sbin", "HOME": str(scratch),
                   "CODEX_HOME": str(home), "LANG": "en_US.UTF-8", "TERM": "xterm-256color"}
            version = subprocess.run([binary, "--version"], env=env, capture_output=True, text=True, check=True, timeout=5).stdout.strip()
            catalog_fact = None
            catalog_config = ""
            if catalog_path is not None:
                original = catalog_path.read_bytes()
                assert hashlib.sha256(original).hexdigest() == CATALOG_HASHES.get(version.split()[-1]), "catalog_version_hash_mismatch"
                source = next(x for x in json.loads(original)["models"] if x["slug"] == "gpt-6.1-sol")
                aliases = []
                for suffix, effort in (("parent", "low"), ("fixed", "high"), ("explicit", "high")):
                    entry = copy.deepcopy(source)
                    entry.update(slug="mrh-synthetic-" + suffix, display_name="MRH synthetic " + suffix,
                                 description="Scripted loopback fixture only; no actual model", upgrade=None,
                                 availability_nux=None, default_reasoning_level=effort,
                                 tool_mode=None, multi_agent_version="v1", use_responses_lite=False,
                                 supports_search_tool=False)
                    aliases.append(entry)
                catalog = scratch/"synthetic-models.json"
                catalog.write_text(json.dumps({"models": aliases}))
                catalog_config = "model_catalog_json=" + json.dumps(str(catalog)) + "\n"
                catalog_fact = {"installed_version": version, "source_sha256": hashlib.sha256(original).hexdigest(),
                                "source_tag": "rust-v" + version.split()[-1],
                                "source_path": "codex-rs/models-manager/models.json", "aliases": [x["slug"] for x in aliases],
                                "fixture_capability_overrides": {"tool_mode": None, "multi_agent_version": "v1",
                                   "use_responses_lite": False, "supports_search_tool": False},
                                "actual_model_execution": False}
            base = "http://127.0.0.1:" + str(server.server_address[1]) + "/v1"
            (home/"config.toml").write_text('model="mrh-synthetic-parent"\nmodel_reasoning_effort="low"\nmodel_provider="mrh_fixture"\nsandbox_mode="workspace-write"\napproval_policy="never"\n[model_providers.mrh_fixture]\nname="MRH loopback fixture"\nbase_url='+json.dumps(base)+'\nrequires_openai_auth=false\nwire_api="responses"\nrequest_max_retries=0\nstream_max_retries=0\n[analytics]\nenabled=false\n')
            (home/"config.toml").write_text(catalog_config + (home/"config.toml").read_text())
            wrapper = scratch/"fixture_hook.py"
            log = scratch/"hook-events.jsonl"
            db_path = scratch/"facts.sqlite3"
            control = scratch/"scenario.txt"
            control.write_text("main")
            wrapper.write_text('''import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from mrh.codex import handle_event
from mrh.core import Classification, ScriptedClassifier
from mrh.store import Store
event=json.load(sys.stdin)
scenario=Path(sys.argv[4]).read_text().strip()
caps={"configuration_known":True,"main_model":"mrh-synthetic-parent","main_effort":"low",
      "original_model":"mrh-synthetic-parent","original_effort":"low","original_resolution_known":True,
      "roles":{"default":{"known":True,"rewrite_allowed":True}},
      "models":{"mrh-synthetic-fixed":{"available":True,"efforts":["high"]}}}
policy={"top_mode":"Main" if scenario in ("main","double","goal") else "Fixed",
        "fixed":{"model":"mrh-synthetic-fixed","effort":"high"}}
classifier=ScriptedClassifier([RuntimeError("fixture_error") if scenario=="failure" else Classification("Top",.49 if scenario=="low" else .9)])
output=handle_event(event,Store(sys.argv[2]),True,classifier=classifier,policy=policy,capabilities=caps)
safe={key:event.get(key) for key in ("hook_event_name","session_id","turn_id","tool_use_id","tool_name","tool_input","tool_response")}
with Path(sys.argv[3]).open("a") as f:f.write(json.dumps({"event":safe,"output":output,"classifier_calls":classifier.calls})+"\\n")
print(json.dumps(output))
''')
            command = shlex.join([sys.executable, str(wrapper), str(Path(__file__).resolve().parents[1]/"src"), str(db_path), str(log), str(control)])
            (home/"hooks.json").write_text(json.dumps({"hooks": {kind: [
                {"matcher": "^spawn_agent$", "hooks": [{"type": "command", "command": command, "timeout": 5}]}]
                for kind in ("PreToolUse", "PostToolUse")}}))
            trust = trust_fixture(binary, env, work, scope)
            rpc = Rpc(binary, env, work, scope)
            try:
                rpc.request("initialize", {"clientInfo": {"name": "mrh-e4", "version": "1"}, "capabilities": {"experimentalApi": True}})
                rpc.write({"method": "initialized"})
                hooks = rpc.request("hooks/list", {"cwd": str(work)})
                statuses = [h["trustStatus"] for row in hooks.get("result", {}).get("data", []) for h in row["hooks"]]
                assert statuses and all(x == "trusted" for x in statuses), statuses
                cases = []
                core_scenarios = ("main", "fixed", "double", "explicit", "low", "failure")
                scenarios = core_scenarios + ("goal",) if scenario == "all" else core_scenarios if scenario == "core" else (scenario,)
                for case in scenarios:
                    fixture.scenario = case; fixture.step = 0; control.write_text(case)
                    event_start, request_start = len(rpc.events), len(fixture.requests)
                    before_logs = len(log.read_text().splitlines()) if log.exists() else 0
                    thread = rpc.request("thread/start", {"cwd": str(work), "model": "mrh-synthetic-parent", "modelProvider": "mrh_fixture",
                                                      "sandbox": "workspace-write", "approvalPolicy": "never"})
                    if "error" in thread:
                        raise ValueError("thread_start_refused")
                    parent = thread["result"]["thread"]["id"]; fixture.root_id = parent
                    goal = None
                    if case == "goal":
                        goal = rpc.request("thread/goal/set", {"threadId": parent, "objective": "Exercise two scripted delegations in this isolated fixture", "status": "active", "origin": "user"})
                        if "error" in goal:
                            cases.append({"scenario": case, "status": "unsupported", "goal_response": goal}); continue
                    completed = rpc.turn(parent, "MRH_PARENT_" + case + " credential-free fixture. Use native delegation only.")
                    events = rpc.events[event_start:]
                    child_ids = {i for e in events if e.get("method") == "item/completed" for i in e.get("params", {}).get("item", {}).get("receiverThreadIds", [])}
                    rpc.await_children(child_ids)
                    if goal is not None:
                        goal = rpc.request("thread/goal/get", {"threadId": parent})
                        rpc.request("thread/goal/set", {"threadId": parent, "status": "complete", "origin": "user"})
                        rpc.request("thread/goal/clear", {"threadId": parent})
                    parent_read = rpc.request("thread/read", {"threadId": parent, "includeTurns": False})
                    parent_config = {k: parent_read["result"]["thread"].get(k) for k in ("id", "model", "reasoningEffort", "modelProvider")}
                    assert parent_config["model"] == "mrh-synthetic-parent" and parent_config["reasoningEffort"] == "low", "configured_parent_changed"
                    events = rpc.events[event_start:]
                    requests = fixture.requests[request_start:]
                    logs = [json.loads(line) for line in log.read_text().splitlines()[before_logs:]] if log.exists() else []
                    proof = check_case(case, parent, completed, requests, events, logs)
                    cases.append({"scenario": case, "parent_configured_identity": parent_config, "proof": proof,
                                  "requests": requests, "native_events": curate_events(events), "hook_events": logs, "goal_state": goal})
                result = {"evidence_kind": "installed_host_scripted_loopback_provider", "binary": binary, "version": version,
                          "catalog": catalog_fact, "trust": trust, "trust_status": statuses, "cases": cases,
                          "real_provider_requests": 0, "desktop_ui_validation": False,
                          "actual_OpenAI_model_execution": False, "actual_Jev_execution": False,
                          "rpc_methods": rpc.methods, "credential_environment_forwarded": False,
                          "auth_files_copied": False, "provider_auth_header_supplied": False,
                          "elapsed_seconds": round(time.monotonic()-started, 3)}
                sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"src"))
                from mrh.store import Store
                store = Store(db_path)
                result["synthetic_stats"] = store.stats(True)
                result["live_stats"] = store.stats()
                assert result["live_stats"]["jev_attempts"] == 0 and result["live_stats"]["confirmed_children"] == 0
                if scenario in ("core", "all"):
                    assert result["synthetic_stats"]["simulated_children"] == 4, "native_receipt_count_mismatch"
            finally:
                code = rpc.close()
            result["app_server_exit"] = code
        result["temporary_files_removed"] = not scratch.exists()
    finally:
        server.shutdown(); server.server_close(); serving.join(2)
    result["server_stopped"] = not serving.is_alive()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scenario", choices=("core", "all", "main", "fixed", "double", "explicit", "low", "failure", "goal"), default="core")
    parser.add_argument("--catalog", type=Path)
    args = parser.parse_args()
    result = inspect(args.binary, args.scenario, args.catalog)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"elapsed_seconds": result["elapsed_seconds"], "trust": result["trust_status"],
                      "version": result["version"], "cases": [{"scenario": c["scenario"], "proof": c.get("proof"), "status": c.get("status")} for c in result["cases"]],
                      "cleanup": {key: result[key] for key in ("app_server_exit", "temporary_files_removed", "server_stopped")}}, indent=2))


if __name__ == "__main__": main()
