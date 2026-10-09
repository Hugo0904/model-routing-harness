# E2 settled implementation seams

Names in this note are B's within-contract implementation choices. R1 and A D2 remain authoritative. Runtime stdlib only; source package `mrh`, Python >=3.11.

CLI owns `src/mrh/cli.py`, terminal owns `src/mrh/terminal.py`. Installer owns `src/mrh/installer.py`. Parent owns core/service/store/codex/types and packaging. No worker edits another owner's files.

`Store(path)` creates a private SQLite store and sibling runtime-only HMAC key. `Store.stats(synthetic=False)` is pure and returns one JSON-safe object:

```
{
  "schema_version": 1, "updated_at": "ISO or null", "partition": "live|synthetic",
  "proposals": 0, "jev_attempts": 0, "synthetic_attempts": 0,
  "classified_tasks": 0, "low_confidence_tasks": 0,
  "tiers": {"Light": 0, "Small": 0, "Mid": 0, "Top": 0},
  "outcomes": {}, "requested_models": {}, "confirmed_children": 0,
  "actual_models": {}, "unknown_actual_model_children": 0,
  "cost": null, "tokens": null, "quota": null,
  "capabilities": {"jev": "unavailable", "codex": "candidate_unverified", "claude": "unsupported", "gemini": "unsupported"}
}
```

`simulation.run_demo(store)` inserts idempotent synthetic example events using core/service and returns stats(synthetic=True). It makes no remote call. CLI imports lazily; normal stats never demo/classify. CLI JSON must print exactly the same stats object; UI can format this object but never compute separate counters. CLI chooses flags/subcommand details. Default state path can be `~/.local/state/model-routing-harness/events.sqlite3` only when the user actually invokes CLI; import/--help/doctor/config-preview should not create it. Tests always pass `--db` under TemporaryDirectory. Include stats/status/doctor/config preview/demo and hook. Doctor describes unavailable/candidate boundaries and never probes credentials/network. For `hook`, delegate stdin JSON to `codex.handle_event(event, store=None, candidate=False, simulation=None)`; default return is `{}` passthrough. `--candidate` does not itself fabricate classification; a separate explicit simulation selector may inject a synthetic tier/confidence only for isolated tests/demo. Hook errors use safe stderr codes and machine stdout `{}`. The parent supplies the adapter.

Installer API after A D3: prepare(home,command,action)->Plan, apply(plan)->dict. Plan.public previews without private commands and says mutation_supported=false. Public apply/disable always refuse exclusive_target_unverified. Only SyntheticHome() creates and owns a private fresh TemporaryDirectory; its apply checks exact fixture ownership and serializes cooperating calls. No arbitrary path/flag establishes exclusivity. Fixture merges only managed pre/post spawn entries, preserves config/trust/main bytes and other hooks, checks source hashes, rejects malformed/TOML/ambiguous sources. Non-cooperating external-editor race remains documented, not fixed by a lock. Real shared-home activation/disable is unsupported in E2.

## E3 within-contract seams

Parent owns attempts.py deadline guard, typesafe.py permission/credential/HTTP transport, core/service/store lifecycle/cost/anomaly, docs/packaging/integration. Protocol worker owns only typesafe_protocol.py/test_typesafe_protocol.py, terminal worker only terminal.py/test_terminal_provider.py.
Protocol API: PINNED_MODEL='jev-1.13.0', serialize_request(task,context=None)->dict, parse_response(dict)->ParsedAnswer with .classification (core.Classification) and .telemetry dict containing requested_model, response_model, input_tokens, output_tokens. Optional usage invalid/absent -> both None. Typed errors use core.ClassifierFailure(reason, telemetry=None); fixed codes typesafe_malformed_response/typesafe_model_mismatch/typesafe_invalid_task, no raw JSON in exception. Only safe bounded actual model string may survive mismatch metadata. Four choice keys lower-case light/small/mid/top, our rubric version mrh-tier-v1. Parser uses provider confidence directly; finite probabilities over exact four keys must sum to1 (local floating point tolerance1e-6, official docs give no numeric tolerance). No client/transport/credential/Store code in protocol worker.
Stats v2 adds jev {attempt_states:{}, requested_models:{}, response_models:{}, input_tokens:null|int, output_tokens:null|int, known_input_tokens:int, known_output_tokens:int, usage_unavailable_attempts:int, estimated_cost:null|{amount,currency:'USD',kind:'estimate',model,price_source,price_date,unit}}, and handback_anomalies:int. CLI JSON stays Store.stats object. Renderer shows Jev telemetry separately from child actual models, provider cost is explicitly an estimate; unknown remains unavailable. Plain composition bar uses visible delimiters/glyphs plus counts/percentages, including width28. No UI redesign.
Final E3 seams: jev.source labels actual_provider_transport / explicit_synthetic_offline_transport / unavailable, and handback_anomaly_evidence separates confirmed/reported/synthetic counts. Injected transport must explicitly synthetic=True; only exact production HttpTransport is live. request(body,headers,deadline,enter) calls enter() first; it returns a closed/deadline check for network edges. Requested-but-not-entered invocation is not counted. Client strips credential/task/context model echoes before any metadata persistence. Ordinary cost requires original_model/original_effort/original_resolution_known=True.
