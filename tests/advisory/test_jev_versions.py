import io
import json
import os
import stat
import tempfile
import time
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from mrh.adapters.providers import typesafe_models as tm
from mrh.adapters.providers.typesafe import HttpResponse, TypesafeClassifier
from mrh.adapters.providers.typesafe_protocol import parse_response, serialize_request
from mrh.advisory import calibration
from mrh.advisory.store import AdviceStore, version_change
from mrh.infrastructure import settings_v2 as v2
from mrh.presentation import ctrl, dashboard, stats_view
from mrh.routing.classification_spec import is_jev_alias, is_jev_model
from mrh.routing.core import ClassifierFailure
from tests.presentation.test_dashboard import settings as dash_settings

KEY = "tsk_synthetic_test_value_00000000"
NOW = 1_800_000_000


def answer(model, **extra):
    return {"model": model, "answers": {"tier": {"type": "choice", "choice": "mid",
            "probabilities": {"light": 0.1, "small": 0.1, "mid": 0.7, "top": 0.1}, "confidence": 0.7}},
            "usage": {"input_tokens": 440, "output_tokens": 45}, **extra}


class RuleTests(unittest.TestCase):
    def test_what_counts_as_a_jev_model(self):
        for good in ("jev-latest", "jev-preview", "jev-1.13.0", "jev-1.14.0", "jev-10.2.33"):
            self.assertTrue(is_jev_model(good), good)
        for bad in ("jev", "jev-1.13", "jev-1.13.0-rc1", "Jev-1.13.0", "jev-fast", "gpt-6-luna", "jev-latest ", "jev-1.13.0\n", None, 5):
            self.assertFalse(is_jev_model(bad), bad)
        self.assertTrue(is_jev_alias("jev-preview")); self.assertFalse(is_jev_alias("jev-1.13.0"))

    def test_new_installs_default_to_latest_and_an_existing_pin_is_kept(self):
        self.assertEqual(v2.default_settings()["classifier"]["model"], "jev-latest")
        pinned = {**v2.default_settings(), "classifier": {"provider": "jev", "model": "jev-1.13.0", "timeout_seconds": 10}}
        self.assertEqual(v2.validate(pinned)["classifier"]["model"], "jev-1.13.0")


class WireTests(unittest.TestCase):
    def test_the_configured_model_is_what_is_requested(self):
        self.assertEqual(serialize_request("t")["model"], "jev-1.13.0")                       # unchanged default
        for model in ("jev-latest", "jev-1.14.0"):
            self.assertEqual(serialize_request("t", model=model)["model"], model)

    def test_an_exact_version_must_come_back_as_itself_an_alias_may_resolve_to_any_jev_release(self):
        self.assertEqual(parse_response(answer("jev-1.14.0"), "jev-1.14.0").classification.model, "jev-1.14.0")
        with self.assertRaises(ClassifierFailure) as raised:
            parse_response(answer("jev-1.13.0"), "jev-1.14.0")
        self.assertEqual(raised.exception.reason, "typesafe_model_mismatch")
        for alias in ("jev-latest", "jev-preview"):
            self.assertEqual(parse_response(answer("jev-1.14.0"), alias).classification.model, "jev-1.14.0")   # resolved
            self.assertEqual(parse_response(answer(alias), alias).classification.model, alias)                  # or echoed
            with self.assertRaises(ClassifierFailure):
                parse_response(answer("some-other-model"), alias)
        self.assertEqual(parse_response(answer("jev-1.13.0")).telemetry["requested_model"], "jev-1.13.0")

    def test_the_classifier_sends_its_model_and_records_what_answered(self):
        class Transport:
            synthetic = True
            def __init__(self): self.bodies = []
            def request(self, body, headers, deadline, enter):
                enter(); self.bodies.append(body)
                return HttpResponse(200, json.dumps(answer("jev-1.14.0")).encode())
        events = []
        class Recorder:
            deadline = time.monotonic() + 5
            def check(self): pass
            def invoke(self, attempt_id, fn, **kw):
                events.append(("invoke", kw)); return fn(lambda: (lambda: None))
            def finish(self, attempt_id, outcome, **meta): events.append((outcome, meta))
        transport = Transport()
        result = TypesafeClassifier(enabled=True, task_export_permitted=True, credential_resolver=lambda: "k" * 8,
                                    transport=transport, model="jev-latest").classify("task", None, Recorder())
        self.assertEqual(transport.bodies[0]["model"], "jev-latest"); self.assertEqual(events[0][1]["requested_model"], "jev-latest")
        self.assertEqual(result.model, "jev-1.14.0"); self.assertEqual(events[1][1]["response_model"], "jev-1.14.0")
        with self.assertRaises(ClassifierFailure):
            TypesafeClassifier(model="jev-turbo")


class ListTests(unittest.TestCase):
    BODY = json.dumps({"models": [
        {"name": "jev-1.14.0", "description": "newest", "release_date": "2026-10-14"},
        {"name": "jev-1.13.0", "description": "stable\n  with   spaces", "release_date": "2026-09-10"},
        {"name": "jev-latest", "description": "alias", "release_date": "2026-09-10"},
        {"name": "jev-preview", "description": "alias", "release_date": "2026-10-14"},
        {"name": "other-model", "description": "ignored"}, {"name": "jev-1.14.0"}, "junk", {"description": "no name"}]}).encode()

    def test_only_well_formed_jev_entries_survive_and_text_is_bounded(self):
        models = tm.parse(self.BODY)
        self.assertEqual([m["name"] for m in models], ["jev-1.14.0", "jev-1.13.0", "jev-latest", "jev-preview"])
        self.assertEqual(models[1]["description"], "stable with spaces")
        for bad in (b"not json", b"[]", b'{"models": 5}', b'{"models": [{"name": "x"}]}'):
            with self.assertRaises(tm.ModelsError):
                tm.parse(bad)

    def test_fetch_sends_the_key_only_in_the_header_and_maps_failures(self):
        calls = []
        class Fake:
            def __init__(self, status=200, body=None, error=None): self.status, self.body, self.error = status, body or ListTests.BODY, error
            def get(self, headers, timeout):
                calls.append(headers)
                if self.error: raise self.error
                return self.status, self.body
        self.assertEqual(len(tm.fetch(lambda: KEY, Fake())), 4)
        self.assertEqual(calls[0]["Authorization"], "Bearer " + KEY)
        for fake, reason in ((Fake(401), "http_401"), (Fake(error=OSError()), "network"), (Fake(200, b"x" * 70000), "http_200")):
            with self.assertRaises(tm.ModelsError) as raised:
                tm.fetch(lambda: KEY, fake)
            self.assertEqual(str(raised.exception), reason)
        with self.assertRaises(tm.ModelsError) as raised:
            tm.fetch(lambda: (_ for _ in ()).throw(RuntimeError("no key")), Fake())
        self.assertEqual(str(raised.exception), "no_credentials")
        with self.assertRaises(tm.ModelsError):
            tm.fetch(lambda: "bad key with spaces", Fake())

    def test_the_cache_lives_in_project_disposable_cache_not_legacy_state_or_settings(self):
        from mrh.infrastructure import temporary
        expected = temporary.project_root() / 'runtime/cache/mrh/jev-models.json'
        self.assertEqual(tm.cache_path({"MRH_STATE_DIR": "/tmp/somewhere"}), expected)
        self.assertEqual(tm.cache_path({}), expected)
        self.assertEqual(tm.cache_path(), expected)  # the suite binds a disposable project

    def test_the_real_transport_is_disabled_for_the_whole_suite(self):
        with self.assertRaises(OSError):
            tm.HttpModelsTransport().get({}, 1)

    def test_cache_is_used_for_a_day_refreshed_after_and_falls_back_in_order(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        cache = Path(tmp.name) / tm.CACHE_NAME
        fetched = []
        def fetcher():
            fetched.append(1); return tm.parse(self.BODY)
        models, note = tm.known_models(cache, NOW, fetcher)
        self.assertEqual((len(models), note, len(fetched)), (4, "官方清單（剛更新）", 1))
        self.assertEqual(stat.S_IMODE(os.stat(cache).st_mode), 0o600)
        self.assertNotIn(KEY, cache.read_text())
        models, note = tm.known_models(cache, NOW + 3600, fetcher)
        self.assertEqual((len(fetched), note), (1, "官方清單（快取，1 小時前更新）"))             # fresh: no second request
        def failing():
            raise tm.ModelsError("network")
        models, note = tm.known_models(cache, NOW + 3 * 86400, failing)
        self.assertEqual((len(models), note), (4, "清單未更新：沿用 3 天前的快取"))
        models, note = tm.known_models(Path(tmp.name) / "none.json", NOW, failing)
        self.assertEqual([m["name"] for m in models], ["jev-latest", "jev-preview", "jev-1.13.0"]); self.assertIn("內建項目", note)
        models, note = tm.known_models(Path(tmp.name) / "none2.json", NOW, None)
        self.assertEqual(len(models), 3)
        cache.write_text('{"fetched_at": 1, "models": [{"name": "evil; rm"}]}')
        self.assertEqual(len(tm.known_models(cache, NOW, None)[0]), 3)                            # a tampered cache is ignored

    def test_menu_order_aliases_first_then_versions_newest_first_and_the_current_value_is_always_present(self):
        names = [n for n, _ in tm.choices(tm.parse(self.BODY), "jev-1.12.0")]
        self.assertEqual(names, ["jev-latest", "jev-preview", "jev-1.14.0", "jev-1.13.0", "jev-1.12.0"])


class MenuAndKeyTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name).resolve() / "owned" / "settings.json"; v2.init(self.path)

    def set(self, key, value):
        out, err = io.StringIO(), io.StringIO()
        return ctrl.main(Namespace(settings=self.path, width=100, json=False, ctrl_action="set", key=key, value=value),
                         stdin=io.StringIO(), stdout=out, stderr=err), err.getvalue()

    def test_the_model_key_accepts_aliases_and_exact_versions_with_a_chinese_refusal_otherwise(self):
        for model in ("jev-preview", "jev-1.14.0", "jev-latest"):
            self.assertEqual(self.set("classifier.model", model)[0], 0)
            self.assertEqual(v2.read(self.path)["classifier"]["model"], model)
        code, err = self.set("classifier.model", "jev-turbo")
        self.assertNotEqual(code, 0); self.assertIn("jev-latest、jev-preview，或指定版本", err)

    def test_the_menu_lists_the_official_versions_and_the_choice_is_saved(self):
        class Tty(io.StringIO):
            def isatty(self): return True
            def fileno(self): raise OSError
        with patch.object(ctrl, "fetch_jev_models", lambda secrets: tm.parse(ListTests.BODY)):
            out = io.StringIO()
            # classifier -> keep Jev -> third entry (jev-1.14.0) -> save -> (timeout, rich) back out -> quit
            ctrl.main(Namespace(settings=self.path, width=100, json=False, ctrl_action=None),
                      stdin=Tty("\n".join(["2", "1", "3", "1", "back", "back", "14"]) + "\n"), stdout=out, stderr=io.StringIO())
        text = out.getvalue()
        self.assertIn("官方清單（剛更新）", text); self.assertIn("jev-1.14.0（2026-10-14）", text); self.assertIn("jev-1.13.0（2026-09-10）", text)
        self.assertIn("指定版本號才會固定", text)
        self.assertEqual(v2.read(self.path)["classifier"]["model"], "jev-1.14.0")
        self.assertTrue(tm.cache_path().exists()); self.assertNotIn(KEY, text)
        self.assertFalse((self.path.parent / tm.CACHE_NAME).exists())                              # never inside the profile directory
        self.assertEqual(v2.read(self.path)["classifier"]["model"], "jev-1.14.0")                  # ...so the profile stays readable


class ChangeReminderTests(unittest.TestCase):
    def test_only_the_latest_switch_counts(self):
        self.assertIsNone(version_change([]))
        self.assertIsNone(version_change([(1, "jev-1.13.0"), (2, "jev-1.13.0")]))
        self.assertEqual(version_change([(1, "a"), (2, "a"), (3, "b"), (4, "b")]), {"from": "a", "to": "b", "at": 3})
        self.assertEqual(version_change([(1, "a"), (3, "b"), (5, "a")]), {"from": "b", "to": "a", "at": 5})

    def seed(self, store, rid, ts, model):
        store.attempt(rid, "jev", "classification_requested", ts - 1); store.attempt(rid, "jev", "started", ts - 0.5)
        store.attempt(rid, "jev", "returned", ts, response_model=model, input_tokens=440, output_tokens=45)

    def test_the_reminder_shows_for_a_week_on_status_and_stats_and_not_otherwise(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        store = AdviceStore(Path(tmp.name) / "advice.sqlite3"); now = time.time()
        self.seed(store, "a", now - 3 * 86400, "jev-1.13.0"); self.seed(store, "b", now - 86400, "jev-1.14.0")
        data = store.stats(0)
        self.assertEqual(data["classifier_change"]["to"], "jev-1.14.0")
        note = stats_view.version_change_note(data, now)
        self.assertIn("分級器版本已從 jev-1.13.0 變為 jev-1.14.0", note); self.assertIn("信心門檻建議重算", note)
        self.assertIn(note, dashboard.render(dash_settings(), data, "全部紀錄", 120, False, today="x"))
        self.assertIn("！" + note, stats_view.render(data, "全部紀錄", 0.65, False))
        self.assertIsNone(stats_view.version_change_note(data, now + 8 * 86400))                   # after a week it goes away
        self.assertIsNone(stats_view.version_change_note({"classifier_change": None}, now))
        self.assertEqual(AdviceStore.read_version_change(store.path)["from"], "jev-1.13.0")

    def test_the_threshold_suggestion_uses_only_data_after_the_change_and_says_so(self):
        rows = [{"request_id": f"r{n}", "ts": NOW - 5000 + n, "platform": "claude", "session_id": "s", "turn_id": f"t{n}", "call_id": f"c{n}",
                 "action": "advise", "tier": "Light", "confidence": 0.9} for n in range(40)]
        change = {"from": "jev-1.13.0", "to": "jev-1.14.0", "at": NOW - 5000 + 35}                # only 5 rows after the switch
        result = calibration.suggest_threshold(rows, [], v2.default_settings()["policy"], NOW, since=change["at"])
        self.assertEqual(result["status"], "insufficient")
        self.assertIn("只計算分級器版本變更（jev-1.13.0 → jev-1.14.0）之後的資料", " ".join(calibration.describe(result, change)))


if __name__ == "__main__":
    unittest.main()
