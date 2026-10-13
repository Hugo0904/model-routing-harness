"""Plain-language statistics for the control center. Product terms stay in English; explanations in Chinese."""
from __future__ import annotations

from mrh.presentation.terminal import cell_width

PLATFORM = {"claude": "Claude Code", "codex": "Codex", "gemini": "Gemini"}
REASON = {
    "explicit_model": "主模型已自己指定模型",
    "explicit_effort": "主模型已自己指定推理強度（effort）",
    "named_role": "專門角色、fork 或自訂子代理（不干預）",
    "advice_already_given": "同一任務 10 分鐘內已建議過（不重複攔）",
    "low_confidence": "分級信心低於門檻",
    "no_candidates_for_platform": "該等級沒有設定這個平台的模型",
    "classifier_timeout": "分級器逾時",
    "classifier_error": "分級器錯誤",
    "malformed_classification": "分級器回覆格式不對",
    "typesafe_http_402": "Jev 餘額不足",
    "typesafe_http_401": "Jev 金鑰無效",
    "typesafe_missing_credentials": "找不到 Jev 金鑰",
    "typesafe_http_429": "Jev 呼叫太頻繁（被限流）",
}
PROVIDER = {"jev": "Jev", "codex_subscription": "Codex 訂閱", "claude_subscription": "Claude 訂閱", "synthetic": "測試資料"}
JEV_USD_PER_INPUT_TOKEN = 0.042 / 1_000_000


def _pad(text, width):
    """Pad by terminal cells: a CJK character takes two."""
    return text + " " * max(1, width - cell_width(text))


def _usd(amount):
    return "$0" if amount == 0 else ("< $0.0001" if amount < 0.0001 else f"${amount:.4f}")


def _pct(part, whole):
    return f"{part * 100 // whole}%" if whole else "—"


def render(data, period_label, threshold=None):
    d = data["decisions"]
    advised, main, kept = d.get("advise", 0), d.get("continue_main", 0), d.get("preserve", 0)
    total = advised + main + kept
    lines = [f"MRH 統計 ─ {period_label}", ""]
    if not total:
        return "\n".join(lines + ["  這段期間沒有任何子代理委派經過 MRH。",
                                  "  （路由關閉、不在生效範圍，或主模型沒有派子代理時都不會有紀錄。）", ""])
    platforms = "、".join(f"{PLATFORM.get(p, p)} {sum(v.values())}" for p, v in sorted(data["per_platform"].items()))
    lines += [f"■ 子代理委派：共 {total} 次（{platforms}）",
              "    " + _pad("給建議，請主模型改用你設定的模型", 40) + f"{advised:>4} 次",
              "    " + _pad("判定為 Top，請主模型自己做", 40) + f"{main:>4} 次",
              "    " + _pad("沒有介入，原樣放行", 40) + f"{kept:>4} 次", ""]
    if data["kept_unchanged"]:
        lines.append("■ 沒有介入的原因")
        for reason, n in sorted(data["kept_unchanged"].items(), key=lambda x: -x[1]):
            label = REASON.get(reason, f"其他（{reason}）")
            if reason == "low_confidence" and threshold is not None:
                label += f"（門檻 {threshold:.2f}）"
            lines.append("    " + _pad(label, 52) + f"{n:>4} 次")
        lines.append("")
    followed = data["children_following_advice"]
    lines += ["■ 建議的效果",
              f"    給了 {advised} 次建議 → 主模型照建議改派 {followed} 次（{_pct(followed, advised)}）"]
    if followed:
        lines.append("    實際執行的模型：" + "、".join(f"{m} {n} 次" for m, n in sorted(data["followed_models"].items())))
    if advised > followed:
        lines.append("    沒照做的部分：主模型可能自己完成，或改派了清單以外的模型。")
    lines.append("")
    if data["tiers"]:
        order = ("Light", "Small", "Mid", "Top")
        lines += ["■ 分級結果（分級器判定的難度）",
                  "    " + " · ".join(f"{t} {data['tiers'][t]}" for t in order if t in data["tiers"]), ""]
    lines.append("■ 分級器用量")
    if not data["classifier_usage"]:
        lines.append("    沒有呼叫分級器。")
    for kind, u in sorted(data["classifier_usage"].items()):
        cost = ("估計 " + _usd(u["input_tokens"] * JEV_USD_PER_INPUT_TOKEN) if kind == "jev" else "使用訂閱額度")
        lines.append(f"    {PROVIDER.get(kind, kind)}：呼叫 {u['calls']} 次，輸入 {u['input_tokens']:,} tokens，{cost}")
    return "\n".join(lines + [""])
