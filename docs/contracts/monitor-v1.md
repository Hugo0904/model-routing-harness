# Monitor metadata snapshot v1

MRH provides a project-local public CLI contract. No Monitor UI, private Monitor
database, daemon or background integration is installed by this feature.

```sh
mrh status --json --include-events --days 0
```

`--include-events` is accepted only on `status` and requires `--json`; text mode
is rejected with exit 2 before reading statistics. Without it, existing JSON,
human cards, Hook behavior and default costs remain unchanged. Status still
defaults to seven days; `--days 0` selects all retained records. The existing
`stats` command keeps its shorter default window.

The existing aggregates and opt-in `events` are computed from **one SQLite
read-only transaction** and the same owner algorithms. Reads do not create or
migrate a database, collect usage, prune, checkpoint or write records. With a
valid profile and no DB, the result is a known empty snapshot. Invalid or
unreadable source yields the existing CLI error/exit 2, no fabricated empty JSON;
the opt-in JSON also refuses nonfinite aggregate numbers.

The schema is [monitor-v1.schema.json](monitor-v1.schema.json). Its root allows
existing aggregate properties; typed event objects are strict whitelists.
[monitor-v1.synthetic.json](monitor-v1.synthetic.json) is entirely synthetic,
not collected data or a natural comparison sample. `example_only` is a fixture
annotation, not a field emitted by MRH.

## Envelope and refresh

Existing `status.format_version=1` and `status.generated_at` describe the public
status envelope and its observation time. The independent opt-in object is:

```json
{"events":{"format_version":1,"since":0,"items":[]}}
```

`since` is the selected Unix-time lower bound. Items contain retained source
events at/after that time, ordered by source `timestamp`, then `event_id`.
Classification first/last times and phases cover the selected window only.
The envelope observation time is not a source event timestamp.

This is a **complete replaceable snapshot**, not an append-only stream. A local
consumer invokes the CLI, checks exit/JSON/schema versions, then replaces its
previous same-scope snapshot; it must not sum refreshes or phase rows. A failed
read leaves the consumer's old view visibly stale/unknown, not reset to zero.
Retention or reset can remove events; disappearance does not prove a task never
happened. Changing the window changes the selected entities. No cursor,
pagination, realtime delivery or cross-database atomicity is promised.

## Stable identities

Canonical hash input is the UTF-8 encoding of
`json.dumps(parts, ensure_ascii=True, separators=(",", ":"), allow_nan=False)`.
JSON array order is significant; ASCII escapes, compact separators and no
normalization of native strings are frozen in v1. Hash is lowercase SHA-256.

| kind | event_id | source identity |
|---|---|---|
| decision | `decision:` + existing request_id | Existing stored decision ID, not SQLite rowid |
| classification_request | `classification:` + hash | `[request_id, provider_kind]` |
| child | `child:` + hash | `[platform, session_id, call_id]` |

Example vectors: `["q-1","jev"]` hashes to
`d376c2eed20e51b6739919dccdbfd4ac32e740b8878cc682e1e6c50a7786390e`;
`["codex","synthetic-session","call-1"]` hashes to
`be088471a9cda899609f5243fa767c8f10e36a1bbe94350fc0fe9d8f0e5bb51b`.
IDs do not depend on generated_at, row order, mutable models or usage. Later
classification phases can update one item while its ID remains unchanged. A
different native call gets a different child ID. These opaque correlations are
not an anonymity guarantee or permission to export sensitive source content.

## Item and aggregate meaning

- **decision**: platform/request_id, action/reason/tier/confidence/provider,
  validated candidates, `origin` ordinary/packet_query/packet_release, and the
  exact aggregate `counted_in_decisions` inclusion flag. All retained decisions
  are listed, including excluded releases/reissues. `recorded_links` contains
  only stored correlation or packet query/release IDs; it does not manufacture
  an inferred relation. Contradictory packet membership has null origin.
- **classification_request**: one item per request/provider, first/last phase
  times, distinct phases in timestamp/phase-name order, and the same entered,
  returned, failed, unknown rules as classifier statistics. Input/output tokens
  are the maximum known value across its phases, or null when none is known,
  not a sum of phase reports. Requested/response model is supplied only when
  unambiguous and valid; otherwise null. Platform comes only from exactly one
  matching decision, even if that decision is outside the selected window;
  manual/unlinked requests keep null platform. One item is not necessarily an
  entered API call: `entered=false` may be only a classification request.
- **child**: nullable requested model/effort and separate nullable native
  `resolved_model`. Requested is never substituted for observed. Stored
  `recorded_advice_request_id`/`recorded_followed` are reported as stored, not as
  a new validated adoption inference. Usage-observed models remain a separate
  existing aggregate domain; no per-child pricing/quality inference is added.

Optional malformed model/code metadata is null/unknown; invalid required source
identity/timestamps or incompatible existing data may fail the read under the
existing error contract. Candidates with invalid model metadata are unknown
(`null`), while a valid empty candidate set is `[]`. Unknown native models do
not become the current CLI model or a configured candidate.

Legacy `decisions` already excludes reissues and packet releases but includes
packet queries; do not add packet classifications to it again. Packet children
are a subset of `children_started`, not additional children. Classifier
`requests` groups phases; `calls` reflects entered attempts. Advice, requested
model, observed child, validated following and usage comparison are different
facts. A zero following counter with no eligible link is not a rejection rate.
Existing costs/savings remain assumption-based API conversions, not bills or
measured savings. Period defaults and all other legacy aggregate definitions
remain with `AdviceStore.stats` and the shared `ctrl.statistics` owner.

The remaining legacy aggregate families keep their existing definitions:

| fields | meaning |
|---|---|
| `since`, `decisions`, `per_platform`, `kept_unchanged`, `tiers` | Selected decision window and the counted action/reason/tier composition; tiers describe classifications, not child models or work progress. |
| `roles`, `role_reasons`, `role_recorded`, `explicit_without_role` | Metadata actually recorded for counted decisions; old absent role fields remain unknown. |
| `classifier_usage`, `classifier_requests/calls/failed_requests`, token totals, latency, versions | Selected attempt groups with known maxima per request; aggregate token subtotals and unknown-call counters must be read together. |
| `confidence`, `classifier_change` | Existing global retained-history helpers: last-24h/all-time confidence and model-version change. These are not silently narrowed to the selected status window. |
| `manual_classifications` | Selected grouped IDs carrying the manual prefix; not delegations. |
| `reissues`, `inferred_links`, `unverified_reissues` | Validated recorded/legacy-inferred reissues and separately unverified claims; not extra classification tasks. |
| `children_started`, `children_models`, `children_inherited`, `observed_models` | Selected child rows; children_models prefers native resolved then requested, inherited has neither; observed_models uses only native resolved values. |
| `children_following_advice`, `children_following_prior_advice`, `followed_models`, `followed_requested_models`, `unverified_followed_children` | Validated link/candidate matching, prior-window advice, requested/native distinctions, and stored claims which could not be verified. |
| `packet_classifications/releases/children_started/children_following_advice` | Overlapping packet control/query/release/child subsets; never add them to ordinary totals blindly. |
| `redispatch` | Ordinary task redispatch episodes within the existing 30-minute grouping window, excluding packet control calls. |
| `usage` | Existing collected/legacy/uncollected snapshots, model/effort comparison, token subtotals and assumption-based cost/saving; no transcript scan on read. |

Events never export raw session/call/agent IDs, task/hash/body, packet body/hash,
workspace/source-file paths, arbitrary candidate JSON, context/provenance,
credentials or raw exceptions. Only the documented scalar/structured whitelist
is projected; this is not an automatic secret scanner for a malicious producer.
Monitor consumers use this CLI instead of opening MRH's private SQLite. Live
external integrations and UI acceptance require their own implementation and verification.
