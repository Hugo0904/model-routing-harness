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
    "source_changed_during_read": "讀取期間來源有變動，保留原快照與時間",
}


def render(summary, days):
    lines = ["子代理用量收集（只讀本機紀錄檔，不連網、不花錢）", "",
             f"範圍：最近 {days} 天、已記錄的子代理，共 {summary['candidates']} 個",
             f"  這次保存快照      {summary['collected']:>4} 個（含更新 {summary.get('updated', 0)} 個）",
             f"  來源未變，不重讀  {summary.get('unchanged', 0):>4} 個",
             f"  最近變動，下次再收  {summary['running']:>2} 個",
             f"  找不到紀錄檔      {summary['not_found']:>4} 個",
             f"  讀不懂            {summary['unreadable'] + summary['other']:>4} 個"]
    reasons = {}
    for item in summary["details"]:
        if item["reason"] != "transcript_changed_within_10_minutes":
            reason = item["reason"]
            label = ("用量缺失或格式不合法：" + reason.split(":", 1)[1] if reason.startswith("invalid_usage:") else
                     "用量分量互相矛盾：" + reason.split(":", 1)[1] if reason.startswith("inconsistent_usage:") else REASON.get(reason, reason))
            key = (stats_view.PLATFORM.get(item["platform"], item["platform"]), label)
            reasons[key] = reasons.get(key, 0) + 1
    if reasons:
        lines += ["", "沒收到的原因："] + [f"  {platform}：{reason}  {n} 個" for (platform, reason), n in sorted(reasons.items())]
    lines += ["", "十分鐘未變只表示可讀快照，不代表已結束；讀取失敗會保留舊快照。", "看結果：mrh stats（「子代理實際用量」段落）"]
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
