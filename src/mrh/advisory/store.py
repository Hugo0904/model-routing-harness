"""advice.sqlite3: idempotency, one-advice-per-task dedupe, outcomes and statistics.

Task text is never stored; only a salted-free SHA-256 of the normalized text, used
for dedupe. Nothing here can hold a credential.
"""
from __future__ import annotations

import hashlib
from contextlib import closing
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
CREATE TABLE IF NOT EXISTS packet_links(
  packet_id TEXT PRIMARY KEY, query_request_id TEXT NOT NULL UNIQUE,
  platform TEXT NOT NULL, session_id TEXT NOT NULL, turn_id TEXT NOT NULL,
  task_hash TEXT NOT NULL, body_sha256 TEXT NOT NULL, body_length INTEGER NOT NULL,
  workspace TEXT NOT NULL, revision INTEGER NOT NULL, query_call_id TEXT NOT NULL,
  ts REAL NOT NULL, release_request_id TEXT UNIQUE, release_call_id TEXT,
  release_ts REAL, selected_model TEXT, selected_effort TEXT, origin TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS packet_imports(
  packet_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, ts REAL NOT NULL);
"""
_META = {"requested_model", "response_model", "input_tokens", "output_tokens", "error_reason"}


def payload(row):
    """Legacy candidate lists and new correlation metadata share the existing JSON field."""
    value = json.loads(row["candidates"])
    return {"candidates": value} if isinstance(value, list) else (value if isinstance(value, dict) else {})


def candidates(row):
    return tuple(payload(row).get("candidates", ()))


def _average(rows, since):
    """{"avg": mean confidence or None, "n": classifications} for rows at or after `since`."""
    values = [r["confidence"] for r in rows if r["confidence"] is not None and r["ts"] >= since]
    return {"avg": sum(values) / len(values) if values else None, "n": len(values)}


def _encode(req, data, extra=None):
    """New rows always carry the spawn's role key (None when there was none): its presence marks rows that recorded it.
    `extra` is the classifier's own record (probabilities, answering model); only those two keys are kept."""
    from mrh.routing.types import safe_id
    role = req.role if req.role is None or safe_id(req.role) else "other"
    kept = {k: v for k, v in (extra or {}).items() if k in ("probabilities", "classifier_model")}
    return json.dumps({**({"candidates": data} if isinstance(data, list) else data), "role": role, **kept})


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


def _packet_rows(db):
    # Read-only older databases are not migrated by a status read.
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='packet_links'").fetchone():
        return []
    return [dict(r) for r in db.execute("SELECT * FROM packet_links")]


def _packet_relations(rows, packets):
    by_id = {r['request_id']: r for r in rows}
    result = {}
    for p in packets:
        query, release = by_id.get(p['query_request_id']), by_id.get(p['release_request_id'])
        if not query or not release:
            continue
        if (any(query[k] != p[k] or release[k] != p[k] for k in ('platform', 'session_id', 'turn_id', 'task_hash'))
                or query['call_id'] != p['query_call_id'] or release['call_id'] != p['release_call_id']
                or request_id(p['platform'], p['session_id'], p['turn_id'], p['query_call_id']) != query['request_id']
                or request_id(p['platform'], p['session_id'], p['turn_id'], p['release_call_id']) != release['request_id']
                or release['action'] != 'preserve' or not 0 <= release['ts'] - query['ts'] <= FOLLOW_WINDOW_SECONDS):
            continue
        if p['origin'] != 'legacy_import':
            meta = payload(release).get('packet', {})
            if meta != {k: p[k] for k in ('packet_id', 'query_request_id', 'body_sha256', 'body_length', 'workspace', 'revision', 'selected_model', 'selected_effort')}:
                continue
        elif release['reason'] != 'explicit_model':
            continue
        result[release['request_id']] = (query, {'model': p['selected_model'], 'effort': p['selected_effort']}, p)
    return result


class AdviceStore:
    def __init__(self, path):
        self.path = str(path)
        first = not os.path.exists(self.path)
        if first:
            try:
                fd = os.open(self.path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
                os.close(fd)
            except FileExistsError:
                first = False
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

    TABLES = ("advice", "attempts", "children", "notices")

    def _delete_plan(self, db, where, value):
        plan = {t:{r[0] for r in db.execute(f'SELECT rowid FROM {t} WHERE {where}',(value,))} for t in self.TABLES}
        for p in _packet_rows(db):
            q = db.execute('SELECT rowid FROM advice WHERE request_id=?',(p['query_request_id'],)).fetchone()
            if q and q[0] not in plan['advice']:
                continue
            if q is None and not (p['ts'] >= value if where == 'ts>=?' else p['ts'] < value):
                continue
            for t in ('advice','attempts'):
                plan[t].update(r[0] for r in db.execute(f'SELECT rowid FROM {t} WHERE request_id IN (?,?)', (p['query_request_id'],p['release_request_id'])))
            if p['release_call_id']:
                plan['children'].update(r[0] for r in db.execute('SELECT rowid FROM children WHERE platform=? AND session_id=? AND call_id=?', (p['platform'],p['session_id'],p['release_call_id'])))
        return plan

    def preview_since(self, cutoff):
        """What a reset from `cutoff` (epoch seconds; rows with ts >= cutoff) would delete, and what would remain. Writes nothing."""
        with closing(self.connect(readonly=True)) as db:
            delete = {t:len(ids) for t,ids in self._delete_plan(db,'ts>=?',cutoff).items()}
            total = {t: db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in self.TABLES}
            first, last = db.execute("SELECT MIN(ts), MAX(ts) FROM advice WHERE ts>=?", (cutoff,)).fetchone()
        return {"delete": delete, "keep": {t: total[t] - delete[t] for t in self.TABLES}, "first": first, "last": last}

    def _delete(self, where, value):
        with closing(self.connect()) as db:
            db.execute("BEGIN IMMEDIATE")                  # one transaction: never half-deleted
            plan = self._delete_plan(db,where,value)
            removed_packets = set()
            for p in _packet_rows(db):
                q = db.execute('SELECT rowid FROM advice WHERE request_id=?',(p['query_request_id'],)).fetchone()
                if ((q and q[0] in plan['advice']) or
                        (q is None and (p['ts'] >= value if where == 'ts>=?' else p['ts'] < value))):
                    removed_packets.add(p['packet_id'])
            deleted = {t:0 for t in self.TABLES}
            for t, ids in plan.items():
                ids = list(ids)
                for start in range(0,len(ids),500):
                    chunk = ids[start:start+500]
                    deleted[t] += db.execute(f"DELETE FROM {t} WHERE rowid IN ({','.join('?' for _ in chunk)})",chunk).rowcount
            # Relations are control metadata, not extra calls. Keep a surviving
            # query isolated, clear a deleted release, and remove dangling links.
            for p in _packet_rows(db):
                if p['packet_id'] in removed_packets:
                    if p['release_request_id']:
                        deleted['advice'] += db.execute('DELETE FROM advice WHERE request_id=?', (p['release_request_id'],)).rowcount
                        deleted['children'] += db.execute('DELETE FROM children WHERE platform=? AND session_id=? AND call_id=?',
                                                         (p['platform'], p['session_id'], p['release_call_id'])).rowcount
                    deleted['attempts'] += db.execute('DELETE FROM attempts WHERE request_id=?', (p['query_request_id'],)).rowcount
                    db.execute('DELETE FROM packet_links WHERE packet_id=?', (p['packet_id'],))
                elif p['release_request_id'] and not db.execute('SELECT 1 FROM advice WHERE request_id=?', (p['release_request_id'],)).fetchone():
                    db.execute('UPDATE packet_links SET release_request_id=NULL,release_call_id=NULL,release_ts=NULL,selected_model=NULL,selected_effort=NULL WHERE packet_id=?', (p['packet_id'],))
            # Import markers intentionally survive reset/retention: an explicit
            # repeated upgrade must not resurrect intentionally deleted history.
            db.commit()
        if sum(deleted.values()):                          # give the space back to the file system
            with closing(self.connect()) as db:
                db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                db.execute("VACUUM")
        return deleted

    def delete_since(self, cutoff):
        """Manual reset: remove every record at or after `cutoff`. Settings and keys are not stored here."""
        return self._delete("ts>=?", cutoff)

    def prune_before(self, cutoff):
        return self._delete("ts<?", cutoff)

    def maintain(self, retention_days, now):
        """Drop records older than the retention period, at most once per calendar day (0 = keep forever)."""
        if not retention_days:
            return 0
        today = int(now // 86400)
        with closing(self.connect()) as db:
            if db.execute("PRAGMA user_version").fetchone()[0] == today:
                return 0
            db.execute(f"PRAGMA user_version={today}")
        return sum(self.prune_before(now - retention_days * 86400).values())

    @classmethod
    def read_stats(cls, path, since):
        reader = cls.__new__(cls)
        reader.path = str(path)
        return reader.stats(since)

    @classmethod
    def read_rows(cls, path):
        """Every advice row and child row, read-only, as plain dicts (for the threshold suggestion)."""
        reader = cls.__new__(cls)
        reader.path = str(path)
        with reader.connect(readonly=True) as db:
            db.execute("BEGIN")
            return [dict(r) for r in db.execute("SELECT * FROM advice")], [dict(r) for r in db.execute("SELECT * FROM children")]

    def call(self, rid):
        with self.connect() as db:
            row = db.execute("SELECT * FROM advice WHERE request_id=? AND NOT EXISTS "
                             "(SELECT 1 FROM packet_links p WHERE p.query_request_id=advice.request_id OR p.release_request_id=advice.request_id)", (rid,)).fetchone()
        return dict(row) if row else None

    def recent_advice(self, platform, session_id, thash, now):
        with self.connect() as db:
            row = db.execute("SELECT * FROM advice WHERE platform=? AND session_id=? AND task_hash=? AND ts>=? "
                             "AND action IN ('advise','continue_main') AND NOT EXISTS "
                             "(SELECT 1 FROM packet_links p WHERE p.query_request_id=advice.request_id OR p.release_request_id=advice.request_id) ORDER BY ts DESC LIMIT 1",
                             (platform, session_id, thash, now - DEDUPE_SECONDS)).fetchone()
        return dict(row) if row else None

    def preserve_explicit(self, rid, req, thash, provider, now):
        """Claim a unique same-task advice and save the replacement atomically."""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT * FROM advice WHERE request_id=?", (rid,)).fetchone()
            if existing:
                return {**dict(existing), "_replayed": True}
            rows = db.execute("SELECT * FROM advice WHERE platform=? AND session_id=? AND NOT EXISTS "
                              "(SELECT 1 FROM packet_links p WHERE p.query_request_id=advice.request_id OR p.release_request_id=advice.request_id)",
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
                        "preserve", reason, None, None, provider, _encode(req, data)))
            return {**dict(db.execute("SELECT * FROM advice WHERE request_id=?", (rid,)).fetchone()), "_replayed": False}

    def save(self, rid, req, thash, advice, provider, now):
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO advice VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (rid, now, req.platform, req.session_id, req.turn_id, req.call_id, thash, advice.action,
                        advice.reason, advice.tier, advice.confidence, provider, _encode(req, list(advice.candidates), advice.extra)))

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
            rows = db.execute("SELECT * FROM advice WHERE platform=? AND session_id=? AND NOT EXISTS "
                              "(SELECT 1 FROM packet_links p WHERE p.query_request_id=advice.request_id OR p.release_request_id=advice.request_id)",
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
            packets = _packet_rows(db)
        children = [c for c in every_child if c["ts"] >= since]
        packet_ids = {rid for p in packets for rid in (p['query_request_id'], p['release_request_id']) if rid}
        ordinary = [r for r in rows if r['request_id'] not in packet_ids]
        packet_links = _packet_relations(rows, packets)
        links = _links(ordinary)
        inferred = _inferred(ordinary, every_child, links)
        links.update(inferred)
        by_call = {}
        for row in rows:
            by_call.setdefault((row["platform"], row["session_id"], row["call_id"]), []).append(row)
        recent = [r for r in rows if r["ts"] >= since]
        packet_releases = {p['release_request_id'] for p in packets if p['release_request_id']}
        packet_queries = {p['query_request_id'] for p in packets}
        counted = [r for r in recent if r["request_id"] not in links and r['request_id'] not in packet_releases]
        by_action, per_platform, reasons, tiers, roles, role_reasons = {}, {}, {}, {}, {}, {}
        role_recorded, explicit_without_role = 0, 0
        def inc(mapping, key):
            mapping[key] = mapping.get(key, 0) + 1
        for row in counted:
            inc(by_action, row["action"]); inc(per_platform.setdefault(row["platform"], {}), row["action"])
            if row["action"] == "preserve": inc(reasons, row["reason"])
            if row["tier"] is not None: inc(tiers, row["tier"])
            meta = payload(row)
            if "role" in meta:                      # older rows never recorded the role; they stay unknown
                role_recorded += 1
                if meta["role"]:
                    inc(roles, meta["role"]); inc(role_reasons.setdefault(meta["role"], {}), row["reason"])
                elif row["reason"] in ("explicit_model", "explicit_effort"):
                    explicit_without_role += 1
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
        manual = len({rid for (rid, _) in grouped if str(rid).startswith("manual-")})   # `mrh classify`: costs, but no delegation
        durations, versions = [], {}
        for events in grouped.values():
            started = [e["ts"] for e in events if e["outcome"] == "started"]
            answered = sorted((e for e in events if e["outcome"] in ("returned", "late_returned")), key=lambda e: e["ts"])
            if started and answered:
                durations.append(max(0.0, answered[0]["ts"] - min(started)))
            if answered and answered[0]["response_model"]:
                versions[answered[0]["response_model"]] = versions.get(answered[0]["response_model"], 0) + 1
        latency = {"avg": sum(durations) / len(durations) if durations else None, "max": max(durations) if durations else None,
                   "n": len(durations)}
        followed_models, requested_models, observed_models, followed, unverified, prior = {}, {}, {}, 0, 0, 0
        packet_started, packet_followed, child_models, inherited = 0, 0, {}, 0
        for child in children:
            if child["resolved_model"]:
                inc(observed_models, child["resolved_model"])
            if child["resolved_model"] or child["requested_model"]:
                inc(child_models.setdefault(child["platform"], {}), child["resolved_model"] or child["requested_model"])
            else:
                inherited += 1
            pre = by_call.get((child["platform"], child["session_id"], child["call_id"]), [])
            link = links.get(pre[0]["request_id"]) if len(pre) == 1 else None
            packet_link = packet_links.get(pre[0]['request_id']) if len(pre) == 1 else None
            if packet_link:
                q, selected, p = packet_link
                exact = (child['agent_id'] and child['ts'] >= pre[0]['ts']
                         and child['requested_model'] == selected['model'] and child['requested_effort'] == selected['effort'])
                packet_started += int(bool(exact))
                if exact and q['action'] == 'advise' and _matches(q, child['requested_model'], child['requested_effort']):
                    link = (q, selected)
                    packet_followed += 1
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
        packet_reissues = {rid for rid,(query,selected,_) in packet_links.items()
                           if query['action']=='advise' and _matches(query,selected['model'],selected['effort'])}
        return {"since": since, "reissues": sum(r["request_id"] in links or r['request_id'] in packet_reissues for r in recent),
                "inferred_links": sum(r["request_id"] in inferred for r in recent),
                "unverified_reissues": sum(r["reason"] == "advice_reissue" for r in counted),
                "unverified_followed_children": unverified,
                "children_following_prior_advice": prior,
                "decisions": by_action, "per_platform": per_platform, "kept_unchanged": reasons,
                "tiers": tiers, "classifier_usage": usage,
                "classifier_latency": latency, "classifier_versions": versions, "manual_classifications": manual,
                "classifier_calls": sum(u["calls"] for u in usage.values()),
                "classifier_requests": sum(u["requests"] for u in usage.values()),
                "classifier_failed_requests": sum(u["failed"] for u in usage.values()),
                "classifier_input_tokens": sum(u["input_tokens"] for u in usage.values()),
                "classifier_output_tokens": sum(u["output_tokens"] for u in usage.values()),
                "children_started": len(children), "children_following_advice": followed,
                "followed_models": followed_models, "followed_requested_models": requested_models,
                "observed_models": observed_models,
                "confidence": {"last_24h": _average(rows, time.time() - 86400), "total": _average(rows, 0)},
                "roles": roles, "role_reasons": role_reasons, "role_recorded": role_recorded, "explicit_without_role": explicit_without_role,
                "children_models": child_models, "children_inherited": inherited,
                "packet_classifications": sum(r['request_id'] in packet_queries and r['tier'] is not None for r in recent),
                "packet_releases": sum(r['request_id'] in packet_links for r in recent),
                "packet_children_started": packet_started, "packet_children_following_advice": packet_followed}


class PacketStore(AdviceStore):
    """A narrow view of the same authoritative DB; the decision engine is unchanged.

    Packet IDs are integration correlations. Native request IDs and exact scope
    come from the adapter; neither ordinary advice nor another packet is reused.
    """
    def __init__(self, path, packet_id, phase='query'):
        super().__init__(path)
        self.packet_id, self.phase = packet_id, phase

    def link(self, db):
        p = db.execute('SELECT * FROM packet_links WHERE packet_id=?', (self.packet_id,)).fetchone()
        if p is None:
            raise ValueError('packet_query_unbound')
        return dict(p)

    def bind(self, req, body_sha256, body_length, workspace, revision, now):
        values = (self.packet_id, request_id(req.platform, req.session_id, req.turn_id, req.call_id),
                  req.platform, req.session_id, req.turn_id, task_hash(req.platform, req.session_id, req.task),
                  body_sha256, body_length, workspace, revision, req.call_id)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT * FROM packet_links WHERE packet_id=?', (self.packet_id,)).fetchone()
            fields = ('packet_id','query_request_id','platform','session_id','turn_id','task_hash','body_sha256','body_length','workspace','revision','query_call_id')
            if old:
                if tuple(old[k] for k in fields) != values:
                    raise ValueError('packet_binding_conflict')
                return dict(old)
            if (db.execute('SELECT 1 FROM advice WHERE request_id=?',(values[1],)).fetchone()
                    or db.execute('SELECT 1 FROM attempts WHERE request_id=?',(values[1],)).fetchone()):
                raise ValueError('packet_query_request_conflict')
            db.execute('INSERT INTO packet_links(packet_id,query_request_id,platform,session_id,turn_id,task_hash,body_sha256,body_length,workspace,revision,query_call_id,ts,origin) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)', values + (now,'native'))
            return self.link(db)

    def query_row(self):
        with self.connect() as db:
            p = self.link(db)
            row = db.execute('SELECT * FROM advice WHERE request_id=?', (p['query_request_id'],)).fetchone()
            if row and any(row[k] != p[k] for k in ('platform','session_id','turn_id','task_hash')):
                raise ValueError('packet_binding_conflict')
            return dict(row) if row else None

    def call(self, rid):
        with self.connect() as db:
            p = self.link(db)
            wanted = p['query_request_id'] if self.phase == 'query' else p['release_request_id']
            if rid != wanted:
                return None
            row = db.execute('SELECT * FROM advice WHERE request_id=?', (rid,)).fetchone()
            return dict(row) if row else None

    def recent_advice(self, *args):
        return None

    def save(self, rid, req, thash, advice, provider, now):
        # A concurrent explicit reset may remove an in-flight binding. Do not
        # resurrect its detached query or attempts after the network returns.
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            p = self.link(db)
            if self.phase != 'query' or rid != p['query_request_id'] or thash != p['task_hash']:
                raise ValueError('packet_query_conflict')
            db.execute('INSERT OR IGNORE INTO advice VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                       (rid,now,req.platform,req.session_id,req.turn_id,req.call_id,thash,advice.action,advice.reason,advice.tier,advice.confidence,provider,_encode(req, list(advice.candidates), advice.extra)))

    def attempt(self, rid, kind, outcome, now, **meta):
        values = {k:v for k,v in meta.items() if k in _META}
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if rid != self.link(db)['query_request_id']:
                raise ValueError('packet_query_conflict')
            db.execute('INSERT INTO attempts VALUES(?,?,?,?,?,?,?,?,?)',
                       (rid,now,kind,outcome,values.get('requested_model'),values.get('response_model'),values.get('input_tokens'),values.get('output_tokens'),values.get('error_reason')))

    def preserve_explicit(self, rid, req, thash, provider, now):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            p = self.link(db)
            if self.phase != 'release' or any(getattr(req,k) != p[k] for k in ('platform','session_id','turn_id')) or thash != p['task_hash']:
                raise ValueError('packet_binding_conflict')
            if not db.execute('SELECT 1 FROM advice WHERE request_id=?', (p['query_request_id'],)).fetchone():
                raise ValueError('packet_classification_record_missing')
            if p['release_request_id']:
                raise ValueError('packet_release_already_claimed')
            if db.execute('SELECT 1 FROM advice WHERE request_id=?', (rid,)).fetchone():
                raise ValueError('packet_release_conflict')
            p.update(selected_model=req.explicit_model, selected_effort=req.explicit_effort)
            meta = {k:p[k] for k in ('packet_id','query_request_id','body_sha256','body_length','workspace','revision','selected_model','selected_effort')}
            db.execute('INSERT INTO advice VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                       (rid,now,req.platform,req.session_id,req.turn_id,req.call_id,thash,'preserve','packet_release',None,None,provider,json.dumps({'candidates':[],'packet':meta})))
            db.execute('UPDATE packet_links SET release_request_id=?,release_call_id=?,release_ts=?,selected_model=?,selected_effort=?,origin=? WHERE packet_id=?',
                       (rid,req.call_id,now,req.explicit_model,req.explicit_effort,'legacy_query_native_release' if p['origin']=='legacy_import' else p['origin'],self.packet_id))
            return {**dict(db.execute('SELECT * FROM advice WHERE request_id=?',(rid,)).fetchone()),'_replayed':False}

    def record_packet_child(self, child, now):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            p = self.link(db)
            if (any(getattr(child,k) != p[k] for k in ('platform','session_id'))
                    or child.call_id != p['release_call_id'] or not child.agent_id
                    or child.requested_model != p['selected_model'] or child.requested_effort != p['selected_effort']):
                raise ValueError('packet_child_conflict')
            rows = db.execute('SELECT * FROM advice WHERE request_id IN (?,?)', (p['query_request_id'],p['release_request_id'])).fetchall()
            relation = _packet_relations(rows,[p]).get(p['release_request_id'])
            if not relation or now < relation[0]['ts'] or now < p['release_ts']:
                raise ValueError('packet_child_scope_invalid')
            followed = relation[0]['action']=='advise' and _matches(relation[0],child.requested_model,child.requested_effort)
            db.execute('INSERT OR IGNORE INTO children VALUES(?,?,?,?,?,?,?,?,?,?)',
                       (child.call_id,child.platform,child.session_id,now,child.requested_model,child.requested_effort,child.resolved_model,child.agent_id,p['query_request_id'],int(followed)))
            saved = db.execute('SELECT * FROM children WHERE platform=? AND session_id=? AND call_id=?', (child.platform,child.session_id,child.call_id)).fetchone()
            if (saved['agent_id'] != child.agent_id or saved['requested_model'] != child.requested_model
                    or saved['requested_effort'] != child.requested_effort or saved['advice_request_id'] != p['query_request_id']):
                raise ValueError('packet_child_conflict')
            return bool(followed)
