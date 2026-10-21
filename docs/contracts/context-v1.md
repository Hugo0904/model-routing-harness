# Optional context contract v1

This project-local extension is implemented and tested with isolated producers.
No external context producer, private-memory reader, Hook field or CLI context flag
is connected by default. MRH works independently; neither `None` nor unavailable context
is an error by itself.

A trusted embedding caller may pass the keyword-only `context_provider` to
`mrh.advisory.engine.decide` or `mrh.application.classify.run`. Existing
positional calls and default provider request bodies remain compatible.

```python
from mrh.routing.types import ContextSummary
from mrh.advisory import engine

def approved_context(task: str, timeout_seconds: float) -> ContextSummary | None:
    # Entirely synthetic example. An embedding application must first obtain
    # real permission for the task and the minimal nonsensitive summary.
    return ContextSummary(
        summary="The synthetic project uses Python.",
        source_ref="example:approved-note",  # opaque local provenance only
        permitted_export=True,
    )

# req/settings/store/classifier_factory belong to the existing trusted caller.
# Its original workspace, task-export and route gates still apply.
advice = engine.decide(req, settings, store, classifier_factory,
                       context_provider=approved_context)
```

The producer receives only the already-authorized task and its bounded remaining
seconds. It must return `ContextSummary | None`. MRH calls it only for an
otherwise eligible Jev classification with
`settings["task_export_permitted"] is True`. Other classifier providers receive
`context=None`. Explicit model/effort, named-role protection, replay and task
deduplication return before this lookup. Native adapters supply no producer;
default `None` creates no context lookup/thread, file reader, service or external-memory
import. Manual classification retains its existing ability to ask while routing
is disabled, but still requires literal task export permission.

The context wait is at most 0.100 seconds and at most the remaining original
`GuardedAttempts`/outer hook budget. It consumes that classification deadline;
neither factory work nor task-only fallback gets a new allowance. A timeout,
exception, absent or invalid summary falls back to task-only classification if
time remains; an exhausted original deadline preserves the existing timeout
result. No producer retry is added. A late producer may finish its own work in
memory, but its return cannot start another MRH classification, write a record,
or export context. Bounded waiting does not prove producer/remote cancellation.

Validation requires all of:

- The actual `ContextSummary` type and `permitted_export is True` (not `1`).
- A nonblank string summary, at most 4096 UTF-8 bytes, valid UTF-8. Over-limit
  content is rejected in full, never truncated or rewritten.
- A nonblank string `source_ref`, at most 256 characters, without Unicode
  control/format/surrogate characters. It is opaque: never dereferenced, sent
  to the classifier, persisted or used to locate a private file.

Only the approved summary string reaches the existing Jev `state.context_summary`.
The reference, summary and producer exception are not stored in Advice,
attempts, notices, statistics or logs. Context does not adjust confidence,
policy, Main/Fixed, role protection or the selected candidate.

Both permissions are necessary. A dataclass flag is an assertion from a trusted
embedding application, not proof of human consent and not an automatic secret
detector. The caller must not supply credentials, full memory or private
transcripts. Adding a real external context producer and proving its content/export
authorization is a separate optional integration; this contract grants no
permission to read private state or another repository.
