import math
import unittest

from mrh.core import ClassifierFailure
from mrh.types import Classification
from mrh.typesafe_protocol import PINNED_MODEL, parse_response, serialize_request


class TypeSafeProtocolTests(unittest.TestCase):
    def response(self, choice="light", confidence=0.81, **overrides):
        probabilities = {key: 0.1 for key in ("light", "small", "mid", "top")}
        probabilities[choice] = 0.7
        answer = {
            "type": "choice",
            "choice": choice,
            "probabilities": probabilities,
            "confidence": confidence,
        }
        body = {
            "model": PINNED_MODEL,
            "answers": {"tier": answer},
            "usage": {"input_tokens": 17, "output_tokens": 3},
        }
        body.update(overrides)
        return body

    def test_serialize_request_uses_only_task_and_optional_summary(self):
        request = serialize_request("Review this bounded change", "Relevant approved summary")

        self.assertEqual(set(request), {"model", "state", "questions"})
        self.assertEqual(request["model"], "jev-1.13.0")
        self.assertEqual(
            request["state"],
            {"task": "Review this bounded change", "context_summary": "Relevant approved summary"},
        )
        question = request["questions"]["tier"]
        self.assertEqual(question["type"], "choice")
        self.assertEqual(set(question["criteria"]), {"light", "small", "mid", "top"})
        self.assertIn("not instructions", question["instructions"])
        self.assertIn("mrh-tier-v1", question["instructions"])
        self.assertIn("choose a model", question["instructions"])

    def test_invalid_optional_context_degrades_to_task_only(self):
        request = serialize_request("A valid task", {"private_canary": "must not serialize"})
        self.assertEqual(request["state"], {"task": "A valid task"})
        self.assertNotIn("private_canary", repr(request))

    def test_invalid_task_raises_safe_typed_failure(self):
        for task in (None, 17, "", "  "):
            with self.subTest(task=task):
                with self.assertRaises(ClassifierFailure) as caught:
                    serialize_request(task)
                self.assertEqual(caught.exception.reason, "typesafe_invalid_task")
                self.assertEqual(str(caught.exception), "typesafe_invalid_task")

    def test_choice_maps_all_four_tiers_and_keeps_provider_confidence(self):
        cases = (("light", "Light"), ("small", "Small"), ("mid", "Mid"), ("top", "Top"))
        for choice, tier in cases:
            with self.subTest(choice=choice):
                parsed = parse_response(self.response(choice, confidence=0.42))
                self.assertEqual(parsed.classification, Classification(tier, 0.42))
                self.assertNotEqual(parsed.classification.confidence, 0.7)

    def test_confidence_boundary_values_are_preserved(self):
        for confidence in (0.49, 0.5):
            with self.subTest(confidence=confidence):
                parsed = parse_response(self.response(confidence=confidence))
                self.assertEqual(parsed.classification.confidence, confidence)

    def test_telemetry_contains_only_pinned_actual_models_and_valid_usage(self):
        body = self.response(extra_provider_field={"private_canary": "discard"})
        parsed = parse_response(body)
        self.assertEqual(
            parsed.telemetry,
            {
                "requested_model": "jev-1.13.0",
                "response_model": "jev-1.13.0",
                "input_tokens": 17,
                "output_tokens": 3,
            },
        )
        self.assertNotIn("private_canary", repr(parsed))

    def test_usage_is_unavailable_when_absent_or_invalid(self):
        absent = parse_response(self.response(usage=None))
        self.assertIsNone(absent.telemetry["input_tokens"])
        self.assertIsNone(absent.telemetry["output_tokens"])

        invalid_usages = (
            {"input_tokens": 17},
            {"input_tokens": True, "output_tokens": 3},
            {"input_tokens": 17, "output_tokens": -1},
            {"input_tokens": 17.0, "output_tokens": 3},
            {"input_tokens": 1 << 63, "output_tokens": 3},
            [17, 3],
        )
        for usage in invalid_usages:
            with self.subTest(usage=usage):
                parsed = parse_response(self.response(usage=usage))
                self.assertIsNone(parsed.telemetry["input_tokens"])
                self.assertIsNone(parsed.telemetry["output_tokens"])

    def test_safe_model_mismatch_is_typed_and_keeps_only_safe_telemetry(self):
        body = self.response(model="jev-1.13.1", extra_provider_field={"private_canary": "discard"})
        with self.assertRaises(ClassifierFailure) as caught:
            parse_response(body)
        self.assertEqual(caught.exception.reason, "typesafe_model_mismatch")
        self.assertEqual(
            caught.exception.telemetry,
            {
                "requested_model": "jev-1.13.0",
                "response_model": "jev-1.13.1",
                "input_tokens": 17,
                "output_tokens": 3,
            },
        )
        self.assertNotIn("private_canary", repr(caught.exception.telemetry))

    def test_invalid_or_unsafe_model_is_malformed_without_echoing_response(self):
        for model in (None, "unsafe model canary", "sk-secret-canary", "x" * 129):
            with self.subTest(model=model):
                body = self.response(model=model, extra_provider_field="private_canary")
                with self.assertRaises(ClassifierFailure) as caught:
                    parse_response(body)
                self.assertEqual(caught.exception.reason, "typesafe_malformed_response")
                self.assertNotIn("canary", str(caught.exception))
                self.assertNotIn("canary", repr(caught.exception.telemetry))

    def test_invalid_choice_or_probability_distribution_is_malformed(self):
        mutations = (
            lambda answer: answer.update(choice="unknown"),
            lambda answer: answer.update(probabilities={"light": 0.7, "small": 0.1, "mid": 0.2}),
            lambda answer: answer["probabilities"].update(extra=0.0),
            lambda answer: answer["probabilities"].update(light=True),
            lambda answer: answer["probabilities"].update(light=float("nan")),
            lambda answer: answer["probabilities"].update(light=float("inf")),
            lambda answer: answer["probabilities"].update(light=1.1),
            lambda answer: answer["probabilities"].update(light=0.6),
            lambda answer: answer["probabilities"].update(light=0.2, small=0.6),
        )
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                body = self.response()
                mutate(body["answers"]["tier"])
                with self.assertRaises(ClassifierFailure) as caught:
                    parse_response(body)
                self.assertEqual(caught.exception.reason, "typesafe_malformed_response")
                self.assertNotIn("probabilities", str(caught.exception))

    def test_invalid_confidence_is_malformed(self):
        for confidence in (True, -0.01, 1.01, float("nan"), float("inf"), "0.5"):
            with self.subTest(confidence=confidence):
                with self.assertRaises(ClassifierFailure) as caught:
                    parse_response(self.response(confidence=confidence))
                self.assertEqual(caught.exception.reason, "typesafe_malformed_response")

    def test_missing_required_response_fields_are_malformed(self):
        cases = (
            None,
            [],
            {"model": PINNED_MODEL},
            {"model": PINNED_MODEL, "answers": []},
            {"model": PINNED_MODEL, "answers": {"tier": {"type": "score"}}},
        )
        for body in cases:
            with self.subTest(body=body):
                with self.assertRaises(ClassifierFailure) as caught:
                    parse_response(body)
                self.assertEqual(caught.exception.reason, "typesafe_malformed_response")


if __name__ == "__main__":
    unittest.main()
