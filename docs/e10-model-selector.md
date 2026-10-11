# E10 short model selector

E10-B-001 implements D19 with D20's keyboard correction. `mrh model light`, `small`, `mid`, `top`, and `mrh model` now open the existing local CLI's selector. In a real POSIX TTY, Up/Down and Enter select the AI/profile, model, supported effort and Save, including first-use binding confirmation and Top Main/Fixed. Left returns; Escape or Ctrl-C cancels. Numbers are optional. Non-interactive input exits explicitly without creating a profile or selecting a default model.

E10R implements D22/D23. Back retains the current profile's unsaved draft and returns one step. A classified target whose model or required effort is confirmed unusable requests a supported Hook deny, naming its tier/target and `mrh model <tier>`. Update the configuration and explicitly rerun as a new proposal. The same stopped call does not resume after settings changes. See [E10R evidence and acceptance steps](e10r-operator-stop.md).

Normal use requires no typed path, model ID, effort or confirmation word:

```sh
mrh model light
mrh model
```

First use lists detected installed tools and asks to create an MRH profile. Discovery alone is not binding, account login or working routing. One registered profile loads automatically; multiple profiles get a chooser. The registry lives at `~/.local/state/model-routing-harness/model-bindings`; separate sibling owned settings files remain the sole policy source. `--root /absolute/private/root` isolates acceptance. `--bind` explicitly adds a profile; advanced `--bind --associate-settings /absolute/owned/settings.json` associates known existing settings once, preserving values. This task installed no real user profile, changed no PATH or login, and retained A's preview.

The selector saves canonical request IDs and a separately chosen supported effort. `inherit` remains unresolved. Top Main changes only the mode, retaining inactive Fixed data and never setting the main model. Existing revision/CAS, cancellation, ownership, default-off/export/workspace gates, rates and JSON behavior remain. A final current snapshot rechecks model/effort; removed options or a failed refresh return to selection without a policy write. Binding/catalog conflicts and a changed executable require reopening/rebinding, not cache reuse or silent adoption. `--bind` creates a separate confirmed profile when an installation changes; it does not reset the old one.

## Actual coverage and remaining source contracts

| Tool or boundary | E10 result | Remaining claim |
|---|---|---|
| Codex shell 0.159.3 and bundled CLI 0.162.0-alpha.17.2 | Supported public `account/read` + `model/list` in fresh credential-free homes; model IDs/efforts come from returned values | Installed tool-advertised defaults only; account-specific access and same-call compatibility unconfirmed |
| Claude Code | Detected candidate; help/model docs inspected; selector states catalog unsupported | No implemented non-secret scoped catalog/effort/account adapter; SDK reference fetch failed at web size limit, not proof that no interface exists |
| Gemini CLI | Detected candidate; bundled help and model/ACP docs inspected; selector states catalog unsupported | ACP is an investigation route; complete no-auth scoped catalog/effort/account contract and adapter remain unverified |
| Retirement | Explicit authoritative retired entries are excluded and explained; missing entries mean unavailable in this list/scope | Codex ModelList supplies no explicit retirement signal; confirmed-retirement evidence here is synthetic |
| Execution | Existing trusted same-call unavailability and cached effects are checked; negative fixture catalog veto stays synthetic | Account-scoped catalog veto requires reliable host/account identity; downstream unavailable-error observation is absent from the current agent-id receipt seam |

The [official Codex picker contract](https://learn.chatgpt.com/docs/app-server#list-models-modellist) supplies model request IDs and supported efforts, including pagination. The adapter queries the actual installed native executable in a new temporary HOME/CODEX_HOME, with no credential environment and outbound proxies pointed at a closed loopback port. `account/read` must report no account. Source, exact executable hash/version, fetched epoch, scope and assurance are persisted with each binding's cache. Model IDs are not hard-coded and this chat's tool metadata is not used. Public `account/read` lacks a unique reliable account/workspace identity for this cache contract, so account-confirmed assertions are explicitly refused.

Successful snapshots replace only catalog metadata. Failure/partial/unauthenticated results preserve the last success for labeled display but cannot authorize selection or infer retirement. No background refresh occurs. Missing advertised defaults cannot veto an account-specific model. Only explicit retirement signals and isolated synthetic negative catalogs are consumed at the existing eligibility seam; catalog presence never manufactures HostSnapshot compatibility. There is no new downstream listener, blind child retry, Main conversion or paid call. [Claude model configuration](https://code.claude.com/docs/en/model-config), [Gemini model selection](https://geminicli.com/docs/cli/model/) and [ACP documentation](https://geminicli.com/docs/cli/acp-mode/) are discovery references, not evidence of working MRH adapters.

## Verification and interaction evidence

[Verification](evidence/e10-verification.json), [public-source discovery](evidence/e10-discovery.json), [installed entry](evidence/e10-package.json), and [synthetic error PTYs](evidence/e10-fixture-pty.json) retain identities, scope, failures and timing. Twenty-five focused cases passed in 0.451 seconds: 12 selector/catalog/registry groups and 13 affected existing fact/table/settings cases. No broad suite, host rebuild/replay or real API/model test was run. E9's unaffected persistence and E8/core/provider evidence are reused.

One final E10 offline install walkthrough completed in 3.736 seconds outside the source checkout/PYTHONPATH; all 26 archive and installed Python bytes matched the E10 candidate. Wheel SHA256: `ee086d828710f3d9fbafa5633898f83d3d807d33730e0068d079c099fc890cdb`. The actual installed `mrh` short command completed fresh binding, model selection, arrow-selected effort, Save, canonical readback and unchanged disabled/export gates. Actual public catalog observation is separate from simulated recovery. No model request occurred. Owned install state/venv/wheel and fixture homes are removed and absence read back.

Historical E10 actual PTY evidence:

- [First use, arrow-selected effort and Save at 120 columns](evidence/e10-first-use-120.ansi)
- [Missing saved target, explicit replacement at 56 columns](evidence/e10-unavailable-56.ansi)
- [Top Main at 120 columns](evidence/e10-top-main-120.ansi)
- [Synthetic failed refresh and recovery at 56 columns](evidence/e10-offline-recovery-56.ansi)
- [Synthetic explicit retirement and replacement](evidence/e10-retired-56.ansi)
- [Synthetic unavailable target and Escape cancellation](evidence/e10-unavailable-120.ansi)
- [Synthetic partial list and retry](evidence/e10-partial-56.ansi)
- [Synthetic offline cache and Cancel](evidence/e10-offline-120.ansi)

Each ANSI has a corresponding plain `.txt` transcript. Raw ANSI preserves emitted prompt padding and cursor movements; TXT strips styles/display padding. The ordinary source/docs/JSON/TXT diff check passes. Raw ANSI separately passes with an invocation-only `core.whitespace=-blank-at-eol` exemption for intentional prompt spaces; no global Git setting or raw output was changed. The initial staged whitespace check flagged those spaces and the initial local commit was created before separating the checks; this format review corrects the reporting gap. Five error PTYs passed in 0.562 seconds, using only arrows/Enter/Escape and verifying cancellation bytes. A0 parent inspected transcripts and readbacks. Native macOS Terminal appearance is unobserved. A completed E10 personal interaction/readback in D22 and found the Back defects; fresh E10R personal acceptance remains pending.

Initial issues are preserved in verification: a non-echoing test stream joined a prompt/frame (fixed by newline); a pre-D20 package assertion incorrectly compared a phrase across wrapped lines (helper normalization repaired and updated keyboard flow verified); and a new negative-only test found a None guard missing from an advertised omission (fixed before the final checks/package). These do not justify rerunning unrelated product checks. Whole-task effort and initial failed-smoke duration were not measured; package/check seconds above are scoped evidence.

## A's manual keyboard acceptance

Use an actual PTY with the installed candidate or source `PYTHONPATH=src`. Start `mrh model light --root /absolute/fresh/private/root`; choose an AI, confirm binding, choose a model and effort with arrows/Enter, then Save. Inspect `mrh settings show --path <owned settings path printed in the registry>` for exact IDs and unchanged activation/export/workspace fields. The root flag/readback command belong to isolated verification, not the normal user interaction. For multiple bound profiles, explicitly add another using `--bind`, then rerun the short command.

The [manual fixture helper](../scripts/model_selector_fixture.py) uses an explicit private owned root and refuses non-fixture existing bindings. It performs no host/provider call, preserves policy on subsequent runs and labels every source/error as synthetic:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3.11 scripts/model_selector_fixture.py --root /absolute/fresh/retired-root --scenario retired --width 56
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3.11 scripts/model_selector_fixture.py --root /absolute/fresh/offline-root --scenario offline --width 120
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3.11 scripts/model_selector_fixture.py --root /absolute/fresh/recovery-root --scenario recovery --width 56
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3.11 scripts/model_selector_fixture.py --root /absolute/fresh/partial-root --scenario partial --width 56
```

`unavailable` is also supported. `retired` exposes a synthetic old-model notice and only valid replacement options; Escape preserves its old mapping. `offline` retains a display-only last cache and offers Retry/Back/Cancel. `recovery` fails once then succeeds after Enter on Retry; `partial` similarly rejects the first incomplete list. Confirm canonical save and activation/export flags, or compare settings bytes across cancellation. Remove only the private root and its generated sibling `mrh-profile-<id>` after inspection. Automated reproduction helpers are [installed walkthrough](../scripts/verify_model_package.py) and [error PTYs](../scripts/verify_model_fixtures.py).

R2 provider/account/retirement-observation gaps and original R1 production/autonomous/Desktop gaps remain in the original denominator. Return this bounded E10 to A for actual interaction acceptance and the remaining decision. Latest account readback unexpectedly reports 1% used / 99% remaining instead of D19's historical 6%; the change's cause is unverified and B used no reset/reserve. The D19 return boundary still applies; no follow-on work is self-dispatched.

E10R changes source bytes; the older wheel does not contain these repairs. Package inclusion evidence is reused because the runtime module layout is unchanged; no E10R installed-byte identity is claimed.
