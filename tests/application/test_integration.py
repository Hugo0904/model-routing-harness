import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from mrh.presentation.cli import main
from mrh.routing.core import Classification, ScriptedClassifier
from mrh.adapters.hosts.codex import handle_event
from mrh.application.service import process
from mrh.application.simulation import demo_capabilities, demo_policy, run_demo
from mrh.infrastructure.store import Store
from mrh.routing.types import Proposal


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "events.sqlite3"
        self.store = Store(self.path)



    def test_store_attempt_and_complete_failures_leave_unknown_pending(self):
        for stage in ("attempt", "complete"):
            real = self.store
            class Broken:
                def claim(self, p): return real.claim(p)
                def attempt(self, *args):
                    if stage == "attempt": raise RuntimeError("PRIVATE_ERROR_CANARY")
                    return real.attempt(*args)
                def complete(self, *args): raise RuntimeError("PRIVATE_ERROR_CANARY")
            p = Proposal("codex", "simulation", "s", "t", stage, {"message": "task"}, True)
            d = process(p, demo_policy(), demo_capabilities(), Broken(), ScriptedClassifier([Classification("Top", 0.9)]))
            self.assertEqual(d.reason, "store_error")
            retry = ScriptedClassifier([Classification("Top", 0.9)])
            again = process(p, demo_policy(), demo_capabilities(), real, retry)
            self.assertEqual(again.reason, "proposal_pending"); self.assertEqual(retry.calls, 0)


if __name__ == "__main__": unittest.main()
