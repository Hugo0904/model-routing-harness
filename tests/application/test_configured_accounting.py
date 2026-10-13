import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from mrh.presentation import cli; from mrh.infrastructure import settings
from mrh.infrastructure.store import Store
from tests.adapters.test_typesafe import FakeTransport


def saved_events(surface="shell", scenario="explicit"):
    path = Path(__file__).resolve().parents[2] / ("tests/fixtures/e5-" + surface + "-plugin.json")
    case = next(c for c in json.loads(path.read_text())["cases"] if c["scenario"] == scenario)
    return [copy.deepcopy(row["event"]) for row in case["injected_runtime_events"]]


class UnavailableHost:
    synthetic = True
    def __init__(self): self.calls = 0
    def resolve(self, event):
        self.calls += 1
        raise RuntimeError("HOST_PRIVATE_CANARY")


class AccountingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.path = self.root / "state/settings.json"
        settings.init(self.path)
        self.keys = 0

    def key(self):
        self.keys += 1
        raise AssertionError("credential resolver must not execute")

    def admit(self, event, path=None):
        path = path or self.path
        settings.update(path, provider='typesafe',classifier_model='jev-1.13.0',
                        enabled=True, task_export_permitted=True, allowed_workspaces=[event["cwd"]])

    def hook(self, event, path=None, resolver=None, transport=None, production=False, settings_warning=False):
        out, err = io.StringIO(), io.StringIO()
        deps = {"credential_resolver": self.key}
        if not production:
            deps.update(host_resolver=resolver or UnavailableHost(), transport=transport or FakeTransport())
        with contextlib.redirect_stderr(err):
            code = cli.main(["hook", "--settings", str(path or self.path)], stdin=io.StringIO(json.dumps(event)),
                            stdout=out, stderr=err, runtime_dependencies=deps)
        self.assertEqual(code, 0)
        expected = {"systemMessage": (
            "MRH: settings could not be loaded; original tool call preserved. "
            "Use mrh stats --details with this profile's --settings or --db. "
            "Recording and warning deduplication are unavailable; this fault may be absent from history."
        )} if settings_warning else {}
        self.assertEqual(json.loads(out.getvalue()), expected)
        self.assertNotIn("PRIVATE", out.getvalue())
        self.assertNotIn("PRIVATE", err.getvalue())

    def test_saved_native_explicit_pre_post_replay_and_conflict_have_one_fact_no_provider(self):
        for surface in ("shell", "bundled"):
            with self.subTest(surface=surface):
                path = self.root / ("state-" + surface) / "settings.json"; settings.init(path)
                pre, post = saved_events(surface)
                original = copy.deepcopy(pre)
                self.admit(pre, path)
                host, fake = UnavailableHost(), FakeTransport()
                with patch("mrh.adapters.providers.typesafe.TypesafeClassifier.classify", side_effect=AssertionError("classifier ran")):
                    for event in (pre, pre, post, post): self.hook(event, path, host, fake)
                    changed = copy.deepcopy(pre); changed["tool_input"]["message"] = "CONFLICT_TASK_PRIVATE_CANARY"
                    self.hook(changed, path, host, fake)
                stats = Store(path.parent / "events.sqlite3").stats(True)
                self.assertEqual(stats["proposals"], 1)
                self.assertEqual(stats["outcomes"], {"explicit_model": 1})
                self.assertEqual(stats["synthetic_attempts"], 0)
                self.assertEqual(stats["simulated_children"], 1)
                self.assertEqual(stats["actual_models"], {})
                self.assertEqual(stats["confirmed_children"], 0)
                self.assertEqual(host.calls, 0); self.assertEqual(fake.calls, []); self.assertEqual(self.keys, 0)
                self.assertEqual(pre, original)
                with Store(path.parent / "events.sqlite3").connect() as db:
                    facts = str([tuple(r) for table in ("proposals", "attempts", "receipts") for r in db.execute("SELECT * FROM " + table)])
                self.assertNotIn("CONFLICT_TASK_PRIVATE_CANARY", facts)

    def test_unknown_exception_is_durable_and_post_needs_no_new_resolution(self):
        pre, post = saved_events()
        for event in (pre, post):
            event["tool_use_id"] += "-unknown"
            event["tool_input"].pop("model"); event["tool_input"].pop("reasoning_effort")
        self.admit(pre)
        host, fake = UnavailableHost(), FakeTransport()
        with patch("mrh.adapters.providers.typesafe.TypesafeClassifier.classify", side_effect=AssertionError("classifier ran")):
            for event in (pre, pre, post, post): self.hook(event, resolver=host, transport=fake)
        stats = Store(self.path.parent / "events.sqlite3").stats(True)
        self.assertEqual(stats["proposals"], 1)
        self.assertEqual(stats["outcomes"], {"missing_role_protection": 1})
        self.assertEqual(stats["synthetic_attempts"], 0)
        self.assertEqual(stats["simulated_children"], 1)
        self.assertEqual(stats["actual_models"], {})
        self.assertEqual(stats["confirmed_children"], 0)
        self.assertEqual(fake.calls, []); self.assertEqual(self.keys, 0)
        # Pre may query unavailable metadata again on replay, but Post never
        # does. The canonical service still deduplicates recorded outcomes.
        self.assertEqual(host.calls, 2)

    def test_default_production_unknown_records_reported_child_without_http_or_key(self):
        pre, post = saved_events()
        for event in (pre, post):
            event["tool_use_id"] += "-production-unknown"
            event["tool_input"].pop("model")
            event['tool_input'].pop('reasoning_effort',None)
        self.admit(pre)
        with patch("mrh.adapters.providers.typesafe.HttpTransport.request", side_effect=AssertionError("HTTP ran")), \
             patch("mrh.adapters.providers.typesafe.TypesafeClassifier.classify", side_effect=AssertionError("classifier ran")):
            self.hook(pre, production=True); self.hook(post, production=True)
        stats = Store(self.path.parent / "events.sqlite3").stats()
        self.assertEqual(stats["outcomes"], {"missing_role_protection": 1})
        self.assertEqual(stats["reported_children"], 1)
        self.assertEqual(stats["jev_attempts"], 0)
        self.assertEqual(stats["confirmed_children"], 0); self.assertEqual(stats["actual_models"], {})
        self.assertEqual(self.keys, 0)

    def test_denied_disabled_scope_and_invalid_ids_create_no_facts(self):
        pre, _ = saved_events(); self.admit(pre)
        for field in ("enabled", "task_export_permitted"):
            settings.update(self.path, **{field: False})
            self.hook(pre)
            self.assertFalse((self.path.parent / "events.sqlite3").exists())
            settings.update(self.path, **{field: True})
        settings.update(self.path, allowed_workspaces=[]); self.hook(pre)
        self.assertFalse((self.path.parent / "events.sqlite3").exists())
        self.admit(pre)
        for field in ("session_id", "turn_id", "tool_use_id"):
            event = copy.deepcopy(pre); event[field] = "invalid id PRIVATE_CANARY"
            self.hook(event)
            self.assertFalse((self.path.parent / "events.sqlite3").exists())
        self.assertEqual(self.keys, 0)


    def test_unowned_malformed_and_partition_mismatch_do_not_gain_facts(self):
        pre, _ = saved_events(); self.admit(pre)
        self.hook(pre, path=self.root / "unowned/settings.json", settings_warning=True)
        self.assertFalse((self.root / "unowned").exists())
        class LiveContext:
            synthetic = False
            def resolve(self, event): raise AssertionError("must not resolve mismatched context")
        self.hook(pre, resolver=LiveContext(), transport=FakeTransport())
        self.assertFalse((self.path.parent / "events.sqlite3").exists())
        self.path.write_text('{"PRIVATE_SETTINGS_CANARY":"private"}')
        self.hook(pre, settings_warning=True)
        self.assertFalse((self.path.parent / "events.sqlite3").exists())
        self.assertEqual(self.keys, 0)


if __name__ == "__main__": unittest.main()
