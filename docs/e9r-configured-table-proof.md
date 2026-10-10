# E9R current configuration table and installed entry

E9R-B-001 corrects A D15's observed `status --settings` presentation defect and completes the new commands' offline installed-entry boundary. The current-data path now uses an aligned Tier / Requested Model / Effort / Mode table at wide widths, with a lavender bold Top row. The same presenter supplies stats/status and settings view/editor current/saved displays. Historical counts remain outside the table; they do not describe execution under the current policy.

Top Main shows `Current main agent`, no fixed target and no invented effort. Top Fixed reads only the real `fixed` mapping. Light/Small/Mid unset show `Unset`/`Preserve`, absent explicit effort shows `inherit`, and long identifiers wrap into aligned continuation rows without loss. At narrow widths the fields stack by tier, with explicit model/effort/mode. The accepted graphite/lavender palette, before/after Save summary and plain/NO_COLOR behavior remain.

CLI/editor persistence code is byte-identical to accepted E9. Settings schema, writer/locking, initial-revision rejection, gates, rates, cancellation, raw JSON, core/provider behavior and E8 host evidence are reused. E9R changes presentation and its assertions, not classification or routing. D15 resolved GPT clarification: configurable scope is model/optional effort per host and Top Main/Fixed. Rubric/prompt/0.5 are not editable requirements. Only the Codex candidate is supported; other hosts still need separate configuration and working adapters.

## Affected checks

[Verification](evidence/e9r-verification.json) records six focused checks passing in 0.076 seconds: three current-table semantic/geometry/sanitization groups and the three E9 public settings-flow cases with changed display assertions. They cover aligned columns, Top styling in both presenters, no history columns, ignored legacy Top, Main vs stored inactive Fixed, unset/inherit across widths 24/28/56/80/120, long IDs and terminal control stripping. Two initial fixture assertions were corrected (MODE matched a substring of MODEL; naive whole-output letter counting subtracted the old model); production code was unchanged for that retry. No broad E9/core/host rerun was added.

Impeccable layout was applied as a scoped refinement of the actual A screenshot and existing code/palette. The shell Node failed with `ERR_REQUIRE_ESM`; the bundled Node then loaded context and ran the before/after mechanical scan. Its empty web-detector results do not prove Python terminal geometry. Actual PTY output and column/cell-width checks supply that proof. A0 parent inspected those outputs; A owns final rendered acceptance. No native macOS Terminal window or new screenshot is claimed.

## Offline installed boundary

[Installed package evidence](evidence/e9r-package.json) records the existing stdlib PEP517 backend building the current wheel, followed by `pip --no-index --no-deps --no-build-isolation` in one owned temporary venv. All archive and installed Python file bytes match the candidate source manifest, including `settings_editor.py`. The actual installed `mrh` executable runs from an outside work directory with no `PYTHONPATH`; installed module paths and version are read back independently. This closes module/entrypoint packaging coverage without claiming global installation, version publication or installed Codex replacement.

The installed CLI performs init → interactive edit/Save → same-file JSON readback → settings view/status/raw stats JSON. Saved models and optional efforts match, enable/export remain off, repeated reads preserve settings/statistics, and switching to Main retains inactive Fixed data without displaying it. This isolated smoke completed in 3.715 seconds. No provider/model/credential request occurred. The owned venv, wheel, settings, event DB/key, temporary home and work directory were removed, with absence read back after cleanup. Archive/source identities and useful evidence remain; E3/E6/E9 history is not overwritten.

Current-data outputs for A's visible check:

- [120-column installed status](evidence/e9r-status-120.txt), [raw ANSI](evidence/e9r-status-120.ansi)
- [56-column installed status](evidence/e9r-status-56.txt), [raw ANSI](evidence/e9r-status-56.ansi)
- [Installed settings view](evidence/e9r-view-120.txt), [Main view](evidence/e9r-main-view-120.txt)
- [Installed editor current/review/saved transcript](evidence/e9r-editor-120.txt)

The `.ansi` preserves emitted styles with CRLF normalized; plain transcripts strip ANSI/display padding only. This is genuine POSIX PTY data from the installed CLI, not a fabricated image or a new web settings product.

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests python3.11 -m unittest test_config_table test_settings_cli.SettingsCliTests.test_save_readback_preserves_other_fields_and_json_dashboard_shape test_settings_cli.SettingsCliTests.test_unset_inherit_main_and_no_change_save test_settings_cli.SettingsCliTests.test_narrow_color_no_color_and_history_separation -v
PYTHONDONTWRITEBYTECODE=1 python3.11 scripts/verify_configured_package.py --output-prefix /absolute/evidence/e9r
```

The installed walkthrough validates a fresh owned temporary file; it does not touch real settings or activate routing. No full suite, host build, native lifecycle/Goal, true API/account, Monitor, global settings, image generation or remote push was used. Shared README/requirements/acceptance records remain A-owned. Executor metadata matched this active B turn as Sol 6.1/xhigh. Latest quota checkpoint is 8 percent remaining; below-7 natural save/pause and no reset/reserve remain. Original R1 and production/autonomous/model/platform gaps remain open.
