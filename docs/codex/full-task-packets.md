# Codex opt-in full-task packets

Packets are an explicit option, never the ordinary installation default.
Use `./setup --host codex --codex-packets` and retain that choice when updating
an existing opt-in installation. The [validation summary](../validation.md)
describes the limited title/full-text comparison; it does not prove opaque
native message equality, natural packet adoption or savings.

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
  --workspace <verified native workspace>
```

Preparation has no session/turn flags and no Monitor dependency. It stores the
workspace and current settings revision. After file/hash/workspace/revision/expiry
and export checks, the first valid query hook event binds its native session,
turn and tool-use ID once under the packet lock, before classification. The
binding lives in the receipt, not the immutable brief. Later query/release events
must match the bound session/turn; missing native scope and unbound release stop.
Optional `--user-model`/`--user-effort` records only an explicit human choice,
never the skill baseline; release must preserve it. Existing v1 bound packets
remain compatible until expiry after explicit history upgrade.

Preparation atomically creates a random packet ID, exact UTF-8 task hash and
length, and a ten-minute immutable packet. New plaintext lives in an owner-only
subdirectory of the fixed MRH project runtime/tmp/mrh; dispatch receipts remain
in the owned sibling of the settings profile. Legacy bodies remain under their
original lifecycle and are not swept by project cleanup. Regular-file, owner, permissions, no-symlink,
size, hash, scope, revision and expiry checks precede export. The packet ID is
not a native or Monitor request ID. Task names are `mrh_packet_<id>` and
`mrh_release_<id>`; the child message is exactly the packet's `task` field.

Query attempts are denied before child creation, even with a named worker/profile.
The adapter creates a distinct query with actual native scope, the full task and
no execution profile. Its scoped store view isolates query dedupe while writing
the same authoritative statistics database as dispatch.
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
the message, not by later child file reads. Status is read-only; explicit `finish`
cleans expired/cancelled bodies and retains the receipt. An expired hook read also
stops and cleans before export. Remove only this task's
temporary input when no longer needed; retain required evidence and receipts.

Query receipts include read-only native HTTP send/return observations: task and
wire-body hash/length plus response status/hash/length. Headers, keys and task text
are never logged, and real transport is not replaced. Send plus response proves
that boundary, not independent service-side receipt. Requested and observed child
execution profiles remain separate.

All new classification attempts, advice, releases and child records use the same
profile `advice.sqlite3`. Packet receipts contain retry/binding/cleanup/transport
control data, not a second classification ledger. Explicit packet links isolate
packet queries from ordinary task dedupe and same-model inference without
changing the decision engine. A query counts once; its release does not add a
second tier/call. A child counts once; adoption requires that exact release's
requested profile match the query's candidates. Another adequate skill choice
is recorded as classified and dispatched, with adoption false. Resolved model
and unreported usage remain unknown. `status`, `stats` and the dashboard share
this source, including packet classification/release/confirmed-child fields.

During a local upgrade, explicitly run:

```text
mrh codex-task --settings <same settings.json> import-history
```

It checks only the owned packet root and v1 receipt/query DB pairs. It preserves
original request/attempt/time facts and validates scope/hash plus any exact
existing release/child record before a central transaction adds them with an
import fingerprint. Repeating a successful import adds no counts. Incomplete,
conflicting or unverifiable history is reported under `unknown`; repair the
actual cause before retrying. Originals remain non-active historical evidence,
and are never summed by CLI statistics. Read-only status never runs migration.
Statistics reset/retention clean affected packet lineage; import markers survive to prevent
an upgrade from resurrecting intentionally deleted history.


Project `mrh cleanup --apply` removes only new disposable bodies and caches,
not the receipts or shared database. A removed body invalidates that old packet;
classification interrupted by cleanup fails without another query. Unknown
release identity remains unknown, with retries denied; a new task can prepare
its own independent packet. Cleanup does not invoke `finish`, statistics reset
or retention. See [disposable storage](../usage.md#清除可丟棄暫存).
Windows does not support the packet protocol; a community delegation skill does
not enable it. See [platform capabilities](../compatibility.md).
