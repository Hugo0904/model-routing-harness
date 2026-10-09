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
