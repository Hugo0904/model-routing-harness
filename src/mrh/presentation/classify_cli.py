"""`mrh classify`: ask the classifier about one task. Nothing is delegated and the task text is never stored."""
from __future__ import annotations

import json
from pathlib import Path

from mrh.application import classify
from mrh.application import ctrl_logic as logic
from mrh.infrastructure import settings_v2 as v2
from mrh.presentation import stats_view
from mrh.presentation.terminal import cell_width

MAX_TASK_BYTES = 60_000       # the Jev request body is capped at 64 KB including its fixed wording
BAR = 20
HINT = {
    "empty_task": "請提供任務內容：mrh classify \"任務內容\"，或用 --stdin 從標準輸入讀取。",
    "export_not_permitted": "外送許可未開啟，所以不會把任務文字送出。要開啟請執行：mrh ctrl set task_export on",
    "typesafe_missing_credentials": "找不到 Jev 金鑰。請執行：mrh key set jev",
    "typesafe_invalid_task": "任務內容無法送出（太長或格式不對）。",
    "classifier_timeout": "分級逾時，沒有結果（不會自動重試）。",
    "malformed_classification": "分級器回覆的格式不對，沒有結果。",
}
ACTION = {
    "advise": lambda c: logic.format_candidates(c["candidates"]),
    "continue_main": lambda c: "Top：交回主模型自己做",
}
REASON_TEXT = {
    "low_confidence": "信心低於門檻，hook 不會給建議（沿用主模型的選擇）",
    "no_candidates_for_platform": "這個等級在此平台沒有設定模型",
}


def _fail(stderr, reason):
    stderr.write("mrh: " + (HINT.get(reason) or (stats_view.REASON.get(reason) and stats_view.REASON[reason] + f"（{reason}）") or f"分級失敗（{reason}）") + "\n")
    return 2


def _bar(fraction):
    filled = round(BAR * fraction)
    return "█" * filled + "░" * (BAR - filled)


def render(result, task_chars):
    label = stats_view.PROVIDER.get(result["provider"], result["provider"])
    lines = ["MRH 顧問分級（只問，不派工）", f"分級器：{label}" + (f" · {result['model']}" if result["model"] else ""), ""]
    gate = "hook 會給建議" if result["confidence"] >= result["threshold"] else "低於門檻，hook 不會給建議"
    lines.append(f"難度：{result['tier'].lower()}　信心 {result['confidence']:.2f}（門檻 {result['threshold']:.2f}，{gate}）")
    if result["probabilities"]:
        for tier in ("Light", "Small", "Mid", "Top"):
            p = result["probabilities"][tier]
            lines.append(f"  {tier.lower():<6}{_bar(p)} {p * 100:>3.0f}%")
    lines += ["", "各平台的建議（照目前設定）："]
    for platform, rec in result["recommended"].items():
        text = ACTION[rec["action"]](rec) if rec["action"] in ACTION else REASON_TEXT.get(rec["reason"], rec["reason"])
        lines.append(f"  {stats_view.PLATFORM.get(platform, platform)}：{text}")
    facts = []
    if result["latency_seconds"] is not None:
        facts.append(f"耗時 {result['latency_seconds']:.1f} 秒")
    if result["input_tokens"] is not None:
        facts.append(f"輸入 {result['input_tokens']:,} tokens")
    if result["estimated_usd"] is not None:
        facts.append(f"估計 {stats_view._usd(result['estimated_usd'])}")
    elif result["provider"] != "jev":
        facts.append("使用訂閱額度")
    lines += ["", "　".join(facts) if facts else "（分級器沒有回報耗時與用量）",
              "這是手動查詢：不算進派工統計，費用照算；任務文字不會被保存。"]
    return "\n".join(lines) + "\n"


def main(args, *, stdin, stdout, stderr, classifier_factory=None, clock=None):
    from mrh.advisory.store import AdviceStore
    import time
    try:
        path = v2.resolve_settings_path(args.settings)
        settings = v2.read(path)
    except Exception:
        stderr.write("mrh: 找不到設定檔：請用 --settings 指定、設定 MRH_SETTINGS，或先完成安裝\n")
        return 2
    if args.stdin and args.task is not None:
        stderr.write("mrh: 任務內容請擇一：直接寫在指令後面，或用 --stdin。\n"); return 2
    task = stdin.read(MAX_TASK_BYTES + 1) if args.stdin else args.task
    if isinstance(task, str) and len(task.encode()) > MAX_TASK_BYTES:
        stderr.write("mrh: 任務內容太長（上限約 60 KB）。\n"); return 2
    platforms = (args.platform,) if args.platform else ("claude", "codex")
    extras = {k: v for k, v in (("title", args.title), ("role", args.role)) if v}
    try:
        result = classify.run(settings, task, store=AdviceStore(Path(path).parent / "advice.sqlite3"), platforms=platforms,
                              extras=extras, classifier_factory=classifier_factory, clock=clock or time.time)
    except classify.ClassifyError as exc:
        return _fail(stderr, exc.reason)
    if args.json:
        stdout.write(json.dumps({**result, "format_version": 1, "manual": True}, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    else:
        stdout.write(render(result, len(task)))
    return 0
