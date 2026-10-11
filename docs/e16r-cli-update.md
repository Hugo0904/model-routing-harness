# E16R: confirm an installed CLI update without replacing its profile

This repairs D35's unusable update recovery. The accepted E16 public Gemini transport and offline isolation remain unchanged. It is a local candidate, awaiting A's personal acceptance; it does not establish account access, Gemini routing or formal host adoption.

## Keyboard operation

Run the candidate's `mrh model light` (or the desired tier). When an installed CLI changes, the old catalog is display-only. In **LIST UNAVAILABLE**, use Up/Down and Enter to choose **Inspect updated installed CLI**. Select an installed CLI of the same kind; no path, model ID or shell command is entered. Left returns to the unavailable screen.

MRH describes that installation and obtains a fresh catalog before showing **CONFIRM CLI UPDATE**. Review the old/new executable, version and identity, then confirm or cancel with the same keys. Cancellation before confirmation retains the old binding. An unsupported Gemini version remains unsupported; retry does not relax the tested 0.63.0 boundary.

Confirmation updates only the existing binding's installation metadata and matching catalog. Its binding ID, settings path and profile association remain the same. The current unsaved model draft is retained. An absent model or incompatible effort is explained and requires an explicit choice or cancellation. Nothing substitutes or saves a model automatically. Top Main remains the user's choice.

Model policy still needs its separate ordinary **Save**. Cancelling model edits after confirming the CLI update retains the confirmed installation metadata but leaves policy/settings/history bytes unchanged. The screen states this distinction. A CLI update is not fault recovery or routing activation and cannot clear a stored operator stop.

## Ownership and failure behavior

`Registry.rebind` owns the single atomic registry replacement. It requires the reviewed registry revision and old binding identity, validates the same tool kind and new catalog scope/version, verifies the existing profile association, and rechecks the candidate installation hash under the registry lock. A catalog older than five minutes is refused. The new identity and its fresh catalog are written together; the old-scope catalog can never accompany an adopted identity.

Refresh now takes the registry revision captured before acquisition. Save also checks that revision along with its existing binding/catalog and policy CAS. A concurrent metadata winner is preserved. Failed acquisition, unsupported version, changed candidate during review, stale catalog or CAS conflict leaves the original identity/profile/policy/history intact. Existing failed-refresh diagnostics may remain. No second profile, state store or SQLite migration is introduced.

The stale empty-discovery text now includes the supported tested Gemini metadata path. The new flow uses the existing discovery, description and catalog adapters. No Hook, provider/authentication operation, vendor modification or activation is added.

## Local candidate and evidence

Candidate: `/Users/shawn/Code/model-routing-harness/dist/model-routing-harness-0.3.0-e16r-macos-arm64`.

Archive SHA256: `f8b7907938f4bbb63311b747380f9f77a7cf2a47a5012d69212e082651c0dd2a` (26,799,367 bytes). Manifest SHA256: `8267cdad863e0cf528655c8934855ae025c6d8450f0c4e5649c570ed9aaac3a4`. Runtime source commit: `83860170a84d7bcff8ff992e0f315840a387b788`.

The pinned E15 CPython 3.11.17 cache/runtime and 19 notices are reused without another download. The E15 and E16 candidates remain intact. The actual entry check uses a fresh owned HOME/work root, 24×56 PTY and an empty controlled PATH except the owned Gemini link. Node is the copied existing CLI prerequisite; MRH imports run from the bundle's private interpreter/archive.

Focused checks cover same-profile atomic replacement, policy/history and a real stored synthetic stop, catalogue/identity mismatch, commit-time installation changes, stale revision/catalog, concurrent refresh/save, cancellation, unsupported/failed acquisition, preserved draft/effort, missing selections and same-kind installation choice. See [verification summary](evidence/e16r-verification.json), [source identities](evidence/e16r-source-identity.json), [build](evidence/e16r-build.json), [actual keyboard entry](evidence/e16r-bundled-entry.json), and [cleanup](evidence/e16r-cleanup.json).

The final 41 focused checks passed in 0.617 seconds. The actual bundled keyboard flow passed in 33.332 seconds. All 2,059 manifest file/link records and 38 source identities match; all 27 unaffected runtime modules and the `target_veto` function retain their E16 bytes. Twelve retained owned process-group IDs are absent, disposable roots are removed, and the exact CLI-argument host query returns no remaining process.

The actual keyboard evidence changes only owned npm payload chunks while retaining the executable stub. It covers cancellation before update confirmation, accepted metadata followed by model cancellation, a draft interrupted by another update, explicit final Save, and actual unsupported-version refusal. Profile IDs, policy/history byte equality, fresh catalog scope, original public vendor identity and retained stored stop are read back. The stored stop is deliberately synthetic and does not replay native host/provider traffic.

Transcripts: [initial save](evidence/e16r-initial-save.txt), [cancel confirmation](evidence/e16r-cancel-confirm.txt), [confirm then cancel model edits](evidence/e16r-confirm-cancel.txt), [draft recovery and cancel](evidence/e16r-draft-recovery-cancel.txt), [separate Save](evidence/e16r-separate-save.txt), and [unsupported version](evidence/e16r-unsupported-cancel.txt).

The first PTY attempt timed out; its diagnostic run reached the unavailable screen. [The retained frame](evidence/e16r-bundled-entry.failure.json) and [exact isolated version diagnostic](evidence/e16r-version-diagnostic.json) established outer-tool sandbox interference: `sandbox-exec: sandbox_apply: Operation not permitted`, exit 71. The unchanged offline fixture passed after the approved execution permitted the original inner sandbox to start; private-path/network denies remained unchanged. Those unsuccessful attempts are not acceptance evidence. The final cleanup query likewise needed read-only host visibility because the outer sandbox's `pgrep` returned exit 3 with `sysmond service not found`.

Reuse E16's public ACP parsing, isolation canaries and process cleanup and the unaffected E14/D23 semantics. No whole old suite, native host build or new version matrix is run. A owns hands-on acceptance and the remaining original R1/R2/R3 obligations.
