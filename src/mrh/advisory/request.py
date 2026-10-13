"""Platform-neutral request/result of one advisory decision."""
from __future__ import annotations

from dataclasses import dataclass, field

ACTIONS = ("passthrough", "preserve", "advise", "continue_main")


@dataclass(frozen=True)
class AdvisoryRequest:
    platform: str           # codex | claude | gemini
    session_id: str
    turn_id: str
    call_id: str
    task: str
    explicit_model: str | None = None
    explicit_effort: str | None = None
    role: str | None = None  # a named, non-default role; always respected
    cwd: str | None = None


@dataclass(frozen=True)
class Child:
    """What a PostToolUse says was actually started."""
    platform: str
    session_id: str
    call_id: str
    requested_model: str | None
    requested_effort: str | None
    resolved_model: str | None
    agent_id: str | None


@dataclass(frozen=True)
class Advice:
    action: str
    reason: str
    tier: str | None = None
    confidence: float | None = None
    candidates: tuple = ()      # ({"model": ..., "effort": ...?}, ...) for the request's platform
    request_id: str = ""
    notice: str | None = None   # one-time user-visible fault notice; never contains task text
    extra: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.action not in ACTIONS:
            raise ValueError("invalid_action")
