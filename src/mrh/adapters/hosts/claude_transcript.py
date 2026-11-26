"""The main model and effort behind one Claude Code delegation, read from the main conversation's transcript.

The transcript is an unpublished Claude Code format (checked on 2.1.310-2.1.326): one JSON record per line; an `assistant`
record carries `message.model`, a top-level `effort`, `sessionId`, `isSidechain`, and the `tool_use` block of the call in
`message.content`. Anything that does not match exactly is "unknown" (None), and the caller then behaves as if this reader
did not exist. Nothing here raises for a bad file; a caller still guards against the unexpected.
"""
from __future__ import annotations

import json
import os
import stat

from mrh.routing.types import safe_id, safe_model_id

EFFORTS = ("low", "medium", "high", "xhigh", "max")
# Only the end of the file is read. In local transcripts the line that holds an Agent call was at most ~35 KB, and everything
# from that line up to the call's own result (written after the child finished) at most ~77 KB. 1 MiB leaves room for several
# parallel calls and large neighbouring records; a line pushed out of the window is simply not found (the advice stays as it was).
TAIL_BYTES = 1 << 20


def _tail(path, limit=None):
    """The complete lines among the last `limit` bytes of a regular file, or None. A line cut by the window is dropped."""
    limit = TAIL_BYTES if limit is None else limit
    if not isinstance(path, str) or not os.path.isabs(path):
        return None
    try:
        if not stat.S_ISREG(os.stat(path).st_mode):      # never open a FIFO or device: it could block the hook
            return None
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0))
    except (OSError, ValueError):
        return None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):               # swapped between stat and open
            return None
        start = max(0, info.st_size - limit)
        os.lseek(fd, start, os.SEEK_SET)
        chunks, left = [], info.st_size - start
        while left > 0:
            chunk = os.read(fd, min(left, 1 << 16))
            if not chunk:
                break
            chunks.append(chunk)
            left -= len(chunk)
    except OSError:
        return None
    finally:
        os.close(fd)
    lines = b"".join(chunks).split(b"\n")
    return lines[1:] if start > 0 else lines


def _calls(record):
    message = record.get("message") if isinstance(record, dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    return [b.get("id") for b in content if isinstance(b, dict) and b.get("type") == "tool_use"] if isinstance(content, list) else []


def call_record(lines, call_id):
    """The one record whose `message.content` holds the `tool_use` block of `call_id`, or None.

    Other records that merely mention the id (attachments, queue operations, results) are skipped, and so is a line that is not
    valid JSON. Two records holding the same block are ambiguous: None. There is deliberately no fallback to "the last line"."""
    needle = call_id.encode()
    found = []
    for line in lines:
        if needle not in line:
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if call_id in _calls(record):
            found.append(record)
    return found[0] if len(found) == 1 else None


def _main(record, session_id):
    if (record.get("type") != "assistant" or record.get("sessionId") != session_id or record.get("isSidechain") is True):
        return None
    model, effort = record["message"].get("model"), record.get("effort")
    if not safe_model_id(model) or model.startswith("<") or effort not in EFFORTS:
        return None
    return model, effort


def main_model(event):
    """(model, effort) of the main conversation turn that made this call, or None when it cannot be read exactly."""
    if not isinstance(event, dict):
        return None
    session, call = event.get("session_id"), event.get("tool_use_id")
    if not safe_id(session) or not safe_id(call):
        return None
    lines = _tail(event.get("transcript_path"))
    record = call_record(lines, call) if lines is not None else None
    return _main(record, session) if record is not None else None
