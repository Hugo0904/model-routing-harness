"""advice.sqlite3: idempotency, one-advice-per-task dedupe, outcomes and statistics.

Task text is never stored; only a salted-free SHA-256 of the normalized text, used
for dedupe. Nothing here can hold a credential.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time

DEDUPE_SECONDS = 600
FOLLOW_WINDOW_SECONDS = 600

_SCHEMA = """
CREATE TABLE IF NOT EXISTS advice(
  request_id TEXT PRIMARY KEY, ts REAL NOT NULL, platform TEXT NOT NULL, session_id TEXT NOT NULL,
  turn_id TEXT NOT NULL, call_id TEXT NOT NULL, task_hash TEXT NOT NULL, action TEXT NOT NULL,
  reason TEXT NOT NULL, tier TEXT, confidence REAL, provider TEXT, candidates TEXT NOT NULL DEFAULT '[]');
CREATE INDEX IF NOT EXISTS advice_task ON advice(platform, session_id, task_hash, ts);
CREATE TABLE IF NOT EXISTS attempts(
  request_id TEXT NOT NULL, ts REAL NOT NULL, kind TEXT NOT NULL, outcome TEXT NOT NULL,
  requested_model TEXT, response_model TEXT, input_tokens INTEGER, output_tokens INTEGER, error_reason TEXT);
CREATE TABLE IF NOT EXISTS notices(session_id TEXT NOT NULL, reason TEXT NOT NULL, ts REAL NOT NULL, PRIMARY KEY(session_id, reason));
CREATE TABLE IF NOT EXISTS children(
  call_id TEXT NOT NULL, platform TEXT NOT NULL, session_id TEXT NOT NULL, ts REAL NOT NULL,
  requested_model TEXT, requested_effort TEXT, resolved_model TEXT, agent_id TEXT,
  advice_request_id TEXT, followed INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(platform, session_id, call_id));
"""
_META = {"requested_model", "response_model", "input_tokens", "output_tokens", "error_reason"}


def payload(row):
    """Legacy candidate lists and new correlation metadata share the existing JSON field."""
    value = json.loads(row["candidates"])
    return {"candidates": value} if isinstance(value, list) else (value if isinstance(value, dict) else {})


def candidates(row):
    return tuple(payload(row).get("candidates", ()))


def _matches(row, model, effort):
    return any(c.get("model") == model and (not c.get("effort") or c["effort"] == effort)
               for c in candidates(row))


def _links(rows):
    """Validate links recorded at hook time. Same platform, session and turn; the re-issued model/effort must match a suggestion."""
    by_id = {r["request_id"]: r for r in rows}
    links, claims = {}, {}
    for replacement in rows:
        link = payload(replacement).get("correlation", {})
        if not isinstance(link, dict):
            continue
        original = by_id.get(link.get("advice_request_id"))
        if (link.get("version") != 1 or not original or original["action"] != "advise"
                or replacement["action"] != "preserve" or replacement["reason"] != "advice_reissue"
                or any(original[k] != replacement[k] for k in ("platform", "session_id", "turn_id"))
                or not 0 <= replacement["ts"] - original["ts"] <= FOLLOW_WINDOW_SECONDS
                or not _matches(original, link.get("model"), link.get("effort"))):
            continue
        claims.setdefault(original["request_id"], []).append(replacement["request_id"])
        links[replacement["request_id"]] = (original, link)
    return {rid: link for rid, link in links.items() if len(claims[link[0]["request_id"]]) == 1}


def _inferred(rows, children, links):
    """Older rows carry no recorded link. Pair each re-issued child with the earliest unclaimed suggestion of the same
    platform, session and turn whose model/effort it matches, within the follow window. One suggestion is used once."""
    by_call = {(r["platform"], r["session_id"], r["call_id"]): r for r in rows}
    taken = {original["request_id"] for original, _ in links.values()}
    found = {}
    for child in sorted(children, key=lambda c: c["ts"]):
        pre = by_call.get((child["platform"], child["session_id"], child["call_id"]))
        if (not pre or pre["request_id"] in links or pre["action"] != "preserve" or not child["requested_model"]
                or pre["reason"] not in ("explicit_model", "advice_reissue")):
            continue
        eligible = sorted((r for r in rows if r["action"] == "advise" and r["request_id"] not in taken
                           and all(r[k] == pre[k] for k in ("platform", "session_id", "turn_id"))
                           and 0 <= pre["ts"] - r["ts"] <= FOLLOW_WINDOW_SECONDS
                           and _matches(r, child["requested_model"], child["requested_effort"])), key=lambda r: r["ts"])
        if eligible:
            taken.add(eligible[0]["request_id"])
            found[pre["request_id"]] = (eligible[0], {"version": 1, "advice_request_id": eligible[0]["request_id"],
                                                     "model": child["requested_model"], "effort": child["requested_effort"]})
    return found


def task_hash(platform, session_id, task):
    normalized = " ".join(str(task).split())
    return hashlib.sha256(json.dumps([platform, session_id, normalized]).encode()).hexdigest()


def request_id(platform, session_id, turn_id, call_id):
    return hashlib.sha256(json.dumps([platform, session_id, turn_id, call_id]).encode()).hexdigest()


class AdviceStore:
    def __init__(self, path):
        self.path = str(path)
        first = not os.path.exists(self.path)
        with self.connect() as db:
            db.executescript(_SCHEMA)
        if first:
            os.chmod(self.path, 0o600)

    def connect(self, readonly=False):
        from pathlib import Path
        db = sqlite3.connect(Path(self.path).resolve().as_uri() + "?mode=ro", uri=True, timeout=5) if readonly else sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        if not readonly:
            db.execute("PRAGMA journal_mode=WAL")
        return db

    @classmethod
    def read_stats(cls, path, since):
        reader = cls.__new__(cls)
        reader.path = str(path)
        return reader.stats(since)

    def call(self, rid):
        with self.connect() as db:
            row = db.execute("SELECT * FROM advice WHERE request_id=?", (rid,)).fetchone()
        return dict(row) if row else None

    def recent_advice(self, platform, session_id, thash, now):
        with self.connect() as db:
            row = db.execute("SELECT * FROM advice WHERE platform=? AND session_id=? AND task_hash=? AND ts>=? "
                             "AND action IN ('advise','continue_main') ORDER BY ts DESC LIMIT 1",
                             (platform, session_id, thash, now - DEDUPE_SECONDS)).fetchone()
        return dict(row) if row else None

    def preserve_explicit(self, rid, req, thash, provider, now):
        """Claim a unique same-task advice and save the replacement atomically."""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT * FROM advice WHERE request_id=?", (rid,)).fetchone()
            if existing:
                return {**dict(existing), "_replayed": True}
            rows = db.execute("SELECT * FROM advice WHERE platform=? AND session_id=?",
                              (req.platform, req.session_id)).fetchall()
            taken = {original["request_id"] for original, _ in _links(rows).values()}
            # Historical claimed children are left untouched, but are not claimed again.
            taken.update(r[0] for r in db.execute("SELECT advice_request_id FROM children WHERE platform=? AND session_id=?",
                                                 (req.platform, req.session_id)) if r[0])
            eligible = sorted((r for r in rows if r["action"] == "advise" and r["turn_id"] == req.turn_id
                               and now - FOLLOW_WINDOW_SECONDS <= r["ts"] <= now
                               and r["request_id"] not in taken and _matches(r, req.explicit_model, req.explicit_effort)),
                              key=lambda r: r["ts"])
            data, reason = [], "explicit_model"
            if eligible:                       # parallel spawns with the same suggestion are paired one-to-one, oldest first
                reason = "advice_reissue"
                data = {"candidates": [], "correlation": {"version": 1, "advice_request_id": eligible[0]["request_id"],
                        "model": req.explicit_model, "effort": req.explicit_effort}}
            db.execute("INSERT INTO advice VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (rid, now, req.platform, req.session_id, req.turn_id, req.call_id, thash,
                        "preserve", reason, None, None, provider, json.dumps(data)))
            return {**dict(db.execute("SELECT * FROM advice WHERE request_id=?", (rid,)).fetchone()), "_replayed": False}

    def save(self, rid, req, thash, advice, provider, now):
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO advice VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (rid, now, req.platform, req.session_id, req.turn_id, req.call_id, thash, advice.action,
                        advice.reason, advice.tier, advice.confidence, provider, json.dumps(list(advice.candidates))))

    def attempt(self, rid, kind, outcome, now, **meta):
        values = {k: v for k, v in meta.items() if k in _META}
        with self.connect() as db:
            db.execute("INSERT INTO attempts VALUES(?,?,?,?,?,?,?,?,?)",
                       (rid, now, kind, outcome, values.get("requested_model"), values.get("response_model"),
                        values.get("input_tokens"), values.get("output_tokens"), values.get("error_reason")))

    def first_notice(self, session_id, reason, now):
        with self.connect() as db:
            return db.execute("INSERT OR IGNORE INTO notices VALUES(?,?,?)", (session_id, reason, now)).rowcount == 1

    def record_child(self, child, now):
        """Only the exact pre-call's recorded correlation can establish adoption."""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute("SELECT * FROM advice WHERE platform=? AND session_id=?",
                              (child.platform, child.session_id)).fetchall()
            pre = [r for r in rows if r["call_id"] == child.call_id]
            link = _links(rows).get(pre[0]["request_id"]) if len(pre) == 1 else None
            followed_id = (link[0]["request_id"] if link and now >= pre[0]["ts"] and child.agent_id and child.requested_model == link[1]["model"]
                           and child.requested_effort == link[1]["effort"] else None)
            db.execute("INSERT OR IGNORE INTO children VALUES(?,?,?,?,?,?,?,?,?,?)",
                       (child.call_id, child.platform, child.session_id, now, child.requested_model, child.requested_effort,
                        child.resolved_model, child.agent_id, followed_id, 1 if followed_id else 0))
            saved = db.execute("SELECT * FROM children WHERE platform=? AND session_id=? AND call_id=?",
                               (child.platform, child.session_id, child.call_id)).fetchone()
        return bool(followed_id and saved["advice_request_id"] == followed_id and saved["followed"]
                    and saved["agent_id"] == child.agent_id and saved["requested_model"] == child.requested_model
                    and saved["requested_effort"] == child.requested_effort)

    def stats(self, since):
        """Counts since `since` (epoch seconds), overall and per platform. No task text exists to return."""
        with self.connect(readonly=True) as db:
            db.execute("BEGIN")
            rows = db.execute("SELECT * FROM advice").fetchall()
            attempts = db.execute("SELECT * FROM attempts WHERE ts>=?", (since,)).fetchall()
            every_child = db.execute("SELECT * FROM children").fetchall()
        children = [c for c in every_child if c["ts"] >= since]
        links = _links(rows)
        inferred = _inferred(rows, every_child, links)
        links.update(inferred)
        by_call = {}
        for row in rows:
            by_call.setdefault((row["platform"], row["session_id"], row["call_id"]), []).append(row)
        recent = [r for r in rows if r["ts"] >= since]
        counted = [r for r in recent if r["request_id"] not in links]
        by_action, per_platform, reasons, tiers = {}, {}, {}, {}
        def inc(mapping, key):
            mapping[key] = mapping.get(key, 0) + 1
        for row in counted:
            inc(by_action, row["action"]); inc(per_platform.setdefault(row["platform"], {}), row["action"])
            if row["action"] == "preserve": inc(reasons, row["reason"])
            if row["tier"] is not None: inc(tiers, row["tier"])
        usage, grouped = {}, {}
        for row in attempts:
            grouped.setdefault((row["request_id"], row["kind"]), []).append(row)
        for (_, kind), events in grouped.items():
            u = usage.setdefault(kind, {"calls": 0, "requests": 0, "returned": 0, "failed": 0, "unknown": 0,
                                       "input_tokens": 0, "output_tokens": 0, "usage_unknown_calls": 0})
            phases = {e["outcome"] for e in events}; u["requests"] += 1
            entered = bool(phases & {"started", "returned", "error", "unknown", "late_returned", "late_error"})
            u["calls"] += int(entered)
            returned = bool(phases & {"returned", "late_returned"})
            failed = bool(phases & {"error", "late_error", "classification_error"}) and not returned
            u["returned"] += int(returned); u["failed"] += int(failed); u["unknown"] += int(entered and not returned and not failed)
            for field in ("input_tokens", "output_tokens"):
                u[field] += max((e[field] for e in events if e[field] is not None), default=0)
            u["usage_unknown_calls"] += int(entered and not any(e["input_tokens"] is not None for e in events))
        followed_models, requested_models, observed_models, followed, unverified, prior = {}, {}, {}, 0, 0, 0
        for child in children:
            if child["resolved_model"]:
                inc(observed_models, child["resolved_model"])
            pre = by_call.get((child["platform"], child["session_id"], child["call_id"]), [])
            link = links.get(pre[0]["request_id"]) if len(pre) == 1 else None
            valid = (link and child["ts"] >= pre[0]["ts"]
                     and child["requested_model"] == link[1]["model"] and child["requested_effort"] == link[1]["effort"])
            if valid:
                if link[0]["ts"] < since:
                    prior += 1
                    continue
                followed += 1
                inc(followed_models if child["resolved_model"] else requested_models,
                    child["resolved_model"] or child["requested_model"])
            elif child["followed"]:
                unverified += 1
        return {"since": since, "reissues": sum(r["request_id"] in links for r in recent),
                "inferred_links": sum(r["request_id"] in inferred for r in recent),
                "unverified_reissues": sum(r["reason"] == "advice_reissue" for r in counted),
                "unverified_followed_children": unverified,
                "children_following_prior_advice": prior,
                "decisions": by_action, "per_platform": per_platform, "kept_unchanged": reasons,
                "tiers": tiers, "classifier_usage": usage,
                "classifier_calls": sum(u["calls"] for u in usage.values()),
                "classifier_requests": sum(u["requests"] for u in usage.values()),
                "classifier_failed_requests": sum(u["failed"] for u in usage.values()),
                "classifier_input_tokens": sum(u["input_tokens"] for u in usage.values()),
                "classifier_output_tokens": sum(u["output_tokens"] for u in usage.values()),
                "children_started": len(children), "children_following_advice": followed,
                "followed_models": followed_models, "followed_requested_models": requested_models,
                "observed_models": observed_models}
