"""Explicit hand-filled parser fixtures, NOT source/host emission evidence."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from mrh import isolated_host_export as export
from mrh.core import route, ScriptedClassifier, Classification
from mrh.facts import CallScope
from mrh.runtime import SupportedHostResolver
from mrh.service import process
from mrh.store import Store
from mrh.types import Proposal


SCOPE = CallScope("codex", "session", "turn", "call")


def fixture(role="unprotected"):
    known = lambda value: {"known": True, "value": value, "source": "explicit-parser-fixture"}
    return {"schema_version": 1, "producer_revision": export.BASE_REVISION, "surface": "native-v1",
            "scope": SCOPE.__dict__, "validity": {"kind": "frozen-invocation", "nonce": "fixture-nonce", "expires": "hook-completion"},
            "facts": {"role_protection": known(role), "deny_supported": known(True), "rewrite_supported": known(True),
                      "original_model": known("original"), "original_effort": known("high")},
            "targets": [], "target_availability": "unknown-account; no catalog promotion",
            "effort_semantics": "configured-request-not-provider-execution"}


def fixture_exchange(value):
    # Tests deliberately cross the private code-level fixture seam. These
    # bytes were NOT emitted by a verified Codex source/binary.
    return export.ExportExchange(export._Emission(json.dumps(value).encode(), SCOPE, "0"*64, export._SEAL))


class IsolatedExportTests(unittest.TestCase):
    def event(self):
        return {"session_id": SCOPE.session_id, "turn_id": SCOPE.turn_id, "tool_use_id": SCOPE.tool_call_id,
                "tool_input": {"message": "fixture", "pending_delegation": fixture()}, "pending_delegation": fixture()}

    def test_bare_json_source_revision_nonce_and_known_never_mint_exchange(self):
        with self.assertRaisesRegex(export.ExportError, "unverified_producer"):
            export.ExportExchange(fixture())
        event = self.event()
        facts = SupportedHostResolver().resolve(event)
        self.assertFalse(facts.role_protection.known)
        p = Proposal("codex", "unknown", "session", "turn", "call", event["tool_input"], False)
        self.assertEqual(route(p, {"top_mode": "Main"}, facts).reason, "missing_role_protection")

    def test_launcher_rejects_relative_executable_and_rebased_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); (root/"target").mkdir()
            (root/"OWNED.json").write_text(json.dumps({"owner": "MRH-001-E7"}))
            binary = root/"target/producer"; binary.write_bytes(b"explicit unexecuted fixture"); binary.chmod(0o700)
            digest = hashlib.sha256(binary.read_bytes()).hexdigest()
            with self.assertRaisesRegex(export.ExportError, "unverified_producer"):
                export.SourceTestProducer(root, "target/producer", digest)
            producer = export.SourceTestProducer(root, binary, digest)
            with patch("subprocess.run", side_effect=AssertionError("must not execute")):
                with self.assertRaisesRegex(export.ExportError, "unsafe_producer_environment"):
                    producer.capture(SCOPE, [], environment={"HOME": "relative"})
                with self.assertRaisesRegex(export.ExportError, "unsafe_producer_environment"):
                    producer.capture(SCOPE, [], environment={"TYPESAFE_API_KEY": "not-forwarded"})

    def test_fixture_main_and_protected_effort_and_task_forgery(self):
        p = Proposal("codex", "simulation", "session", "turn", "call", {"message": "fixture"}, True)
        for role, reason in (("unprotected", "top_main_requested"), ("effort", "fixed_role_effort"), ("model_effort", "fixed_role_model")):
            exchange = fixture_exchange(fixture(role))
            event = self.event(); event["pending_delegation"] = fixture("unprotected")
            classifier = ScriptedClassifier([Classification("Top", .9)])
            result = route(p, {"top_mode": "Main"}, exchange.resolve(event), classifier)
            self.assertEqual(result.reason, reason)
            self.assertEqual(classifier.calls, int(role == "unprotected"))

    def test_expired_foreign_wire_version_revision_and_malformed_fact(self):
        exchange = fixture_exchange(fixture()); exchange.close()
        with self.assertRaisesRegex(export.ExportError, "expired_host_export"): exchange.resolve(self.event())
        event = self.event(); event["turn_id"] = "foreign"
        with self.assertRaisesRegex(export.ExportError, "host_fact_scope_mismatch"): fixture_exchange(fixture()).resolve(event)
        cases = []
        missing = fixture(); missing.pop("schema_version"); cases.append((missing, "invalid_host_export"))
        for key, value, reason in (("schema_version", 2, "unsupported_host_export_version"),
                                  ("schema_version", True, "unsupported_host_export_version"),
                                  ("producer_revision", "foreign", "unsupported_producer")):
            wire = fixture(); wire[key] = value; cases.append((wire, reason))
        wire = fixture(); wire["scope"] = dict(SCOPE.__dict__, turn_id="foreign"); cases.append((wire, "host_fact_scope_mismatch"))
        wire = fixture(); wire["facts"]["deny_supported"]["value"] = "true"; cases.append((wire, "invalid_host_export"))
        wire = fixture(); wire["facts"]["role_protection"] = {"known": False, "value": "unprotected", "source": "fixture"}; cases.append((wire, "invalid_host_export"))
        for wire, reason in cases:
            with self.assertRaisesRegex(export.ExportError, reason): fixture_exchange(wire).resolve(self.event())

    def test_local_target_acceptance_does_not_promote_remote_availability(self):
        wire = fixture(); wire["targets"] = [{"model": "target", "host_accepted": {"known": True, "value": True, "source": "fixture"},
            "available": {"known": False, "source": "remote-account-unknown"},
            "efforts": {"known": True, "value": ["high"], "source": "fixture"},
            "inherited_effort": {"known": True, "value": "high", "source": "fixture"}}]
        facts = fixture_exchange(wire).resolve(self.event()); self.assertFalse(facts.targets[0].available.known)
        p = Proposal("codex", "simulation", "session", "turn", "call", {}, True)
        classifier = ScriptedClassifier([Classification("Top", .9)])
        result = route(p, {"top_mode": "Fixed", "fixed": {"model": "target", "effort": "high"}}, facts, classifier)
        self.assertEqual(result.reason, "missing_target_model"); self.assertEqual(classifier.calls, 0)
        forged = copy.deepcopy(wire); forged["targets"][0]["available"] = {"known": True, "value": True, "source": "fixture"}
        with self.assertRaisesRegex(export.ExportError, "invalid_host_export"): fixture_exchange(forged).resolve(self.event())

    def test_cached_effect_rechecks_current_source_fixture_without_new_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp)/"facts.sqlite3")
            p = Proposal("codex", "simulation", "session", "turn", "call", {}, True)
            classifier = ScriptedClassifier([Classification("Top", .9)])
            first = process(p, {"top_mode": "Main"}, fixture_exchange(fixture()).resolve(self.event()), store, classifier)
            self.assertEqual(first.action, "return_to_main"); stats = store.stats(True)
            second = process(p, {"top_mode": "Main"}, fixture_exchange(fixture("effort")).resolve(self.event()), store, classifier)
            self.assertEqual(second.reason, "fixed_role_effort"); self.assertEqual(classifier.calls, 1)
            self.assertEqual(store.stats(True), stats)


if __name__ == "__main__": unittest.main()
