import copy
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest

from mrh.cli import main
from mrh.core import Classification, ScriptedClassifier, route
from mrh.service import process
from mrh.simulation import demo_capabilities, demo_policy
from mrh.store import Store
from mrh.types import Decision, Proposal
from mrh.typesafe_protocol import PINNED_MODEL


class FactsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "events.sqlite3"
        self.store = Store(self.path)

    def proposal(self, call="c", synthetic=True):
        return Proposal("codex", "simulation" if synthetic else "cli", "s", "t", call,
                        {"message": "fixture"}, synthetic)

    def test_resolved_baseline_cost_negative_positive_unknown_and_fixed(self):
        caps, policy = demo_capabilities(), demo_policy()
        caps["main_model"] = "gpt-6-astra"
        caps["original_model"] = "gpt-6-luna"
        policy["tiers"]["Mid"] = {"model": "gpt-6.1-sol", "effort": "high"}
        policy["rates"] = {model: {"currency": "USD", "unit": "per-million", "service": "synthetic",
                                  "source_ref": "fixture-v1", "components": {"input": rate, "output": rate * 2}}
                           for model, rate in [("gpt-6-astra", 10), ("gpt-6.1-sol", 5), ("gpt-6-luna", 1)]}
        before = copy.deepcopy(caps)
        def decide():
            return route(self.proposal(), policy, caps, ScriptedClassifier([Classification("Mid", 0.9)]))
        self.assertEqual(decide().reason, "cost_unknown")  # Main expensive cannot justify upgrading original cheap child.
        self.assertEqual(caps, before)
        caps["original_model"] = "gpt-6-astra"
        self.assertEqual(decide().action, "request_child")
        caps["original_resolution_known"] = False
        self.assertEqual(decide().reason, "cost_unknown")
        caps["original_resolution_known"] = True
        del caps["original_effort"]
        self.assertEqual(decide().reason, "cost_unknown")
        policy["top_mode"] = "Fixed"
        self.assertEqual(route(self.proposal(), policy, caps, ScriptedClassifier([Classification("Top", 0.9)])).action, "request_child")

    def test_lifecycle_concurrent_replays_count_once_conflicts_rejected(self):
        proposal = self.proposal()
        self.store.claim(proposal)
        def update():
            other = Store(self.path)
            other.attempt(proposal.identity, "0", "synthetic", "requested", requested_model=PINNED_MODEL)
        workers = [threading.Thread(target=update) for _ in range(4)]
        for worker in workers: worker.start()
        for worker in workers: worker.join(2); self.assertFalse(worker.is_alive())
        self.assertEqual(self.store.stats(True)["synthetic_attempts"], 0)
        self.store.attempt(proposal.identity, "0", "synthetic", "started")
        for _ in range(2):
            self.store.attempt(proposal.identity, "0", "synthetic", "returned", response_model=PINNED_MODEL,
                               input_tokens=12, output_tokens=1)
        snapshot = self.store.stats(True)
        self.assertEqual(snapshot["synthetic_attempts"], 1)
        self.assertEqual(snapshot["jev"]["source"], "explicit_synthetic_offline_transport")
        for phase, metadata in [("error", {}), ("returned", {"input_tokens": 13}), ("late_error", {})]:
            with self.assertRaises(ValueError):
                self.store.attempt(proposal.identity, "0", "synthetic", phase, **metadata)
        with self.assertRaisesRegex(ValueError, "evidence_partition_mismatch"):
            self.store.attempt(proposal.identity, "1", "jev", "requested")
        self.assertEqual(self.store.stats(True), snapshot)
        self.assertEqual(self.store.stats()["jev_attempts"], 0)

    def test_v1_migration_preserves_prior_events_and_does_not_invent_usage(self):
        path = Path(self.temp.name) / "v1.sqlite3"
        Path(str(path) + ".key").write_bytes(b"x" * 32)
        proposal = self.proposal("old")
        decision = Decision(reason="classifier_error", synthetic=True)
        timestamp = "2026-10-09T00:00:00+00:00"
        with sqlite3.connect(path) as db:
            db.executescript("""
              CREATE TABLE proposals (id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, synthetic INTEGER NOT NULL,
                platform TEXT NOT NULL,surface TEXT NOT NULL,session_id TEXT NOT NULL,turn_id TEXT NOT NULL,
                tool_call_id TEXT NOT NULL,state TEXT NOT NULL,decision TEXT,occurred_at TEXT NOT NULL,updated_at TEXT);
              CREATE TABLE attempts (id TEXT PRIMARY KEY,proposal_id TEXT NOT NULL,kind TEXT NOT NULL,
                outcome TEXT NOT NULL,occurred_at TEXT NOT NULL);
              CREATE TABLE receipts (id TEXT PRIMARY KEY,proposal_id TEXT NOT NULL,agent_id TEXT NOT NULL,
                evidence_kind TEXT NOT NULL,source_ref TEXT NOT NULL,actual_model TEXT,verified INTEGER NOT NULL,
                body TEXT NOT NULL,occurred_at TEXT NOT NULL);
              PRAGMA user_version=1;
            """)
            db.execute("INSERT INTO proposals VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (proposal.identity, "a" * 64, 1,
                       "codex", "simulation", "s", "t", "old", "complete", json.dumps(decision.as_dict()), timestamp, timestamp))
            db.execute("INSERT INTO attempts VALUES (?,?,?,?,?)", (proposal.identity + ":attempt:0", proposal.identity,
                       "synthetic", "error", timestamp))
            db.execute("INSERT INTO receipts VALUES (?,?,?,?,?,?,?,?,?)", ("old-receipt", proposal.identity, "a",
                       "synthetic", "old-fixture", None, 0, "{}", timestamp))
            before = {table: [tuple(row) for row in db.execute("SELECT * FROM " + table)]
                      for table in ("proposals", "attempts", "receipts")}
        migrated = Store(path)
        with migrated.connect() as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 2)
            for table, original in before.items():
                current = [tuple(row)[:len(original[0])] for row in db.execute("SELECT * FROM " + table)]
                self.assertEqual(current, original)
            self.assertEqual(db.execute("SELECT phase FROM attempts").fetchone()[0], "legacy")
        stats = migrated.stats(True)
        self.assertEqual(stats["schema_version"], 2)
        self.assertEqual(stats["updated_at"], timestamp)
        self.assertEqual(stats["proposals"], 1); self.assertEqual(stats["synthetic_attempts"], 1)
        self.assertEqual(stats["simulated_children"], 1)
        self.assertIsNone(stats["jev"]["input_tokens"])
        self.assertIsNone(stats["jev"]["estimated_cost"])
        self.assertEqual(stats["jev"]["source"], "unavailable")
        self.assertEqual(Store(path).stats(True), stats)

    def receipt(self, proposal, agent, kind, **fields):
        result = {"event_id": "receipt-" + agent, "proposal_id": proposal.identity, "platform": proposal.platform,
                  "surface": proposal.surface, "session_id": proposal.session_id, "turn_id": proposal.turn_id,
                  "tool_call_id": proposal.tool_call_id, "agent_id": agent, "evidence_kind": kind, "source_ref": "test-only-verifier"}
        result.update(fields)
        return result

    def test_main_unexpected_trusted_child_is_anomaly_not_handback_success(self):
        proposal = self.proposal(synthetic=False)
        self.store.claim(proposal)
        self.store.complete(proposal.identity, Decision("return_to_main", "top_main_requested", "Top", 0.9))
        self.assertEqual(self.store.stats()["confirmed_children"], 0)
        reported = self.receipt(proposal, "reported", "reported")
        self.store.record_observation(reported)
        self.assertEqual(self.store.stats()["confirmed_children"], 0)
        verified = self.receipt(proposal, "verified", "provider_observed", actual_model="observed-test-model",
                                model_evidence="provider_observed")
        with self.assertRaisesRegex(ValueError, "unverified_source"):
            self.store.record_observation(verified)
        # Explicit isolated test verifier; there is no production host verifier.
        self.store.record_observation(verified, verifier=lambda receipt: receipt == verified)
        self.store.record_observation(verified, verifier=lambda receipt: receipt == verified)
        stats = self.store.stats()
        self.assertEqual(stats["confirmed_children"], 1)
        self.assertEqual(stats["actual_models"], {"observed-test-model": 1})
        self.assertEqual(stats["handback_anomalies"], 2)
        self.assertEqual(stats["handback_anomaly_evidence"], {"confirmed": 1, "reported": 1, "synthetic": 0})
        self.assertEqual(stats["outcomes"]["top_main_requested"], 1)  # Requested action, no success counter.
        self.assertEqual(stats["requested_models"], {})
        self.assertEqual(stats["jev_attempts"], 0)

    def test_cli_exports_same_v2_provider_stats_without_network(self):
        proposal = self.proposal()
        self.store.claim(proposal)
        self.store.attempt(proposal.identity, "0", "synthetic", "requested", requested_model=PINNED_MODEL)
        self.store.attempt(proposal.identity, "0", "synthetic", "started")
        self.store.attempt(proposal.identity, "0", "synthetic", "returned", response_model=PINNED_MODEL,
                           input_tokens=100, output_tokens=2)
        self.store.complete(proposal.identity, Decision(reason="classifier_error", synthetic=True))
        snapshot = self.store.stats(True)
        stdout, stderr = io.StringIO(), io.StringIO()
        self.assertEqual(main(["stats", "--db", str(self.path), "--synthetic", "--json"], stdout=stdout, stderr=stderr), 0)
        self.assertEqual(json.loads(stdout.getvalue()), snapshot)
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(self.store.stats(True), snapshot)


if __name__ == "__main__":
    unittest.main()
