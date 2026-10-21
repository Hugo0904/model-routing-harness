"""The words the parent model reads. Kept short, deterministic and free of task text."""

EFFORT_PARAM = {"codex": "reasoning_effort", "claude": "effort"}  # Claude Code gained an Agent `effort` parameter in 2.1.292


def _entry(platform, number, candidate):
    parts = [f"model={candidate['model']}"]
    if candidate.get("effort") and platform in EFFORT_PARAM:
        parts.append(f"{EFFORT_PARAM[platform]}={candidate['effort']}")
    return f"  {number}. " + " ".join(parts)


def _level(tier, gear):
    return f"tier {tier}" + (f", gear {gear}" if gear else "")


def advise(platform, tier, confidence, candidates, gear=None):
    lines = [f"MRH routing advice ({_level(tier, gear)}, confidence {confidence:.2f}): this delegation was not started.",
             "Re-issue the same delegation with one of these, in order of preference:"]
    lines += [_entry(platform, n, c) for n, c in enumerate(candidates, 1)]
    if platform == "codex":
        lines += [
            "This is an expected routing handoff, not a task failure. The next action is a new spawn_agent call.",
            'Use fork_turns="none" with the chosen model and reasoning_effort; full-history forks inherit the parent model and reject overrides.',
            "Keep the original subtask and task_name. Put its necessary context, constraints and expected result in message so the child can work without inherited history.",
            "Wait for the child and integrate its result. The explicit model on the replacement call is respected and will not be classified again.",
        ]
    lines.append("If none is available to you, do the subtask yourself in this conversation. Do not ask the user.")
    return "\n".join(lines)


def continue_main(tier, confidence, gear=None):
    return (f"MRH routing advice ({_level(tier, gear)}, confidence {confidence:.2f}): this subtask needs the main model. "
            "The delegation was not started; do the subtask yourself in this conversation. "
            "Do not create a replacement subagent and do not ask the user.")


NOTICES = {
    "typesafe_http_402": "the Jev account has no credit left",
    "typesafe_http_401": "the Jev API key was rejected",
    "typesafe_missing_credentials": "no Jev API key was found (run: mrh key set jev)",
    "typesafe_http_429": "Jev rate limit reached",
    "classifier_timeout": "the classifier timed out",
}


def fault_notice(reason):
    detail = NOTICES.get(reason, f"the classifier was unavailable ({reason})")
    return (f"MRH: {detail}; the delegation proceeds unchanged. Briefly inform the user; "
            "do not retry the original tool. Recording may be incomplete; local timeout does not prove remote cancellation.")


def fault_output(event, reason="runtime_unavailable"):
    """Safe, event-specific model context; no permission override or tool rewrite."""
    if (not isinstance(event, dict) or event.get("hook_event_name") not in ("PreToolUse", "PostToolUse")
            or not isinstance(event.get("tool_input"), dict)
            or event.get("tool_name") not in ("spawn_agent", "collaborationspawn_agent", "Agent", "Task")):
        return {}
    reasons = {"settings_unavailable": "settings unavailable", "sqlite_busy": "local records unavailable",
               "hook_deadline": "hook time budget exhausted", "runtime_unavailable": "hook runtime unavailable"}
    phase = event["hook_event_name"]
    text = "MRH: " + reasons.get(reason, reasons["runtime_unavailable"]) + "; original work proceeds unchanged. "
    text += ("The tool already returned; do not repeat a successful tool. " if phase == "PostToolUse" else
             "Do not retry the original tool. ")
    text += "Briefly inform the user. Recording and warning deduplication may be unavailable; results remain unknown."
    return {"hookSpecificOutput": {"hookEventName": phase, "additionalContext": text}, "systemMessage": text}
