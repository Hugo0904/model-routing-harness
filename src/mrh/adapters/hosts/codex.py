"""Codex Hook candidate. Successful serialization is not host adoption."""
import copy
import json
import sys
from mrh.routing.core import Classification, ScriptedClassifier, UnavailableClassifier
from mrh.application.service import process
from mrh.routing.types import Proposal, safe_id
from mrh.routing.facts import CallScope, HostSnapshot
from mrh.routing.faults import notice_for, warning, category

SPAWN_NAMES = ('spawn_agent','collaborationspawn_agent')


def canonical_event(event):
    # Exact canonical V2 name observed on official 0.159.3. This changes only
    # internal matching, never the original replacement argument object.
    if isinstance(event,dict) and event.get('tool_name') in SPAWN_NAMES:
        return {**event,'tool_name':'spawn_agent'}
    return event


def serialize(decision, original, call_id, notice=None):
    if decision.action == "preserve":
        return notice if notice is not None else warning(decision.reason) if category(decision) == "fault_fallback" else {}
    if decision.action == 'operator_update_required':
        return {**(notice or {}), 'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'permissionDecision': 'deny',
                'permissionDecisionReason': f'MRH stopped delegation: {decision.tier} target {decision.target_model} is unavailable ({decision.reason}). Update this tier with mrh model {decision.tier.lower()}, then explicitly rerun the task as a new proposal. This call will not resume automatically.'}}
    if decision.action == "return_to_main":
        return {**(notice or {}), "hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                "permissionDecisionReason": f"MRH Top Main: delegation {call_id} was not executed. Continue its original unexecuted subtask in this same parent; do not create a replacement child. The selected main model remains unchanged."}}
    rewritten = copy.deepcopy(original)
    rewritten.update(decision.patch)
    return {**(notice or {}), "hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow", "updatedInput": rewritten}}


def handle_event(event, store=None, candidate=False, simulation=None, *, classifier=None, policy=None, capabilities=None, optional_context=None):
    event=canonical_event(event)
    if not candidate:
        return {}
    if not isinstance(event, dict) or event.get("tool_name") != "spawn_agent":
        return {}
    if event.get("hook_event_name") not in ("PreToolUse", "PostToolUse"):
        return {}
    original = event.get("tool_input")
    if not isinstance(original, dict):
        print("mrh: invalid_hook_input", file=sys.stderr)
        return {}
    synthetic = simulation is not None or getattr(classifier, "synthetic", False) is True
    try:
        proposal = Proposal("codex", "simulation" if synthetic else "unknown", event.get("session_id"),
                            event.get("turn_id"), event.get("tool_use_id"), original, synthetic)
        identity = proposal.identity
    except (ValueError, TypeError):
        print("mrh: invalid_hook_identity", file=sys.stderr)
        return {}
    if event["hook_event_name"] == "PostToolUse":
        if store is None:
            return {}
        response = event.get("tool_response")
        # Installed Codex 0.159.3 / 0.162 emits spawn_agent output as a JSON
        # string. The earlier injected candidate also accepts a dict. Keep only
        # the bounded agent identifier; neither form verifies actual model.
        if isinstance(response, str):
            try:
                response = json.loads(response) if len(response.encode()) <= 65536 else None
            except (ValueError, UnicodeError):
                response = None
        agent_id = response.get("agent_id") if isinstance(response, dict) else None
        task_reference = response.get('task_name') if isinstance(response,dict) else None
        source_ref='codex-hook-candidate'
        if agent_id is None and safe_id(task_reference):
            agent_id=task_reference
            source_ref='codex-native-v2-task-reference'
        if not safe_id(agent_id):
            print("mrh: child_receipt_unavailable", file=sys.stderr)
            return {}
        receipt = {"event_id": identity + ":child:" + agent_id, "proposal_id": identity,
                   "platform": proposal.platform, "surface": proposal.surface,
                   "session_id": proposal.session_id, "turn_id": proposal.turn_id,
                   "tool_call_id": proposal.tool_call_id, "agent_id": agent_id,
                   "evidence_kind": "synthetic" if synthetic else "reported", "source_ref": source_ref}
        try:
            store.record_observation(receipt)
        except Exception:
            print("mrh: child_receipt_rejected", file=sys.stderr)
        return {}
    from mrh.application.simulation import demo_capabilities, demo_policy
    # No default-role or capability inference in a production caller. Legacy
    # dictionaries remain confined to the explicitly synthetic adapter path.
    caps = capabilities if capabilities is not None else demo_capabilities() if synthetic else HostSnapshot(CallScope.for_proposal(proposal), False)
    policy = policy if policy is not None else demo_policy() if synthetic else {"top_mode": "Main"}
    classifier = classifier or UnavailableClassifier()
    if simulation is not None:
        if not isinstance(simulation, dict):
            return {}
        policy = simulation.get("policy", policy)
        caps = simulation.get("capabilities", caps)
        classifier = ScriptedClassifier([Classification(simulation.get("tier"), simulation.get("confidence", 0.9))])
    decision = process(proposal, policy, caps, store, classifier, optional_context)
    if decision.reason == 'operator_stop_unavailable':
        print('mrh: operator_stop_unavailable; host has no verified deny control; delegation is not confirmed stopped', file=sys.stderr)
    return serialize(decision, original, proposal.tool_call_id, notice_for(proposal, decision, store))
