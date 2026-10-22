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


def _usd(value):
    return "未知" if value is None else f"US${value:,.4f}"


def _secs(value):
    return "未知" if value is None else f"{value:.1f} 秒"


def render_overhead(report, days):
    r = report
    share = "未知" if r["advised_share"] is None else f"{r['advised_share'] * 100:.0f}%"
    lines = ["攔下重派的開銷（只讀本機紀錄，不連網、不花錢）", "",
             f"範圍：最近 {days:g} 天",
             f"  委派總數            {r['delegations']:>4} 次",
             f"  MRH 給了建議        {r['advised']:>4} 次（{share}）",
             f"  其中主模型照辦重派  {r['reissues']:>4} 次；沒重派 {r['advised_not_reissued']} 次", "",
             "每次重派的代價：",
             f"  等待：分級器讓委派多等的時間  中位數 {_secs(r['classifier_seconds_median'])}，合計 {_secs(r['classifier_seconds_total'])}",
             f"  等待：攔下到主模型重派        中位數 {_secs(r['deny_to_reissue_seconds_median'])}",
             f"  分級費用（Jev）               合計 {_usd(r['classifier_usd_total'])}",
             f"  主模型多跑的那一輪（輸入端）  合計 {_usd(r['main_extra_input_usd_total'])}（可算 {r['main_extra_known']} / {r['reissues']} 次）", "",
             "和省下的錢相比：",
             f"  子代理省下（換算，輸入端）    合計 {_usd(r['saving_usd_total'])}（可算 {r['saving_known']} / {r['reissues']} 次）"]
    if r["compared"]:
        lines += [f"  兩邊都算得出的 {r['compared']} 次：省 {_usd(r['compared_saving_usd'])}，開銷 {_usd(r['compared_overhead_usd'])}，"
                  f"淨賺 {_usd(r['compared_saving_usd'] - r['compared_overhead_usd'])}；省得比開銷多的有 {r['compared_net_positive']} 次"]
    else:
        lines += ["  還沒有任何一次兩邊都算得出來，不能判斷划不划算。"]
    lines += ["", "注意：", "  ‧ 主模型多跑的那一輪只含輸入端（Claude 的紀錄沒有最終輸出量），所以是下限；Codex 沒有逐請求的父層用量，不計入（顯示未知，不當 0）。",
              "  ‧ 金額是依官方價格表換算，不是帳單；沒收集用量的子代理請先執行 mrh usage collect。",
              "  ‧ 這只量成本，不量品質。"]
    return "\n".join(lines) + "\n"


def overhead_main(args, *, stdout, stderr, now=None, claude_root=None):
    from mrh.advisory import overhead
    try:
        path = v2.resolve_settings_path(args.settings)
        v2.read(path)
    except Exception:
        stderr.write("mrh: 找不到設定檔：請用 --settings 指定、設定 MRH_SETTINGS，或先完成安裝\n")
        return 2
    db = Path(path).parent / "advice.sqlite3"
    if not db.exists():
        stdout.write("還沒有任何統計資料。\n")
        return 0
    days = args.days if args.days is not None else 30
    if days <= 0:
        stderr.write("mrh: --days 必須大於 0\n")
        return 2
    current = time.time() if now is None else now
    report = overhead.build(db, current - days * 86400, claude_root=claude_root)
    stdout.write(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n" if args.json else render_overhead(report, days))
    return 0


def main(args, *, stdin, stdout, stderr, now=None, **roots):
    if getattr(args, "usage_action", "collect") == "overhead":
        return overhead_main(args, stdout=stdout, stderr=stderr, now=now, claude_root=roots.get("claude_root"))
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
