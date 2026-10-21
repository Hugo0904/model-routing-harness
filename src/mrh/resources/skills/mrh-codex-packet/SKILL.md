---
name: mrh-codex-packet
description: Handle the optional MRH full-task packet protocol for a real Codex delegation when this plugin was explicitly installed with packet support. Use only for that protocol; task decomposition and worker selection remain with the parent.
---

Use this protocol only when delegation is independently authorized and worthwhile.
Read the plugin's `../../binding.json` relative to this file's skill directory;
the plugin root also contains `launcher.py` and `runtime.pyz`. Require
`platform: codex` and `codex_packets: true`. An ordinary installation does not
enable this workflow. It sends the full proposed child task to the configured
classifier only when the profile permits export; installation grants no consent.

There is one protocol owner per task. If another workflow already prepared a
packet or performed its query, continue that same packet; never prepare or query
a second one. With an engineering Router, the Router owns task/role/profile
selection and this skill owns only the packet mechanics. Do not copy worker
roles, change model rankings, or start a child merely to exercise this protocol.

1. Write the complete intended child brief before dispatch. Preserve constraints,
   owned files, required evidence and the exact child message. A human's explicit
   model/effort and a named role's fixed profile take precedence; when they already
   settle an ineligible dispatch, use the ordinary protected native call without
   a classification. Keep ordinary unmarked calls ordinary.
2. Save that exact UTF-8 brief in an owner-only regular temporary file. Use the
   interpreter and settings path from the binding, and this plugin's runtime:
   `<python> -I -B <plugin-root>/runtime.pyz codex-task --settings <settings> prepare
   --body-file <file> --workspace <verified-native-workspace>`. Do not invent
   session/turn IDs. Only explicit human choices belong in `--user-model` and
   `--user-effort`; the parent's proposed baseline is not a human choice.
3. Call the native spawn tool with `task_name=mrh_packet_<id>` and the exact saved
   message. This is a query: the hook must deny child creation and return the
   receipt/advice. Preserve any independent hook denial. If the hook did not
   clearly complete, stop and read `codex-task ... status --id <id>`; do not retry
   blindly or fall back to task-name classification.
4. Compare complete candidate profiles against current host capabilities, role
   requirements and the adequate baseline. Advice does not establish a fixed
   strength ordering. Top/Main keeps the work in the parent unless a recorded
   explicit human profile controls it. Missing/failed/unknown advice does not
   authorize a more expensive profile or an unknown release retry.
5. For an eligible accepted choice, make one native release with
   `task_name=mrh_release_<id>`, the same exact message and chosen explicit
   model/effort/role. Respect native limits and all other hooks. A released call
   without a confirmed spawn result is unknown, not safe to repeat. Report
   requested and actually observed model/effort separately.
6. Read the receipt. `finish --id <id>` cancels an unreleased packet and removes
   its body; it refuses a live unknown release. Remove only this task's temporary
   input once no longer needed, retaining receipt and required evidence. Do not
   edit immutable packets or treat preparation as actual model execution.

No Monitor, global Skill, credential copy, provider probe or new service is
required. No second query, hidden retry, model launch for testing, or blanket
external-call permission is introduced by this skill.
