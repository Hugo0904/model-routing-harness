# Local daily dispatch collector

This is a separate, opt-in local collector, independent of the MRH classifier,
provider, plugin and model routing. It makes no network or model calls and never
denies or rewrites a dispatch. Its only handlers are `UserPromptSubmit`,
`PreToolUse` and `PostToolUse`, using the official
[Codex hook format](https://learn.chatgpt.com/docs/hooks?translationFallback=zh-Hant).

The operator config selects the local workspace roots and excluded implementation
chats. This installation covers this Mac account's home workspaces, including
Code, Documents/Codex and other local projects. Remote hosts, Claude and nested
subagent delegations are outside this installation's acceptance scope.

## Capture and evidence

The prompt hook records the actual session, turn and cwd in a short-lived private
context. Turns started by app-to-chat messages need not emit `UserPromptSubmit`.
The `PreToolUse` handler therefore also matches ordinary tools: on the first
tool of a turn without a recorded reminder, it creates the same private context
from the native event and returns model-visible `additionalContext`. Subsequent
tools in that turn return no repeated reminder and retain no tool input.
`PostToolUse` still matches only delegation tools.

Immediately before a genuine, independently needed root `spawn_agent`,
the parent sends the complete **actual tool JSON** to the injected stage command.
Stage verifies the recorded context and normal `CODEX_THREAD_ID` environment;
PreToolUse must match that same session, turn, cwd and non-body fields. A stale
root stage or a subagent's different turn cannot bind. No context means no sample.

Stage writes only the collector's owner-only `/private/tmp` spool, not the central
dataset. It therefore needs no cross-project write grant or recurring escalation.
The normal successful Post hook copies the exact request bytes to the persistent
central capture directory, then commits its receipt and index under locks. The
canonical JSON pointers always reference persistent requests, never tmp files.

If the very first tool is a delegation with no prior stage, the collector does
not deny it or reconstruct its original body later. It records the missing
capture and whether the reminder was first prepared at that dispatch, and
provides the context for a later, independently needed dispatch. A reminder
being emitted is not proof that the parent followed it. Failed captures are not
backfilled, and no extra dispatch is created just to test collection.

The October 16 diagnosis matched three successful root delegations to collector
misses in two native `app_tool_send_message` turns. Those turns had no user item,
no collector reminder in their saved developer messages, and no stage call.
This identified a missing turn-entry path, rather than a parent ignoring a
delivered reminder. Isolated process tests exercise that absent-prompt path;
future natural capture remains a separate observation.

Native encrypted message equality is **unobservable**. Receipts label this
`parent_pre_dispatch_attestation` and `unobservable_ciphertext`; plaintext alone
can be `verified_plaintext`. Requested models are never relabelled as actual
executing models. The parent excludes credentials or sensitive original data
*before* stage; regex filtering is only supplementary. Missing/ambiguous captures,
failures, retries and continuations cannot invent additional successful samples.

At ten total samples the last Post announces completion and collection stops;
there is no scheduler, daemon, history scan, external sharing or paid comparison.
Existing samples and their original hashes remain intact during scope migration.

## Install, review and recover

`scripts/collection/install.py install --help` lists explicit dataset, private
interpreter, workspace and exclusion arguments. The installer copies a fixed
version beneath its independent owner directory, hashes every installed file,
backs up the hook file and old dataset scope, and appends three exact marked
handlers. It preserves all unrelated handlers, including Canopy. Concurrent hook
edits refuse publication rather than restoring an old whole-file backup.

New or changed non-managed hooks require normal official `/hooks` review and trust
of their exact definitions. Installation is not native activation; isolated event
fixtures do not prove trust or a natural cross-chat dispatch. Do not use bypass
flags, disguise a handler as managed, or edit trust storage. After the host loads
the reviewed hook configuration, existing chats can receive the reminder on
UserPromptSubmit or their first ordinary PreToolUse event. A turn whose first
tool already dispatches a child can still miss pre-capture; the collector remains
non-blocking. Keep official activation and the next genuine dispatch as separate
proof.

Use the fixed installed `install.py --root <owner-root> status`, `disable`, or
`uninstall` with its recorded private interpreter. Disable/uninstall removes only
the recorded exact commands, retaining other owners' subsequent edits, installed
files, captures and backups. Config `enabled` describes configuration, not native
trust. Status deliberately retains that uncertainty.

Each capture is at most 64 KiB and there are at most 64 retained spool captures;
capacity stops new capture without deleting originals. Events and bindings each
retain at most 256 metadata records. Native prompt contexts retain at most 64
metadata files for 24 hours; only those recorded ephemeral files may be evicted.
Interrupted writes use bounded fixed recovery slots and fail without claiming
success if a slot remains. Retained originals require an explicit owner decision
for cleanup; normal work proceeds when collection cannot run.
