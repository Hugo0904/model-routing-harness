"""Single-file HTML dashboard: flow, tier table, proportion bars. Reads settings + decision log; no network, no scripts."""
from __future__ import annotations

import html
import time

from mrh.adapters.providers import registry
from mrh.application import ctrl_logic as logic
from mrh.infrastructure import settings_v2 as v2
from mrh.presentation import stats_view

TIER_WHEN = {"Light": "機械性工作，一眼就能驗證結果", "Small": "需要閱讀，規格明確到足以檢查",
             "Mid": "實作加測試、診斷、量測", "Top": "跨系統設計、證據互相矛盾、在多種設計間取捨"}
TIER_COLOR = {"Light": "#4b50a8", "Small": "#6469c9", "Mid": "#a9aef5", "Top": "#e8eafc"}
PLATFORM_TITLE = {"claude": "CLAUDE CODE", "codex": "CODEX", "gemini": "GEMINI"}

CSS = """
:root{--bg:#23262e;--card:#252830;--edge:#3a3d4a;--text:#eceef6;--dim:#9a9eb0;--faint:#6d7184;--lav:#a9aef5;--pur:#6469c9;--track:#464a63}
@media (prefers-color-scheme:light){:root{--bg:#f3f4f9;--card:#fff;--edge:#d5d8e6;--text:#1d2030;--dim:#5b6076;--faint:#8a8fa5;--track:#dfe2f0}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 ui-monospace,SFMono-Regular,Menlo,Consolas,"PingFang TC","Noto Sans TC",monospace}
.wrap{max-width:1040px;margin:0 auto;padding:36px 20px 28px}
.chip{display:inline-block;border:1px solid var(--edge);border-radius:999px;padding:6px 18px;color:var(--dim);letter-spacing:.14em;font-size:12px}
h1{font-size:clamp(28px,5vw,46px);line-height:1.15;margin:20px 0 8px}.sub{color:var(--dim);margin:0 0 24px;max-width:860px}
.card{background:var(--card);border:1px solid var(--edge);border-radius:14px;padding:22px 24px;margin-bottom:18px}
.label{color:var(--faint);letter-spacing:.14em;font-size:12px;margin:0 0 14px}
.flow{display:grid;grid-template-columns:1fr auto 1fr auto 1fr auto 1fr;gap:10px;align-items:stretch;margin-bottom:22px}
.box{border:1px solid var(--edge);border-radius:12px;padding:14px 16px}.box.hl{border-color:var(--lav)}
.box b{display:block;font-size:17px}.box span{color:var(--dim);font-size:13px}.arrow{align-self:center;color:var(--faint)}
table{width:100%;border-collapse:collapse}th{color:var(--faint);font-weight:400;letter-spacing:.12em;font-size:12px;text-align:left;padding:8px 10px 10px}
td{padding:14px 10px;border-top:1px solid var(--edge);vertical-align:top}td.t{font-weight:700}td.w{color:var(--dim)}
tr.top td{background:rgba(120,125,230,.12)}tr.top td:first-child{border-left:3px solid var(--lav)}small{display:block;color:var(--lav);font-size:13px}
ul{margin:16px 0 0;padding:0;list-style:none}li{color:var(--text);padding:3px 0 3px 18px;position:relative}li:before{content:"•";color:var(--lav);position:absolute;left:0}
.cols{display:grid;grid-template-columns:1.1fr 1fr;gap:34px}@media(max-width:820px){.flow{grid-template-columns:1fr}.arrow{display:none}.cols{grid-template-columns:1fr}.box{min-width:0}}
.pcts{display:flex;font-size:14px;margin-bottom:6px}.stack{display:flex;height:50px;border-radius:8px;overflow:hidden;background:var(--track)}.stack i{display:block;border-right:3px solid var(--card)}
.legend{display:flex;flex-wrap:wrap;gap:18px;margin:14px 0 10px;color:var(--dim)}.legend em{font-style:normal;display:inline-block;width:14px;height:14px;border-radius:3px;margin-right:6px;vertical-align:-2px}
.bar{margin:0 0 20px}.bar .row{display:flex;justify-content:space-between;align-items:baseline;gap:10px}.bar .track{height:14px;border-radius:7px;background:var(--track);margin:6px 0 4px;overflow:hidden}.bar .fill{height:100%;background:var(--lav);border-radius:7px}
.bar .note{color:var(--faint);font-size:13px}.foot{display:flex;justify-content:space-between;color:var(--faint);font-size:12px;letter-spacing:.1em;border-top:1px solid var(--edge);padding-top:14px;margin-top:6px;gap:12px;flex-wrap:wrap}
.note2{color:var(--faint);font-size:12px;margin-top:10px}.empty{color:var(--dim);padding:18px 0}
"""


def _e(value):
    return html.escape(str(value))


def _pct(part, whole):
    return round(part * 100 / whole) if whole else 0


def _models(settings, tier, platform):
    pool = settings["policy"]["fixed"] if tier == "Top" else settings["policy"]["tiers"].get(tier, {})
    return logic.format_candidates(pool.get(platform, [])) if pool.get(platform) else "—"


def render(settings, data, period_label, generated=None):
    d, policy, c = data["decisions"], settings["policy"], settings["classifier"]
    advised, main, kept = d.get("advise", 0), d.get("continue_main", 0), d.get("preserve", 0)
    total = advised + main + kept
    followed = data["children_following_advice"]
    platforms = [p for p in ("claude", "codex", "gemini") if any(policy["tiers"].get(t, {}).get(p) for t in v2.TIERS) or policy["fixed"].get(p)]
    usage = data["classifier_usage"].get("jev")
    per_call = (usage["input_tokens"] * stats_view.JEV_USD_PER_INPUT_TOKEN / usage["calls"]) if usage and usage["calls"] else None
    jev_line = f"約 ${per_call:.5f} / 次" if per_call else "按 token 計費，約 $0.00002 / 次"

    rows = []
    for tier in ("Light", "Small", "Mid", "Top"):
        top = tier == "Top"
        claude = (settings["policy"]["fixed"] if tier == "Top" else settings["policy"]["tiers"].get(tier, {})).get("claude", [])
        price = stats_view.claude_price(claude[0]["model"]) if claude else "—"
        cells = "".join(f"<td>{_e(_models(settings, tier, p))}" + ("<small>留給主模型</small>" if top and policy["top_mode"] == "Main" and p == platforms[0] else "") + "</td>" for p in platforms)
        rows.append(f'<tr class="{"top" if top else ""}"><td class="t">{tier.lower()}</td>{cells}<td>{_e(price)}</td><td class="w">{_e(TIER_WHEN[tier])}</td></tr>')
    head = "".join(f"<th>{PLATFORM_TITLE[p]}</th>" for p in platforms)

    if total:
        tiers = [(t, data["tiers"].get(t, 0)) for t in ("Light", "Small", "Mid", "Top") if data["tiers"].get(t)]
        tsum = sum(n for _, n in tiers)
        pcts = "".join(f'<span style="width:{_pct(n, tsum)}%">{_pct(n, tsum)}%</span>' for _, n in tiers)
        stack = "".join(f'<i style="width:{_pct(n, tsum)}%;background:{TIER_COLOR[t]}"></i>' for t, n in tiers)
        legend = "".join(f'<span><em style="background:{TIER_COLOR[t]}"></em>{t.lower()} {n}</span>' for t, n in tiers)
        left = (f'<div class="pcts">{pcts}</div><div class="stack">{stack}</div><div class="legend">{legend}</div>'
                f'<div>{advised + main} 次由路由器處理（{advised} 次給建議、{main} 次留給主模型）· {kept} 次原樣放行</div>')
        def bar(title, part, whole, note):
            return (f'<div class="bar"><div class="row"><span>{_e(title)}</span><span>{_pct(part, whole)}%</span></div>'
                    f'<div class="track"><div class="fill" style="width:{_pct(part, whole)}%"></div></div><div class="note">{_e(note)}</div></div>')
        right = (bar("主模型照建議改派", followed, advised, f"{followed} / {advised} 次建議") +
                 bar("路由器有出手的比例", advised + main, total, f"{advised + main} / {total} 次委派") +
                 bar("信心足夠、可分級的比例", total - data["kept_unchanged"].get("low_confidence", 0), total,
                     f"信心門檻 {policy['threshold']:.2f}"))
    else:
        left = '<div class="empty">這段期間還沒有子代理委派經過 MRH。</div>'
        right = ""

    bullets = ["只有主模型沒指定模型、推理強度或專門角色時，才給建議",
               f"分級信心低於 {policy['threshold']:.2f}，原樣放行，沿用主模型的選擇",
               "Top 難度留給主模型，路由器只會降低成本，不會把成本墊高" if policy["top_mode"] == "Main" else "Top 難度建議改用你設定的 Top 清單",
               "失敗不擋工作：沒金鑰、沒網路、回答怪異，都照原樣放行"]
    stamp = generated or time.strftime("%Y-%m-%d")
    return f"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>MRH 委派路由報表</title><style>{CSS}</style></head><body><div class="wrap">
<div class="chip">MRH · DELEGATION ROUTER</div><h1>Route the task, not the session.</h1>
<p class="sub">派子代理時，hook 先請 {_e(registry.LABELS[c["provider"]])} 判斷這份任務需要哪一級，再從你設定的表格選模型。主模型保留最難的判斷。</p>
<div class="card"><p class="label">HOW A DELEGATION IS ROUTED</p>
<div class="flow"><div class="box"><b>主模型</b><span>自己決定要不要派子代理<br>並寫下任務說明</span></div><div class="arrow">→</div>
<div class="box hl"><b>{_e(c["model"])}</b><span>一道選擇題<br>{_e(jev_line)} · 約 0.5 秒</span></div><div class="arrow">→</div>
<div class="box"><b>難度</b><span>light · small · mid · top</span></div><div class="arrow">→</div>
<div class="box"><b>模型</b><span>依你設定的表格<br>各工具各自一份</span></div></div>
<table><tr><th>TIER</th>{head}<th>$/MTOK IN/OUT</th><th>WHEN</th></tr>{"".join(rows)}</table><div class="note2">價格為 Claude 官方牌價（美元／百萬 token，輸入／輸出），僅供參考；Codex 以訂閱額度計，不列價格。</div><ul>{"".join(f"<li>{_e(b)}</li>" for b in bullets)}</ul></div>
<div class="card"><p class="label">WHERE {total} DELEGATIONS WENT · {_e(period_label)}</p><div class="cols"><div>{left}</div><div>{right}</div></div></div>
<div class="foot"><span>NUMBERS FROM THE ROUTER'S DECISION LOG · {_e(stamp)}</span><span>MRH</span></div></div></body></html>"""
