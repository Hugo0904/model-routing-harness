import io
import json
import sqlite3
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

from mrh.adapters.providers.typesafe import HttpResponse, TypesafeClassifier
from mrh.advisory.store import AdviceStore
from mrh.infrastructure import settings_v2 as v2
from mrh.presentation import cli, classify_cli, stats_view

SECRET_TASK = "rewrite the invoice export, ticket ABC-1234"


class Transport:
    synthetic = True

    def __init__(self, probabilities=None, status=200, model="jev-1.13.0", confidence=None):
        self.probabilities = probabilities or {"light": 0.05, "small": 0.15, "mid": 0.72, "top": 0.08}
        self.status, self.model, self.confidence, self.bodies = status, model, confidence, []

    def request(self, body, headers, deadline, enter):
        enter()
        self.bodies.append(body)
        choice = max(self.probabilities, key=self.probabilities.get)
        answer = {"type": "choice", "choice": choice, "probabilities": self.probabilities,
                  "confidence": self.confidence if self.confidence is not None else self.probabilities[choice]}
        return HttpResponse(self.status, json.dumps({"model": self.model, "answers": {"tier": answer},
                                                     "usage": {"input_tokens": 440, "output_tokens": 45}}).encode())


class ClassifyTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name).resolve() / "owned" / "settings.json"; v2.init(self.path)
        self.db = self.path.parent / "advice.sqlite3"

    def configure(self, export=True, enabled=False):
        settings = v2.read(self.path)
        settings["task_export_permitted"], settings["enabled"] = export, enabled
        settings["policy"] = v2.validate({**settings, "policy": {"threshold": 0.65, "top_mode": "Main", "tiers": {
            "Light": {"claude": [{"model": "haiku", "effort": "medium"}]},
            "Mid": {"claude": [{"model": "sonnet", "effort": "high"}], "codex": [{"model": "gpt-6.1-sol", "effort": "high"}]}}}})["policy"]
        v2.update(self.path, **{k: settings[k] for k in ("task_export_permitted", "enabled", "policy")})

    def ask(self, transport=None, task=SECRET_TASK, **options):
        args = Namespace(task=task, stdin=False, title=None, role=None, platform=None, json=False, settings=self.path)
        for key, value in options.items():
            setattr(args, key, value)
        out, err = io.StringIO(), io.StringIO()
        transport = transport or Transport()
        factory = lambda: TypesafeClassifier(enabled=True, task_export_permitted=True, credential_resolver=lambda: "k" * 8, transport=transport)
        code = classify_cli.main(args, stdin=io.StringIO(options.get("stdin_text", "")), stdout=out, stderr=err, classifier_factory=factory)
        return code, out.getvalue(), err.getvalue(), transport

    def counts(self):
        with sqlite3.connect(self.db) as db:
            return {t: db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("advice", "attempts", "children")}

    def test_full_flow_prints_tier_probabilities_suggestions_cost_and_writes_only_attempts(self):
        self.configure()
        code, out, err, transport = self.ask()
        self.assertEqual((code, err), (0, ""))
        for expected in ("難度：mid", "信心 0.72", "gpt-6.1-sol:high", "sonnet:high", "mid   ", " 72%", "輸入 440 tokens", "估計 < $0.0001",
                         "不算進派工統計", "jev-1.13.0"):
            self.assertIn(expected, out)
        counts = self.counts()
        self.assertEqual((counts["advice"], counts["children"]), (0, 0))                 # not a delegation
        self.assertGreaterEqual(counts["attempts"], 3)
        with sqlite3.connect(self.db) as db:
            self.assertTrue(all(r[0].startswith("manual-") for r in db.execute("SELECT request_id FROM attempts")))
            dump = "".join(str(row) for table in ("advice", "attempts") for row in db.execute(f"SELECT * FROM {table}"))
        self.assertNotIn("ABC-1234", dump)                                               # the task text is never stored
        self.assertEqual(transport.bodies[0]["state"], {"task": SECRET_TASK})            # nothing extra unless asked

    def test_it_works_with_routing_switched_off_and_the_manual_call_shows_in_statistics(self):
        self.configure(enabled=False)
        self.assertEqual(self.ask()[0], 0)
        data = AdviceStore.read_stats(self.db, 0)
        self.assertEqual(data["manual_classifications"], 1)
        self.assertEqual(data["decisions"], {})
        self.assertEqual(sum(u["input_tokens"] for u in data["classifier_usage"].values()), 440)   # the cost is counted
        self.assertEqual(data["classifier_latency"]["n"], 1)
        text = stats_view.render(data, "全部紀錄", 0.65, False)
        self.assertNotIn("子代理委派：共", text)                                          # no delegations at all
        data["decisions"] = {"advise": 1}; data["per_platform"] = {"claude": {"advise": 1}}
        self.assertIn("其中手動查詢（mrh classify）1 次", stats_view.render(data, "全部紀錄", 0.65, False))

    def test_low_confidence_top_and_missing_platform_are_explained(self):
        self.configure()
        _, out, _, _ = self.ask(Transport({"light": 0.3, "small": 0.3, "mid": 0.3, "top": 0.1}, confidence=0.3))
        self.assertIn("門檻 0.65，低於門檻，hook 不會給建議", out)                          # headline note
        self.assertEqual(out.count("信心低於門檻，hook 不會給建議"), 2)                    # and one line per platform
        _, out, _, _ = self.ask(Transport({"light": 0.01, "small": 0.02, "mid": 0.07, "top": 0.9}), task="another task")
        self.assertIn("Top：交回主模型自己做", out)
        _, out, _, _ = self.ask(Transport({"light": 0.9, "small": 0.05, "mid": 0.03, "top": 0.02}), task="third task")
        self.assertIn("Codex：這個等級（檔位）在此平台沒有設定模型", out)
        _, out, _, _ = self.ask(task="fourth task", platform="codex")
        self.assertNotIn("Claude Code：", out)

    def test_json_output_has_stable_fields_and_no_task_text(self):
        self.configure()
        code, out, _, _ = self.ask(json=True)
        data = json.loads(out)
        self.assertEqual(code, 0)
        for key in ("format_version", "manual", "request_id", "provider", "model", "tier", "confidence", "probabilities", "threshold",
                    "recommended", "latency_seconds", "input_tokens", "output_tokens", "estimated_usd"):
            self.assertIn(key, data)
        self.assertEqual((data["tier"], data["manual"], data["recommended"]["codex"]["action"]), ("Mid", True, "advise"))
        self.assertNotIn("ABC-1234", out)

    def test_title_and_role_are_sent_only_when_given(self):
        self.configure()
        _, _, _, transport = self.ask(title="invoice export", role="luna_worker")
        self.assertEqual(transport.bodies[0]["state"], {"task": SECRET_TASK, "title": "invoice export", "subagent_role": "luna_worker"})

    def test_task_can_come_from_stdin_but_not_both(self):
        self.configure()
        code, out, _, transport = self.ask(task=None, stdin=True, stdin_text="from standard input")
        self.assertEqual(code, 0); self.assertEqual(transport.bodies[0]["state"]["task"], "from standard input")
        code, _, err, _ = self.ask(task="both", stdin=True, stdin_text="x")
        self.assertEqual(code, 2); self.assertIn("擇一", err)

    def test_refusals_are_chinese_exit_2_and_never_call_the_classifier(self):
        self.configure(export=False)
        code, _, err, transport = self.ask()
        self.assertEqual(code, 2); self.assertIn("外送許可未開啟", err); self.assertIn("mrh ctrl set task_export on", err)
        self.assertEqual(transport.bodies, []); self.assertEqual(self.counts()["attempts"], 0)
        self.configure()
        for task, fragment in (("   ", "請提供任務內容"), (None, "請提供任務內容")):
            code, _, err, transport = self.ask(task=task)
            self.assertEqual(code, 2); self.assertIn(fragment, err); self.assertEqual(transport.bodies, [])
        code, _, err, _ = self.ask(task="x" * 70000)
        self.assertEqual(code, 2); self.assertIn("太長", err)

    def test_provider_failures_are_reported_in_chinese_and_recorded_without_retry(self):
        self.configure()
        code, _, err, transport = self.ask(Transport(status=401))
        self.assertEqual(code, 2); self.assertIn("Jev 金鑰無效", err); self.assertEqual(len(transport.bodies), 1)    # no retry
        self.assertEqual(self.counts()["advice"], 0)
        self.assertEqual(AdviceStore.read_stats(self.db, 0)["manual_classifications"], 1)

    def test_the_command_is_registered_on_the_real_cli_and_listed(self):
        self.assertIn("mrh classify", cli.COMMAND_LIST)
        args = cli.build_parser().parse_args(["classify", "do a thing", "--platform", "claude", "--json", "--title", "t"])
        self.assertEqual((args.task, args.platform, args.json, args.title, args.stdin), ("do a thing", "claude", True, "t", False))


if __name__ == "__main__":
    unittest.main()
