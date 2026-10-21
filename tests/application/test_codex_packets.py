import json
import os
from pathlib import Path
import tempfile
import unittest

from mrh.adapters.hosts import codex_packets as p
from mrh.application import advisory_runtime as rt
from mrh.infrastructure import settings_v2 as v2
from mrh.routing.core import ClassifierFailure
from mrh.routing.types import Classification

SESSION = "00000000-0000-4000-8000-000000000001"
TURN = "00000000-0000-4000-8000-000000000002"
TASK = "FULL-TASK unique Ω\nRead the specified input, preserve first casing, write only output.json.\nNo further delegation."


class Classifier:
    def __init__(self, tier="Light", fail=False):
        self.calls, self.tasks, self.tier, self.fail = 0, [], tier, fail
    def classify(self, task, context, recorder):
        self.calls += 1; self.tasks.append(task)
        if self.fail: raise ClassifierFailure("typesafe_http_401")
        return Classification(self.tier, .9)


class PacketTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.settings = self.root / "profile" / "settings.json"
        v2.init(self.settings)
        v2.update(self.settings, enabled=True, task_export_permitted=True, allowed_workspaces=[str(self.root)],
                  policy={"tiers": {"Light": {"codex": [{"model": "gpt-6-luna", "effort": "high"}]}}})
        self.fake = Classifier()
    def prep(self, **kwargs):
        return p.prepare(self.settings, TASK, self.root, clock=lambda: 1000, **kwargs)
    def event(self, packet, release=False, **change):
        return {"hook_event_name": "PreToolUse", "tool_name": "spawn_agent", "session_id": SESSION,
                "turn_id": TURN, "tool_use_id": ('release_' if release else 'query_')+packet['packet_id'], "cwd": str(self.root),
                "tool_input": {"message": "gAAAA" + "A" * 100,
                  "task_name": packet["release_task_name" if release else "query_task_name"],
                  "agent_type": "luna_worker", "model": "gpt-6-luna", "reasoning_effort": "max"}, **change}
    def run_hook(self, event):
        return rt.handle(event, "codex", self.settings, codex_packets=True,
                         classifier_factory=lambda: self.fake, clock=lambda: 1001)
    def reason(self, response):
        self.assertEqual(response["hookSpecificOutput"]["permissionDecision"], "deny")
        return response["hookSpecificOutput"]["permissionDecisionReason"]

    def test_opaque_full_text_once_profile_preserved_release_unknown_and_completion(self):
        packet = self.prep()
        self.assertIn("classification ready", self.reason(self.run_hook(self.event(packet))))
        self.assertEqual(self.fake.tasks, [TASK])
        self.assertTrue((self.settings.parent / "advice.sqlite3").exists())
        self.assertFalse((Path(packet['body_path']).parent/'query.sqlite3').exists())
        self.assertIn("classification ready", self.reason(self.run_hook(self.event(packet, tool_use_id="query2"))))
        self.assertEqual(self.fake.calls, 1)
        release = self.event(packet, True)
        self.assertEqual(self.run_hook(release)["hookSpecificOutput"]["permissionDecision"], "allow")
        row = p.status(self.settings, packet["packet_id"], clock=lambda: 1001)
        self.assertEqual((row["state"], row["role"], row["requested_model"], row["requested_effort"]),
                         ("released", "luna_worker", "gpt-6-luna", "max"))
        self.assertEqual(self.fake.calls, 1)
        self.assertIn("spawn_outcome_unknown", self.reason(self.run_hook(release)))
        post = {**release, "hook_event_name": "PostToolUse", "tool_response": {"task_name": "child-one"}}
        self.assertEqual(self.run_hook(post), {})
        row = p.status(self.settings, packet["packet_id"], clock=lambda: 1001)
        self.assertEqual((row["state"], row["child_id"]), ("completed", "child-one"))
        self.assertFalse(Path(packet["body_path"]).exists()); self.assertNotIn(TASK, json.dumps(row))
        self.assertIn("already_completed", self.reason(self.run_hook(release)))

    def test_invalid_scope_revision_hash_never_export(self):
        for kind in ("scope", "revision", "hash"):
            with self.subTest(kind=kind):
                packet = self.prep(); event = self.event(packet)
                if kind == "scope":
                    self.run_hook(event)
                    event["session_id"] = TURN
                elif kind == "revision": v2.update(self.settings, policy={"threshold":.7})
                else:
                    f=Path(packet["body_path"]); os.chmod(f, 0o600)
                    d=json.loads(f.read_text()); d["task"] += "tampered"; f.write_text(json.dumps(d))
                    os.chmod(f,0o400)
                self.assertIn("packet_hash_invalid" if kind=="hash" else "packet_scope_invalid", self.reason(self.run_hook(event)))
        self.assertEqual(self.fake.calls, 1)

    def test_expiry_cleans_body_preserves_receipt(self):
        packet = self.prep()
        out = rt.handle(self.event(packet), "codex", self.settings, codex_packets=True,
                        classifier_factory=lambda: self.fake, clock=lambda: 1601)
        self.assertIn("expired", self.reason(out)); self.assertEqual(self.fake.calls, 0)
        self.assertFalse(Path(packet["body_path"]).exists())
        self.assertEqual(p.status(self.settings, packet["packet_id"], clock=lambda: 1601)["state"], "expired")

    def test_no_caller_scope_no_export_and_size_bound(self):
        packet=self.prep();self.assertIsNone(p.status(self.settings,packet['packet_id'],clock=lambda:1001)['binding'])
        self.assertIn('native_scope_required',self.reason(self.run_hook(self.event(packet,session_id=None))))
        self.assertEqual(self.fake.calls,0)
        with self.assertRaises(p.PacketError): p.prepare(self.settings,"a"*(p.MAX_TASK_BYTES+1),self.root)
        v2.update(self.settings,task_export_permitted=False)
        with self.assertRaises(p.PacketError): self.prep()

    def test_typesafe_state_task_receives_full_packet_not_opaque_message(self):
        from mrh.adapters.providers.typesafe import TypesafeClassifier, HttpResponse
        packet=self.prep(); seen=[]
        answer={"model":"jev-1.13.0","answers":{"tier":{"type":"choice","choice":"light","confidence":.9,
                "probabilities":{"light":.9,"small":.1,"mid":0,"top":0}}}}
        class Transport:
            synthetic=True
            def request(self,body,headers,deadline,enter):
                enter(); seen.append(body["state"]["task"])
                return HttpResponse(200,json.dumps(answer).encode())
        factory=lambda:TypesafeClassifier(enabled=True,task_export_permitted=True,transport=Transport(),credential_resolver=lambda:"synthetic-test-value")
        out=rt.handle(self.event(packet),"codex",self.settings,codex_packets=True,classifier_factory=factory,clock=lambda:1001)
        self.assertIn("classification ready",self.reason(out)); self.assertEqual(seen,[TASK])
        self.assertNotIn("synthetic-test-value",json.dumps(p.status(self.settings,packet["packet_id"],clock=lambda:1001)))

    def test_packet_root_symlink_fifo_permissions_rejected(self):
        for kind in ("symlink", "fifo", "permission", "writable", "root"):
            with self.subTest(kind=kind):
                packet=self.prep(); f=Path(packet["body_path"])
                if kind=="permission": os.chmod(f,0o444)
                elif kind=="writable": os.chmod(f,0o600)
                elif kind=="root":
                    d=f.parent; moved=d.with_name(d.name+"-moved"); d.rename(moved); d.symlink_to(moved)
                else:
                    f.unlink()
                    if kind=="symlink": f.symlink_to(self.settings)
                    else: os.mkfifo(f,0o600)
                self.reason(self.run_hook(self.event(packet)))
        self.assertEqual(self.fake.calls,0)

    def test_bad_marker_missing_packet_feature_disabled_fail_closed(self):
        packet=self.prep()
        for name in ("mrh_packet_../../secret", "mrh_packet_"+"f"*32):
            event=self.event(packet); event["tool_input"]["task_name"]=name
            self.reason(self.run_hook(event))
        out=rt.handle(self.event(packet),"codex",self.settings,classifier_factory=lambda:self.fake)
        self.assertIn("not_enabled",self.reason(out)); self.assertEqual(self.fake.calls,0)

    def test_all_export_workspace_gates_block_opt_in(self):
        for update in ({"enabled":False},{"task_export_permitted":False},{"allowed_workspaces":["/elsewhere"]}):
            packet=self.prep(); v2.update(self.settings,**update)
            self.reason(self.run_hook(self.event(packet)))
            v2.update(self.settings,enabled=True,task_export_permitted=True,allowed_workspaces=[str(self.root)])
        self.assertEqual(self.fake.calls,0)

    def test_crashed_processing_or_failure_never_reclassified_released(self):
        packet=self.prep(); d=p._directory(self.settings,packet["packet_id"])
        row=p.status(self.settings,packet["packet_id"],clock=lambda:1001); row["state"]="classifying"; p._write(d/"receipt.json",row)
        self.assertIn("do not retry",self.reason(self.run_hook(self.event(packet)))); self.assertEqual(self.fake.calls,0)
        packet=self.prep(); self.fake.fail=True
        self.assertIn("failed",self.reason(self.run_hook(self.event(packet))))
        self.reason(self.run_hook(self.event(packet))); self.reason(self.run_hook(self.event(packet,True)))
        self.assertEqual(self.fake.calls,1)

    def test_lock_contention_returns_processing_without_wait_or_call(self):
        packet=self.prep(); d=p._directory(self.settings,packet["packet_id"])
        with p._lock(d): self.assertIn("in_progress",self.reason(self.run_hook(self.event(packet))))
        self.assertEqual(self.fake.calls,0)

    def test_top_main_and_explicit_human_profile_priority(self):
        self.fake.tier="Top"
        packet=self.prep(); self.run_hook(self.event(packet))
        self.assertIn("continue_in_parent",self.reason(self.run_hook(self.event(packet,True))))
        packet=self.prep(user_model="gpt-6-luna",user_effort="max"); self.run_hook(self.event(packet))
        release=self.event(packet,True); release["tool_input"]["reasoning_effort"]="high"
        self.assertIn("must_be_preserved",self.reason(self.run_hook(release)))
        release["tool_input"]["reasoning_effort"]="max"
        self.assertEqual(self.run_hook(release)["hookSpecificOutput"]["permissionDecision"],"allow")

    def test_unknown_post_and_finish_cannot_hide_uncertain_release(self):
        packet=self.prep(); self.run_hook(self.event(packet)); release=self.event(packet,True); self.run_hook(release)
        self.run_hook({**release,"hook_event_name":"PostToolUse","tool_response":{}})
        self.assertEqual(p.status(self.settings,packet["packet_id"],clock=lambda:1001)["state"],"released")
        with self.assertRaises(p.PacketError): p.status(self.settings,packet["packet_id"],finish=True,clock=lambda:1001)
        self.assertTrue(Path(packet["body_path"]).exists())

    def test_unmarked_codex_and_all_claude_events_unchanged(self):
        event={"hook_event_name":"PreToolUse","tool_name":"spawn_agent","session_id":SESSION,"turn_id":TURN,
               "tool_use_id":"normal","cwd":str(self.root),"tool_input":{"message":"Normal task","model":"gpt-6-luna","agent_type":"luna_worker"}}
        self.assertEqual(self.run_hook(event),{}); self.assertEqual(self.fake.calls,0)
        v2.update(self.settings,policy={"tiers":{"Light":{"claude":[{"model":"haiku"}]}}})
        event.update(tool_name="Agent",tool_input={"prompt":TASK,"task_name":"mrh_packet_"+"f"*32})
        out=rt.handle(event,"claude",self.settings,codex_packets=True,classifier_factory=lambda:self.fake)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"],"deny")
        self.assertEqual(self.fake.tasks,[TASK]); self.assertFalse(p.root_for(self.settings).exists())


    def test_plaintext_mismatch_invalid_json_and_cli_settings_failure_stop(self):
        import io
        from mrh.presentation.cli import main
        packet=self.prep(); event=self.event(packet); event["tool_input"]["message"]="different task"
        self.assertIn("message_mismatch",self.reason(self.run_hook(event)))
        event=self.event(packet); f=Path(packet["body_path"]); os.chmod(f,0o600);f.write_text("[]");os.chmod(f,0o400)
        self.reason(self.run_hook(event)); self.assertEqual(self.fake.calls,0)
        out=io.StringIO()
        main(["hook","--platform","codex","--codex-packets","--settings",str(self.root/"wrong.json")],
             stdin=io.StringIO(json.dumps(event)),stdout=out,stderr=io.StringIO())
        self.assertIn("settings_path_invalid",self.reason(json.loads(out.getvalue())))


if __name__ == "__main__": unittest.main()
