import contextlib
import copy
import io
import json
import multiprocessing
from pathlib import Path
import tempfile
import time
import unittest
from mrh.core import Classification, ScriptedClassifier, UnavailableClassifier
from mrh.service import process
from mrh.simulation import demo_capabilities, demo_policy
from mrh.store import Store
from mrh.types import ContextSummary, Decision, Proposal


def writer(path, index, same, barrier, output):
    store = Store(path)
    proposal = Proposal("codex", "simulation", "s", "t", "same" if same else f"call-{index}",
                        {"message": "concurrency fixture"}, True)
    classifier = ScriptedClassifier([Classification("Top", 0.9)])
    barrier.wait(timeout=10)
    d = process(proposal, demo_policy(), demo_capabilities(), store, classifier)
    output.put((d.reason, classifier.calls))


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "events.sqlite3"
        self.store = Store(self.path)

    def proposal(self, call="c", synthetic=True, text="PROMPT_PRIVATE_CANARY"):
        return Proposal("codex", "simulation" if synthetic else "cli", "s", "goal-later-turn", call,
                        {"message": text, "extra": {"secret": "sk-proj-FICTIONAL_CANARY"}}, synthetic)

    def decide(self, proposal=None, entries=None, policy=None, context=None):
        classifier = ScriptedClassifier(entries or [Classification("Top", 0.9)])
        d = process(proposal or self.proposal(), policy or demo_policy(), demo_capabilities(), self.store, classifier, context)
        return d, classifier

    def receipt(self, proposal, **changes):
        v = {"event_id": "receipt-1", "proposal_id": proposal.identity, "platform": proposal.platform,
             "surface": proposal.surface, "session_id": proposal.session_id, "turn_id": proposal.turn_id,
             "tool_call_id": proposal.tool_call_id, "agent_id": "agent-1", "evidence_kind": "synthetic",
             "source_ref": "isolated-test"}
        v.update(changes)
        return v

    def test_replay_cached_and_conflict_pending_do_not_reclassify(self):
        d, c = self.decide()
        same, repeat = self.decide()
        self.assertEqual(d, same); self.assertEqual(repeat.calls, 0)
        conflict, conflicting = self.decide(self.proposal(text="changed"))
        self.assertEqual(conflict.reason, "proposal_conflict"); self.assertEqual(conflicting.calls, 0)
        pending = self.proposal("pending")
        self.assertEqual(self.store.claim(pending)[0], "new")
        d, c = self.decide(pending)
        self.assertEqual(d.reason, "proposal_pending"); self.assertEqual(c.calls, 0)
        stats = self.store.stats(True)
        self.assertEqual(stats["proposals"], 2); self.assertEqual(stats["classified_tasks"], 1)
        self.assertEqual(stats["pending_proposals"], 1)

    def test_retries_counts_later_delegations_and_query_is_pure(self):
        self.decide(entries=[RuntimeError("SECRET_ERROR_CANARY"), Classification("Small", 0.49)])
        self.decide(self.proposal("new-goal-delegation"))
        snapshot = self.store.stats(True)
        self.assertEqual(snapshot["proposals"], 2)
        self.assertEqual(snapshot["synthetic_attempts"], 3)
        self.assertEqual(snapshot["jev_attempts"], 0)
        self.assertEqual(snapshot["classified_tasks"], 2)
        self.assertEqual(snapshot["low_confidence_tasks"], 1)
        self.assertEqual(self.store.stats(True), snapshot)
        self.assertEqual(self.store.stats()["proposals"], 0)
        self.assertEqual(self.store.stats()["jev_attempts"], 0)

    def test_separate_process_claims_same_and_different_ids(self):
        context = multiprocessing.get_context("spawn")
        for same, expected in [(True, 1), (False, 4)]:
            path = str(Path(self.temp.name) / ("same.sqlite3" if same else "different.sqlite3"))
            barrier, output = context.Barrier(4), context.Queue()
            workers = [context.Process(target=writer, args=(path, i, same, barrier, output)) for i in range(4)]
            for p in workers: p.start()
            results = [output.get(timeout=15) for _ in workers]
            for p in workers:
                p.join(timeout=15); self.assertEqual(p.exitcode, 0)
            s = Store(path).stats(True)
            self.assertEqual(s["proposals"], expected)
            self.assertEqual(s["classified_tasks"], expected)
            self.assertEqual(s["synthetic_attempts"], expected)
            self.assertEqual(sum(calls for _, calls in results), expected)

    def test_canary_absent_from_facts_diagnostics_and_public_json(self):
        captured = io.StringIO()
        with contextlib.redirect_stderr(captured):
            self.decide(context=lambda: ContextSummary("CONTEXT_PRIVATE_CANARY", "test-source", True))
            self.decide(self.proposal("bad"), entries=[RuntimeError("ERROR_PRIVATE_CANARY")])
        with self.store.connect() as db:
            text = "\n".join(str(tuple(row)) for table in ("proposals", "attempts", "receipts") for row in db.execute("SELECT * FROM " + table))
        output = text + captured.getvalue() + json.dumps(self.store.stats(True))
        for needle in ("PROMPT_PRIVATE_CANARY", "CONTEXT_PRIVATE_CANARY", "ERROR_PRIVATE_CANARY", "sk-proj-FICTIONAL_CANARY"):
            self.assertNotIn(needle, output)
        self.assertNotIn(self.store.key.hex(), output)

    def test_receipts_correlate_and_do_not_promote_claimed_models(self):
        p = self.proposal()
        pol = demo_policy(); pol["top_mode"] = "Fixed"
        self.decide(p, policy=pol)
        receipt = self.receipt(p)
        self.store.record_observation(receipt)
        self.store.record_observation(receipt)
        s = self.store.stats(True)
        self.assertEqual(s["simulated_children"], 1); self.assertEqual(s["confirmed_children"], 0)
        self.assertEqual(s["requested_models"], {"gpt-6-astra": 1}); self.assertEqual(s["actual_models"], {})
        for changes in [{"turn_id": "wrong", "event_id": "wrong-correlation"},
                        {"actual_model": "gpt-6-astra", "model_evidence": "configured", "event_id": "wrong-model"},
                        {"evidence_kind": "provider_observed", "actual_model": "gpt-6-astra",
                         "model_evidence": "provider_observed", "event_id": "fake-observation"}]:
            with self.assertRaises(ValueError): self.store.record_observation(self.receipt(p, **changes))
        self.assertEqual(self.store.stats(True), s)
        self.assertEqual(self.store.stats()["confirmed_children"], 0)

    def test_top_main_never_fabricates_child_but_records_correlated_anomaly(self):
        p = self.proposal()
        self.decide(p)
        self.assertEqual(self.store.stats(True)["simulated_children"], 0)
        self.store.record_observation(self.receipt(p))
        self.assertEqual(self.store.stats(True)["simulated_children"], 1)
        self.assertEqual(self.store.stats(True)["handback_anomalies"], 1)
        self.assertEqual(self.store.stats(True)["confirmed_children"], 0)

    def test_pending_receipt_and_raw_optional_metadata_are_rejected(self):
        p = self.proposal("pending-receipt")
        self.store.claim(p)
        with self.assertRaisesRegex(ValueError, "proposal_pending"):
            self.store.record_observation(self.receipt(p))
        self.store.complete(p.identity, process(self.proposal("separate"), demo_policy(), demo_capabilities(),
                                               classifier=ScriptedClassifier([Classification("Top", 0.9)])))
        self.assertEqual(self.store.stats(True)["simulated_children"], 0)
        fixed = self.proposal("optional-canary")
        pol = demo_policy(); pol["top_mode"] = "Fixed"
        self.decide(fixed, policy=pol)
        with self.assertRaisesRegex(ValueError, "invalid_model_evidence"):
            self.store.record_observation(self.receipt(fixed, model_evidence={"raw": "OPTIONAL_CANARY"}))
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM receipts").fetchone()[0], 0)

    def test_cached_patch_cannot_contain_raw_text_and_missing_key_is_not_recreated(self):
        p = self.proposal("raw-patch")
        self.store.claim(p)
        with self.assertRaisesRegex(ValueError, "invalid_decision"):
            self.store.complete(p.identity, Decision(action="request_child", patch={"model": "gpt-6-astra", "message": "RAW_CANARY"}, synthetic=True))
        with self.store.connect() as db:
            self.assertIsNone(db.execute("SELECT decision FROM proposals WHERE id=?", (p.identity,)).fetchone()[0])
        key = Path(str(self.path) + ".key")
        key.unlink()
        with self.assertRaisesRegex(ValueError, "missing_runtime_key"):
            Store(self.path)
        self.assertFalse(key.exists())

    def test_live_unavailable_and_reported_receipt_unknown_model(self):
        p = self.proposal(synthetic=False)
        d = process(p, demo_policy(), demo_capabilities(), self.store, UnavailableClassifier())
        self.assertEqual(d.reason, "classifier_unavailable")
        r = self.receipt(p, evidence_kind="reported")
        self.store.record_observation(r)
        s = self.store.stats()
        self.assertEqual(s["jev_attempts"], 0); self.assertEqual(s["classified_tasks"], 0)
        self.assertEqual(s["confirmed_children"], 0); self.assertEqual(s["reported_children"], 1)
        self.assertEqual(s["actual_models"], {}); self.assertIsNone(s["cost"])
        with self.assertRaisesRegex(ValueError, "unverified_actual_model"):
            self.store.record_observation(self.receipt(p, event_id="fake-configured", evidence_kind="reported",
                                                     actual_model="gpt-6-astra", model_evidence="configured"))

    def test_store_failure_preserves_and_sanitizes_diagnostic(self):
        class Broken:
            def claim(self, *_): raise RuntimeError("ERROR_PRIVATE_CANARY")
        output = io.StringIO()
        with contextlib.redirect_stderr(output):
            d = process(self.proposal(), demo_policy(), demo_capabilities(), Broken(), ScriptedClassifier([]))
        self.assertEqual(d.reason, "store_error")
        self.assertIn("stage=claim", output.getvalue()); self.assertNotIn("CANARY", output.getvalue())


if __name__ == "__main__": unittest.main()
