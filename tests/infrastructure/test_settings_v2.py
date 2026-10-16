import json
import tempfile
import unittest
from pathlib import Path

from mrh.infrastructure import owned, settings, settings_v2 as v2
from mrh.infrastructure.settings_schema import SettingsError, default_settings


def v1_fixture():
    value = default_settings()
    value["revision"] = 5
    value["provider"], value["classifier_model"] = "typesafe", "jev-1.13.0"
    value["policy"] = {"top_mode": "Fixed", "timeout_seconds": 20.0, "fixed": {"model": "gpt-6.1-sol", "effort": "high"},
                       "tiers": {"Light": {"model": "gpt-5.6-luna", "effort": "low"}, "Top": {"model": "ignored"}},
                       "rates": {}}
    return value


class SettingsV2Tests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name).resolve() / "owned" / "settings.json"

    def write_v1(self, value):
        settings.init(self.path)
        owned.replace_owned(self.path, (json.dumps(value) + "\n").encode())

    def test_v1_migrates_in_memory_without_losing_choices(self):
        self.write_v1(v1_fixture())
        before = self.path.read_bytes()
        got = v2.read(self.path)
        self.assertEqual(self.path.read_bytes(), before)  # reading never rewrites
        self.assertEqual((got["schema_version"], got["revision"]), (2, 5))
        self.assertEqual(got["classifier"], {"provider": "jev", "model": "jev-1.13.0", "timeout_seconds": 20.0})
        self.assertEqual(got["policy"]["tiers"], {"Light": {"codex": [{"model": "gpt-5.6-luna", "effort": "low"}]}})
        self.assertEqual(got["policy"]["fixed"], {"codex": [{"model": "gpt-6.1-sol", "effort": "high"}]})
        self.assertEqual(got["policy"]["top_mode"], "Fixed")

    def test_first_update_writes_v2_even_when_content_is_unchanged(self):
        self.write_v1(v1_fixture())
        saved = v2.update(self.path, expected_revision=5, enabled=False)
        self.assertEqual(saved["revision"], 6)
        self.assertEqual(json.loads(self.path.read_bytes())["schema_version"], 2)
        self.assertEqual(v2.update(self.path, enabled=False)["revision"], 6)  # now a true no-op

    def test_stale_revision_is_rejected_and_file_untouched(self):
        v2.init(self.path)
        v2.update(self.path, expected_revision=0, enabled=True)
        before = self.path.read_bytes()
        with self.assertRaises(SettingsError) as raised:
            v2.update(self.path, expected_revision=0, enabled=False)
        self.assertEqual(raised.exception.reason, "settings_conflict")
        self.assertEqual(self.path.read_bytes(), before)

    def test_invalid_documents_are_rejected(self):
        good = v2.default_settings()
        bad = [
            {**good, "classifier": {**good["classifier"], "model": "jev-fast"}},                  # not an alias or an exact version
            {**good, "classifier": {**good["classifier"], "model": "jev-1.13"}},
            {**good, "classifier": {**good["classifier"], "model": "gpt-6-luna"}},
            {**good, "classifier": {**good["classifier"], "provider": "openai_api"}},             # unknown provider
            {**good, "classifier": {**good["classifier"], "timeout_seconds": 31}},
            {**good, "policy": {"threshold": 0.49}}, {**good, "policy": {"threshold": 1.0}},
            {**good, "policy": {"top_mode": "Fixed"}},                                            # Fixed needs a list
            {**good, "policy": {"tiers": {"Top": {}}}},                                           # Top uses `fixed`
            {**good, "policy": {"tiers": {"Light": {"cursor": []}}}},                             # unknown platform
            {**good, "policy": {"tiers": {"Light": {"codex": [{"model": "m"}] * 6}}}},            # too many
            {**good, "policy": {"tiers": {"Light": {"codex": [{"model": "sk-secret"}]}}}},        # secret-looking id
        ]
        for value in bad:
            with self.subTest(value=value["policy"], classifier=value["classifier"]):
                with self.assertRaises(SettingsError):
                    v2.validate(value)

    def test_settings_path_resolution_order(self):
        home = self.path.parent.parent
        pointer = home / ".config" / "model-routing-harness" / "active-settings"
        pointer.parent.mkdir(parents=True); pointer.write_text("/pointer/settings.json\n")
        self.assertEqual(v2.resolve_settings_path(None, {}, home), Path("/pointer/settings.json"))
        self.assertEqual(v2.resolve_settings_path(None, {"MRH_SETTINGS": "/env/settings.json"}, home), Path("/env/settings.json"))
        self.assertEqual(v2.resolve_settings_path("/flag/settings.json", {"MRH_SETTINGS": "/env/settings.json"}, home), Path("/flag/settings.json"))
        with self.assertRaises(SettingsError):
            v2.resolve_settings_path("relative/settings.json", {}, home)


if __name__ == "__main__":
    unittest.main()
