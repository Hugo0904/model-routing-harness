import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from mrh.attempts import GuardedAttempts
from mrh.codex import handle_event
from mrh.core import ClassifierFailure
from mrh.service import process
from mrh.simulation import demo_capabilities, demo_policy
from mrh.store import Store
from mrh.types import ContextSummary, Proposal
from mrh.typesafe import HttpResponse, HttpTransport, TypesafeClassifier, classifier_from_config
from mrh.typesafe_protocol import PINNED_MODEL


def answer(confidence=0.8, model=PINNED_MODEL, usage=True):
    result = {"model": model, "answers": {"tier": {"type": "choice", "choice": "top",
              "probabilities": {"light": 0.05, "small": 0.1, "mid": 0.15, "top": 0.7},
              "confidence": confidence}}, "discard_me": "BODY_PRIVATE_CANARY"}
    if usage:
        result["usage"] = {"input_tokens": 100, "output_tokens": 10}
    return result


class FakeTransport:
    synthetic = True

    def __init__(self, response=None, error=None):
        self.response = response or HttpResponse(200, json.dumps(answer()).encode())
        self.error = error
        self.calls = []

    def request(self, body, headers, deadline, enter):
        enter()
        self.calls.append((copy.deepcopy(body), dict(headers), deadline))
        if self.error:
            raise self.error
        return self.response


class TypesafeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / "facts.sqlite3")
        self.resolutions = 0

    def resolve(self):
        self.resolutions += 1
        return "FAKE_KEY_PRIVATE_CANARY"

    def proposal(self, call="c", **changes):
        values = {"platform": "codex", "surface": "simulation", "session_id": "s", "turn_id": "t",
                  "tool_call_id": call, "tool_input": {"message": "TASK_PRIVATE_CANARY"}, "synthetic": True}
        values.update(changes)
        return Proposal(**values)

    def classify(self, transport=None, call="c", context=None, **gates):
        transport = transport or FakeTransport()
        classifier = TypesafeClassifier(enabled=gates.get("enabled", True),
                      task_export_permitted=gates.get("task_export_permitted", True),
                      credential_resolver=gates.get("resolver", self.resolve), transport=transport)
        result = process(self.proposal(call), demo_policy(), demo_capabilities(), self.store, classifier, context)
        return result, transport

    def test_default_disable_export_key_and_early_host_gates_have_zero_attempts(self):
        for i, (gates, reason) in enumerate([
            ({"enabled": False}, "typesafe_disabled"),
            ({"task_export_permitted": False}, "typesafe_export_denied"),
            ({"resolver": lambda: None}, "typesafe_missing_credentials"),
            ({"resolver": lambda: "invalid\nheader"}, "typesafe_missing_credentials")]):
            result, transport = self.classify(call=str(i), **gates)
            self.assertEqual(result.reason, reason)
            self.assertEqual(transport.calls, [])
        self.assertEqual(self.resolutions, 0)
        # Never evaluate or read the real environment key, even in this test.
        with patch("mrh.typesafe.environment_credential", side_effect=AssertionError("resolver touched")):
            default = classifier_from_config()
            self.assertFalse(default.enabled)
        for proposal, reason in [
            (self.proposal("explicit", tool_input={"model": "explicit", "message": "task"}), "explicit_model"),
            (self.proposal("other", tool_name="exec_command"), "unrelated_event")]:
            fake = FakeTransport()
            classifier = TypesafeClassifier(enabled=True, task_export_permitted=True,
                          credential_resolver=self.resolve, transport=fake)
            self.assertEqual(process(proposal, demo_policy(), demo_capabilities(), self.store, classifier).reason, reason)
            self.assertEqual(fake.calls, [])
        self.assertEqual(self.resolutions, 0)
        self.assertEqual(self.store.stats(True)["synthetic_attempts"], 0)
        self.assertEqual(self.store.stats()["jev_attempts"], 0)
        with self.assertRaises(ClassifierFailure):
            classifier_from_config({"endpoint": "https://untrusted.invalid"})

    def test_wire_confidence_context_and_safe_telemetry_chain(self):
        for i, (confidence, action) in enumerate([(0.49, "preserve"), (0.5, "return_to_main")]):
            fake = FakeTransport(HttpResponse(200, json.dumps(answer(confidence)).encode()))
            result, _ = self.classify(fake, str(i), lambda: ContextSummary("SUMMARY_PRIVATE_CANARY", "test", True))
            self.assertEqual(result.action, action)
            self.assertEqual(result.confidence, confidence)  # max probability is 0.7
            body, headers, deadline = fake.calls[0]
            self.assertEqual(body["model"], PINNED_MODEL)
            self.assertEqual(set(body), {"model", "state", "questions"})
            self.assertEqual(body["state"], {"task": "TASK_PRIVATE_CANARY", "context_summary": "SUMMARY_PRIVATE_CANARY"})
            self.assertEqual(set(body["questions"]["tier"]["criteria"]), {"light", "small", "mid", "top"})
            self.assertEqual(headers, {"Authorization": "Bearer FAKE_KEY_PRIVATE_CANARY", "Content-Type": "application/json"})
            self.assertGreater(deadline, 0)
        _, fake = self.classify(call="denied-summary", context=lambda: ContextSummary("DENIED_CANARY", "test", False))
        self.assertEqual(set(fake.calls[0][0]["state"]), {"task"})
        stats = self.store.stats(True)
        self.assertEqual(stats["synthetic_attempts"], 3)
        self.assertEqual(stats["jev_attempts"], 0)
        self.assertEqual(stats["jev"]["response_models"], {PINNED_MODEL: 3})
        self.assertEqual(stats["jev"]["input_tokens"], 300)
        self.assertAlmostEqual(stats["jev"]["estimated_cost"]["amount"], 300 * 0.042 / 1_000_000)
        self.assertEqual(stats["actual_models"], {})
        with self.store.connect() as db:
            facts = "\n".join(str(tuple(row)) for table in ("proposals", "attempts", "receipts")
                              for row in db.execute("SELECT * FROM " + table))
        exported = facts + json.dumps(stats)
        for canary in ("KEY_PRIVATE_CANARY", "TASK_PRIVATE_CANARY", "SUMMARY_PRIVATE_CANARY", "BODY_PRIVATE_CANARY", "DENIED_CANARY"):
            self.assertNotIn(canary, exported)

    def test_exact_one_attempt_for_typed_http_and_network_failures_no_raw_diagnostics(self):
        scenarios = [(HttpResponse(code, b"ERROR_PRIVATE_CANARY"), None, "typesafe_http_" + str(code))
                     for code in (401, 422, 429, 529)]
        scenarios += [(HttpResponse(503, b"ERROR_PRIVATE_CANARY"), None, "typesafe_http_5xx"),
                      (HttpResponse(302, b"REDIRECT_PRIVATE_CANARY"), None, "typesafe_redirect_rejected"),
                      (HttpResponse(200, b"x" * 65537), None, "typesafe_oversized_response"),
                      (None, OSError("ERROR_PRIVATE_CANARY"), "typesafe_network_error"),
                      (None, TimeoutError("ERROR_PRIVATE_CANARY"), "typesafe_timeout")]
        diagnostics = io.StringIO()
        for i, (response, error, reason) in enumerate(scenarios):
            fake = FakeTransport(response, error)
            with contextlib.redirect_stderr(diagnostics):
                result, _ = self.classify(fake, str(i))
            self.assertEqual(result.reason, reason)
            self.assertEqual(len(fake.calls), 1)
            with self.store.connect() as db:
                rows = db.execute("SELECT * FROM attempts WHERE proposal_id=?", (self.proposal(str(i)).identity,)).fetchall()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["phase"], "unknown" if error and isinstance(error, TimeoutError) else "error")
        self.assertEqual(self.store.stats(True)["synthetic_attempts"], len(scenarios))
        self.assertEqual(self.store.stats()["jev_attempts"], 0)
        self.assertNotIn("CANARY", diagnostics.getvalue() + json.dumps(self.store.stats(True)))

    def test_mismatch_malformed_and_unknown_usage_preserve_safe_model_only(self):
        malformed = answer(); malformed["answers"]["tier"]["choice"] = "other"
        unknown_usage = answer(); unknown_usage["usage"]["input_tokens"] = True
        for i, (data, reason) in enumerate([
            (answer(model="jev-other"), "typesafe_model_mismatch"),
            (malformed, "typesafe_malformed_response"),
            (unknown_usage, "top_main_requested"),
            (answer(usage=False), "top_main_requested")]):
            result, _ = self.classify(FakeTransport(HttpResponse(200, json.dumps(data).encode())), str(i))
            self.assertEqual(result.reason, reason)
        stats = self.store.stats(True)["jev"]
        self.assertEqual(stats["response_models"], {"jev-other": 1, PINNED_MODEL: 3})
        self.assertIsNone(stats["input_tokens"])
        self.assertEqual(stats["usage_unavailable_attempts"], 2)
        self.assertIsNone(stats["estimated_cost"])
        duplicate = b'{"model":"jev-1.13.0","model":"jev-other"}'
        result, _ = self.classify(FakeTransport(HttpResponse(200, duplicate)), "duplicate")
        self.assertEqual(result.reason, "typesafe_malformed_response")

    def test_fixed_https_transport_certificate_deadline_size_and_cleanup(self):
        connection = unittest.mock.MagicMock()
        response = connection.getresponse.return_value
        response.status = 302
        response.read1.side_effect = [b"redirect", b""]
        context = object()
        with patch("mrh.typesafe.ssl.create_default_context", return_value=context) as cert, \
             patch("mrh.typesafe.http.client.HTTPSConnection", return_value=connection) as create:
            result = HttpTransport().request({"model": PINNED_MODEL}, {"Authorization": "Bearer fake"}, time.monotonic() + 1,
                                            lambda: (lambda: None))
        self.assertEqual(result.status, 302)
        cert.assert_called_once_with()
        args, kwargs = create.call_args
        self.assertEqual(args, ("api.typesafe.ai",))
        self.assertEqual(kwargs["port"], 443); self.assertIs(kwargs["context"], context)
        self.assertLessEqual(kwargs["timeout"], 1)
        self.assertEqual(connection.request.call_args.args[:2], ("POST", "/v1/systemone"))
        self.assertEqual(response.read1.call_args_list, [unittest.mock.call(65537), unittest.mock.call(65529)])
        connection.close.assert_called_once()
        with patch("mrh.typesafe.http.client.HTTPSConnection") as create:
            with self.assertRaises(TimeoutError):
                HttpTransport().request({}, {}, time.monotonic() - 1, lambda: (lambda: None))
            create.assert_not_called()

    def test_candidate_uses_injected_transport_and_preserves_main_and_input(self):
        fake = FakeTransport()
        classifier = TypesafeClassifier(enabled=True, task_export_permitted=True, credential_resolver=self.resolve, transport=fake)
        event = {"hook_event_name": "PreToolUse", "tool_name": "spawn_agent", "session_id": "s", "turn_id": "t",
                 "tool_use_id": "candidate", "tool_input": {"message": "task", "unknown": {"keep": True}}}
        policy = demo_policy(); policy["top_mode"] = "Fixed"
        caps = demo_capabilities()
        original = copy.deepcopy((event, caps, policy))
        result = handle_event(event, self.store, True, classifier=classifier, policy=policy, capabilities=caps)
        self.assertEqual(result["hookSpecificOutput"]["updatedInput"]["model"], "gpt-6-astra")
        self.assertEqual((event, caps, policy), original)
        self.assertEqual(len(fake.calls), 1)
        repeat = handle_event(event, self.store, True, classifier=classifier, policy=policy, capabilities=caps)
        self.assertEqual(repeat, result); self.assertEqual(len(fake.calls), 1)

    def test_provider_model_echo_cannot_export_credential_task_or_summary(self):
        for i, value in enumerate(("FAKE_KEY_PRIVATE_CANARY", "TASK_PRIVATE_CANARY", "SUMMARY_PRIVATE_CANARY")):
            fake = FakeTransport(HttpResponse(200, json.dumps(answer(model="echo." + value)).encode()))
            result, _ = self.classify(fake, "echo-" + str(i), lambda: ContextSummary("SUMMARY_PRIVATE_CANARY", "test", True))
            self.assertEqual(result.reason, "typesafe_model_mismatch")
        with self.store.connect() as db:
            persisted = "\n".join(str(tuple(row)) for table in ("attempts", "proposals") for row in db.execute("SELECT * FROM " + table))
        exported = persisted + json.dumps(self.store.stats(True))
        self.assertNotIn("PRIVATE_CANARY", exported)
        self.assertEqual(self.store.stats(True)["jev"]["response_models"], {})

    def test_unknown_or_claimed_live_injected_transport_is_rejected(self):
        for marker in (None, False):
            class Unverified:
                def request(self, *_):
                    raise AssertionError("must not be called")
            fake = Unverified()
            if marker is not None:
                fake.synthetic = marker
            with self.assertRaises(ClassifierFailure) as error:
                TypesafeClassifier(enabled=True, task_export_permitted=True, credential_resolver=self.resolve, transport=fake)
            self.assertEqual(error.exception.reason, "typesafe_unverified_transport")
        self.assertEqual(self.resolutions, 0)
        self.assertEqual(self.store.stats()["jev_attempts"], 0)

    def forced_timeout(self, classifier, entered, call):
        finished = threading.Event()
        workers = []
        def bounded(fn, _timeout):
            def work():
                try:
                    fn()
                except Exception:
                    pass
                finally:
                    finished.set()
            worker = threading.Thread(target=work)
            workers.append(worker); worker.start()
            self.assertTrue(entered.wait(2), "worker did not reach barrier")
            raise TimeoutError()
        with patch("mrh.core.bounded_call", side_effect=bounded):
            result = process(self.proposal(call), demo_policy(), demo_capabilities(), self.store, classifier)
        self.assertEqual(result.reason, "classifier_timeout")
        return result, finished, workers

    def test_late_callback_cannot_admit_request_after_routing_timeout(self):
        entered, release = threading.Event(), threading.Event()
        fake = FakeTransport()
        client = TypesafeClassifier(enabled=True, task_export_permitted=True, credential_resolver=self.resolve, transport=fake)
        class Delayed:
            synthetic = True
            def classify(self, task, context, recorder):
                entered.set(); release.wait(2)
                return client.classify(task, context, recorder)
        _, finished, workers = self.forced_timeout(Delayed(), entered, "late-before")
        release.set(); self.assertTrue(finished.wait(2))
        for worker in workers: worker.join(2)
        self.assertEqual(fake.calls, []); self.assertEqual(self.resolutions, 0)
        self.assertEqual(self.store.stats(True)["synthetic_attempts"], 0)

    def test_cancellation_in_gap_before_transport_entry_does_not_start_attempt(self):
        entered, release = threading.Event(), threading.Event()
        class DelayedEntry(FakeTransport):
            def request(self, body, headers, deadline, enter):
                entered.set(); release.wait(2)
                return super().request(body, headers, deadline, enter)
        fake = DelayedEntry()
        client = TypesafeClassifier(enabled=True, task_export_permitted=True, credential_resolver=self.resolve, transport=fake)
        _, finished, workers = self.forced_timeout(client, entered, "entry-gap")
        release.set(); self.assertTrue(finished.wait(2))
        for worker in workers: worker.join(2)
        self.assertEqual(fake.calls, [])
        self.assertEqual(self.store.stats(True)["synthetic_attempts"], 0)
        with self.store.connect() as db:
            row = db.execute("SELECT phase FROM attempts").fetchone()
        self.assertEqual(row["phase"], "requested")

    def test_inflight_timeout_late_response_keeps_unknown_and_frozen_decision(self):
        entered, release = threading.Event(), threading.Event()
        class Inflight(FakeTransport):
            def request(self, body, headers, deadline, enter):
                enter()
                entered.set(); release.wait(2)
                self.calls.append((body, headers, deadline))
                return self.response
        fake = Inflight()
        client = TypesafeClassifier(enabled=True, task_export_permitted=True, credential_resolver=self.resolve, transport=fake)
        result, finished, workers = self.forced_timeout(client, entered, "inflight")
        self.assertEqual(self.store.stats(True)["jev"]["attempt_states"], {"unknown": 1})
        release.set(); self.assertTrue(finished.wait(2))
        for worker in workers: worker.join(2)
        stats = self.store.stats(True)
        self.assertEqual(stats["jev"]["attempt_states"], {"unknown": 1, "late_returned": 1})
        self.assertEqual(stats["synthetic_attempts"], 1)
        self.assertEqual(stats["classified_tasks"], 0)
        self.assertEqual(process(self.proposal("inflight"), demo_policy(), demo_capabilities(), self.store, client), result)
        self.assertEqual(len(fake.calls), 1)


if __name__ == "__main__":
    unittest.main()
