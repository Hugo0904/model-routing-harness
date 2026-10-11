import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from mrh.adapters.hosts.codex import handle_event
from mrh.application.simulation import demo_policy
from mrh.infrastructure.store import Store


class InstalledShapeReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name)/"facts.sqlite3")
        self.event = {"hook_event_name":"PreToolUse", "tool_name":"spawn_agent", "session_id":"s", "turn_id":"t",
                      "tool_use_id":"c", "tool_input":{"message":"fixture task", "fork_context":False}}

    def decide(self, mode="Fixed"):
        policy = demo_policy(); policy["top_mode"] = mode
        return handle_event(self.event, self.store, True, {"tier":"Top", "policy":policy})

    def post(self, response, rewritten=None):
        event = copy.deepcopy(self.event)
        event.update(hook_event_name="PostToolUse", tool_response=response)
        if rewritten is not None:
            event["tool_input"] = rewritten
        return handle_event(event, self.store, True, {"tier":"Top"})

    def test_installed_json_string_output_and_rewritten_input_record_one_synthetic_child(self):
        pre = self.decide()
        rewritten = pre["hookSpecificOutput"]["updatedInput"]
        response = json.dumps({"agent_id":"native-fixture-child", "nickname":"BODY_PRIVATE_CANARY"})
        self.assertEqual(self.post(response, rewritten), {})
        self.post(response, rewritten)
        stats = self.store.stats(True)
        self.assertEqual(stats["simulated_children"], 1)
        self.assertEqual(stats["synthetic_attempts"], 1)
        self.assertEqual(stats["confirmed_children"], 0)
        self.assertEqual(stats["actual_models"], {})
        with self.store.connect() as db:
            self.assertNotIn("BODY_PRIVATE_CANARY", str([tuple(r) for r in db.execute("SELECT * FROM receipts")]))

    def test_malformed_oversized_or_non_id_output_is_safe_unavailable(self):
        self.decide()
        diagnostics = io.StringIO()
        with contextlib.redirect_stderr(diagnostics):
            for response in ('ERROR_PRIVATE_CANARY', 'x'*65537, json.dumps({"agent_id":{"raw":"PRIVATE_CANARY"}})):
                self.assertEqual(self.post(response), {})
        self.assertNotIn("CANARY", diagnostics.getvalue())
        self.assertEqual(self.store.stats(True)["simulated_children"], 0)

    def test_unexpected_json_string_child_after_main_is_retained_as_anomaly(self):
        self.decide("Main")
        self.post('{"agent_id":"unexpected-fixture-child"}')
        stats = self.store.stats(True)
        self.assertEqual(stats["handback_anomalies"], 1)
        self.assertEqual(stats["simulated_children"], 1)
        self.assertEqual(stats["confirmed_children"], 0)


if __name__ == "__main__": unittest.main()
