import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from mrh import cli, settings
from mrh.runtime import configured_event
from mrh.settings_schema import SettingsError
from mrh.simulation import demo_capabilities
from mrh.store import Store
from mrh.typesafe import classifier_from_config, TypesafeClassifier
from test_typesafe import FakeTransport


class SyntheticHost:
    synthetic = True
    def resolve(self, event):
        return demo_capabilities()


class SettingsRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.path = self.root / "state" / "settings.json"
        settings.init(self.path)
        self.resolutions = 0
        self.event = {"hook_event_name": "PreToolUse", "tool_name": "spawn_agent", "session_id": "session",
                      "turn_id": "turn", "tool_use_id": "call", "cwd": str(self.workspace),
                      "tool_input": {"message": "TASK_E5_PRIVATE_CANARY"}}

    def key(self):
        self.resolutions += 1
        return "KEY_E5_PRIVATE_CANARY"

    def cli(self, args, deps=None, event=None):
        out, err = io.StringIO(), io.StringIO()
        code = cli.main(args, stdin=io.StringIO(json.dumps(event or self.event)), stdout=out, stderr=err,
                        runtime_dependencies=deps)
        return code, out.getvalue(), err.getvalue()

    def admit(self, **changes):
        settings.update(self.path, enabled=True, task_export_permitted=True,
                        allowed_workspaces=[str(self.workspace)], **changes)

    def test_public_configuration_and_enable_are_independent_idempotent_and_read_only_show(self):
        initial = self.path.read_bytes()
        self.assertEqual(self.cli(["settings", "init", "--path", str(self.path)])[0], 0)
        self.assertEqual(self.path.read_bytes(), initial)
        args = ["settings", "configure", "--path", str(self.path), "--provider", "typesafe",
                "--allow-workspace", str(self.workspace), "--permit-task-export"]
        self.assertEqual(self.cli(args)[0], 0)
        self.assertFalse(settings.read(self.path)["enabled"])
        before = {p.name: p.read_bytes() for p in self.path.parent.iterdir()}
        with patch("mrh.typesafe.environment_credential", side_effect=AssertionError("key read")):
            code, output, _ = self.cli(["settings", "show", "--path", str(self.path)])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output)["readiness_reason"], "missing_role_protection")
            self.assertFalse(json.loads(output)["live_routing_ready"])
            self.assertEqual(self.cli(["doctor", "--plain"])[0], 0)
        self.assertEqual({p.name: p.read_bytes() for p in self.path.parent.iterdir()}, before)
        settings.update(self.path, enabled=True)
        saved = self.path.read_bytes()
        settings.init(self.path)
        self.assertEqual(self.path.read_bytes(), saved)
        self.assertEqual(self.cli(["settings", "disable", "--path", str(self.path)])[0], 0)
        self.assertFalse(settings.read(self.path)["enabled"])
        self.assertTrue(settings.read(self.path)["task_export_permitted"])
        revision = settings.read(self.path)["revision"]
        with self.assertRaisesRegex(SettingsError, "settings_conflict"):
            settings.update(self.path, expected_revision=revision-1, enabled=True)
        self.assertFalse(settings.read(self.path)["enabled"])

    def test_each_export_gate_combination_has_zero_key_and_transport_until_all_true(self):
        for enabled in (False, True):
            for permit in (False, True):
                for scoped in (False, True):
                    settings.update(self.path, enabled=enabled, task_export_permitted=permit,
                                    allowed_workspaces=[str(self.workspace)] if scoped else [])
                    fake = FakeTransport()
                    event = copy.deepcopy(self.event)
                    event["tool_use_id"] = "case-" + str(int(enabled))+str(int(permit))+str(int(scoped))
                    before = self.resolutions
                    code, output, _ = self.cli(["hook", "--settings", str(self.path)],
                        {"host_resolver": SyntheticHost(), "transport": fake, "credential_resolver": self.key}, event)
                    self.assertEqual(code, 0)
                    admitted = enabled and permit and scoped
                    self.assertEqual(len(fake.calls), int(admitted))
                    self.assertEqual(self.resolutions-before, int(admitted))
                    self.assertEqual(bool(json.loads(output)), admitted)
        # A task-controlled declaration cannot authorize another host workspace.
        outside = copy.deepcopy(self.event); outside["cwd"] = str(self.root)
        outside["tool_input"].update(task_export_permitted=True, allowed_workspaces=[str(self.root)])
        fake = FakeTransport()
        self.assertEqual(configured_event(outside, self.path, host_resolver=SyntheticHost(), transport=fake,
                                         credential_resolver=self.key), {})
        self.assertEqual(fake.calls, [])

    def test_public_hook_uses_real_factory_and_parser_main_fixed_receipt_disable(self):
        self.admit()
        fake = FakeTransport()
        with patch("mrh.runtime.classifier_from_config", wraps=classifier_from_config) as factory:
            code, text, _ = self.cli(["hook", "--settings", str(self.path)],
                {"host_resolver": SyntheticHost(), "transport": fake, "credential_resolver": self.key})
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(text)["hookSpecificOutput"]["permissionDecision"], "deny")
            factory.assert_called_once()
            self.assertEqual(factory.call_args.kwargs["transport"], fake)
        body, headers, _ = fake.calls[0]
        self.assertEqual(body["model"], "jev-1.13.0")
        self.assertEqual(body["state"], {"task": "TASK_E5_PRIVATE_CANARY"})
        self.assertEqual(headers["Authorization"], "Bearer KEY_E5_PRIVATE_CANARY")
        settings.update(self.path, policy={"top_mode": "Fixed", "fixed": {"model": "gpt-6-astra", "effort": "high"}})
        fixed = copy.deepcopy(self.event); fixed["tool_use_id"] = "fixed-call"
        result = configured_event(fixed, self.path, host_resolver=SyntheticHost(), transport=FakeTransport(), credential_resolver=self.key)
        self.assertEqual(result["hookSpecificOutput"]["updatedInput"]["model"], "gpt-6-astra")
        post = {**fixed, "hook_event_name": "PostToolUse", "tool_input": result["hookSpecificOutput"]["updatedInput"],
                "tool_response": json.dumps({"agent_id": "synthetic-child"})}
        configured_event(post, self.path, host_resolver=SyntheticHost(), transport=FakeTransport(), credential_resolver=self.key)
        settings.update(self.path, enabled=False)
        fake = FakeTransport(); before = self.resolutions
        self.assertEqual(configured_event(self.event, self.path, host_resolver=SyntheticHost(), transport=fake,
                                         credential_resolver=self.key), {})
        self.assertEqual(self.resolutions, before); self.assertEqual(fake.calls, [])
        store = Store(self.path.parent / "events.sqlite3")
        self.assertEqual(store.stats(True)["simulated_children"], 1)
        self.assertEqual(store.stats()["jev_attempts"], 0)
        with store.connect() as db:
            facts = "\n".join(str(tuple(row)) for table in ("proposals", "attempts", "receipts") for row in db.execute("SELECT * FROM " + table))
        for value in ("TASK_E5_PRIVATE_CANARY", "KEY_E5_PRIVATE_CANARY", "BODY_PRIVATE_CANARY"):
            self.assertNotIn(value, facts + json.dumps(store.stats(True)))

    def test_unknown_host_explicit_fixed_role_unrelated_and_failures_preserve(self):
        self.admit()
        for name, event, resolver in [
                ("unresolved", self.event, None),
                ("explicit", {**self.event, "tool_input": {"message": "task", "model": "operator-choice"}}, SyntheticHost()),
                ("unrelated", {**self.event, "tool_name": "exec_command"}, SyntheticHost()),
                ("fixed-role", {**self.event, "tool_input": {"message": "task", "agent_type": "fixed"}}, SyntheticHost())]:
            event = {**event, "tool_use_id": "independent-" + name}
            fake = FakeTransport(); before = self.resolutions
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(configured_event(event, self.path, host_resolver=resolver, transport=fake,
                                                 credential_resolver=self.key), {}, name)
            self.assertEqual(fake.calls, [], name); self.assertEqual(self.resolutions, before, name)
        observed = Store(self.path.parent / "events.sqlite3").stats(True)
        self.assertEqual(observed["outcomes"].get("fixed_role_model"), 1)
        self.assertEqual(observed["outcomes"].get("explicit_model"), 1)
        self.assertEqual(observed["synthetic_attempts"], 0)
        for call, resolver, fake in [("missing-key", lambda: None, FakeTransport()),
                                     ("failure", self.key, FakeTransport(error=OSError("PRIVATE_ERROR_CANARY")))]:
            event = {**self.event, "tool_use_id": call}
            self.assertEqual(configured_event(event, self.path, host_resolver=SyntheticHost(), transport=fake,
                                             credential_resolver=resolver), {})
            self.assertEqual(len(fake.calls), 1 if call == "failure" else 0)
        self.path.write_text('{"PRIVATE_INVALID_CANARY":"private"}')
        fake = FakeTransport(); before = self.resolutions
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(configured_event(self.event, self.path, host_resolver=SyntheticHost(), transport=fake,
                                             credential_resolver=self.key), {})
        self.assertNotIn("PRIVATE", err.getvalue())
        self.assertEqual(fake.calls, []); self.assertEqual(self.resolutions, before)

    def test_nonowned_symlink_and_foreign_file_are_preserved(self):
        foreign = self.root / "foreign"; foreign.mkdir(); marker = foreign / "original"; marker.write_bytes(b"original")
        with self.assertRaises(SettingsError): settings.init(foreign / "settings.json")
        self.assertEqual(list(foreign.iterdir()), [marker]); self.assertEqual(marker.read_bytes(), b"original")
        link = self.root / "link"; link.symlink_to(self.path.parent)
        with self.assertRaises(SettingsError): settings.init(link / "settings.json")
        original = self.path.read_bytes(); self.path.unlink(); self.path.symlink_to(marker)
        with self.assertRaises(SettingsError): settings.update(self.path, enabled=True)
        self.assertEqual(marker.read_bytes(), b"original")
        self.path.unlink(); self.path.write_bytes(original)
        outsider = self.path.parent / "not-mrh"; outsider.write_bytes(b"preserve")
        with self.assertRaises(SettingsError): settings.update(self.path, enabled=True)
        self.assertEqual(outsider.read_bytes(), b"preserve"); self.assertEqual(self.path.read_bytes(), original)

    def test_disable_is_neutral_for_new_invocations_without_promising_inflight_cancellation(self):
        self.admit()
        entered, release = threading.Event(), threading.Event()
        fake = FakeTransport()
        request = fake.request
        def waiting(body, headers, deadline, enter):
            value = request(body, headers, deadline, enter)
            entered.set()
            if not release.wait(1): raise AssertionError("fixture release absent")
            return value
        fake.request = waiting
        result = []
        worker = threading.Thread(target=lambda: result.append(configured_event(self.event, self.path,
            host_resolver=SyntheticHost(), transport=fake, credential_resolver=self.key)))
        worker.start()
        try:
            self.assertTrue(entered.wait(1))
            settings.update(self.path, enabled=False)
            next_transport = FakeTransport(); before = self.resolutions
            self.assertEqual(configured_event({**self.event, "tool_use_id": "after-disable"}, self.path,
                host_resolver=SyntheticHost(), transport=next_transport, credential_resolver=self.key), {})
            self.assertEqual(next_transport.calls, []); self.assertEqual(self.resolutions, before)
        finally:
            release.set(); worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(result[0]["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertFalse(settings.read(self.path)["enabled"])

    def test_oversized_serialized_settings_refuse_before_replacement(self):
        before = self.path.read_bytes()
        rates = {"model-" + str(i): {"currency": "USD", "unit": "token", "service": "test", "source_ref": "fixture",
                                  "components": {"input": 1, "output": 2}} for i in range(500)}
        with self.assertRaisesRegex(SettingsError, "settings_oversized"):
            settings.update(self.path, policy={"top_mode": "Main", "rates": rates})
        self.assertEqual(self.path.read_bytes(), before)

    def test_wrong_uid_empty_target_is_refused_without_ownership_marker(self):
        from mrh import owned
        empty = self.root / "other-owner"; empty.mkdir()
        with patch("mrh.owned.os.getuid", return_value=empty.stat().st_uid+1):
            with self.assertRaises(owned.OwnedError): owned.initialize(empty, "settings", settings.FILES)
        self.assertEqual(list(empty.iterdir()), [])

    def test_cooperating_writers_serialize_and_stale_revision_cannot_overwrite(self):
        barrier = threading.Barrier(3)
        results = []
        def change(value):
            barrier.wait()
            try:
                settings.update(self.path, expected_revision=0, enabled=value, task_export_permitted=not value)
                results.append("written")
            except SettingsError as exc:
                results.append(exc.reason)
        workers = [threading.Thread(target=change, args=(value,)) for value in (False, True)]
        for worker in workers: worker.start()
        barrier.wait()
        for worker in workers: worker.join(2)
        self.assertTrue(all(not worker.is_alive() for worker in workers))
        self.assertCountEqual(results, ["written", "settings_conflict"])
        value = settings.read(self.path)
        self.assertEqual(value["revision"], 1)
        self.assertNotEqual(value["enabled"], value["task_export_permitted"])


if __name__ == "__main__": unittest.main()
