"""Add or remove MRH's hook in a Claude Code settings.json. Dry-run unless asked; always backs up."""
from __future__ import annotations

import difflib
import json
import os
import shlex
import tempfile
import time
from pathlib import Path

MATCHER = "Agent|Task"
EVENTS = ("PreToolUse", "PostToolUse")
MARK = "model-routing-harness"


class ClaudeHookError(ValueError):
    pass


def command_for(artifact_root):
    root = Path(artifact_root)
    artifact = json.loads((root / "artifact.json").read_text())
    launcher = root / "plugins" / MARK / "launcher.py"
    if not launcher.is_file():
        raise ClaudeHookError("artifact has no launcher; run: mrh plugin prepare --advisory")
    return f"{shlex.quote(artifact['python'])} -I -B {shlex.quote(str(launcher))} claude"


def _ours(entry):
    return isinstance(entry, dict) and any(MARK in h.get("command", "") and h.get("command", "").endswith(" claude")
                                           for h in entry.get("hooks", []) if isinstance(h, dict))


def plan(text, command, remove=False):
    """Return the new file text. Everything that is not MRH's own entry is preserved verbatim."""
    try:
        document = json.loads(text) if text.strip() else {}
    except ValueError:
        raise ClaudeHookError("settings.json is not valid JSON; not touching it") from None
    if not isinstance(document, dict) or not isinstance(document.get("hooks", {}), dict):
        raise ClaudeHookError("unexpected settings.json shape; not touching it")
    hooks = document.setdefault("hooks", {})
    for event in EVENTS:
        entries = [e for e in hooks.get(event, []) if not _ours(e)]
        if not remove:
            entries.append({"matcher": MATCHER, "hooks": [{"type": "command", "command": command, "timeout": 50}]})
        if entries:
            hooks[event] = entries
        else:
            hooks.pop(event, None)
    if not hooks:
        document.pop("hooks")
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def diff(before, after, name):
    return "".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True), name + " (current)", name + " (proposed)"))


def apply(path, after):
    path = Path(path)
    backup = None
    if path.exists():
        backup = path.with_name(path.name + f".mrh-bak-{time.strftime('%Y%m%d-%H%M%S')}")
        backup.write_bytes(path.read_bytes())
        os.chmod(backup, path.stat().st_mode & 0o777)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".mrh-write-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(after)
        if path.exists():
            os.chmod(tmp, path.stat().st_mode & 0o777)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return backup
