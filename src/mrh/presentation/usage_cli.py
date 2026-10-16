"""`mrh usage collect`: gather what each recorded sub-agent actually used from the local transcript files."""
from __future__ import annotations

import json
import time
from pathlib import Path

from mrh.advisory import usage_collect
from mrh.infrastructure import settings_v2 as v2
from mrh.presentation import stats_view

REASON = {
    "claude_transcript_not_found": "找不到 Claude 的子代理紀錄檔",
    "codex_rollout_not_found": "找不到 Codex 的子代理紀錄檔",
    "transcript_changed_within_10_minutes": "紀錄檔 10 分鐘內還有變動（可能還在執行）",
    "no_usage_records": "紀錄檔裡沒有用量資料",
    "read_error": "紀錄檔讀取失敗",
    "too_large": "紀錄檔太大（上限 256 MB）",
    "platform_not_supported": "這個平台不支援收集",
}


def render(summary, days):
    lines = ["子代理用量收集（只讀本機紀錄檔，不連網、不花錢）", "",
             f"範圍：最近 {days} 天、已記錄但還沒收集的子代理，共 {summary['candidates']} 個",
             f"  這次新收集        {summary['collected']:>4} 個",
             f"  仍在執行，下次再收  {summary['running']:>2} 個",
             f"  找不到紀錄檔      {summary['not_found']:>4} 個",
             f"  讀不懂            {summary['unreadable'] + summary['other']:>4} 個"]
    reasons = {}
    for item in summary["details"]:
        if item["reason"] != "transcript_changed_within_10_minutes":
            key = (stats_view.PLATFORM.get(item["platform"], item["platform"]), REASON.get(item["reason"], item["reason"]))
            reasons[key] = reasons.get(key, 0) + 1
    if reasons:
        lines += ["", "沒收到的原因："] + [f"  {platform}：{reason}  {n} 個" for (platform, reason), n in sorted(reasons.items())]
    lines += ["", "看結果：mrh stats（「子代理實際用量」段落）"]
    return "\n".join(lines) + "\n"


def main(args, *, stdin, stdout, stderr, now=None, **roots):
    from mrh.advisory.store import AdviceStore
    try:
        path = v2.resolve_settings_path(args.settings)
        v2.read(path)
    except Exception:
        stderr.write("mrh: 找不到設定檔：請用 --settings 指定、設定 MRH_SETTINGS，或先完成安裝\n")
        return 2
    db = Path(path).parent / "advice.sqlite3"
    if not db.exists():
        stdout.write("還沒有任何統計資料，沒有可收集的子代理。\n")
        return 0
    days = args.days if args.days is not None else 30
    if days <= 0:
        stderr.write("mrh: --days 必須大於 0\n")
        return 2
    summary = usage_collect.collect(AdviceStore(db), time.time() if now is None else now, days=days, **roots)
    stdout.write(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n" if args.json else render(summary, days))
    return 0
