"""Codex Hook candidate. Successful serialization is not host adoption."""
import copy
import json
import sys
from .core import Classification, ScriptedClassifier, UnavailableClassifier
from .service import process
from .types import Proposal, safe_id
from .facts import CallScope, HostSnapshot


def serialize(decision, original, call_id):
    if decision.action == "preserve":
        return {}
    if decision.action == "return_to_main":
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                "permissionDecisionReason": f"MRH Top Main requested for existing subtask {call_id}; main continuation remains unverified."}}
    rewritten = copy.deepcopy(original)
    rewritten.update(decision.patch)
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow", "updatedInput": rewritten}}


def handle_event(event, store=None, candidate=False, simulation=None, *, classifier=None, policy=None, capabilities=None, optional_context=None):
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
        if not safe_id(agent_id):
            print("mrh: child_receipt_unavailable", file=sys.stderr)
            return {}
        receipt = {"event_id": identity + ":child:" + agent_id, "proposal_id": identity,
                   "platform": proposal.platform, "surface": proposal.surface,
                   "session_id": proposal.session_id, "turn_id": proposal.turn_id,
                   "tool_call_id": proposal.tool_call_id, "agent_id": agent_id,
                   "evidence_kind": "synthetic" if synthetic else "reported", "source_ref": "codex-hook-candidate"}
        try:
            store.record_observation(receipt)
        except Exception:
            print("mrh: child_receipt_rejected", file=sys.stderr)
        return {}
    from .simulation import demo_capabilities, demo_policy
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
    return serialize(decision, original, proposal.tool_call_id)
