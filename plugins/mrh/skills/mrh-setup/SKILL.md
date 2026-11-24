---
name: mrh-setup
description: Finish the one-time local setup of Model Routing Harness (MRH) after the mrh plugin is installed, or check why MRH is not running. Use when the user says 「完成 MRH 設定」, 「檢查 MRH 設定」, "finish MRH setup" or "set up MRH". Shows a preview first and changes nothing until the user agrees.
---

# MRH setup

The `mrh` plugin only connects this host's delegation hooks to the MRH engine. The engine itself (a private
Python, the program, the `mrh` command) lives in the user's home directory and is installed by the steps
below. Until then the hooks pass every delegation through unchanged.

## Rules

- Preview first. Apply only after the user says yes to that preview in this conversation.
- Never ask for, read, type or store the Jev API key. The user stores it in their own terminal.
- Never enable MRH or widen its workspace scope for the user. Enabling sends task text to a paid classifier.
- Make no model or classifier call to test the result.
- If the host refuses network access or writes to the home directory, do not work around it. Give the user
  the commands from steps 2 to 4 to run in their own terminal, and continue from step 5 when they are done.
- Supported: macOS on Apple Silicon. On any other system stop and point the user to `docs/install.md` in the
  repository; this plugin's hook does not run there.

## Steps

`<host>` is `claude` when you are Claude Code and `codex` when you are Codex.

1. Look at what is there. Run `command -v mrh`. When it prints a path, run `mrh setup --check --json`.
   If `hosts.<host>.configured` is true, the engine is already connected: skip to step 5. If `mrh` exists
   but does not know `setup`, it is an older installation; continue, and the same steps move it over
   while keeping its settings, statistics and key.

2. Fetch the latest release into a private temporary directory.

   ```sh
   git ls-remote --tags --refs https://github.com/Hugo0904/model-routing-harness.git 'v*'
   ```

   Choose the highest `vMAJOR.MINOR.PATCH` tag from that list. If there is none, stop and tell the user no
   release has been published yet. Then:

   ```sh
   mrh_tmp=$(mktemp -d) && git clone --quiet --depth 1 --branch <tag> https://github.com/Hugo0904/model-routing-harness.git "$mrh_tmp/model-routing-harness"
   ```

3. Preview. From `$mrh_tmp/model-routing-harness`:

   ```sh
   ./setup --engine-only --host <host> --dry-run --json
   ```

   Add a second `--host` only when the user says they also use the other host and have this plugin there.
   Show the user the result in plain words, including:
   - every file under `apply_downloads`, with its size and address: the pinned, hash-checked Python 3.11
     runtime files that applying fetches. An empty list means nothing is downloaded. When the reason is
     `python_3_11_or_pinned_bootstrap_required`, this machine has no Python that can run the full preview;
     the list is still what applying fetches, and the items below still hold;
   - it writes under `~/.local/share/model-routing-harness`, `~/.config/model-routing-harness` and
     `~/Library/Caches/model-routing-harness`, links `~/.local/bin/mrh`, and adds a marked PATH block to the
     shell profile;
   - anything listed under `legacy_registration`: an older MRH hook registration that will be removed
     because this plugin replaces it;
   - MRH stays disabled afterwards.

4. Only after the user agrees, apply with the same arguments minus `--dry-run`:

   ```sh
   ./setup --engine-only --host <host> --json
   ```

   When `status` is not `installed`, report `reason` and stop; rerunning the same command resumes it.
   Then remove the temporary directory: `rm -rf "$mrh_tmp"`.

5. Tell the user what is left for them, using `next_steps` from the output when present. Do not do these
   for them:
   - Codex only: open `/hooks`, review and trust the two MRH hooks. They do not run before that.
   - In a new terminal: `mrh key set jev`.
   - `mrh ctrl` to choose models.
   - After agreeing that task text is sent to the classifier: `mrh setup --enable --workspace "/"`
     (`/` means every project; a project path limits it).

Later updates do not use this skill: the user runs `mrh update` in a terminal.
