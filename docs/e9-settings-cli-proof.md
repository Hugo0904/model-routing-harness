# E9 CLI model-policy configuration

E9-B-001 implements A D14's actual terminal settings flow. Users choose Light/Small/Mid model and optional effort, then Top Main or Fixed and its model/effort. Jev still chooses the tier; the existing rubric and 0.5 threshold are unchanged. This does not enable installed routing or prove account/model support. A owns visible acceptance and the unchanged full R1 denominator.

## Use the real CLI

From the repository, with Python 3.11+:

```sh
PYTHONPATH=src python3.11 -m mrh settings init --path /absolute/fresh/mrh-state/settings.json
PYTHONPATH=src python3.11 -m mrh settings edit --path /absolute/fresh/mrh-state/settings.json
PYTHONPATH=src python3.11 -m mrh settings view --path /absolute/fresh/mrh-state/settings.json
PYTHONPATH=src python3.11 -m mrh status --settings /absolute/fresh/mrh-state/settings.json
PYTHONPATH=src python3.11 -m mrh stats --settings /absolute/fresh/mrh-state/settings.json --json
```

Use `init` explicitly on a fresh or already MRH-owned settings folder. Edit/view never adopt an arbitrary JSON file or discover settings from a task. The editor displays current values first. Enter keeps a value, `unset` removes a Light/Small/Mid mapping, `inherit` removes its explicit effort, and `cancel` exits. Top Main refers to the current main agent; Fixed needs a target model and optional effort. Inactive stored Fixed settings remain intact when switching to Main. Model and effort identifiers are requests; host compatibility remains checked at delegation, not asserted by this editor.

The final before/after summary precedes a normal `save`/`cancel` choice. Before Save confirmation, cancel, EOF and Ctrl-C write nothing. After confirmation, the existing owned atomic writer runs with the initial revision as `expected_revision`; a concurrent actor's change refuses Save and asks the user to reopen. Unchanged Save does not rewrite the file. Other policy fields/rates/provider/workspaces/export/enabled remain intact; editing never enables routing, permits task export or calls a provider. No new writer or ownership bypass was added.

The new `settings view` is human-readable. Existing `init/show/configure/enable/disable` JSON output remains compatible. `status`/`stats --settings` validate that file before opening its associated `events.sqlite3`, and `--db` is mutually exclusive. Without `--settings`, prior database behavior remains. Stats JSON is the unchanged Store object, without presentation fields. Reading counts repeatedly adds no events.

Current model/effort configuration is shown separately from historical composition and confirmed execution. Top uses `policy.top_mode` and `policy.fixed`, never the ignored `tiers.Top`. An unset tier preserves the original delegation. `--details`, `--plain`, `NO_COLOR`, forced color and narrow/wide widths stay available. The graphite/lavender dashboard system is preserved. Operator settings cannot be combined with the fixed demo policy; no-argument `./demo` remains temporary and isolated.

## Evidence and reproduction

[Focused verification](evidence/e9-verification.json) records 26 passing checks in 0.206 seconds: seven new public settings-flow groups, 18 existing CLI/presentation compatibility cases, and one existing JSON settings/gate/idempotence case. Coverage includes saved-file equality, preservation of unrelated settings, initial-revision conflicts, cancel/EOF/Ctrl-C before Save, invalid/unowned refusal, invalid input recovery, Main/Fixed/unset/inherit, unchanged Save, ignored legacy Top, raw JSON, NO_COLOR, ANSI sanitization and 24/28/56/120-column fitting. Existing schema/locking/core/provider/host evidence is reused for unchanged guarantees; no full suite or host build was repeated.

The actual subprocess/PTY walkthrough passed in 0.723 seconds. It performs interactive Save, reads the same actual file through `settings show`, displays the associated store, checks cancel/EOF and a real Ctrl-C keystroke, and confirms repeated statistics plus isolated demo leave that settings file unchanged. One explicitly synthetic old-model proposal proves the associated DB path and history separation; it is not a demo execution under the current settings. There are zero provider calls, confirmed children or actual model claims.

Reviewable outputs are the [120-column editor transcript](evidence/e9-editor-120.txt), [56-column settings-backed dashboard](evidence/e9-status-56.txt), [actual Ctrl-C transcript](evidence/e9-cancel-pty.txt) and [policy/readback/cleanup](evidence/e9-walkthrough.json). Matching `.ansi` files preserve emitted styles with CRLF normalized; plain transcripts remove ANSI, right-side display padding and trailing empty display rows. This is a real POSIX terminal child, not an observed native macOS Terminal window or a new screenshot. A handles visible acceptance.

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests python3.11 -m unittest test_settings_cli test_cli test_settings_runtime.SettingsRuntimeTests.test_public_configuration_and_enable_are_independent_idempotent_and_read_only_show -v
PYTHONDONTWRITEBYTECODE=1 python3.11 scripts/verify_settings_editor.py --output-prefix /absolute/evidence/e9
```

The walkthrough uses one owned TemporaryDirectory, passes only a clean child environment, and removes settings/SQLite/key/temporary home afterward. No images, install changes, global settings, real credentials, external requests, Monitor identities, browser product, Goal or push are created. Raw/transcribed formal evidence remains. A's earlier visual and E8 commits are preserved; shared README/requirements/task acceptance records are left for A integration. Current executor metadata matched the active native B turn as `gpt-6.1-sol` / `xhigh`. Quota checkpoint is 9 percent remaining, with the human's below-7 pause rule unchanged and no reset/reserve.

A0 parent reviewed the changed consumer paths and actual transcripts. The full original product remains incomplete: production host adoption, true models/Jev/account, autonomous Main/Goal, platform integrations and final acceptance retain their prior gaps. E9 adds usable model-policy controls; it does not make classification definitions configurable pending A's separate clarification.
