"""Vendor event -> AdvisoryRequest, and Advice -> vendor hook output.

Event shapes come from real hooks: Codex 0.159.3 (`spawn_agent`, see adapters/hosts/codex.py)
and Claude Code 2.1.x (`Agent`, fixture tests/fixtures/claude_agent_events.json).
"""
from __future__ import annotations

import json
import re

from mrh.advisory import advice_text
from mrh.advisory.request import Advice, AdvisoryRequest, Child
from mrh.routing.types import safe_id, safe_model_id

CODEX_TOOLS = ("spawn_agent", "collaborationspawn_agent")
CLAUDE_TOOLS = ("Agent", "Task")


# Codex 0.159.3 hands hooks the delegation `message` as an opaque Fernet token; only `task_name` is readable.
_CIPHERTEXT = re.compile(r"gAAAA[A-Za-z0-9_\-]{60,}={0,2}")


def _readable_task(data):
    message = _text(data.get("message"))
    if message is not None and not _CIPHERTEXT.fullmatch(message.strip()):
        return message
    name = data.get("task_name")
    return re.sub(r"[_\-]+", " ", name).strip() if safe_id(name) else None


def _text(value):
    return value if isinstance(value, str) and value.strip() else None


def _model(value):
    return value if safe_model_id(value) else None


class _Host:
    platform = ""
    tools: tuple = ()

    def spawn_event(self, event, phase):
        return (isinstance(event, dict) and event.get("hook_event_name") == phase
                and event.get("tool_name") in self.tools and isinstance(event.get("tool_input"), dict))

    # -- shared output ---------------------------------------------------------------
    def output(self, advice: Advice):
        if advice.action in ("advise", "continue_main"):
            reason = (advice_text.advise(self.platform, advice.tier, advice.confidence, advice.candidates)
                      if advice.action == "advise" else advice_text.continue_main(advice.tier, advice.confidence))
            return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                           "permissionDecisionReason": reason}}
        return {"systemMessage": advice.notice} if advice.notice else {}


class CodexHost(_Host):
    platform, tools = "codex", CODEX_TOOLS

    def request(self, event):
        if not self.spawn_event(event, "PreToolUse"):
            return None
        data = event["tool_input"]
        ids = [event.get(k) for k in ("session_id", "turn_id", "tool_use_id")]
        task = _readable_task(data)
        if task is None or not all(safe_id(i) for i in ids):
            return None
        role = data.get("agent_type")
        return AdvisoryRequest("codex", *ids, task, data.get("model"), data.get("reasoning_effort"),
                               None if role in (None, "default") else str(role), event.get("cwd"))

    def child(self, event):
        if not self.spawn_event(event, "PostToolUse"):
            return None
        data, response = event["tool_input"], event.get("tool_response")
        if isinstance(response, str) and len(response) <= 65536:
            try:
                response = json.loads(response)
            except ValueError:
                response = None
        response = response if isinstance(response, dict) else {}
        agent = response.get("agent_id") or response.get("task_name")
        if not all(safe_id(event.get(k)) for k in ("session_id", "tool_use_id")):
            return None
        return Child("codex", event["session_id"], event["tool_use_id"], _model(data.get("model")),
                     data.get("reasoning_effort") if safe_id(data.get("reasoning_effort")) else None,
                     None, agent if safe_id(agent) else None)


class ClaudeHost(_Host):
    platform, tools = "claude", CLAUDE_TOOLS

    def request(self, event):
        if not self.spawn_event(event, "PreToolUse"):
            return None
        data = event["tool_input"]
        session, call = event.get("session_id"), event.get("tool_use_id")
        turn = event.get("prompt_id") or session
        task = _text(data.get("prompt")) or _text(data.get("description"))
        if task is None or not all(safe_id(i) for i in (session, turn, call)):
            return None
        role = data.get("subagent_type")
        return AdvisoryRequest("claude", session, turn, call, task, data.get("model"), None,
                               None if role in (None, "general-purpose") else str(role), event.get("cwd"))

    def child(self, event):
        if not self.spawn_event(event, "PostToolUse"):
            return None
        data, response = event["tool_input"], event.get("tool_response")
        response = response if isinstance(response, dict) else {}
        if not all(safe_id(event.get(k)) for k in ("session_id", "tool_use_id")):
            return None
        agent, resolved = response.get("agentId"), response.get("resolvedModel")
        return Child("claude", event["session_id"], event["tool_use_id"], _model(data.get("model")), None,
                     _model(resolved), agent if safe_id(agent) else None)


HOSTS = {"codex": CodexHost(), "claude": ClaudeHost()}
