"""Collect what each sub-agent actually used, from the vendors' own local transcript files (`mrh usage collect`).

Read-only and local: no network, no classifier. Only numbers, model names, effort and identifiers are kept; task text never
reaches the database. Settled files provide snapshots, not lifecycle completion. Explicit collection refreshes changed sources; unchanged bodies are not read.

Known limits, stated where they matter rather than patched over:
- Claude transcripts record `output_tokens` at the start of the stream, not the final count. Claude output is therefore always
  `None` (unknown) and is never estimated.
- A Codex rollout keeps one cumulative token total per thread. If the thread used several models, the total cannot be split
  between them and is stored under one combined key that the price table does not know.
"""
from __future__ import annotations

import json
import math
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
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _required(value, field):
    value = _n(value)
    if value is None:
        raise ValueError("invalid_usage:" + field)
    return value


def observation(usage):
    """Metadata shared by every entry; absent or inconsistent means legacy/unverified."""
    if not isinstance(usage, dict) or not usage:
        return None
    values = [e.get("observation") if isinstance(e, dict) else None for e in usage.values()]
    first = values[0]
    if not isinstance(first, dict) or type(first.get("version")) is not int or first["version"] != 1 or first.get("semantics") != "settled_snapshot":
        return None
    stamp = first.get("collected_at")
    if type(stamp) not in (int, float) or stamp < 0 or not math.isfinite(stamp):
        return None
    if not isinstance(first.get("sources"), list) or not first["sources"]:
        return None
    if any(v != first for v in values):
        return None
    for source in first["sources"]:
        if not isinstance(source, dict) or not isinstance(source.get("name"), str) or Path(source["name"]).name != source["name"]:
            return None
        if any(_n(source.get(k)) is None for k in ("device", "inode", "size", "mtime_ns")):
            return None
    return first


def _fingerprint(paths):
    result = []
    for path in paths:
        st = path.stat()
        result.append({"name": path.name, "device": st.st_dev, "inode": st.st_ino, "size": st.st_size, "mtime_ns": st.st_mtime_ns})
    return result


def _blank():
    return {name: 0 for name in _FIELDS}


def _empty_entry():
    return {"requests": 0, "output": None, "reasoning": None, "small": _blank(), "large": _blank()}


def _lines(path):
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("too_large")
    with open(path, encoding="utf-8", errors="replace") as handle:
        yield from handle


# ---- Claude Code -------------------------------------------------------------------------------------------------------
def parse_claude(path):
    """{model: entry}. Messages repeat in the file (one line per content block), so they are counted once by message id."""
    seen, entries = {}, {}
    for line in _lines(path):
        if '"usage"' not in line:
            continue
        try:
            record = json.loads(line)
        except ValueError:
            raise ValueError("invalid_usage:json") from None
        message = record.get("message") if isinstance(record, dict) and record.get("type") == "assistant" else None
        if not isinstance(message, dict) or "usage" not in message:
            continue
        usage, mid, model = message.get("usage"), message.get("id"), message.get("model")
        if isinstance(model, str) and model.startswith("<"):
            continue
        if not isinstance(usage, dict) or not isinstance(mid, str) or not mid or not isinstance(model, str) or not safe_id(model):
            raise ValueError("invalid_usage:message_identity")
        inp = _required(usage.get("input_tokens"), "input_tokens")
        read = _required(usage.get("cache_read_input_tokens"), "cache_read_input_tokens")
        written = _required(usage.get("cache_creation_input_tokens"), "cache_creation_input_tokens")
        created = usage.get("cache_creation")
        if created is None and written == 0:
            w5 = w1 = 0  # nonnegative components of an observed zero total
        elif created is None:
            raise ValueError("invalid_usage:cache_creation_ttl_split")
        elif isinstance(created, dict):
            w5 = _required(created.get("ephemeral_5m_input_tokens"), "ephemeral_5m_input_tokens")
            w1 = _required(created.get("ephemeral_1h_input_tokens"), "ephemeral_1h_input_tokens")
            if w5 + w1 > written:
                raise ValueError("inconsistent_usage:cache_creation")
        else:
            raise ValueError("invalid_usage:cache_creation")
        parts = {"input": inp, "cache_write_5m": w5, "cache_write_1h": w1,
                 "cache_write": written - w5 - w1, "cache_read": read}
        signature = (model, parts)
        if mid in seen:
            if seen[mid] != signature:
                raise ValueError("inconsistent_usage:repeated_message")
            continue
        seen[mid] = signature
        entry = entries.setdefault(model, _empty_entry())
        entry["requests"] += 1
        bucket = "large" if inp + read + written > LARGE_PROMPT else "small"
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
    """Observed profiles and the latest cumulative token snapshot; absent values stay unknown."""
    models, total, previous = [], None, None
    requests, lengths, complete = 0, [], True
    accounted_input = accounted_output = 0
    for line in _lines(path):
        if '"turn_context"' not in line and '"token_count"' not in line:
            continue
        try:
            record = json.loads(line)
        except ValueError:
            raise ValueError("invalid_usage:json") from None
        if not isinstance(record, dict) or not isinstance(record.get("payload"), dict):
            raise ValueError("invalid_usage:event_payload")
        payload = record["payload"]
        if record.get("type") == "turn_context":
            model, effort = payload.get("model"), payload.get("effort") or payload.get("reasoning_effort")
            if isinstance(model, str) and safe_id(model):
                pair = {"model": model, **({"effort": effort} if isinstance(effort, str) and safe_id(effort) else {})}
                if pair not in models:
                    models.append(pair)
            elif {} not in models:
                models.append({})
            continue
        if payload.get("type") != "token_count":
            continue
        info = payload.get("info")
        if info is None:
            continue  # native token_count can report only rate limits, without usage
        if not isinstance(info, dict):
            raise ValueError("invalid_usage:token_info")
        current = info.get("total_token_usage")
        if current is None:
            raise ValueError("invalid_usage:total_token_usage")
        if not isinstance(current, dict):
            raise ValueError("invalid_usage:total_token_usage")
        counts = {k: _required(current.get(k), k) for k in
                  ("input_tokens", "cached_input_tokens", "cache_write_input_tokens", "output_tokens")}
        if counts["cached_input_tokens"] + counts["cache_write_input_tokens"] > counts["input_tokens"]:
            raise ValueError("inconsistent_usage:input_components")
        if "total_tokens" in current and _required(current["total_tokens"], "total_tokens") != counts["input_tokens"] + counts["output_tokens"]:
            raise ValueError("inconsistent_usage:total_tokens")
        reasoning = _n(current.get("reasoning_output_tokens"))
        if reasoning is not None and reasoning > counts["output_tokens"]:
            raise ValueError("inconsistent_usage:reasoning_output_tokens")
        if previous and any(counts[k] < previous[k] for k in counts):
            raise ValueError("inconsistent_usage:cumulative_reset")
        if counts != previous:
            last = info.get("last_token_usage")
            li = _n(last.get("input_tokens")) if isinstance(last, dict) else None
            lo = _n(last.get("output_tokens")) if isinstance(last, dict) else None
            delta_input = counts["input_tokens"] - (previous["input_tokens"] if previous else 0)
            delta_output = counts["output_tokens"] - (previous["output_tokens"] if previous else 0)
            if li is None or lo is None or li != delta_input or lo != delta_output:
                complete = False
            else:
                lengths.append(li); requests += 1
                accounted_input += li; accounted_output += lo
        total, previous = {**counts, "reasoning_output_tokens": reasoning}, counts
    if total is None:
        return models, {}
    entry = _empty_entry()
    entry["small"].update(input=total["input_tokens"] - total["cached_input_tokens"] - total["cache_write_input_tokens"],
                          cache_read=total["cached_input_tokens"], cache_write=total["cache_write_input_tokens"])
    entry["output"], entry["reasoning"] = total["output_tokens"], total["reasoning_output_tokens"]
    complete = complete and bool(lengths) and accounted_input == total["input_tokens"] and accounted_output == total["output_tokens"]
    entry["requests"] = requests if complete else None
    entry["max_request_input"] = max(lengths) if complete else None
    distinct = sorted({m["model"] for m in models if m.get("model")})
    unambiguous = len(distinct) == 1 and all(m.get("model") for m in models)
    return models, {(distinct[0] if unambiguous else MIXED): entry}


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
    """Explicitly refresh settled snapshots. Failures preserve the previous row and its as-of time."""
    default_claude, default_codex = roots()
    claude_root, codex_root = Path(claude_root or default_claude), Path(codex_root or default_codex)
    candidates = store.usage_candidates(now - days * 86400)
    summary = {"candidates": len(candidates), "collected": 0, "updated": 0, "unchanged": 0,
               "running": 0, "not_found": 0, "unreadable": 0, "other": 0, "details": []}

    def note(kind, child, reason):
        summary[kind] += 1
        summary["details"].append({"platform": child["platform"], "call_id": child["call_id"], "reason": reason})

    index = None
    parent_models = {}
    for child in candidates:
        platform = child["platform"]
        if platform not in ("claude", "codex"):
            note("other", child, "platform_not_supported"); continue
        root = claude_root if platform == "claude" else codex_root
        try:
            try:
                prior = observation(json.loads(child.get("previous_usage") or "{}"))
            except (ValueError, TypeError):
                prior = None
            # Resolve the recorded basenames without opening any transcript or Claude meta body.
            if prior:
                paths = []
                for source in prior["sources"]:
                    pattern = (f"*/{child['session_id']}/subagents/{source['name']}" if platform == "claude" else f"*/*/*/{source['name']}")
                    found = list(root.glob(pattern))
                    if len(found) != 1:
                        break
                    paths.append(found[0])
                if len(paths) == len(prior["sources"]) and _fingerprint(paths) == prior["sources"]:
                    summary["unchanged"] += 1
                    continue
            if platform == "claude":
                found = find_claude_child(root, child["session_id"], child["agent_id"], child["call_id"])
                if not found:
                    note("not_found", child, "claude_transcript_not_found"); continue
                meta, transcript, _ = found
                paths = [meta, transcript]
            else:
                if index is None:
                    index = index_codex(root, [c["ts"] for c in candidates if c["platform"] == "codex"])
                files = index.get((child["session_id"], child["agent_id"]), [])
                if not files:
                    note("not_found", child, "codex_rollout_not_found"); continue
                transcript = min(files, key=lambda item: abs(item[0] - child["ts"]))[1]
                paths = [transcript]
            before = _fingerprint(paths)
            if any(now - source["mtime_ns"] / 1e9 < SETTLE_SECONDS for source in before):
                note("running", child, "transcript_changed_within_10_minutes"); continue
            if platform == "claude":
                meta_data = json.loads(meta.read_text())
                if not isinstance(meta_data, dict) or meta_data.get("toolUseId") != child["call_id"]:
                    note("unreadable", child, "source_changed_during_read"); continue
                effort = meta_data.get("effort")
                effort = effort if isinstance(effort, str) and safe_id(effort) else None
                entries = parse_claude(transcript)
                models = [{"model": m, **({"effort": effort} if effort else {})} for m in sorted(entries)]
            else:
                models, entries = parse_codex(transcript)
            if not entries:
                note("unreadable", child, "no_usage_records"); continue
            parent_key = (platform, child["session_id"])
            if parent_key not in parent_models:
                ids = [c["call_id"] for c in candidates if c["platform"] == platform and c["session_id"] == child["session_id"]]
                reader = claude_parent_models if platform == "claude" else codex_parent_models
                parent_models[parent_key] = reader(root, child["session_id"], ids)
            if _fingerprint(paths) != before:
                note("unreadable", child, "source_changed_during_read"); continue
            metadata = {"version": 1, "semantics": "settled_snapshot", "sources": before, "collected_at": now}
            for entry in entries.values():
                entry["observation"] = metadata
            store.save_usage({"platform": platform, "session_id": child["session_id"], "call_id": child["call_id"], "ts": child["ts"],
                              "source_file": transcript.name, "models": models, "usage": entries,
                              "parent_model": parent_models[parent_key].get(child["call_id"]), "collected_at": now})
            summary["collected"] += 1
            summary["updated"] += int(child.get("previous_usage") is not None)
        except (OSError, ValueError) as exc:
            reason = str(exc)
            safe_reason = reason if reason == "too_large" or reason.startswith(("invalid_usage:", "inconsistent_usage:")) else "read_error"
            note("unreadable", child, safe_reason)
    return summary
