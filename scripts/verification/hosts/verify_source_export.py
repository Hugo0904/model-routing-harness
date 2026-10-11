#!/usr/bin/env python3
"""Execute a reviewed owned Rust test producer; replay into MRH, never native CLI."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
import argparse
import json
import os
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
from mrh.infrastructure import settings
from mrh.routing.facts import CallScope
from mrh.adapters.hosts.isolated_host_export import SourceTestProducer
from mrh.application.runtime import configured_event
from mrh.infrastructure.store import Store
from mrh.adapters.providers.typesafe import HttpResponse
from mrh.adapters.providers.typesafe_protocol import PINNED_MODEL


class ScriptedTransport:
    synthetic = True

    def __init__(self, tier="top"):
        self.calls = 0
        self.tier = tier

    def request(self, body, headers, deadline, enter):
        enter()
        self.calls += 1
        probabilities = {tier: .1 for tier in ("light", "small", "mid", "top")}
        probabilities[self.tier] = .7
        response = {"model": PINNED_MODEL, "answers": {"tier": {"type": "choice", "choice": self.tier,
                    "probabilities": probabilities, "confidence": .9}}}
        return HttpResponse(200, json.dumps(response).encode())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--owned-root", type=Path, required=True)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--sha256", required=True, help="Reviewed build digest outside the wire")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    started = time.monotonic()
    producer = SourceTestProducer(args.owned_root, args.binary, args.sha256)
    root = producer.root
    environment = {"PATH": os.defpath, "HOME": str(root/"home"), "CODEX_HOME": str(root/"home/.codex"),
                   "TMPDIR": str(root/"tmp"), "LANG": "en_US.UTF-8"}
    emitted, exchanges = {}, {}
    cases = {"default": ("e7-default-call", "export_default_main_has_no_child_effect"),
             "protected": ("e7-source-call", "export_uses_real_resolver_and_frozen_role"),
             "targets": ("e7-target-call", "target_explicit_and_inherited_use_actual_resolver")}
    timings = {}
    for label, (call, suffix) in cases.items():
        scope = CallScope("codex", "00000000-0000-4000-8000-000000000001", "e7-source-turn", call)
        began = time.monotonic()
        exchange = producer.capture(scope, ["--exact", "tools::handlers::multi_agents::tests::pending_delegation_"+suffix,
                                           "--nocapture"], environment=environment)
        timings[label] = round(time.monotonic()-began, 3)
        exchanges[label] = exchange
        emitted[label] = json.loads(exchange._emission.payload)
    with tempfile.TemporaryDirectory(prefix="e7-replay-", dir=root/"tmp") as temporary:
        scratch = Path(temporary)
        work = scratch/"work"; work.mkdir()
        rows = []
        def replay(label, exchange, *, call_label=None, policy=None, tier="top"):
            state = scratch/label/"settings.json"
            settings.init(state)
            settings.update(state, enabled=True, task_export_permitted=True, allowed_workspaces=[str(work)],
                            policy=policy or {"top_mode": "Main"})
            scope = exchanges[call_label or label]._emission.scope
            event = {"hook_event_name": "PreToolUse", "tool_name": "spawn_agent", "cwd": str(work),
                     "session_id": scope.session_id, "turn_id": scope.turn_id, "tool_use_id": scope.tool_call_id,
                     "pending_delegation": {"known": True, "role_protection": "unprotected"},
                     "tool_input": {"message": "explicit isolated replay task", "pending_delegation": {"known": True}}}
            transport, keys = ScriptedTransport(tier), []
            def dummy():
                keys.append(1); return "explicit-synthetic-dummy"
            def invoke(value, resolver):
                return configured_event(value, state, host_resolver=resolver, transport=transport, credential_resolver=dummy)
            result = invoke(event, exchange)
            store = Store(state.parent/"events.sqlite3")
            stats = store.stats(True)
            rows.append({"case": label, "output": result, "outcomes": stats["outcomes"],
                         "scripted_transport_calls": transport.calls, "dummy_key_resolutions": len(keys)})
            return event, result, stats, store, invoke, transport, keys

        event, result, stats, store, invoke, transport, keys = replay("default", exchanges["default"])
        assert result["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert transport.calls == len(keys) == 1
        assert stats["synthetic_attempts"] == 1 and stats["actual_models"] == {} and stats["confirmed_children"] == 0
        assert invoke(event, exchanges["default"]) == result and transport.calls == 1 and store.stats(True) == stats
        # A different protected call uses its independently scoped emission.
        # Same-call changed-context replay is a separate parser-fixture test.
        protected_event = {**event, "tool_use_id": exchanges["protected"]._emission.scope.tool_call_id}
        assert invoke(protected_event, exchanges["protected"]) == {} and transport.calls == 1
        assert replay("protected", exchanges["protected"])[1] == {}
        model = emitted["targets"]["targets"][0]["model"]
        assert replay("targets", exchanges["targets"], policy={"top_mode":"Fixed", "fixed":{"model":model,"effort":"low"}})[1] == {}
        # Foreign source scope and an expired exchange fall back to the
        # conservative public resolver path with no classifier work.
        assert replay("foreign", exchanges["protected"], call_label="default")[1] == {}
        exchanges["default"].close()
        assert replay("expired", exchanges["default"], call_label="default")[1] == {}
        # Main permits classification; unknown target availability and absent
        # independently sourced rates keep the ordinary effect neutral.
        ordinary = replay("ordinary", exchanges["targets"], call_label="targets", tier="small",
                          policy={"top_mode":"Main", "tiers":{"Small":{"model":model,"effort":"low"}}})
        assert ordinary[1] == {}
        assert rows[-1]["outcomes"] == {"missing_target_model": 1}
        assert rows[1]["scripted_transport_calls"] == rows[2]["scripted_transport_calls"] == 0
        assert rows[3]["scripted_transport_calls"] == rows[4]["scripted_transport_calls"] == 0
    for exchange in exchanges.values():
        exchange.close()
    evidence = {"kind":"actual-patched-Rust-source-test-emission-to-MRH-synthetic-replay", "synthetic":True,
                "binary_sha256":args.sha256, "source_emissions":emitted, "producer_capture_seconds":timings,
                "replay_cases":rows, "repeated_call_no_extra_attempt":True,
                "protected_source_zero_additional_transport":True, "real_provider_requests":0,
                "patched_native_cli_run":False, "live_hook_freshness_verified":False,
                "real_child_spawned":False, "installed_host_changed":False,
                "owned_replay_state_removed":not scratch.exists(), "elapsed_seconds":round(time.monotonic()-started,3)}
    args.output.write_text(json.dumps(evidence,indent=2)+"\n")
    print(json.dumps({"emissions":len(emitted),"replays":len(rows),"elapsed_seconds":evidence["elapsed_seconds"],
                      "native_cli":False,"real_provider_requests":0,"cleanup":evidence["owned_replay_state_removed"]}))


if __name__ == "__main__":
    main()
