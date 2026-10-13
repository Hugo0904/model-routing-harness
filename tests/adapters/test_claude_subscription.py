import json
import unittest

from mrh.adapters.providers import claude_subscription as cs
from mrh.adapters.providers.registry import build
from mrh.adapters.providers.typesafe import TypesafeClassifier
from mrh.infrastructure import settings_v2 as v2
from mrh.routing.core import ClassifierFailure


def outer(result, **extra):
    return json.dumps({"is_error": False, "result": result, "usage": {"input_tokens": 600, "output_tokens": 40}, **extra}).encode()


class ClaudeParsingTests(unittest.TestCase):
    def test_accepts_the_code_fenced_and_chatty_replies_seen_from_the_real_cli(self):
        for reply in ('```json\n{"tier":"Light","confidence":0.95}\n```',
                      '```json\n{\n  "tier": "Top",\n  "confidence": 0.95\n}\n```\n\n**Reasoning**: cross-system.'):
            with self.subTest(reply=reply[:20]):
                result, tokens = cs.parse_output(outer(reply))
                self.assertIn(result.tier, ("Light", "Top"))
                self.assertEqual(tokens, {"input_tokens": 600, "output_tokens": 40})

    def test_rejects_anything_that_is_not_exactly_tier_and_confidence(self):
        bad = ['{"tier":"Light"}', '{"tier":"Huge","confidence":0.9}', '{"tier":"Mid","confidence":1.5}',
               '{"tier":"Mid","confidence":true}', '{"tier":"Mid","confidence":0.9,"model":"x"}', "no json at all", ""]
        for reply in bad:
            with self.subTest(reply=reply):
                with self.assertRaises(ClassifierFailure) as raised:
                    cs.parse_output(outer(reply))
                self.assertEqual(raised.exception.reason, "claude_subscription_malformed_response")

    def test_cli_level_error_is_a_process_failure(self):
        with self.assertRaises(ClassifierFailure) as raised:
            cs.parse_output(json.dumps({"is_error": True, "result": "login required"}).encode())
        self.assertEqual(raised.exception.reason, "claude_subscription_process_failed")

    def test_child_cannot_run_tools_or_load_settings_and_does_not_recurse(self):
        argv = cs.argv_for("haiku")
        self.assertEqual(argv[argv.index("--tools") + 1], "")
        self.assertEqual(argv[argv.index("--setting-sources") + 1], "")
        for flag in ("--no-session-persistence", "--strict-mcp-config", "--disable-slash-commands"):
            self.assertIn(flag, argv)
        self.assertEqual(cs.environment()[cs.SENTINEL], "1")


class RegistryTests(unittest.TestCase):
    def test_each_provider_is_built_from_settings_with_the_export_gates_copied(self):
        settings = v2.default_settings()
        self.assertIsInstance(build(settings, credential_resolver=lambda: "k", transport=type("T", (), {"synthetic": True})()), TypesafeClassifier)
        for provider, model, cls in (("claude_subscription", "haiku", cs.ClaudeSubscriptionClassifier),):
            built = build({**settings, "enabled": True, "task_export_permitted": True,
                           "classifier": {"provider": provider, "model": model, "timeout_seconds": 25}})
            self.assertIsInstance(built, cls)
            self.assertTrue(built.enabled and built.task_export_permitted)
        self.assertFalse(build({**settings, "classifier": {"provider": "claude_subscription", "model": "haiku", "timeout_seconds": 25}}).enabled)


if __name__ == "__main__":
    unittest.main()
