<div align="center">

# Model Routing Harness (MRH)

**Suggests a suitable model and reasoning effort for each subagent task.**

[繁體中文](README.md) · [Installation guide (Traditional Chinese)](docs/install.md) · [Docs index](docs/README.md)

</div>

MRH is a hook for Codex and Claude Code. When the main model starts a general-purpose subagent without choosing a model, an effort level or a named role, MRH asks the Jev classifier (TypeSafe API) how hard the task is (Light / Small / Mid / Top) and advises re-issuing the delegation with the model and effort you configured for that tier. The main AI keeps the final say, and the main chat's model is never switched. A model, effort or role you set explicitly always wins. Low confidence or any failure lets the original call through unchanged.

## What it does not do

- It does not change the model of your main conversation.
- It does not route delegations that already name a model, an effort or a custom role.
- It does not prove cost savings: usage figures are estimates, not a bill.

## Platforms

| Platform | Status |
| --- | --- |
| macOS, Apple Silicon | Supported. The installer brings its own pinned Python 3.11. |
| Windows x64 (native) | Supported. Needs Git and a native x64 CPython 3.11 or newer; nothing is downloaded. |
| Linux, WSL, Intel Mac | Not supported. |

Hosts: Codex and Claude Code (Claude Code 2.1.296 or newer on macOS). Details and known limits: [compatibility](docs/compatibility.md).

## Install (macOS)

You need Git and a logged-in Codex CLI and/or Claude Code CLI.

```sh
git clone https://github.com/Hugo0904/model-routing-harness.git
cd model-routing-harness
./setup --host claude            # or: --host codex, or both
```

Open a new shell, then check that the command resolves from an ordinary directory:

```sh
(cd "$HOME" && mrh status)
```

Create a key in the [TypeSafe console](https://console.typesafe.ai/keys), store it (macOS prompts for it and keeps it in the Keychain), and pick the models for each tier:

```sh
mrh key set jev
mrh ctrl
```

A fresh install is **disabled** and does not export anything. Enabling it needs your explicit consent to the scope, for example:

```sh
./setup --host claude --workspace "/" --enable   # "/" = all projects; use a project path to limit it
./setup --check --json                           # lists whatever is still pending
```

The full steps, including Windows, are in the [installation guide](docs/install.md) (Traditional Chinese). You can also paste the install prompt from the [Chinese README](README.md#交給-ai-安裝) to an AI that can operate your computer.

## Cost and data export

- Classification uses the TypeSafe Jev API. It is billed to your TypeSafe account, separately from any Codex or Claude subscription.
- Once enabled, the text of each delegated task is sent to TypeSafe for classification: for Claude Code the subagent's prompt (or its description if there is no prompt); for Codex the readable task message, or only the task name when the message is encrypted. The text is sent as is and MRH does not filter its content; your Jev key is used only to authenticate to TypeSafe. The optional Codex full-task classification, extra title/role fields and background summaries send more; see [export and failure handling](docs/design.md#外送與失敗處理) (Traditional Chinese).
- A new install is disabled and forbids export until you explicitly allow it. `mrh ctrl set enabled off` turns routing off at any time.

## Optional: delegation skill

`setup` never installs this. If you want the main AI to hand bounded work to subagents on its own (the main model as the brain, subagents as workers), you can install an optional skill:

```sh
mrh skill install --host claude   # or --host codex
```

See [delegation skills](docs/delegation-skills.md) for status, update and removal.

## Uninstall

On macOS run `./setup --uninstall` from the clone to preview, then add `--yes`. Settings and statistics are kept unless you also pass `--purge-data`, which additionally deletes them and the Jev key in the Keychain. Windows has manual steps only, not verified on a real Windows machine. See [Uninstall](docs/install.md#移除) (Traditional Chinese).

## License

[MIT](LICENSE). Third-party runtime licenses are in [packaging/macos-arm64/LICENSES.md](packaging/macos-arm64/LICENSES.md).
