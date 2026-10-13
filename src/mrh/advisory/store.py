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

    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        return db

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
        """Link a started child to the newest unfollowed advice whose candidates include its model."""
        followed_id = None
        with self.connect() as db:
            if child.requested_model:
                rows = db.execute("SELECT * FROM advice WHERE platform=? AND session_id=? AND action='advise' AND ts>=? "
                                  "ORDER BY ts DESC", (child.platform, child.session_id, now - FOLLOW_WINDOW_SECONDS)).fetchall()
                taken = {r[0] for r in db.execute("SELECT advice_request_id FROM children WHERE followed=1 AND advice_request_id IS NOT NULL")}
                for row in rows:
                    models = {c["model"] for c in json.loads(row["candidates"])}
                    if row["request_id"] not in taken and child.requested_model in models:
                        followed_id = row["request_id"]
                        break
            db.execute("INSERT OR IGNORE INTO children VALUES(?,?,?,?,?,?,?,?,?,?)",
                       (child.call_id, child.platform, child.session_id, now, child.requested_model, child.requested_effort,
                        child.resolved_model, child.agent_id, followed_id, 1 if followed_id else 0))
        return followed_id is not None

    def stats(self, since):
        """Counts since `since` (epoch seconds), overall and per platform. No task text exists to return."""
        with self.connect() as db:
            q = lambda sql: db.execute(sql, (since,)).fetchall()
            by_action = {r[0]: r[1] for r in q("SELECT action,COUNT(*) FROM advice WHERE ts>=? GROUP BY action")}
            per_platform = {}
            for platform, action, n in q("SELECT platform,action,COUNT(*) FROM advice WHERE ts>=? GROUP BY platform,action"):
                per_platform.setdefault(platform, {})[action] = n
            reasons = {r[0]: r[1] for r in q("SELECT reason,COUNT(*) FROM advice WHERE action='preserve' AND ts>=? GROUP BY reason")}
            tiers = {r[0]: r[1] for r in q("SELECT tier,COUNT(*) FROM advice WHERE tier IS NOT NULL AND ts>=? GROUP BY tier")}
            usage = {r[0]: {"calls": r[1], "input_tokens": r[2], "output_tokens": r[3]}
                     for r in q("SELECT kind,COUNT(*),COALESCE(SUM(input_tokens),0),COALESCE(SUM(output_tokens),0) "
                                "FROM attempts WHERE ts>=? AND outcome='returned' GROUP BY kind")}
            kids = db.execute("SELECT COUNT(*),COALESCE(SUM(followed),0) FROM children WHERE ts>=?", (since,)).fetchone()
            followed_models = {r[0]: r[1] for r in q("SELECT COALESCE(resolved_model, requested_model),COUNT(*) FROM children "
                                                     "WHERE followed=1 AND ts>=? GROUP BY 1")}
        return {"since": since, "decisions": by_action, "per_platform": per_platform, "kept_unchanged": reasons,
                "tiers": tiers, "classifier_usage": usage,
                "classifier_calls": sum(u["calls"] for u in usage.values()),
                "classifier_input_tokens": sum(u["input_tokens"] for u in usage.values()),
                "classifier_output_tokens": sum(u["output_tokens"] for u in usage.values()),
                "children_started": kids[0], "children_following_advice": kids[1], "followed_models": followed_models}
