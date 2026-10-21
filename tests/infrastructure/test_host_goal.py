import copy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("mrh_goal_fixture", Path(__file__).resolve().parents[2]/"scripts/verification/hosts/verify_host.py")
host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host)


class GoalRpc:
    def __init__(self, unsupported=None, changed_between=False):
        self.goal = None
        self.methods = []
        self.turns = []
        self.unsupported = unsupported
        self.changed_between = changed_between

    def request(self, method, params):
        self.methods.append(method)
        if method == self.unsupported:
            return {"error": {"code": -32601, "message": "fixture unsupported method"}}
        if method == "thread/goal/get":
            goal = copy.deepcopy(self.goal)
            if self.changed_between and len(self.turns) == 1 and goal and goal["status"] == "active":
                goal["objective"] = "unexpected replacement"
            return {"result": {"goal": goal}}
        if method == "thread/goal/set":
            if self.goal is None:
                self.goal = {"threadId": params["threadId"], "createdAt": 1, "objective": params["objective"]}
            self.goal["status"] = params["status"]
            return {"result": {"goal": copy.deepcopy(self.goal)}}
        if method == "thread/goal/clear":
            self.goal = None
            return {"result": {"cleared": True}}
        raise AssertionError(method)

    def turn(self, parent, prompt):
        self.turns.append((parent, prompt))
        return {"params": {"turn": {"id": "turn-" + str(len(self.turns)), "status": "completed"}}}


class GoalTests(unittest.TestCase):
    def test_actual_lifecycle_brackets_two_distinct_requested_turns(self):
        rpc = GoalRpc()
        completed, proof = host.run_goal_turns(rpc, "parent", host.Fixture("goal"))
        self.assertEqual(completed["params"]["turn"]["id"], "turn-2")
        self.assertEqual(proof["parent_turn_ids"], ["turn-1", "turn-2"])
        self.assertEqual([x["stage"] for x in proof["state_readbacks"]],
                         ["before_creation", "before_first_turn", "between_turns", "after_second_turn", "completed", "cleared"])
        self.assertTrue(proof["completed_and_cleared"])
        self.assertIsNone(rpc.goal)
        self.assertFalse(proof["host_autonomous_continuation_proven"])

    def test_unsupported_goal_get_does_not_create_or_start(self):
        rpc = GoalRpc(unsupported="thread/goal/get")
        completed, proof = host.run_goal_turns(rpc, "parent", host.Fixture("goal"))
        self.assertIsNone(completed)
        self.assertEqual(proof["status"], "unsupported")
        self.assertEqual(rpc.methods, ["thread/goal/get"])
        self.assertEqual(rpc.turns, [])

    def test_refused_goal_creation_does_not_start_or_claim_pass(self):
        rpc = GoalRpc(unsupported="thread/goal/set")
        completed, proof = host.run_goal_turns(rpc, "parent", host.Fixture("goal"))
        self.assertIsNone(completed)
        self.assertEqual(proof["unsupported_stage"], "creation")
        self.assertEqual(rpc.turns, [])
        self.assertNotIn("thread/goal/clear", rpc.methods)

    def test_changed_goal_between_turns_stops_second_turn_and_cleans_own_goal(self):
        rpc = GoalRpc(changed_between=True)
        with self.assertRaisesRegex(AssertionError, "goal_identity_changed"):
            host.run_goal_turns(rpc, "parent", host.Fixture("goal"))
        self.assertEqual(len(rpc.turns), 1)
        self.assertIsNone(rpc.goal)
        self.assertEqual(rpc.methods[-2:], ["thread/goal/clear", "thread/goal/get"])

    def test_reused_calls_or_same_turn_cannot_be_cross_turn_evidence(self):
        proof = {"parent_turn_ids": ["turn-1", "turn-2"]}
        logs = [{"event": {"hook_event_name": "PreToolUse", "turn_id": turn, "tool_use_id": "same-call"},
                 "classifier_calls": 1} for turn in proof["parent_turn_ids"]]
        with self.assertRaisesRegex(AssertionError, "goal_call_identity_reused"):
            host.check_goal_delegations(proof, logs)
        logs[1]["event"].update(tool_use_id="fresh-call", turn_id="turn-1")
        with self.assertRaisesRegex(AssertionError, "goal_cross_turn_hook_mismatch"):
            host.check_goal_delegations(proof, logs)


if __name__ == "__main__": unittest.main()
