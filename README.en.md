<div align="center">

# Model Routing Harness (MRH)

**Suggests a suitable model and reasoning effort for each subagent task.**

[Install with AI](#install-with-ai) · [Install yourself](#install-yourself) · [Commands](#commands) · [Uninstall](#uninstall) · [繁體中文](README.md)

</div>

## What it is

When the main AI (Codex or Claude Code) starts a subagent without choosing a model, MRH asks the Jev classifier how hard the task is (Light / Small / Mid / Top) and suggests re-issuing it with the model and reasoning effort you set for that level. Simple work goes to cheaper models; only hard work uses expensive ones.

- Your main chat's model is never switched; the main AI keeps the final say.
- Delegations that already name a model, an effort or a custom role are left alone.
- If classification fails or is unsure, the original call goes through unchanged.
- A new install is disabled until you agree to turn it on.

## Install with AI

Paste this to an AI that can operate your computer (for example Codex or Claude Code). It stops and asks whenever you need to act or decide:

```text
Please install MRH: https://github.com/Hugo0904/model-routing-harness
Follow docs/install.md in the repo (it is in Traditional Chinese) and:
1. Check my operating system and whether to install for Codex, Claude Code or both; ask me if unsure.
2. Keep my existing settings, keys, statistics, skills and other hooks. On any conflict or same-named command, stop and tell me; do not overwrite.
3. I enter the Jev key, log in and approve Codex hook trust myself; just tell me what to run.
4. Before enabling, ask which projects' task text may be sent to TypeSafe for classification; enable only after I agree.
5. Finish with --check --json, then run mrh status from an ordinary folder in a fresh terminal environment.
6. Report separately: install result, whether the mrh command works, hook trust, and tests not done. Do not call Jev or start subagents just to test (it costs money).
7. Finally ask whether I want the optional delegation skill; install it only if I say yes.
```

## Install yourself

**macOS (Apple Silicon)**: needs Git and a logged-in Codex or Claude Code. The installer brings its own Python.

```sh
git clone https://github.com/Hugo0904/model-routing-harness.git
cd model-routing-harness
./setup --host claude        # --host codex for Codex; give both for both
```

Open a new terminal window, then:

```sh
mrh key set jev              # store your Jev key (create one at https://console.typesafe.ai/keys)
mrh ctrl                     # choose the model for each level
```

Once you agree to send task text to TypeSafe, enable and check from the repo folder:

```sh
./setup --host claude --workspace "/" --enable   # "/" means all projects; or give a project path
./setup --check --json                           # check routing, trust and pending; this does not prove a real delegation
```

**Windows (x64)**: needs Git and a native x64 Python 3.11 or newer; no WSL. Both Codex and Claude Code have native evidence of classification, advice adoption and completed subagents. Claude catalog initialization runs in LPAC with only the `registryRead` capability added for Winsock initialization; network access stays denied. Remaining concurrency limits are documented in the [Windows validation record](docs/windows-validation.md). See the [Windows install guide](docs/install.md#windows-x64) (Traditional Chinese).

Normal installs run the packaged application without a source checkout. Developers can select `--dev` so the next CLI or hook process reads source edits, including with `--codex-packets`. Both modes retain settings and statistics without migration. Dual-mode installation and Windows packets are candidate features awaiting native acceptance; see [development mode](docs/development.md#本機開發安裝--dev).

## Cost and data export

- Classification uses the TypeSafe Jev API, billed to your TypeSafe account, separately from any Codex or Claude subscription.
- Once enabled, the text of each delegated task is sent to TypeSafe: the subagent's prompt for Claude Code; the task message for Codex, or only the task name when the message is encrypted. It is sent as is; MRH does not filter it.
- Optional features (Codex full-task classification, extra title and role, background summaries) send more; see [export rules](docs/design.md#外送與失敗處理) (Traditional Chinese).
- `mrh ctrl set enabled off` turns it off at any time.

## Commands

| Command | Purpose |
| --- | --- |
| `mrh ctrl` | Open the settings menu (models, confidence threshold, projects). |
| `mrh status` | Show the current state. |
| `mrh stats` | Show classification and delegation statistics. |
| `mrh usage collect` | Collect subagent usage from local records; no model call. Cost figures are estimates, not a bill. |
| `mrh usage overhead` | What advising costs (classifier wait, the extra main-model request) next to what it saves; local records only, no cost. |
| `mrh key status jev` | Check whether the Jev key is stored (never shows it). |
| `mrh ctrl set enabled off` | Turn routing off. |
| `mrh cleanup` | Preview removable scratch files; add `--apply` to remove them. Settings and statistics are untouched. |

After installing or updating, open a new terminal window so the `mrh` command is picked up.

## Optional: let the AI delegate on its own

In normal use the main AI rarely starts subagents, so MRH rarely gets a chance to help. To have the main AI act as the planner and hand bounded work to subagents, install this skill (the installer never does it for you):

```sh
mrh skill install --host claude   # --host codex for Codex
```

Status and removal: [delegation skills](docs/delegation-skills.md).

## Update

From the repo folder run `git pull --ff-only`, then rerun `./setup` with the same options as before (for example `./setup --host claude`). `./setup --rollback` returns to the previous version if something goes wrong. A new version exists only when program content changed; after a docs-only update, rerunning `./setup` reports no change.

## Uninstall

**macOS**, from the repo folder:

```sh
./setup --uninstall                      # preview only, changes nothing
./setup --uninstall --yes                # remove MRH, keep settings and statistics
./setup --uninstall --yes --purge-data   # also delete settings, statistics and the Jev key in the Keychain
```

Only what MRH created is removed; other hooks, settings and the rest of your shell startup files stay.

**Windows**: manual steps only, not yet verified on a real Windows machine. See [uninstall](docs/install.md#移除) (Traditional Chinese).

## Support

| Item | Status |
| --- | --- |
| macOS (Apple Silicon) | Supported. Brings its own Python 3.11. |
| Windows (x64) | Supported. Needs Python 3.11 or newer. |
| Linux, WSL, Intel Mac | Not supported. |
| Codex, Claude Code | Native classification, advice adoption and completed subagents verified on macOS and Windows. Claude Code 2.1.296 or newer on macOS. |
| Gemini | Not supported yet. |

The 2026-10-23 Mac acceptance covered the installed `6b0ebd8` update and native delegations on both hosts; Claude Code runs used 2.1.309. A subsequent minimal fix for disappearing SQLite sidecars is installed on both local hosts and passed the affected regressions and agreed concurrent workload. This fix follows commit `6b0ebd8`; that earlier commit does not contain it. Local installation and Git publication are verified separately. The native Codex disabled-profile case remains skipped under the handoff exception. See [validation](docs/validation.md) and [compatibility](docs/compatibility.md).

## License

[MIT](LICENSE). Third-party runtime licenses: [packaging/macos-arm64/LICENSES.md](packaging/macos-arm64/LICENSES.md).
