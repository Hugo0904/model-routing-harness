"""Statistics reset with a preview and a typed confirmation. Only the statistics database is touched."""
from __future__ import annotations

import time

from mrh.presentation.terminal import cell_width

LABEL = {"advice": "委派紀錄", "attempts": "分級器呼叫紀錄（除錯用）", "children": "子代理紀錄", "notices": "已提示過的通知"}


def cutoff_for(scope, days, now):
    """Rows at or after the returned epoch second are deleted."""
    if scope == "all":
        return 0.0
    if scope == "today":
        local = time.localtime(now)
        return time.mktime((local.tm_year, local.tm_mon, local.tm_mday, 0, 0, 0, 0, 0, -1))
    return now - days * 86400


def describe(scope, days):
    if scope == "all":
        return "全部紀錄"
    if scope == "today":
        return "今天（從今天 00:00 起）"
    return f"最近 {days:g} 天內"


def preview_text(preview, scope, days):
    delete, keep = preview["delete"], preview["keep"]
    span = ""
    if preview["first"] is not None:
        fmt = lambda t: time.strftime("%m/%d %H:%M", time.localtime(t))
        span = f"（{fmt(preview['first'])} 到 {fmt(preview['last'])}）"
    lines = [f"將要清除：{describe(scope, days)}{span}", ""]
    for table in delete:
        lines.append("  " + LABEL[table] + " " * (30 - cell_width(LABEL[table])) + f"刪除 {delete[table]:>5} 筆　保留 {keep[table]:>5} 筆")
    lines += ["", "只清除統計資料；設定檔、金鑰與其他功能不受影響。刪除後無法復原。"]
    return "\n".join(lines) + "\n"


def run(store, scope, days, *, yes, interactive, ask, out, now=None):
    """Returns (exit_code, deleted_rows). `ask(prompt)` returns the typed answer (or raises to cancel)."""
    now = time.time() if now is None else now
    preview = store.preview_since(cutoff_for(scope, days, now))
    total = sum(preview["delete"].values())
    out.write(preview_text(preview, scope, days))
    if not total:
        out.write("\n這個範圍內沒有資料，不需要清除。\n")
        return 0, 0
    if not yes:
        if not interactive:
            out.write("\n這只是預覽，沒有刪除任何東西。確定要刪除，請加上 --yes。\n")
            return 0, 0
        phrase = f"刪除 {total}"
        try:
            answer = ask(f"\n要確認的話，請輸入「{phrase}」（輸入其他任何內容都會取消）")
        except (EOFError, KeyboardInterrupt):
            answer = ""
        if " ".join(str(answer).split()) != phrase:
            out.write("\n輸入不符，沒有刪除任何東西。\n")
            return 0, 0
    deleted = store.delete_since(cutoff_for(scope, days, now))
    out.write(f"\n已刪除 {sum(deleted.values())} 筆。\n")
    return 0, sum(deleted.values())
