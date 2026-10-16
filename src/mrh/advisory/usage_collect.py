"""Collect what each sub-agent actually used, from the vendors' own local transcript files (`mrh usage collect`).

Read-only and local: no network, no classifier. Only numbers, model names, effort and identifiers are kept; task text never
reaches the database. A transcript is collected only once it has stopped changing, and a collected one is never read again.

Known limits, stated where they matter rather than patched over:
- Claude transcripts record `output_tokens` at the start of the stream, not the final count. Claude output is therefore always
  `None` (unknown) and is never estimated.
- A Codex rollout keeps one cumulative token total per thread. If the thread used several models, the total cannot be split
  between them and is stored under one combined key that the price table does not know.
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

from mrh.routing.types import safe_id

CLAUDE_ENV = "MRH_CLAUDE_PROJECTS"
CODEX_ENV = "MRH_CODEX_SESSIONS"
SETTLE_SECONDS = 600            # a transcript changed more recently than this may still be running
MAX_FILE_BYTES = 256 * 1024 * 1024
LARGE_PROMPT = 100_000          # prompt tokens (input + cache writes + cache reads) above which Haiku uses its higher price tier
MIXED = "(多個模型)"
_ID = re.compile(r"[A-Za-z0-9_.-]{1,128}")
_FIELDS = ("input", "cache_write_5m", "cache_write_1h", "cache_write", "cache_read")


def roots(environ=None):
    environ = os.environ if environ is None else environ
    return (Path(environ.get(CLAUDE_ENV) or Path.home() / ".claude/projects"),
            Path(environ.get(CODEX_ENV) or Path.home() / ".codex/sessions"))


def _n(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _blank():
    return {name: 0 for name in _FIELDS}


def _empty_entry():
    return {"requests": 0, "output": None, "reasoning": None, "small": _blank(), "large": _blank()}


def _lines(path):
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("too_large")
    with open(path, encoding="utf-8", errors="replace") as handle:
        yield from handle


def _stable(*paths, now):
    return all(now - p.stat().st_mtime >= SETTLE_SECONDS for p in paths)


# ---- Claude Code -------------------------------------------------------------------------------------------------------
def parse_claude(path):
    """{model: entry}. Messages repeat in the file (one line per content block), so they are counted once by message id."""
    seen, entries = set(), {}
    for line in _lines(path):
        if '"usage"' not in line:
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        message = record.get("message") if isinstance(record, dict) and record.get("type") == "assistant" else None
        if not isinstance(message, dict):
            continue
        usage, mid, model = message.get("usage"), message.get("id"), message.get("model")
        if not isinstance(usage, dict) or not isinstance(mid, str) or not isinstance(model, str) or model.startswith("<") or mid in seen:
            continue
        seen.add(mid)
        created = usage.get("cache_creation") if isinstance(usage.get("cache_creation"), dict) else {}
        w5, w1 = _n(created.get("ephemeral_5m_input_tokens")), _n(created.get("ephemeral_1h_input_tokens"))
        unspecified = max(0, _n(usage.get("cache_creation_input_tokens")) - w5 - w1)
        parts = {"input": _n(usage.get("input_tokens")), "cache_write_5m": w5, "cache_write_1h": w1,
                 "cache_write": unspecified, "cache_read": _n(usage.get("cache_read_input_tokens"))}
        entry = entries.setdefault(model, _empty_entry())
        entry["requests"] += 1
        bucket = "large" if sum(parts.values()) > LARGE_PROMPT else "small"
        for name, value in parts.items():
            entry[bucket][name] += value
    return entries


def find_claude_child(root, session_id, agent_id, call_id):
    """(meta path, transcript path, effort) when the sub-agent's own files exist and belong to this tool call, else None."""
    if not (_ID.fullmatch(session_id or "") and _ID.fullmatch(agent_id or "")):
        return None
    for meta in sorted(Path(root).glob(f"*/{session_id}/subagents/agent-{agent_id}.meta.json")):
        transcript = meta.with_name(meta.name.removesuffix(".meta.json") + ".jsonl")
        try:
            data = json.loads(meta.read_text())
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data.get("toolUseId") == call_id and transcript.is_file():
            effort = data.get("effort")
            return meta, transcript, effort if isinstance(effort, str) and safe_id(effort) else None
    return None


def claude_parent_models(root, session_id, call_ids):
    """{call_id: model of the parent message that made the call}, scanning the parent transcript once."""
    wanted, found = set(call_ids), {}
    if not _ID.fullmatch(session_id or ""):
        return found
    for path in sorted(Path(root).glob(f"*/{session_id}.jsonl")):
        try:
            for line in _lines(path):
                if "tool_use" not in line or not any(c in line for c in wanted):
                    continue
                try:
                    message = (json.loads(line) or {}).get("message") or {}
                except ValueError:
                    continue
                for block in message.get("content") or []:
                    if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("id") in wanted:
                        model = message.get("model")
                        if isinstance(model, str) and not model.startswith("<"):
                            found.setdefault(block["id"], model)
        except (OSError, ValueError):
            continue
        if wanted <= set(found):
            break
    return found


# ---- Codex -------------------------------------------------------------------------------------------------------------
def _spawn_source(first_line):
    try:
        meta = json.loads(first_line).get("payload") or {}
        spawn = ((meta.get("source") or {}).get("subagent") or {}).get("thread_spawn")
        if isinstance(spawn, dict):
            return spawn.get("parent_thread_id"), spawn.get("agent_path"), meta.get("timestamp")
    except (ValueError, AttributeError):
        pass
    return None


def index_codex(root, timestamps):
    """{(parent_thread_id, agent_path): [(start epoch, file), ...]} for the day folders around the given epoch seconds (first line only)."""
    days = set()
    for ts in timestamps:
        for shift in (-86400, 0, 86400):
            for converter in (time.localtime, time.gmtime):
                t = converter(ts + shift)
                days.add((t.tm_year, t.tm_mon, t.tm_mday))
    index = {}
    for y, m, d in sorted(days):
        folder = Path(root) / f"{y:04d}" / f"{m:02d}" / f"{d:02d}"
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("rollout-*.jsonl")):
            try:
                with open(path, encoding="utf-8", errors="replace") as handle:
                    source = _spawn_source(handle.readline())
            except OSError:
                continue
            if source and source[0] and source[1]:
                index.setdefault((source[0], source[1]), []).append((_epoch(source[2], path), path))
    return index


def _epoch(stamp, path):
    """When the thread started: its own session timestamp, else the file's modification time."""
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
    except (AttributeError, ValueError):
        return path.stat().st_mtime


def parse_codex(path):
    """(models, entries): every (model, effort) the thread ran with, and its final cumulative token total."""
    models, total = [], None
    for line in _lines(path):
        if '"turn_context"' in line:
            try:
                payload = (json.loads(line).get("payload") or {})
            except ValueError:
                continue
            model, effort = payload.get("model"), payload.get("effort") or payload.get("reasoning_effort")
            if isinstance(model, str) and safe_id(model):
                pair = {"model": model, **({"effort": effort} if isinstance(effort, str) and safe_id(effort) else {})}
                if pair not in models:
                    models.append(pair)
        elif '"token_count"' in line:
            try:
                payload = (json.loads(line).get("payload") or {})
            except ValueError:
                continue
            usage = ((payload.get("info") or {}).get("total_token_usage")) if payload.get("type") == "token_count" else None
            if isinstance(usage, dict):
                total = usage
    if total is None:
        return models, {}
    cached, written = _n(total.get("cached_input_tokens")), _n(total.get("cache_write_input_tokens"))
    entry = _empty_entry()
    entry["small"].update(input=max(0, _n(total.get("input_tokens")) - cached - written), cache_read=cached, cache_write=written)
    entry["output"], entry["reasoning"] = _n(total.get("output_tokens")), _n(total.get("reasoning_output_tokens"))
    distinct = sorted({m["model"] for m in models})
    return models, {(distinct[0] if len(distinct) == 1 else MIXED): entry}


def codex_parent_models(root, parent_id, call_ids):
    """{call_id: the model in effect when the parent made the call} from the parent rollout, scanned once."""
    wanted, found = set(call_ids), {}
    if not _ID.fullmatch(parent_id or ""):
        return found
    for path in sorted(Path(root).glob(f"*/*/*/rollout-*-{parent_id}.jsonl")):
        current = None
        try:
            for line in _lines(path):
                if '"turn_context"' in line:
                    try:
                        model = (json.loads(line).get("payload") or {}).get("model")
                    except ValueError:
                        continue
                    current = model if isinstance(model, str) and safe_id(model) else current
                elif current and '"function_call"' in line:
                    for call in wanted:
                        if call in line and call not in found:
                            found[call] = current
        except (OSError, ValueError):
            continue
    return found


# ---- orchestration -----------------------------------------------------------------------------------------------------
def collect(store, now, *, days=30, claude_root=None, codex_root=None):
    """Collect every recorded sub-agent whose transcript is finished. Returns counts plus a reason per child that was not."""
    default_claude, default_codex = roots()
    claude_root, codex_root = Path(claude_root or default_claude), Path(codex_root or default_codex)
    candidates = store.usage_candidates(now - days * 86400)
    summary = {"candidates": len(candidates), "collected": 0, "running": 0, "not_found": 0, "unreadable": 0, "other": 0, "details": []}

    def note(kind, child, reason):
        summary[kind] += 1
        summary["details"].append({"platform": child["platform"], "call_id": child["call_id"], "reason": reason})

    claude = [c for c in candidates if c["platform"] == "claude"]
    codex = [c for c in candidates if c["platform"] == "codex"]
    for child in candidates:
        if child["platform"] not in ("claude", "codex"):
            note("other", child, "platform_not_supported")

    parents = {}
    for child in claude:
        parents.setdefault(child["session_id"], []).append(child["call_id"])
    claude_models = {s: claude_parent_models(claude_root, s, ids) for s, ids in parents.items()}
    for child in claude:
        found = find_claude_child(claude_root, child["session_id"], child["agent_id"], child["call_id"])
        if not found:
            note("not_found", child, "claude_transcript_not_found"); continue
        meta, transcript, effort = found
        try:
            if not _stable(meta, transcript, now=now):
                note("running", child, "transcript_changed_within_10_minutes"); continue
            entries = parse_claude(transcript)
        except (OSError, ValueError) as exc:
            note("unreadable", child, str(exc) if str(exc) == "too_large" else "read_error"); continue
        if not entries:
            note("unreadable", child, "no_usage_records"); continue
        store.save_usage({"platform": "claude", "session_id": child["session_id"], "call_id": child["call_id"], "ts": child["ts"],
                          "source_file": transcript.name, "models": [{"model": m, **({"effort": effort} if effort else {})} for m in sorted(entries)],
                          "usage": entries, "parent_model": claude_models.get(child["session_id"], {}).get(child["call_id"]),
                          "collected_at": now})
        summary["collected"] += 1

    if codex:
        index = index_codex(codex_root, [c["ts"] for c in codex])
        parents = {}
        for child in codex:
            parents.setdefault(child["session_id"], []).append(child["call_id"])
        codex_models = {s: codex_parent_models(codex_root, s, ids) for s, ids in parents.items()}
        for child in codex:
            files = index.get((child["session_id"], child["agent_id"]), [])
            if not files:
                note("not_found", child, "codex_rollout_not_found"); continue
            path = min(files, key=lambda item: abs(item[0] - child["ts"]))[1]       # a reused name: the thread that started nearest in time
            try:
                if not _stable(path, now=now):
                    note("running", child, "transcript_changed_within_10_minutes"); continue
                models, entries = parse_codex(path)
            except (OSError, ValueError) as exc:
                note("unreadable", child, str(exc) if str(exc) == "too_large" else "read_error"); continue
            if not entries:
                note("unreadable", child, "no_usage_records"); continue
            store.save_usage({"platform": "codex", "session_id": child["session_id"], "call_id": child["call_id"], "ts": child["ts"],
                              "source_file": path.name, "models": models, "usage": entries,
                              "parent_model": codex_models.get(child["session_id"], {}).get(child["call_id"]), "collected_at": now})
            summary["collected"] += 1
    return summary
