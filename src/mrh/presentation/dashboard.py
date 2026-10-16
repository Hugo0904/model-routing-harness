"""Terminal dashboard: rounded cards, routing flow, tier table, proportion bars. 80-120 columns, colour optional."""
from __future__ import annotations

import re
import time

from mrh.adapters.providers import registry
from mrh.application import ctrl_logic as logic
from mrh.presentation import stats_view
from mrh.presentation.report_html import TIER_WHEN
from mrh.presentation.terminal import cell_width

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
RGB = {"border": (74, 78, 98), "dim": (154, 158, 176), "faint": (109, 113, 132), "lav": (169, 174, 245), "text": (236, 238, 246)}
TIERS = ("Light", "Small", "Mid", "Top")
PLATFORM_TITLE = {"claude": "CLAUDE CODE", "codex": "CODEX", "gemini": "GEMINI"}


def vis(text):
    return cell_width(_ANSI.sub("", text))


def pad(text, width):
    return text + " " * max(0, width - vis(text))


def clip(text, width):
    """Truncate to `width` terminal cells (plain text only)."""
    if cell_width(text) <= width:
        return text
    out, used = "", 0
    for ch in text:
        w = cell_width(ch)
        if used + w > width - 1:
            break
        out, used = out + ch, used + w
    return out + "…"


def wrap(text, width):
    lines, line, used = [], "", 0
    for ch in text:
        w = cell_width(ch)
        if used + w > width:
            lines.append(line); line, used = "", 0
        line, used = line + ch, used + w
    return lines + [line] if line else lines


class Paint:
    def __init__(self, on):
        self.on = on

    def __call__(self, text, tone, bold=False):
        if not self.on or not text:
            return text
        r, g, b = RGB[tone]
        return f"\x1b[{'1;' if bold else ''}38;2;{r};{g};{b}m{text}\x1b[0m"


def card(title, body, width, p, tone="border"):
    inner = width - 4
    top = p("╭─ ", tone) + p(title, "faint") + p(" " + "─" * max(0, width - 5 - cell_width(title)) + "╮", tone)
    rows = [p("│", tone) + " " + pad(line, inner) + " " + p("│", tone) for line in body]
    return [top, *rows, p("╰" + "─" * (width - 2) + "╯", tone)]


def box(title, descs, width, p):
    tone = "border"
    inner = width - 4
    rows = [p(clip(title, inner), "text", True), *[p(clip(d, inner), "dim") for d in descs]]
    return [p("╭" + "─" * (width - 2) + "╮", tone),
            *[p("│", tone) + " " + pad(r, inner) + " " + p("│", tone) for r in rows],
            p("╰" + "─" * (width - 2) + "╯", tone)]


def _flow(settings, per_call, inner, p, actual=(), gears=False):
    bw = (inner - 3 * 3) // 4
    # `actual`: captions from most to least detailed; the first one that fits the box is shown.
    caption = next((c for c in actual if cell_width(c) <= bw - 4), None) or "一道選擇題"
    boxes = [("主模型", ["自己決定派工", "並寫下任務說明"]),
             (settings["classifier"]["model"], [caption, per_call]),
             *([("難度分數", ["0～3，依四級機率", "加權算出"]), ("檔位", ["分數落在哪一檔", "就用哪一檔"])] if gears else
               [("難度", ["light · small", "mid · top"]), ("模型", ["依你設定的表格", "各工具各一份"])])]
    arrow_w = 3
    bw = (inner - arrow_w * 3) // 4
    cols = [box(t, d, bw, p) for t, d in boxes]
    lines = []
    for row in range(5):
        parts = []
        for i, col in enumerate(cols):
            parts.append(col[row])
            if i < 3:
                parts.append(p(" → ", "faint") if row == 2 else "   ")
        lines.append(pad("".join(parts), inner))
    return lines


def _table(settings, inner, p):
    policy = settings["policy"]
    platforms = [x for x in ("claude", "codex", "gemini") if any(policy["tiers"].get(t, {}).get(x) for t in ("Light", "Small", "Mid")) or policy["fixed"].get(x)] or ["claude"]

    top_main = policy["top_mode"] == "Main"

    def models(tier, plat):
        if tier == "Top" and top_main:
            return "主模型自己做"
        pool = policy["fixed"] if tier == "Top" else policy["tiers"].get(tier, {})
        return logic.format_candidates(pool.get(plat, [])) if pool.get(plat) else "—"

    widths = [max(cell_width(PLATFORM_TITLE[x]), *(cell_width(models(t, x)) for t in TIERS)) + 2 for x in platforms]
    show_price = "claude" in platforms
    lead, tier_w, price_w = 2, 7, 15
    fixed = lead + tier_w + sum(widths) + (price_w if show_price else 0)
    when_w = max(10, inner - fixed)
    head = pad("", lead) + pad(p("TIER", "faint"), tier_w) + "".join(pad(p(PLATFORM_TITLE[x], "faint"), w) for x, w in zip(platforms, widths))
    head += (pad(p("$/MTOK IN/OUT", "faint"), price_w) if show_price else "") + p("WHEN", "faint")
    lines = [head, p("─" * inner, "border")]
    for tier in TIERS:
        top = tier == "Top"
        claude = (policy["fixed"] if top else policy["tiers"].get(tier, {})).get("claude", [])
        row = p("▌ ", "lav") if top else "  "
        row += pad(p(tier.lower(), "text", True), tier_w)
        for x, w in zip(platforms, widths):
            cell = models(tier, x)
            row += pad(p(cell, "lav" if top and top_main else "text" if cell != "—" else "faint"), w)
        if show_price:
            row += pad(p(stats_view.claude_price(claude[0]["model"]) if claude else "—", "dim"), price_w)
        row += p(clip(TIER_WHEN[tier], when_w), "dim")
        lines.append(row)
        lines.append(p("─" * inner, "border") if not top else "")
    return lines[:-1]


def _gear_table(settings, inner, p):
    """Gears mode: one row per gear, easiest first, with the difficulty-score range it covers."""
    from mrh.infrastructure import settings_v2 as v2
    policy = settings["policy"]
    gears = policy["gears"]
    platforms = [x for x in ("claude", "codex", "gemini") if any(g.get("candidates", {}).get(x) for g in gears)] or ["claude"]

    def cell(gear, plat):
        if gear.get("main"):
            return "主模型自己做"
        return logic.format_candidates(gear["candidates"].get(plat, [])) if gear["candidates"].get(plat) else "—"

    widths = [max(cell_width(PLATFORM_TITLE[x]), *(cell_width(cell(g, x)) for g in gears)) + 2 for x in platforms]
    show_price = "claude" in platforms
    lead, tier_w, price_w = 2, 7, 15
    when_w = max(10, inner - (lead + tier_w + sum(widths) + (price_w if show_price else 0)))
    head = pad("", lead) + pad(p("GEAR", "faint"), tier_w) + "".join(pad(p(PLATFORM_TITLE[x], "faint"), w) for x, w in zip(platforms, widths))
    head += (pad(p("$/MTOK IN/OUT", "faint"), price_w) if show_price else "") + p("WHEN", "faint")
    lines = [head, p("─" * inner, "border")]
    for number, gear in enumerate(gears, 1):
        end = gears[number]["from"] if number < len(gears) else v2.SCORE_MAX
        main = bool(gear.get("main"))
        row = (p("▌ ", "lav") if main else "  ") + pad(p(f"g{number}", "text", True), tier_w)
        for x, w in zip(platforms, widths):
            text = cell(gear, x)
            row += pad(p(text, "lav" if main else "text" if text != "—" else "faint"), w)
        if show_price:
            first = gear.get("candidates", {}).get("claude", [])
            row += pad(p(stats_view.claude_price(first[0]["model"]) if first else "—", "dim"), price_w)
        row += p(clip(f"難度分數 {gear['from']:g}～{end:g}", when_w), "dim")
        lines += [row, p("─" * inner, "border")]
    return lines[:-1]


def _pct_row(parts, width):
    total = sum(n for _, n in parts) or 1
    cells, used = [], 0
    for i, (_, n) in enumerate(parts):
        size = width - used if i == len(parts) - 1 else max(1 if n else 0, round(n * width / total))
        size = max(0, min(size, width - used)); used += size
        cells.append(size)
    row, pos = [" "] * width, 0
    for (tier, n), size in zip(parts, cells):
        label = f"{round(n * 100 / total)}%"
        if size >= len(label):
            for k, ch in enumerate(label):
                row[pos + k] = ch
        pos += size
    return "".join(row)


def _where(data, policy, inner, p, color):
    d = data["decisions"]
    advised, main, kept = d.get("advise", 0), d.get("continue_main", 0), d.get("preserve", 0)
    total = advised + main + kept
    if not total:
        return [p("這段期間還沒有子代理委派經過 MRH。", "dim"),
                *[p(clip(note, inner), "faint") for note in stats_view.accounting_notes(data)]], 0
    skill = stats_view.skill_roles(data)
    skill_total = sum(skill.values())
    parts = [(t, data["tiers"][t]) for t in TIERS if data["tiers"].get(t)] + ([("Skill", skill_total)] if skill_total else [])
    wide = inner >= 96
    left_w = (inner * 11) // 20 if wide else inner
    right_w = inner - left_w - 4 if wide else inner
    bw = left_w
    left = [p(_pct_row(parts, bw), "text"), stats_view.stacked_bar(parts, bw, color)]
    legend = "  ".join(f"{stats_view._swatch(t, color)} {t.lower()} {n}" for t, n in parts)
    left += ["", legend, "", p(f"{advised + main} 次由路由器處理（{advised} 次給建議、{main} 次留給主模型）", "text"),
             *([p(f"{skill_total} 次由 Router skill 自己選模型派工", "text")] if skill_total else []),
             p(f"{kept - skill_total} 次原樣放行", "dim")]
    if data.get("reissues"):
        left += ["", p(f"另有 {data['reissues']} 次是主模型照建議重派的後續呼叫（不重複計算）", "faint")]
    kept_reasons = stats_view.kept_without_skill(data)
    if kept_reasons:
        left.append("")
        for reason, n in sorted(kept_reasons.items(), key=lambda x: -x[1])[:4]:
            left.append(p("· " + clip(stats_view.REASON.get(reason, reason), left_w - 8) + f"  {n}", "dim"))
    followed = data["children_following_advice"]
    left += [p(clip(note, left_w), "faint") for note in stats_view.accounting_notes(data)]

    def bar(title, part, whole, *notes):
        pct = part * 100 // whole if whole else 0
        pb = stats_view.progress_bar(pct, right_w, color)
        return [pad(p(title, "text"), right_w - len(f"{pct}%")) + p(f"{pct}%", "text"), pb,
                *[p(clip(n, right_w), "faint") for n in notes if n], ""]
    role_list = "、".join(f"{r} {n}" for r, n in sorted(skill.items(), key=lambda x: -x[1]))
    right = bar("有改派（MRH＋skill）", *stats_view.rerouted(data),
                f"照 MRH 建議 {followed} / {advised} 次 · skill 自選 {skill_total} 次", role_list)
    if data.get("children_started"):
        matched, started = stats_view.tier_model_children(data, policy)
        right += bar("子代理用了分級表的模型", matched, started, f"{matched} / {started} 個子代理，其餘沿用主模型或其他模型")
    usage = data.get("usage") or {}
    if usage.get("recorded"):                                      # one bar: how much real usage is collected, and the converted saving
        saved = [sv for sv in (usage.get("saving") or {}).values() if sv["children"]]
        right += bar("子代理用量已收集", usage["collected"], usage["recorded"],
                     f"{usage['collected']} / {usage['recorded']} 個子代理" + ("（mrh usage collect）" if usage["uncollected"] else ""),
                     f"節省（換算）{stats_view._usd(sum(sv['usd'] for sv in saved))}" if saved else "")
    conf = data.get("confidence") or {}
    for key, label in (("last_24h", "24 小時內"), ("total", "總平均")):
        c = conf.get(key) or {}
        if c.get("avg") is None:
            right += [p(f"平均信心度 · {label}：沒有分級紀錄", "faint"), ""]
        else:
            right += bar(f"平均信心度 · {label}", round(c["avg"] * 100), 100,
                         f"{c['avg']:.2f}（{c['n']} 次分級）" + (f" · 門檻 {policy['threshold']:.2f}" if key == "total" else ""))
    if not wide:
        return left + [""] + right, total
    height = max(len(left), len(right))
    left += [""] * (height - len(left)); right += [""] * (height - len(right))
    return [pad(a, left_w) + "    " + b for a, b in zip(left, right)], total


def render(settings, data, period_label, width=100, color=False, today=None):
    width = max(80, min(120, width))
    p, inner = Paint(color), max(76, min(120, width)) - 4
    c = settings["classifier"]
    usage = data["classifier_usage"].get("jev")
    per_call = (f"已回報 ${usage['input_tokens'] * stats_view.JEV_USD_PER_INPUT_TOKEN / usage['calls']:.5f}/次"
                if usage and usage["calls"] and not usage.get("usage_unknown_calls") else "呼叫成本尚未完整觀測")
    chip_text = "MRH · DELEGATION ROUTER"
    chip = [p("╭" + "─" * (cell_width(chip_text) + 4) + "╮", "border"), p("│", "border") + "  " + p(chip_text, "dim") + "  " + p("│", "border"),
            p("╰" + "─" * (cell_width(chip_text) + 4) + "╯", "border")]
    status = ("開啟" if settings["enabled"] and settings["task_export_permitted"] else "關閉")
    sub = f"派子代理時，hook 先請 {registry.LABELS[c['provider']]} 判斷這份任務需要哪一級，再從你設定的表格選模型。主模型保留最難的判斷。（路由：{status}）"
    notice = stats_view.version_change_note(data)
    out = [*chip, "", p("Route the task, not the session.", "text", True), *[p(l, "dim") for l in wrap(sub, width - 2)], ""]
    if notice:
        out += [p("！" + clip(notice, width - 4), "lav", True), ""]
    policy = settings["policy"]
    bullets = ["只有主模型沒指定模型、推理強度或專門角色時，才給建議",
               f"分級信心低於 {policy['threshold']:.2f}，原樣放行，沿用主模型的選擇",
               "Top 難度留給主模型，路由器只會降低成本，不會把成本墊高" if policy["top_mode"] == "Main" else "Top 難度建議改用你設定的 Top 清單",
               "失敗不擋工作：沒金鑰、沒網路、回答怪異，都照原樣放行"]
    version, latency = stats_view.main_version(data), data.get("classifier_latency") or {}
    seconds = f"{latency['avg']:.1f} 秒" if latency.get("n") else None
    short = version[4:] if version and version.startswith("jev-") else version
    actual = tuple(c for c in ((f"實際 {version} · {seconds}" if version and seconds else f"實際 {version}" if version else None),
                               (f"{short} · {seconds}" if short and seconds else short),
                               seconds) if c)
    gears_on = settings["policy"].get("mode") == "gears" and settings["policy"].get("gears")
    if gears_on:
        bullets[2] = f"檔位模式：Jev 的四級機率換算成 0～3 的難度分數，落在哪一檔就用哪一檔（共 {len(settings['policy']['gears'])} 檔）；最高檔是上限"
    body = [*_flow(settings, per_call, inner, p, actual, bool(gears_on)), "", *(_gear_table(settings, inner, p) if gears_on else _table(settings, inner, p)),
            "", *[p("• ", "lav") + clip(b, inner - 2) for b in bullets]]
    out += card("HOW A DELEGATION IS ROUTED", body, width, p) + [""]
    where, total = _where(data, policy, inner, p, color)
    out += card(f"WHERE {total} DELEGATIONS WENT · {period_label}", where, width, p) + [""]
    out.append(p(f"NUMBERS FROM THE ROUTER'S DECISION LOG · {today or time.strftime('%Y-%m-%d')}", "faint"))
    return "\n".join(out) + "\n"
