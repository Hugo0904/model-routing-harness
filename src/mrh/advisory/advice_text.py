"""The words the parent model reads. Kept short, deterministic and free of task text."""

EFFORT_PARAM = {"codex": "reasoning_effort", "claude": "effort"}  # Claude Code gained an Agent `effort` parameter in 2.1.292


def _entry(platform, number, candidate):
    parts = [f"model={candidate['model']}"]
    if candidate.get("effort") and platform in EFFORT_PARAM:
        parts.append(f"{EFFORT_PARAM[platform]}={candidate['effort']}")
    return f"  {number}. " + " ".join(parts)


def advise(platform, tier, confidence, candidates):
    lines = [f"MRH routing advice (tier {tier}, confidence {confidence:.2f}): this delegation was not started.",
             "Re-issue the same delegation with one of these, in order of preference:"]
    lines += [_entry(platform, n, c) for n, c in enumerate(candidates, 1)]
    lines.append("If none is available to you, do the subtask yourself in this conversation. Do not ask the user.")
    return "\n".join(lines)


def continue_main(tier, confidence):
    return (f"MRH routing advice (tier {tier}, confidence {confidence:.2f}): this subtask needs the main model. "
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
    return f"MRH: {detail}; the delegation proceeds unchanged."
