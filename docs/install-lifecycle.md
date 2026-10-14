# Installation lifecycle

`./setup` owns checkout installation and update. `mrh_setup.py` owns preflight,
locks, generations, recovery and selected-host adapters. `mrh_bundle.py` owns the
existing fixed runtime/cache/archive/licensing build. Runtime routing, classifier
transport and child contracts do not depend on the installer.

## Ordering and storage

1. Resolve explicit roots and the existing active-settings pointer. Refuse a
   different pointer, foreign bin entry, unknown settings owner, unsupported
   platform/host or conflicting native plugin name/source.
2. Lock the owner-marked `setup-state/` directory. Recheck mutable targets.
3. Build and verify the complete manifest in private staging. Prepare selected
   artifacts there with final generation paths, include the optional skill only
   for packet opt-in, verify again, then rename the whole generation.
4. Store phase/intent in `journal.json`. Register each selected host through its
   own supported interface and read back. Codex uses its official commands;
   Claude performs a settings merge with an exclusive backup and CAS check.
5. Compare the CLI/current/pointer snapshots before replacing them. Commit the
   new state only after selected-host registration. Preserve prior generations.

The control directory is separate from strict settings directories. New settings
start disabled with export denied. Existing settings bytes, policy and statistics
are preserved absent explicit `--enable`/`--workspace`; a rollback never restores
an old database or profile. The current and previous managed manifests retain
reader-compatibility information. Unknown/incompatible readers are refused.

A legacy `app/` stays untouched. The stable bin link points through `current/`
to a new independent generation. This permits a Codex update without modifying
an interpreter/artifact still referenced by Claude. Nonselected hosts are not
rewired. A generation is retained while any configured host can reference it;
this installer does not automatically reclaim old generations.

## Failure and recovery

There is no atomic transaction across native hosts. Registration may complete
before the CLI switch. Intent, target generation and completed steps remain in
`journal.json`; rerunning the same source/arguments reconciles an observed
successful operation after lost acknowledgement. A different pending intent,
foreign marketplace source, unexpected pointer, modified manifest or foreign bin
entry is preserved as a conflict. Correct the actual cause before retrying.

Backups have unique names and retain exact prior Claude configuration bytes.
They are evidence/recovery material, not instructions to overwrite later edits.
The installer never writes Codex's private plugin database or trust records.
Trust review remains in the native UI. A disabled native plugin is preserved as
a preflight decision rather than silently re-enabled.

`--check` and `--dry-run` do not create MRH settings, databases or installation
roots. The latter also does not download. Public native metadata queries may
have the vendor CLI's own runtime behavior; they are not provider/model calls.
Policy readiness uses the public tool-advertised catalog, not account access.
Missing credentials, permission, trust, policy or model evidence stay pending.

## Bootstrap and scope

The shell entry can use an already available Python >=3.11. Otherwise, on macOS
arm64 only, it obtains the exact official runtime in `runtime-lock.json`, checks
size/hash before extraction/execution, then runs the same installer. No remote
shell script is executed. Existing build assets and licensing metadata are
reused. The bootstrap never overrides HOME/CODEX_HOME or installs a vendor CLI.
Explicit root arguments support isolated fixtures without pretending they are a
normal-account native installation. This is an unsigned local candidate.
