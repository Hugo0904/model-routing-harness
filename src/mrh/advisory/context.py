"""Opt-in trusted embedding seam; no discovery, persistence or late export."""
import unicodedata

from mrh.routing.core import bounded_call
from mrh.routing.types import ContextSummary

MAX_WAIT_SECONDS = .100
MAX_SUMMARY_BYTES = 4096
MAX_SOURCE_CHARACTERS = 256


def resolve(task, settings, attempts, context_provider, *, hook_budget=None):
    if (context_provider is None or settings['classifier']['provider'] != 'jev'
            or settings['task_export_permitted'] is not True):
        return None
    if hook_budget is not None:
        hook_budget.check()
    attempts.check()
    seconds = min(MAX_WAIT_SECONDS, attempts.remaining())
    if hook_budget is not None:
        seconds = min(seconds, hook_budget.remaining())
    def lookup():
        attempts.check()
        available = min(seconds, attempts.remaining())
        if hook_budget is not None:
            hook_budget.check()
            available = min(available, hook_budget.remaining())
        return context_provider(task, available)
    try:
        value = bounded_call(lookup, seconds)
    except Exception:
        value = None  # no producer exception text is logged or persisted
    if hook_budget is not None:
        hook_budget.check()
    attempts.check()  # context consumed the existing deadline, never a new one
    if settings['task_export_permitted'] is not True:
        return None
    try:
        if not isinstance(value, ContextSummary) or value.permitted_export is not True:
            return None
        if (not isinstance(value.summary, str) or len(value.summary) > MAX_SUMMARY_BYTES or not value.summary.strip()
                or not isinstance(value.source_ref, str) or len(value.source_ref) > MAX_SOURCE_CHARACTERS
                or not value.source_ref.strip()
                or any(unicodedata.category(c) in ('Cc', 'Cf', 'Cs') for c in value.source_ref)):
            return None
        if len(value.summary.encode('utf-8')) > MAX_SUMMARY_BYTES:
            return None
    except Exception:
        return None
    return value.summary
