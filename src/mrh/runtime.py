"""Public settings -> existing provider factory -> conservative Codex adapter."""
import sys
from pathlib import Path
from .codex import handle_event
from .settings import read, workspace_allowed
from .settings_schema import SettingsError
from .typesafe import classifier_from_config
from .types import safe_id, safe_model_id
from .facts import CallScope, Fact, HostSnapshot, synthetic_legacy_snapshot
from .types import Proposal
from .owned import canonical_path


class SupportedHostResolver:
    """Common Hook fields do not establish active role/effort precedence.

    No transcript, private state, stale separate-process config, or user policy
    is promoted into an observed capability. Future supported adapters can be
    injected independently from the public settings parser.
    """
    synthetic = False

    def resolve(self, event):
        return partial_hook_snapshot(event)


def partial_hook_snapshot(event, synthetic=False):
    scope = CallScope.for_hook(event)
    parent = Fact.observed(scope, event["model"], "canonical-hook-model") if safe_model_id(event.get("model")) else Fact()
    workspace = Fact()
    try:
        if isinstance(event.get("cwd"), str):
            workspace = Fact.observed(scope, str(canonical_path(event["cwd"])), "canonical-hook-cwd")
    except (ValueError, OSError):
        pass
    # No default-role, effort, control or compatibility inference from these
    # observed metadata fields. Model is a Hook slug, not provider execution.
    return HostSnapshot(scope, synthetic, parent_model=parent, workspace=workspace)


def configured_event(event, settings_path, *, host_resolver=None, transport=None, credential_resolver=None):
    # Settings never come from cwd/tool_input. Invalid identities are neutral
    # before any data creation; preserving a valid admitted call still records
    # its existing canonical facts without executing a classifier.
    if not isinstance(event, dict) or event.get("tool_name") != "spawn_agent":
        return {}
    if event.get("hook_event_name") not in ("PreToolUse", "PostToolUse"):
        return {}
    original = event.get("tool_input")
    if not isinstance(original, dict) or not all(safe_id(event.get(k)) for k in ("session_id", "turn_id", "tool_use_id")):
        return {}
    try:
        value = read(settings_path)
        if not value["enabled"] or not value["task_export_permitted"] or not workspace_allowed(value, event.get("cwd")):
            return {}
        resolver = host_resolver if host_resolver is not None else SupportedHostResolver()
        injected = {}
        if transport is not None:
            injected["transport"] = transport
        if credential_resolver is not None:
            injected["credential_resolver"] = credential_resolver
        classifier = classifier_from_config({"schema_version": 1, "model": value["classifier_model"],
                                             "enabled": value["enabled"], "task_export_permitted": value["task_export_permitted"]}, **injected)
        if bool(getattr(resolver, "synthetic", False)) != classifier.synthetic:
            return {}
        caps = partial_hook_snapshot(event, classifier.synthetic)
        if event["hook_event_name"] == "PreToolUse" and original.get("model") is None:
            try:
                observed = resolver.resolve(event)
                if type(observed) is HostSnapshot:
                    caps = observed
                elif classifier.synthetic and isinstance(observed, dict):
                    proposal = Proposal("codex", "simulation", event["session_id"], event["turn_id"], event["tool_use_id"], original, True)
                    caps = synthetic_legacy_snapshot(proposal, observed)
                elif observed is not None:
                    caps = observed  # core rejects generic production assertions
            except Exception:
                # A bounded unavailable state reaches the same core/facts path;
                # no guessed capabilities or raw resolver exception is stored.
                pass
        # Explicit Pre wins in core before resolution/classification. Post uses
        # proposal correlation, independent of any fresh host-capability query.
        from .store import Store
        store = Store(Path(settings_path).parent / "events.sqlite3")
        from .bindings import target_veto
        policy = {**value['policy'], '_target_veto': target_veto(settings_path, synthetic=classifier.synthetic)}
        return handle_event(event, store, True, classifier=classifier, policy=policy, capabilities=caps)
    except SettingsError as exc:
        print("mrh: " + exc.reason, file=sys.stderr)
    except Exception:
        print("mrh: configured_hook_error", file=sys.stderr)
    return {}
