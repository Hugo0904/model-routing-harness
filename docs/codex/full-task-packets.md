# Codex opt-in full-task packets

This adapter supplies the complete proposed child task when the native hook sees
an opaque `message`. It does not change the advisory engine, Jev protocol, worker
contracts or model ranking. Unmarked Codex calls and all Claude calls keep their
existing route. Gemini has no hook integration here.

Use a **separate Codex artifact** prepared with `plugin prepare --advisory
--codex-packets`. Do not refresh an artifact referenced by Claude settings. Its
binding selects Codex packet wiring; invoking it as Claude is rejected. Keep the
previous Codex registration/artifact for recovery and read back Claude hashes.
The public prep CLI is available through the Codex artifact's `runtime.pyz` and
registered interpreter; the shared installed CLI can remain unchanged.

Read the installed plugin's public source and artifact metadata, then invoke:

```text
<artifact.python> -I -B <Codex plugin source>/runtime.pyz codex-task
  --settings <artifact.settings_path> prepare --body-file <owner-only task file>
  --session <verified native session UUID> --turn <verified native turn UUID>
  --workspace <verified native workspace>
```

Scope values come from supported native host metadata. CLI flags only declare
them; UUID format is not authenticity evidence. Missing trusted scope means this
integration is unavailable. The hook matches its actual native event and current
revision. Optional `--user-model`/`--user-effort` records only an explicit human
choice, never the skill baseline; the release must preserve such choices.

Preparation atomically creates a random packet ID, exact UTF-8 task hash and
length, and a ten-minute immutable packet. Its fixed owner-only directory is a
sibling of the settings profile. Regular-file, owner, permissions, no-symlink,
size, hash, scope, revision and expiry checks precede export. The packet ID is
not a native or Monitor request ID. Task names are `mrh_packet_<id>` and
`mrh_release_<id>`; the child message is exactly the packet's `task` field.

Query attempts are denied before child creation, even with a named worker/profile.
The adapter creates a distinct query with actual native scope, the full task and
no execution profile. Its per-packet store is separate from dispatch statistics.
It reuses the unchanged engine/provider and returns classification and candidates
without imposing a strength ranking. The skill compares complete model/effort
profiles with current capabilities and role restrictions. Top/Main continues in
the parent unless a recorded explicit human profile takes precedence.

Release uses the same packet/message and selected explicit profile; real worker
protections remain. Only the first release is permitted. A released call without
confirmed native spawn result stays unknown and retries are denied. This does
not promise exactly-once external execution. States are prepared, classifying,
classified, failed, released, completed, expired and cancelled. Nonblocking locks
explain contention; no enclosing DB transaction spans the network. Crashes and
provider failures are not silently retried. Invalid/disabled/export-denied opt-in
dispatch stops, while unmarked behavior remains unchanged.

`codex-task status --id <id>` returns a receipt without plaintext. `finish` cancels
an unreleased packet and removes its body; it refuses an unexpired unknown release.
Native spawn acknowledgement removes the body because this mode delivers it in
the message, not by later child file reads. Expired status reads also remove the
body and retain the receipt. Query DBs have no task text. Remove only this task's
temporary input when no longer needed; retain required evidence and receipts.

Query receipts include read-only native HTTP send/return observations: task and
wire-body hash/length plus response status/hash/length. Headers, keys and task text
are never logged, and real transport is not replaced. Send plus response proves
that boundary, not independent service-side receipt. Requested and observed child
execution profiles remain separate.
