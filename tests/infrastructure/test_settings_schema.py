import json
import unittest

from mrh.infrastructure.settings_schema import SettingsError, default_settings, parse_settings, validate_settings


class SettingsSchemaTests(unittest.TestCase):
    def assert_invalid(self, value):
        with self.assertRaises(SettingsError) as raised:
            validate_settings(value)
        self.assertEqual(raised.exception.reason, "settings_invalid")
        self.assertEqual(str(raised.exception), "settings_invalid")

    def test_defaults_are_fresh_and_validated_values_are_deep_copies(self):
        first = default_settings()
        second = default_settings()
        self.assertEqual(first, second)
        self.assertIsNot(first, second)
        self.assertIsNot(first["policy"], second["policy"])
        self.assertFalse(first["enabled"])
        self.assertFalse(first["task_export_permitted"])
        self.assertEqual(first["policy"], {
            "top_mode": "Main", "timeout_seconds": 20.0, "tiers": {}, "rates": {},
        })

        value = default_settings()
        value["allowed_workspaces"] = ["/workspace/project"]
        value["policy"] = {
            "top_mode": "Fixed",
            "timeout_seconds": 2,
            "tiers": {"Small": {"model": "gpt-6-luna", "effort": "high"}},
            "fixed": {"model": "gpt-6-astra"},
            "rates": {
                "gpt-6-luna": {
                    "currency": "USD",
                    "unit": "per-million",
                    "service": "synthetic",
                    "source_ref": "rates-v1",
                    "components": {"input": 1.25, "cached": 0},
                },
            },
        }
        copied = validate_settings(value)
        copied["allowed_workspaces"].append("/another/workspace")
        copied["policy"]["tiers"]["Small"]["model"] = "changed"
        copied["policy"]["rates"]["gpt-6-luna"]["components"]["input"] = 9
        self.assertEqual(value["allowed_workspaces"], ["/workspace/project"])
        self.assertEqual(value["policy"]["tiers"]["Small"]["model"], "gpt-6-luna")
        self.assertEqual(value["policy"]["rates"]["gpt-6-luna"]["components"]["input"], 1.25)

        parsed = parse_settings(json.dumps(value, allow_nan=False).encode("utf-8"))
        self.assertEqual(parsed, value)
        self.assertIsNot(parsed["policy"], value["policy"])

    def test_rejects_wrong_top_level_types_and_revision_values(self):
        for field, invalid in (
            ("schema_version", True),
            ("schema_version", 2),
            ("revision", True),
            ("revision", -1),
            ("enabled", 1),
            ("task_export_permitted", "false"),
        ):
            with self.subTest(field=field, invalid=invalid):
                value = default_settings()
                value[field] = invalid
                self.assert_invalid(value)

    def test_rejects_duplicate_keys_nonfinite_json_and_oversized_input(self):
        duplicate = b'{"schema_version":1,"schema_version":1}'
        with self.assertRaises(SettingsError) as raised:
            parse_settings(duplicate)
        self.assertEqual(raised.exception.reason, "settings_invalid")

        nonfinite = default_settings()
        nonfinite['policy']['timeout_seconds']=float('nan')
        serialized = json.dumps(nonfinite)
        with self.assertRaises(SettingsError) as raised:
            parse_settings(serialized.encode("utf-8"))
        self.assertEqual(raised.exception.reason, "settings_invalid")

        with self.assertRaises(SettingsError) as raised:
            parse_settings(b" " * 65_537)
        self.assertEqual(raised.exception.reason, "settings_oversized")
        self.assertEqual(str(raised.exception), "settings_oversized")

    def test_rejects_unknown_secret_and_capability_fields(self):
        for field in ("unexpected", "api_key", "credentials", "capabilities"):
            with self.subTest(field=field):
                value = default_settings()
                value[field] = "private"
                self.assert_invalid(value)

        value = default_settings()
        value["policy"]["capabilities"] = {"models": []}
        self.assert_invalid(value)

    def test_rejects_noncanonical_or_duplicate_workspace_paths(self):
        for paths in (
            ["relative/path"],
            ["/workspace/./project"],
            ["/workspace/../project"],
            ["/workspace/project/"],
            ["/workspace\x00/project"],
            ["/workspace\n/project"],
            ["/workspace/project", "/workspace/project"],
        ):
            with self.subTest(paths=paths):
                value = default_settings()
                value["allowed_workspaces"] = paths
                self.assert_invalid(value)

    def test_policy_contract_and_optional_fields(self):
        value = default_settings()
        value["policy"] = {}
        self.assertEqual(validate_settings(value)["policy"], {})

        for policy in (
            {"top_mode": "Unknown"},
            {"top_mode": "Fixed"},
            {"timeout_seconds": True},
            {"timeout_seconds": 0},
            {"timeout_seconds": 30.01},
            {"tiers": {"Other": {"model": "gpt-6-luna"}}},
            {"tiers": {"Small": {"model": "gpt-6-luna", "available": True}}},
            {"fixed": {"model": "gpt-6-astra", "configuration_known": True}},
            {"rates": {"gpt-6-luna": {"currency": "USD"}}},
            {"rates": {"gpt-6-luna": {
                "currency": "USD", "unit": "per-million", "service": "synthetic",
                "source_ref": "rates-v1", "components": {"input": -1},
            }}},
            {"rates": {"gpt-6-luna": {
                "currency": "USD", "unit": "per-million", "service": "synthetic",
                "source_ref": "rates-v1", "components": {"input": True},
            }}},
        ):
            with self.subTest(policy=policy):
                candidate = default_settings()
                candidate["policy"] = policy
                self.assert_invalid(candidate)


if __name__ == "__main__":
    unittest.main()
