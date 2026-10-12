"""Public settings -> existing provider factory -> conservative Codex adapter."""
import sys
import os
from pathlib import Path
from mrh.adapters.hosts.codex import handle_event, canonical_event
from mrh.infrastructure.settings import read, workspace_allowed
from mrh.infrastructure.settings_schema import SettingsError
from mrh.application.classifier import classifier_from_config
from mrh.adapters.providers.codex_subscription import SENTINEL
from mrh.routing.types import safe_id, safe_model_id
from mrh.routing.facts import CallScope, Fact, HostSnapshot, synthetic_legacy_snapshot
from mrh.routing.types import Proposal
from mrh.infrastructure.owned import canonical_path
from mrh.routing.faults import warning


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


def configured_event(event, settings_path, *, host_resolver=None, transport=None, credential_resolver=None, scope_binding=None, subscription_runner=None):
    if os.environ.get(SENTINEL):
        return {}  # Before settings, DB, auth, host inspection or model work.
    event=canonical_event(event)
    if isinstance(event,dict) and event.get('hook_event_name') == 'SessionStart' and scope_binding is not None:
        try:
            import json
            from mrh.infrastructure.owned import read_regular
            from mrh.adapters.hosts import fresh_cli_scope
            from mrh.adapters.hosts.codex_scope import ScopeError
            descriptor=json.loads(read_regular(scope_binding))['codex_scope']
            if descriptor.get('contract') != fresh_cli_scope.CONTRACT:return {}
            value=read(settings_path)
            if not value['enabled'] or not value['task_export_permitted']:return {}
            return fresh_cli_scope.session_start(descriptor,event,scope_binding)
        except Exception as exc:
            from mrh.adapters.hosts.codex_scope import ScopeError
            reason=str(exc) if isinstance(exc,ScopeError) else 'scope_host_unverified'
            return warning(reason)
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
        if not value["enabled"] or not value["task_export_permitted"]:
            return {}
        if event["hook_event_name"] == "PreToolUse" and not workspace_allowed(value, event.get("cwd")):
            return {}
        resolver = host_resolver if host_resolver is not None else SupportedHostResolver()
        injected = {}
        if transport is not None:
            injected["transport"] = transport
        if credential_resolver is not None:
            injected["credential_resolver"] = credential_resolver
        if subscription_runner is not None:
            injected['subscription_runner'] = subscription_runner
        if value['provider']=='codex_subscription' and scope_binding is not None:
            injected['subscription_binding']=scope_binding
        classifier = classifier_from_config({"provider":value['provider'], "schema_version": 1, "model": value["classifier_model"],
                                             "enabled": value["enabled"], "task_export_permitted": value["task_export_permitted"]}, **injected)
        from mrh.infrastructure.store import Store
        if event["hook_event_name"] == "PostToolUse":
            proposal = Proposal("codex", "simulation" if classifier.synthetic else "unknown",
                                event["session_id"], event["turn_id"], event["tool_use_id"], original, classifier.synthetic)
            store = Store.for_receipt(Path(settings_path).parent / "events.sqlite3", proposal)
            return handle_event(event, store, True, classifier=classifier) if store is not None else {}
        if not (scope_binding is not None and host_resolver is None) and bool(getattr(resolver, "synthetic", False)) != classifier.synthetic:
            return {}
        caps = partial_hook_snapshot(event, classifier.synthetic)
        if (event["hook_event_name"] == "PreToolUse" and original.get("model") is None
                and original.get('reasoning_effort') is None and original.get('agent_type') in (None,'default')):
            try:
                if scope_binding is not None and host_resolver is None:
                    import json
                    from mrh.adapters.hosts.codex_scope import check
                    from mrh.infrastructure.owned import read_regular
                    descriptor=json.loads(read_regular(scope_binding))['codex_scope']
                    observed=check(descriptor,event,synthetic=classifier.synthetic,binding=scope_binding)
                else:observed = resolver.resolve(event)
                if type(observed) is HostSnapshot:
                    caps = observed
                elif classifier.synthetic and isinstance(observed, dict):
                    proposal = Proposal("codex", "simulation", event["session_id"], event["turn_id"], event["tool_use_id"], original, True)
                    caps = synthetic_legacy_snapshot(proposal, observed)
                elif observed is not None:
                    caps = observed  # core rejects generic production assertions
            except Exception as exc:
                # A bounded unavailable state reaches the same core/facts path;
                # no guessed capabilities or raw resolver exception is stored.
                if scope_binding is not None:
                    from mrh.adapters.hosts.codex_scope import rejected, ScopeError
                    reason=str(exc) if isinstance(exc,ScopeError) else 'scope_changed'
                    caps=rejected(event,reason,classifier.synthetic)
        # Explicit Pre wins in core before resolution/classification. Post uses
        # proposal correlation, independent of any fresh host-capability query.
        store = Store(Path(settings_path).parent / "events.sqlite3")
        from mrh.infrastructure.bindings import target_veto
        policy = {**value['policy'], '_target_veto': target_veto(settings_path, synthetic=classifier.synthetic)}
        return handle_event(event, store, True, classifier=classifier, policy=policy, capabilities=caps)
    except SettingsError as exc:
        print("mrh: " + exc.reason, file=sys.stderr)
        if event["hook_event_name"] == "PreToolUse":
            return warning("settings_unavailable")
    except Exception:
        print("mrh: configured_hook_error", file=sys.stderr)
        if event["hook_event_name"] == "PreToolUse":
            return warning("runtime_error")
    return {}
