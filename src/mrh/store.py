"""Minimal keyed facts, atomic claims and immutable receipts; no task text."""
import datetime
from contextlib import contextmanager
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import sqlite3
from .types import Decision, REASONS, TIERS, safe_id, safe_model_id


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class Store:
    def __init__(self, path):
        self.path = Path(path).absolute()
        if self.path.is_symlink():
            raise ValueError("unsafe_store_path")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
        lock = os.open(str(self.path) + ".lock", flags, 0o600)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX)
            key_path = Path(str(self.path) + ".key")
            try:
                fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
            except FileExistsError:
                if key_path.is_symlink():
                    raise ValueError("unsafe_key_path")
                self.key = key_path.read_bytes()
            else:
                if self.path.exists() and self.path.stat().st_size:
                    os.close(fd)
                    key_path.unlink()
                    raise ValueError("missing_runtime_key")
                self.key = os.urandom(32)
                with os.fdopen(fd, "wb") as stream:
                    stream.write(self.key)
                    stream.flush()
                    os.fsync(stream.fileno())
            if len(self.key) != 32:
                raise ValueError("invalid_runtime_key")
            if not self.path.exists():
                fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
                os.close(fd)
            with self.connect() as db:
                db.execute("PRAGMA journal_mode=WAL")
                db.executescript("""
                    CREATE TABLE IF NOT EXISTS proposals (
                      id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL,
                      synthetic INTEGER NOT NULL, platform TEXT NOT NULL,
                      surface TEXT NOT NULL, session_id TEXT NOT NULL,
                      turn_id TEXT NOT NULL, tool_call_id TEXT NOT NULL,
                      state TEXT NOT NULL, decision TEXT, occurred_at TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS attempts (
                      id TEXT PRIMARY KEY, proposal_id TEXT NOT NULL REFERENCES proposals(id),
                      kind TEXT NOT NULL, outcome TEXT NOT NULL, occurred_at TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS receipts (
                      id TEXT PRIMARY KEY, proposal_id TEXT NOT NULL REFERENCES proposals(id),
                      agent_id TEXT NOT NULL, evidence_kind TEXT NOT NULL, source_ref TEXT NOT NULL,
                      actual_model TEXT, verified INTEGER NOT NULL, body TEXT NOT NULL,
                      occurred_at TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS operator_stops (
                      proposal_id TEXT PRIMARY KEY REFERENCES proposals(id),
                      decision TEXT NOT NULL, occurred_at TEXT NOT NULL);
                """)
                columns = {r["name"] for r in db.execute("PRAGMA table_info(proposals)")}
                if "updated_at" not in columns:
                    db.execute("ALTER TABLE proposals ADD COLUMN updated_at TEXT")
                attempt_columns = {r["name"] for r in db.execute("PRAGMA table_info(attempts)")}
                for name, kind in [("phase", "TEXT NOT NULL DEFAULT 'legacy'"), ("requested_model", "TEXT"),
                                   ("response_model", "TEXT"), ("input_tokens", "INTEGER"), ("output_tokens", "INTEGER"),
                                   ("error_reason", "TEXT"), ("late_outcome", "TEXT"), ("updated_at", "TEXT")]:
                    if name not in attempt_columns:
                        db.execute(f"ALTER TABLE attempts ADD COLUMN {name} {kind}")
                receipt_columns = {r["name"] for r in db.execute("PRAGMA table_info(receipts)")}
                if "anomaly" not in receipt_columns:
                    db.execute("ALTER TABLE receipts ADD COLUMN anomaly INTEGER NOT NULL DEFAULT 0")
                db.execute("PRAGMA user_version=3")
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
            os.close(lock)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def fingerprint(self, proposal):
        body = json.dumps({"input": proposal.tool_input, "synthetic": proposal.synthetic,
                           "tool_name": proposal.tool_name}, sort_keys=True, separators=(",", ":"), allow_nan=False)
        return hmac.new(self.key, body.encode(), hashlib.sha256).hexdigest()

    def claim(self, proposal):
        identity, digest = proposal.identity, self.fingerprint(proposal)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT fingerprint,state,decision FROM proposals WHERE id=?", (identity,)).fetchone()
            if row:
                if not hmac.compare_digest(row["fingerprint"], digest):
                    return "conflict", None
                stopped = db.execute('SELECT decision FROM operator_stops WHERE proposal_id=?', (identity,)).fetchone()
                if stopped:
                    return 'cached', Decision.from_dict(json.loads(stopped['decision']))
                if row["state"] == "pending":
                    return "pending", None
                return "cached", Decision.from_dict(json.loads(row["decision"]))
            timestamp = now()
            db.execute("INSERT INTO proposals VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                       (identity, digest, int(proposal.synthetic), proposal.platform, proposal.surface,
                        proposal.session_id, proposal.turn_id, proposal.tool_call_id, "pending", None, timestamp, timestamp))
            return "new", None

    def attempt(self, proposal_id, attempt_id, kind, outcome, **metadata):
        if kind not in ("synthetic", "jev") or outcome not in ("requested", "started", "returned", "error", "unknown", "late_returned", "late_error") or not safe_id(attempt_id):
            raise ValueError("invalid_attempt")
        allowed = {"requested_model", "response_model", "input_tokens", "output_tokens", "error_reason"}
        if set(metadata) - allowed:
            raise ValueError("invalid_attempt_metadata")
        for field in ("requested_model", "response_model"):
            if metadata.get(field) is not None and not safe_id(metadata[field]):
                raise ValueError("invalid_attempt_metadata")
        for field in ("input_tokens", "output_tokens"):
            value = metadata.get(field)
            if value is not None and (type(value) is not int or not 0 <= value <= 2**63-1):
                raise ValueError("invalid_attempt_metadata")
        if metadata.get("error_reason") is not None and (not isinstance(metadata["error_reason"], str) or metadata["error_reason"] not in REASONS):
            raise ValueError("invalid_attempt_metadata")
        identity = proposal_id + ":attempt:" + attempt_id
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            parent = db.execute("SELECT synthetic FROM proposals WHERE id=?", (proposal_id,)).fetchone()
            if not parent or bool(parent["synthetic"]) != (kind == "synthetic"):
                raise ValueError("evidence_partition_mismatch")
            old = db.execute("SELECT * FROM attempts WHERE id=?", (identity,)).fetchone()
            if old and old["kind"] != kind:
                raise ValueError("conflicting_attempt")
            if not old:
                if outcome != "requested":
                    raise ValueError("attempt_not_requested")
                timestamp = now()
                db.execute("INSERT INTO attempts(id,proposal_id,kind,outcome,occurred_at,phase,requested_model,updated_at) VALUES (?,?,?,?,?,?,?,?)",
                           (identity, proposal_id, kind, outcome, timestamp, outcome, metadata.get("requested_model"), timestamp))
                return
            phase = old["phase"]
            late = outcome.startswith("late_")
            if late:
                if phase != "unknown":
                    raise ValueError("invalid_late_transition")
                destination = "late_outcome"
                terminal = outcome[5:]
                if old["late_outcome"] is not None and old["late_outcome"] != terminal:
                    raise ValueError("conflicting_attempt")
            else:
                destination, terminal = "phase", outcome
                valid = phase == outcome or (phase == "requested" and outcome == "started") or (phase == "started" and outcome in ("returned", "error", "unknown"))
                if not valid:
                    raise ValueError("conflicting_attempt")
            for field, value in metadata.items():
                if old[field] is not None and old[field] != value:
                    raise ValueError("conflicting_attempt_metadata")
            updates = {destination: terminal, **metadata}
            if not late:
                updates["outcome"] = outcome
            if all(old[k] == v for k, v in updates.items()):
                return
            updates["updated_at"] = now()
            assignment = ",".join(k + "=?" for k in updates)
            db.execute(f"UPDATE attempts SET {assignment} WHERE id=?", (*updates.values(), identity))

    def complete(self, proposal_id, decision):
        if not isinstance(decision, Decision):
            raise ValueError("invalid_decision")
        decision.validate()
        body = json.dumps(decision.as_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT state,decision,synthetic FROM proposals WHERE id=?", (proposal_id,)).fetchone()
            if not row or bool(row["synthetic"]) != decision.synthetic:
                raise ValueError("invalid_completion")
            if row["state"] == "complete" and row["decision"] != body:
                raise ValueError("conflicting_completion")
            if row["state"] == "pending":
                db.execute("UPDATE proposals SET state='complete',decision=?,updated_at=? WHERE id=?", (body, now(), proposal_id))
            if decision.action == 'operator_update_required':
                self._record_stop(db, proposal_id, decision, body)

    def _record_stop(self, db, proposal_id, decision, body):
        parent = db.execute('SELECT state,synthetic,decision FROM proposals WHERE id=?', (proposal_id,)).fetchone()
        if not parent or parent['state'] != 'complete' or bool(parent['synthetic']) != decision.synthetic:
            raise ValueError('invalid_completion')
        original = Decision.from_dict(json.loads(parent['decision']))
        if original.action == 'operator_update_required':
            if original != decision:
                raise ValueError('conflicting_completion')
        elif (original.action != 'request_child' or original.tier != decision.tier or
              original.confidence != decision.confidence or original.patch['model'] != decision.target_model):
            raise ValueError('invalid_completion')
        old = db.execute('SELECT decision FROM operator_stops WHERE proposal_id=?', (proposal_id,)).fetchone()
        if old and old['decision'] != body:
            raise ValueError('conflicting_completion')
        if not old:
            db.execute('INSERT INTO operator_stops VALUES (?,?,?)', (proposal_id, body, now()))

    def record_stop(self, proposal_id, decision):
        """Latch a later stop without overwriting the historical classification."""
        if not isinstance(decision, Decision) or decision.action != 'operator_update_required':
            raise ValueError('invalid_decision')
        decision.validate()
        body = json.dumps(decision.as_dict(), sort_keys=True, separators=(',', ':'), allow_nan=False)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self._record_stop(db, proposal_id, decision, body)

    def record_observation(self, receipt, verifier=None):
        """Only an injected trusted host/provider adapter can verify observations.

        No CLI importer supplies such a verifier. A source label alone has no
        authority. Simulated proposals cannot be promoted to observed facts.
        """
        allowed = {"event_id", "proposal_id", "platform", "surface", "session_id", "turn_id",
                   "tool_call_id", "agent_id", "evidence_kind", "source_ref", "actual_model", "model_evidence"}
        required = allowed - {"actual_model", "model_evidence"}
        if not isinstance(receipt, dict) or set(receipt) - allowed or not required.issubset(receipt):
            raise ValueError("invalid_receipt")
        if not all(safe_id(receipt[k]) for k in required):
            raise ValueError("invalid_receipt")
        kind = receipt["evidence_kind"]
        if kind not in ("synthetic", "reported", "host_observed", "provider_observed"):
            raise ValueError("unsupported_evidence")
        actual = receipt.get("actual_model")
        model_evidence = receipt.get("model_evidence")
        if model_evidence not in (None, "unavailable", "configured", "reported", "provider_observed"):
            raise ValueError("invalid_model_evidence")
        if actual is None and model_evidence == "provider_observed":
            raise ValueError("invalid_model_evidence")
        verified = kind in ("host_observed", "provider_observed")
        if verified and (verifier is None or verifier(dict(receipt)) is not True):
            raise ValueError("unverified_source")
        if actual is not None and (not safe_model_id(actual) or kind != "provider_observed" or receipt.get("model_evidence") != "provider_observed"):
            raise ValueError("unverified_actual_model")
        body = json.dumps(receipt, sort_keys=True, separators=(",", ":"), allow_nan=False)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            parent = db.execute("SELECT * FROM proposals WHERE id=?", (receipt["proposal_id"],)).fetchone()
            if not parent:
                raise ValueError("uncorrelated_receipt")
            if parent["state"] != "complete":
                raise ValueError("proposal_pending")
            if any(receipt[k] != parent[k] for k in ("platform", "surface", "session_id", "turn_id", "tool_call_id")):
                raise ValueError("uncorrelated_receipt")
            if bool(parent["synthetic"]) != (kind == "synthetic"):
                raise ValueError("evidence_partition_mismatch")
            stopped = db.execute('SELECT 1 FROM operator_stops WHERE proposal_id=?', (receipt['proposal_id'],)).fetchone()
            action = json.loads(parent['decision'])['action']
            anomaly = 2 if stopped or action == 'operator_update_required' else int(action == 'return_to_main')
            old = db.execute("SELECT body FROM receipts WHERE id=?", (receipt["event_id"],)).fetchone()
            if old and old["body"] != body:
                raise ValueError("conflicting_receipt")
            # One child fact per correlated agent, even across alternate receipt IDs.
            duplicate = db.execute("SELECT body FROM receipts WHERE proposal_id=? AND agent_id=?",
                                   (receipt["proposal_id"], receipt["agent_id"])).fetchone()
            if duplicate and not old:
                raise ValueError("duplicate_agent_receipt")
            if not old:
                db.execute("INSERT INTO receipts VALUES (?,?,?,?,?,?,?,?,?,?)",
                           (receipt["event_id"], receipt["proposal_id"], receipt["agent_id"], kind,
                            receipt["source_ref"], actual, int(verified), body, now(), anomaly))

    def stats(self, synthetic=False):
        with self.connect() as db:
            db.execute("BEGIN")
            rows = db.execute("SELECT * FROM proposals WHERE synthetic=?", (int(synthetic),)).fetchall()
            attempts = db.execute("SELECT a.* FROM attempts a JOIN proposals p ON p.id=a.proposal_id WHERE p.synthetic=?", (int(synthetic),)).fetchall()
            receipts = db.execute("SELECT r.* FROM receipts r JOIN proposals p ON p.id=r.proposal_id WHERE p.synthetic=?", (int(synthetic),)).fetchall()
            stops = db.execute('SELECT s.* FROM operator_stops s JOIN proposals p ON p.id=s.proposal_id WHERE p.synthetic=?', (int(synthetic),)).fetchall()
        stop_by_id = {s['proposal_id']: s for s in stops}
        timestamps = [r["updated_at"] or r["occurred_at"] for r in rows+attempts] + [r["occurred_at"] for r in receipts+stops]
        started = [r for r in attempts if r["phase"] != "requested"]
        out = {"schema_version": 2, "updated_at": max(timestamps, default=None),
               "partition": "synthetic" if synthetic else "live", "proposals": len(rows),
               "jev_attempts": sum(r["kind"] == "jev" for r in started),
               "synthetic_attempts": sum(r["kind"] == "synthetic" for r in started),
               "classified_tasks": 0, "low_confidence_tasks": 0, "pending_proposals": 0,
               "operator_stops": 0, "stopped_targets": {},
               "tiers": dict.fromkeys(TIERS, 0), "outcomes": {}, "requested_models": {},
               "confirmed_children": 0, "simulated_children": 0, "reported_children": 0,
               "actual_models": {}, "unknown_actual_model_children": 0,
               "cost": None, "tokens": None, "quota": None,
               "capabilities": {"jev": "unavailable", "codex": "candidate_unverified", "claude": "unsupported", "gemini": "unsupported"}}
        sources = {}
        for row in rows:
            source = (row["platform"], row["surface"])
            sources[source] = sources.get(source, 0) + 1
        out["platforms"] = [{"platform": p, "surface": s, "proposals": n} for (p, s), n in sorted(sources.items())]
        # Public IDs identify facts; never export the keyed content fingerprint.
        out["event_ids"] = {"proposals": sorted(r["id"] for r in rows)[:100],
                            "attempts": sorted(r["id"] for r in attempts)[:100],
                            "receipts": sorted(r["id"] for r in receipts)[:100]}
        out["event_ids_truncated"] = any(len(r) > 100 for r in (rows, attempts, receipts))
        provider = [r for r in started if r["requested_model"] is not None]
        telemetry = {"source": ("explicit_synthetic_offline_transport" if synthetic else "actual_provider_transport") if provider else "unavailable",
                     "attempt_states": {}, "requested_models": {}, "response_models": {},
                     "input_tokens": None, "output_tokens": None, "known_input_tokens": 0,
                     "known_output_tokens": 0, "usage_unavailable_attempts": 0, "estimated_cost": None}
        for r in provider:
            phase = r["phase"]
            telemetry["attempt_states"][phase] = telemetry["attempt_states"].get(phase, 0) + 1
            if r["late_outcome"]:
                label = "late_" + r["late_outcome"]
                telemetry["attempt_states"][label] = telemetry["attempt_states"].get(label, 0) + 1
            for source, target in (("requested_model", "requested_models"), ("response_model", "response_models")):
                if r[source] is not None:
                    telemetry[target][r[source]] = telemetry[target].get(r[source], 0) + 1
            if r["input_tokens"] is None or r["output_tokens"] is None:
                telemetry["usage_unavailable_attempts"] += 1
            else:
                telemetry["known_input_tokens"] += r["input_tokens"]
                telemetry["known_output_tokens"] += r["output_tokens"]
        if provider and not telemetry["usage_unavailable_attempts"]:
            telemetry["input_tokens"] = telemetry["known_input_tokens"]
            telemetry["output_tokens"] = telemetry["known_output_tokens"]
            if all(r["response_model"] == "jev-1.13.0" for r in provider):
                telemetry["estimated_cost"] = {"amount": telemetry["input_tokens"] * 0.042 / 1_000_000,
                        "currency": "USD", "kind": "estimate", "model": "jev-1.13.0", "unit": "per-million-input-tokens",
                        "price_source": "https://docs.typesafe.ai/models", "price_date": "2026-10-10"}
        out["jev"] = telemetry
        for value, name in ((1, 'handback'), (2, 'operator_stop')):
            out[name+'_anomalies'] = sum(r['anomaly'] == value for r in receipts)
            out[name+'_anomaly_evidence'] = {
                'confirmed': sum(r['anomaly'] == value for r in receipts if r['verified']),
                'reported': sum(r['anomaly'] == value for r in receipts if r['evidence_kind'] == 'reported'),
                'synthetic': sum(r['anomaly'] == value for r in receipts if r['evidence_kind'] == 'synthetic')}
        for row in rows:
            if row["state"] == "pending":
                out["pending_proposals"] += 1
                continue
            effective = stop_by_id.get(row['id'], row)
            d = Decision.from_dict(json.loads(effective['decision'])).as_dict()
            reason = d["reason"]
            out["outcomes"][reason] = out["outcomes"].get(reason, 0) + 1
            if d["tier"] is not None:
                out["classified_tasks"] += 1
                out["tiers"][d["tier"]] += 1
            out["low_confidence_tasks"] += reason == "low_confidence"
            if d['action'] == 'operator_update_required':
                out['operator_stops'] += 1
                model = d['target_model']
                out['stopped_targets'][model] = out['stopped_targets'].get(model, 0) + 1
            if d["action"] == "request_child":
                model = d["patch"]["model"]
                out["requested_models"][model] = out["requested_models"].get(model, 0) + 1
        for row in receipts:
            if row["verified"]:
                out["confirmed_children"] += 1
                model = row["actual_model"]
                if model is None:
                    out["unknown_actual_model_children"] += 1
                else:
                    out["actual_models"][model] = out["actual_models"].get(model, 0) + 1
            else:
                key = "simulated_children" if row["evidence_kind"] == "synthetic" else "reported_children"
                out[key] += 1
        return out
