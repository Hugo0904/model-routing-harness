"""`mrh ctrl`: one place for every setting. Interactive menu, `show`, and scripted `set`."""
from __future__ import annotations

import json
import os
import time

from mrh.adapters.providers import registry
from mrh.application import ctrl_logic as logic
from mrh.infrastructure import secrets, settings_v2 as v2
from mrh.infrastructure.settings_schema import SettingsError
from mrh.presentation.menu import Back, Cancelled, Menu
from mrh.presentation import report_html, stats_view
from mrh.presentation.terminal import cell_width, sanitize_text, terminal_width

TOP_HELP = {"Main": "Top 難度由主模型自己做", "Fixed": "Top 難度建議改用「Top 清單」裡的模型"}


def key_state(name="jev", secrets_module=secrets):
    return {"keychain": secrets_module.is_set(name), "environment": bool(os.environ.get(secrets.ENV_VARS[name]))}


def snapshot(settings, path, secrets_module=secrets):
    """Everything `show` prints; contains no secret values."""
    return {"settings_path": str(path), "revision": settings["revision"], "enabled": settings["enabled"],
            "task_export_permitted": settings["task_export_permitted"], "classifier": settings["classifier"],
            "api_key": {"jev": key_state("jev", secrets_module)},
            "threshold": settings["policy"]["threshold"], "top_mode": settings["policy"]["top_mode"],
            "applies_to": v2.effective_roots(settings)[0], "applies_to_source": v2.effective_roots(settings)[1],
            "tiers": settings["policy"]["tiers"],
            "fixed": settings["policy"]["fixed"],
            "generic_roles": settings["policy"].get("generic_roles", v2.DEFAULT_GENERIC_ROLES),
            "retention_days": v2.retention_days(settings)}


def _row(label, text):
    return "  " + label + " " * max(1, 14 - cell_width(label)) + text


def render(snap, width=100):
    c = snap["classifier"]
    key = snap["api_key"]["jev"]
    key_text = "已存在 Keychain" if key["keychain"] else "已設在環境變數" if key["environment"] else "尚未設定（請執行：mrh key set jev）"
    on = snap["enabled"] and snap["task_export_permitted"]
    lines = ["MRH  /  控制中心", "",
             _row("路由", "開啟   每次派子代理，任務內容會送給分級器判斷難度" if on else "關閉   完全不碰子代理委派"),
             _row("分級器", f"{registry.LABELS[c['provider']]} · {c['model']} · 逾時 {c['timeout_seconds']:g} 秒"),
             _row("Jev 金鑰", key_text),
             _row("信心門檻", f"分級信心度達 {snap['threshold']:.2f} 以上才給建議"),
             _row("Top 難度", f"{snap['top_mode']}（{TOP_HELP[snap['top_mode']]}）"),
             _row("適用範圍", (", ".join(snap["applies_to"]) or "（無）") +
                  ("" if snap["applies_to_source"] == "settings" else f"   （清單存放於 {snap['applies_to_source']}）")),
             ""]
    platforms = [p for p in ("claude", "codex", "gemini") if any(snap["tiers"].get(t, {}).get(p) for t in v2.TIERS) or snap["fixed"].get(p)] or ["claude", "codex"]
    widths = [max(14, max(cell_width(logic.format_candidates(snap["tiers"].get(t, {}).get(p, [])) if t != "Top" else logic.format_candidates(snap["fixed"].get(p, []))) for t in (*v2.TIERS, "Top")) + 2) for p in platforms]
    pad = lambda text, w: text + " " * max(1, w - cell_width(text))
    lines.append("  候選模型（依優先順序，第一個最優先）")
    lines.append("    " + pad("難度", 8) + "".join(pad(stats_view.PLATFORM.get(p, p).upper(), w) for p, w in zip(platforms, widths)) + "適用情境")
    for tier in (*v2.TIERS, "Top"):
        pool = snap["fixed"] if tier == "Top" else snap["tiers"].get(tier, {})
        cells = "".join(pad(logic.format_candidates(pool.get(p, [])) if pool.get(p) else "—", w) for p, w in zip(platforms, widths))
        lines.append("    " + pad(tier.lower(), 8) + cells + report_html.TIER_WHEN[tier])
    if snap["top_mode"] == "Main":
        lines.append("    （Top 目前交回主模型自己做；上表 Top 一列只在設為 Fixed 時才會用到）")
    roles = "；".join(f"{p}: {', '.join(r)}" for p, r in snap["generic_roles"].items() if r) or "（無）"
    lines += ["", _row("視為預設角色", roles + "   （其他命名的專門角色一律不干預）"),
              _row("統計保留", "永久保留" if not snap["retention_days"] else f"{snap['retention_days']} 天（超過的紀錄會自動刪除）"),
              _row("設定檔", f"{snap['settings_path']}（版本 {snap['revision']}）")]
    return "\n".join(sanitize_text(line) if i else line for i, line in enumerate(lines)) + "\n"


def apply_set(path, settings, key, value):
    """One write path for scripted and interactive changes. Returns a short confirmation."""
    if key == "allowed_workspaces" and "workspace_allowlist_file" in settings:
        roots = logic.changes_for(settings, key, value)["allowed_workspaces"]
        v2.write_allowlist_file(settings["workspace_allowlist_file"], roots)
        return f"{key} 已寫入 {settings['workspace_allowlist_file']}"
    saved = v2.update(path, expected_revision=settings["revision"], **logic.changes_for(settings, key, value))
    return f"{key} 已儲存（版本 {saved['revision']}）"


def reset_stats(path, scope, days, *, yes, stdin, stdout, ask=None):
    """Delete statistics in a range after a preview and a typed confirmation (or --yes). Settings are never touched."""
    from mrh.advisory.store import AdviceStore
    from mrh.presentation import stats_reset
    db = path.parent / "advice.sqlite3"
    if not db.exists():
        stdout.write("還沒有任何統計資料。\n")
        return 0
    interactive = getattr(stdin, "isatty", lambda: False)()
    ask = ask or (lambda prompt: (stdout.write(prompt + "\n  > "), stdout.flush(), stdin.readline())[-1])
    code, _ = stats_reset.run(AdviceStore(db), scope, days, yes=yes, interactive=interactive, ask=ask, out=stdout)
    return code


def statistics(path, days):
    """Shared data for status, stats, HTML and the machine-readable export."""
    from mrh.advisory.store import AdviceStore
    from mrh.presentation import stats_view
    since = 0 if days is None else time.time() - days * 86400
    label = "全部紀錄" if days is None else ("過去 24 小時" if days == 1 else f"過去 {days:g} 天")
    db = path.parent / "advice.sqlite3"
    data = AdviceStore.read_stats(db, since) if db.exists() else {"since": since, "decisions": {}, "per_platform": {}, "kept_unchanged": {},
        "tiers": {}, "classifier_usage": {}, "children_following_advice": 0, "followed_models": {}, "followed_requested_models": {},
        "reissues": 0, "unverified_reissues": 0, "unverified_followed_children": 0, "classifier_calls": 0, "classifier_requests": 0,
        "classifier_failed_requests": 0, "classifier_input_tokens": 0, "classifier_output_tokens": 0, "children_started": 0,
        "packet_classifications": 0, "packet_releases": 0, "packet_children_started": 0, "packet_children_following_advice": 0,
        "roles": {}, "role_recorded": 0, "explicit_without_role": 0, "children_models": {}, "children_inherited": 0}
    return data, label


def stats_text(path, days, as_json=False, color=False):
    data, label = statistics(path, days)
    if as_json:
        return json.dumps(data, indent=2, sort_keys=True)
    policy = v2.read(path)["policy"]
    return stats_view.render(data, label, policy["threshold"], color, policy)


def report_html_page(path, days):
    """Standalone dashboard page from the settings and the decision log."""
    from mrh.presentation import report_html as page
    data, label = statistics(path, days)
    return page.render(v2.read(path), data, label)


def dashboard_text(path, days, width, color):
    """The card layout: routing flow + tier table + proportion bars."""
    from mrh.presentation import dashboard
    data = status_data(path, days)
    return dashboard.render(data["status"], data, data["status"]["period_label"], width, color)


def status_data(path, days):
    """One public assembly for both the status card and its JSON export."""
    settings = v2.read(path)
    data, label = statistics(path, days)
    data["status"] = {"format_version": 1, "generated_at": time.time(), "period_label": label,
                      "enabled": settings["enabled"], "task_export_permitted": settings["task_export_permitted"],
                      "classifier": {k: settings["classifier"][k] for k in ("provider", "model", "timeout_seconds")},
                      "policy": {k: settings["policy"][k] for k in ("threshold", "top_mode", "tiers", "fixed")}}
    return data


class ModelChoices(list):
    """Picker entries retain their declaration source, not an execution guarantee."""
    def __init__(self, models=(), *, status="unverified", source="未確認的來源", fetched_at=None, blocked=(), reason=None):
        super().__init__(models)
        self.status, self.source, self.fetched_at = status, source, fetched_at
        self.blocked, self.reason = frozenset(blocked), reason

    def description(self):
        stamp = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(self.fetched_at)) if self.fetched_at else "未取得更新時間"
        state = "CLI 宣告清單（不代表帳號實際可用）" if self.status == "advertised" else "清單未確認；離線或更新失敗不等於下架"
        return f"{state}；來源：{self.source}；{stamp}" + (f"；{self.reason}" if self.reason else "")


def list_models(platform, cache={}):
    """Refresh declarations; keep an explicitly labelled last-known list on failure."""
    previous = cache.get(platform)
    if previous is not None and not isinstance(previous, ModelChoices):
        previous = ModelChoices(previous)
    reason = "找不到已安裝的工具"
    try:
        from mrh.adapters.catalogs import catalog
        found = next((c for c in catalog.discover() if c["tool"] == platform), None)
        if found:
            binding = {**catalog.describe_tool(found), "id": "ctrl-" + platform}
            result = catalog.ToolCatalog().refresh(binding)
            value = ModelChoices([(m.id, m.efforts) for m in result.models if m.state == "available"],
                                 status="advertised", source=f"{result.source} / {result.version}", fetched_at=result.fetched_at,
                                 blocked=[m.id for m in result.models if m.state in ("retired", "unavailable")])
            cache[platform] = value
            return value
    except Exception:
        reason = "工具清單更新失敗"
    return ModelChoices(previous if previous is not None else [(m, ()) for m in logic.FALLBACK_MODELS.get(platform, ())],
                        source=("上次的 " + previous.source) if previous is not None else "內建參考名稱（非即時清單）",
                        fetched_at=previous.fetched_at if previous is not None else None,
                        blocked=previous.blocked if previous is not None else (), reason=reason)


class Session:
    def __init__(self, path, menu, stdout, *, models=list_models, secrets_module=secrets):
        self.path, self.menu, self.out, self.models, self.secrets = path, menu, stdout, models, secrets_module

    def settings(self):
        return v2.read(self.path)

    def model_choices(self, platform):
        try:
            value = self.models(platform)
        except Exception:
            value = ModelChoices(reason="工具清單更新失敗")
        choices = value if isinstance(value, ModelChoices) else ModelChoices(value)
        self.menu.note(choices.description())
        return choices

    def check_new_candidates(self, entries, choices):
        if any(c["model"] in choices.blocked for c in entries):
            raise logic.CtrlError("工具已宣告該模型下架或不可選；現有設定保留，不能新增這個選項。")
        declared = dict(choices)
        for entry in entries:
            if choices.status != "advertised" or entry["model"] not in declared:
                raise logic.CtrlError("模型清單未確認，不能新增這個選項；可保留、排序或移除原有設定。")
            elif entry.get("effort") and entry["effort"] not in declared[entry["model"]]:
                raise logic.CtrlError("這個推理強度未在該模型的 CLI 宣告清單中；没有儲存。")
        return entries

    def _confirm_save(self):
        """Esc here means 'not now': nothing is written and the previous screen stays."""
        try:
            ok = self.menu.pick("要儲存這項變更嗎？", [("儲存", True), ("取消", False)]) is True
        except Back:
            ok = False
        if not ok:
            self.menu.note("沒有儲存。")
        return ok

    def save(self, changes, summary):
        current = self.settings()
        self.out.write(f"\n  變更內容：{summary}\n")
        if not self._confirm_save():
            return False
        try:
            v2.update(self.path, expected_revision=current["revision"], **changes)
        except SettingsError as exc:
            self.menu.note("設定在你編輯期間被別處改過，請重新開啟再試；這次沒有儲存。" if exc.reason == "settings_conflict"
                           else "這個值不被接受，沒有儲存任何東西。")
            return False
        self.menu.note("已儲存。")
        return True

    def set_key(self, key, value, summary):
        try:
            current = self.settings()
            if key == "allowed_workspaces" and "workspace_allowlist_file" in current:
                logic.changes_for(current, key, value)          # validate before asking
                self.out.write(f"\n  變更內容：{summary}\n")
                if not self._confirm_save():
                    return False
                self.menu.note(apply_set(self.path, current, key, value)); return True
            return self.save(logic.changes_for(current, key, value), summary)
        except logic.CtrlError as exc:
            self.menu.note(str(exc)); return False

    # -- screens ---------------------------------------------------------------------
    def routing(self):
        s = self.settings()
        on = self.menu.pick("路由", [("開啟：派子代理時，給主模型模型建議", True), ("關閉：完全不碰子代理委派", False)], s["enabled"])
        if on and not s["task_export_permitted"]:
            self.menu.note(f"開啟後，每次派子代理，任務內容會送到「{registry.LABELS[s['classifier']['provider']]}」判斷難度。")
        self.save({"enabled": on, **({"task_export_permitted": True} if on else {})}, f"路由 {'開啟' if on else '關閉'}")

    def classifier(self):
        step = 0
        while True:
            try:
                s = self.settings()["classifier"]
                if step == 0:
                    provider = self.menu.pick("分級器", [(registry.LABELS[p] + ("  （需要 API 金鑰）" if registry.NEEDS_KEY[p] else ""), p)
                                                         for p in v2.PROVIDERS], s["provider"])
                    if provider != s["provider"]:
                        self.set_key("classifier.provider", provider, f"分級器 → {registry.LABELS[provider]}")
                    step = 1
                elif step == 1:
                    if s["provider"] == "jev":
                        step = 2; continue
                    platform = "codex" if s["provider"] == "codex_subscription" else "claude"
                    source = self.model_choices(platform)
                    choices = [(f"{m}" + ("（未確認）" if source.status != "advertised" else ""), m) for m, _ in source] + [("自己輸入模型名稱（未確認）", None)]
                    model = self.menu.pick("分級器用的模型（小而快的最合適）", choices, s["model"])
                    model = model or self.menu.text("模型名稱")
                    self.check_new_candidates([{"model": model}], source)
                    if model != s["model"]:
                        self.set_key("classifier.model", model, f"分級器模型 → {model}")
                    step = 2
                else:
                    timeout = self.menu.text(f"逾時秒數 1–30（目前 {s['timeout_seconds']:g}，直接按 Enter 保持不變）")
                    if timeout:
                        self.set_key("classifier.timeout", timeout, f"逾時 → {timeout} 秒")
                    return
            except Back:
                if step == 0:
                    raise
                step = 0 if step == 1 or self.settings()["classifier"]["provider"] == "jev" else 1
            except logic.CtrlError as exc:
                self.menu.note(str(exc)); step = 1

    def edit_list(self, scope, platform):
        s = self.settings()
        items = list((s["policy"]["fixed"] if scope == "Top" else s["policy"]["tiers"].get(scope, {})).get(platform, []))
        original = list(items)
        key = f"fixed.{platform}" if scope == "Top" else f"tiers.{scope}.{platform}"
        while True:
            self.out.write(f"\n  {scope} / {platform}: {logic.format_candidates(items)}\n")
            trail = [platform, scope.lower()]
            try:
                action = self.menu.pick("編輯候選清單", [("從已安裝工具的模型清單加入", "add"), ("直接輸入模型（模型 或 模型:推理強度）", "type"),
                                        ("移除其中一個", "remove"), ("把其中一個移到最前面（最優先）", "top"), ("全部清空", "clear"), ("儲存並完成", "done")], trail=trail)
            except Back:
                if items != original:
                    self.menu.note("尚未儲存的修改已放棄。")
                raise                                  # one step back: the platform choice
            try:
                if action == "add":
                    models = self.model_choices(platform)
                    if models.status != "advertised":
                        self.menu.note("參考名稱：" + ("、".join(m for m, _ in models) or "無"))
                        self.menu.note("模型清單未確認，不能新增選項；原設定保留。")
                        continue
                    if not models:
                        self.menu.note("這個工具沒有可用的模型清單，請改用「直接輸入模型」。"); continue
                    model, efforts = models[self.menu.pick("模型", [(m + ("（未確認）" if models.status != "advertised" else ""), n) for n, (m, _) in enumerate(models)], trail=[*trail, "模型"])]
                    self.menu.note("推理強度依據：該模型的 CLI 宣告；不是實際執行證明。" if models.status == "advertised" else "沒有已確認的推理清單；預設不指定推理強度。")
                    effort = self.menu.pick("推理強度（effort）", [("不指定推理強度", None), *[(e, e) for e in efforts]], trail=[*trail, model, "effort"]) if efforts else None
                    items += self.check_new_candidates([{"model": model, **({"effort": effort} if effort else {})}], models)
                elif action == "type":
                    entries = logic.parse_candidates(self.menu.text("模型，例如 gpt-5.6-luna:low", trail=[*trail, "模型"]))
                    items += self.check_new_candidates(entries, self.model_choices(platform))
                elif action in ("remove", "top") and items:
                    index = self.menu.pick("要選哪一個", [(logic.format_candidates([c]), n) for n, c in enumerate(items)], trail=trail)
                    items.insert(0, items.pop(index)) if action == "top" else items.pop(index)
                elif action == "clear":
                    items = []
                elif action == "done":
                    if self.save(logic.changes_for(self.settings(), key, logic.format_candidates(items) if items else ""),
                                 f"{scope}/{platform} -> {logic.format_candidates(items)}"):
                        return
                    continue
                if len(items) > v2.MAX_CANDIDATES:
                    items = items[:v2.MAX_CANDIDATES]; self.menu.note(f"最多只保留前 {v2.MAX_CANDIDATES} 個。")
            except logic.CtrlError as exc:
                self.menu.note(str(exc))
            except Back:
                continue                               # Esc inside a sub-step returns to this action menu

    def tiers(self):
        """Platform first (which vendor runs the main model), then tier, then the list; a path is shown at every step."""
        names = {"claude": "Claude Code", "codex": "Codex", "gemini": "Gemini（尚未支援 hook）"}
        step, platform, scope = 0, None, None
        while True:
            try:
                if step == 0:
                    platform = self.menu.pick("主模型是哪一家的工具？（要設定這一家的各難度模型）",
                                              [(f"{names[p]}（{p}）", p) for p in ("claude", "codex", "gemini")]); step = 1
                elif step == 1:
                    scope = self.menu.pick("要設定哪個難度", [(f"{t.lower():<6}{report_html.TIER_WHEN[t]}" + ("　（只在 Top 設為 Fixed 時使用）" if t == "Top" else ""), t)
                                                              for t in (*v2.TIERS, "Top")], trail=[platform]); step = 2
                else:
                    self.edit_list(scope, platform); return
            except Back:
                if step == 0:
                    raise
                step = 0 if step == 1 else 1

    def top(self):
        mode = self.menu.pick("Top 難度怎麼處理", [(f"Main：{TOP_HELP['Main']}", "Main"), (f"Fixed：{TOP_HELP['Fixed']}", "Fixed")], self.settings()["policy"]["top_mode"])
        self.set_key("top_mode", mode, f"Top 難度 → {mode}")

    def threshold(self):
        value = self.menu.text("分級信心度要達到多少才給建議，0.50–0.99（越高越保守）")
        self.set_key("threshold", value, f"信心門檻 → {value}")

    def where(self):
        value = self.menu.text("路由適用的資料夾，用逗號分隔（/ 代表全部）")
        self.set_key("allowed_workspaces", value, f"適用範圍 → {value}")

    def api_key(self):
        state = key_state("jev", self.secrets)
        self.menu.note(f"Jev API 金鑰：Keychain {'已設定' if state['keychain'] else '未設定'}，環境變數 {'已設定' if state['environment'] else '未設定'}。")
        self.menu.note("要存入或更換金鑰，請在終端機執行：mrh key set jev（金鑰由 macOS 提示輸入，不會經過 MRH）。")

    def stats(self):
        days = self.menu.pick("統計期間", [("過去 24 小時", 1), ("過去 7 天", 7), ("過去 30 天", 30), ("全部", None)])
        self.out.write("\n" + stats_text(self.path, days, color=self.menu.color) + "\n")

    def dashboard(self):
        days = self.menu.pick("儀表板統計期間", [("過去 24 小時", 1), ("過去 7 天", 7), ("過去 30 天", 30), ("全部", None)])
        self.out.write("\n" + dashboard_text(self.path, days, self.menu.width, self.menu.color) + "\n")

    def retention(self):
        now = v2.retention_days(self.settings())
        value = self.menu.text(f"統計保留幾天？超過的紀錄會自動刪除（目前 {'永久保留' if not now else str(now) + ' 天'}；0 代表永久保留；直接按 Enter 保持不變）")
        if value:
            self.set_key("stats.retention_days", value, f"統計保留 → {'永久' if value == '0' else value + ' 天'}")

    def reset(self):
        scope, days = self.menu.pick("要清除哪個範圍的統計？", [("今天", ("today", None)), ("最近 7 天內", ("days", 7)), ("最近 30 天內", ("days", 30)),
                                                              ("自己輸入天數", ("custom", None)), ("全部", ("all", None))])
        if scope == "custom":
            raw = self.menu.text("最近幾天內的紀錄要清除？（輸入正整數）")
            if not raw.isdigit() or int(raw) < 1:
                self.menu.note("請輸入大於 0 的整數。"); return
            scope, days = "days", int(raw)
        reset_stats(self.path, scope, days, yes=False, stdin=self.menu.stdin, stdout=self.out,
                    ask=lambda prompt: self.menu.text(prompt.strip()))

    def report(self):
        from pathlib import Path
        import webbrowser
        out = Path.home() / ".local/state/model-routing-harness/report.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report_html_page(self.path, 7), encoding="utf-8")
        self.menu.note(f"已產生網頁報表（過去 7 天）：{out}")
        try:
            webbrowser.open(out.as_uri())
            self.menu.note("已用瀏覽器開啟。")
        except Exception:
            self.menu.note("請自行用瀏覽器開啟上面的檔案。")

    def run(self):
        screens = [("路由開關", self.routing), ("分級器（Jev / Codex 訂閱 / Claude 訂閱）", self.classifier), ("各難度要用的模型", self.tiers),
                   ("Top 難度怎麼處理", self.top), ("信心門檻", self.threshold), ("適用範圍（哪些資料夾）", self.where),
                   ("API 金鑰狀態", self.api_key), ("儀表板（圖表版面）", self.dashboard), ("統計（文字）", self.stats), ("清除統計", self.reset), ("統計保留天數", self.retention), ("網頁報表（選用）", self.report)]
        while True:
            self.out.write("\n" + render(snapshot(self.settings(), self.path, self.secrets), self.menu.width))
            try:
                screen = self.menu.pick("要調整什麼？", [*screens, ("離開", None)])
            except (Back, Cancelled):
                return 0                               # nothing above the main menu: Esc leaves
            if screen is None:
                return 0
            try:
                screen()
            except Back:
                continue                               # Esc inside a screen returns here
            except Cancelled:
                return 0


def _fail(stderr, message):
    stderr.write("mrh: " + message + "\n")
    return 2


def main(args, *, stdin, stdout, stderr, color=False, models=list_models, secrets_module=secrets):
    try:
        path = v2.resolve_settings_path(getattr(args, "settings", None))
    except SettingsError:
        return _fail(stderr, "找不到設定檔：請用 --settings 指定、設定 MRH_SETTINGS，或先完成安裝")
    try:
        action = getattr(args, "ctrl_action", None)
        if not path.exists():
            if action in ("dashboard", "stats", "report"):
                return _fail(stderr, "找不到設定檔；統計讀取不會建立新設定")
            v2.init(path)
        settings = v2.read(path)
        action = getattr(args, "ctrl_action", None)
        if action == "reset":
            if args.all:
                scope, days = "all", None
            elif args.today:
                scope, days = "today", None
            elif args.reset_days:
                scope, days = "days", args.reset_days
            else:
                return _fail(stderr, "請指定範圍：--today、--days N 或 --all（再加 --yes 才會真的刪除，不加只顯示預覽）")
            return reset_stats(path, scope, days, yes=args.yes, stdin=stdin, stdout=stdout)
        if action == "dashboard":
            if getattr(args, "json", False):
                stdout.write(json.dumps(status_data(path, None if args.days == 0 else args.days), indent=2, sort_keys=True) + "\n"); return 0
            stdout.write(dashboard_text(path, None if args.days == 0 else args.days, args.width or terminal_width(), color)); return 0
        if action == "stats":
            stdout.write(stats_text(path, None if args.days == 0 else args.days, args.json, color) + "\n"); return 0
        if action == "report":
            from pathlib import Path
            out = Path(args.out) if args.out else Path.home() / ".local/state/model-routing-harness/report.html"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(report_html_page(path, None if args.days == 0 else args.days), encoding="utf-8")
            stdout.write(f"報表已產生：{out}\n")
            if args.open:
                import webbrowser
                webbrowser.open(out.as_uri())
            return 0
        if action == "keys":
            stdout.write("\n".join(logic.key_names()) + "\n"); return 0
        if action == "show":
            snap = snapshot(settings, path, secrets_module)
            stdout.write(json.dumps(snap, indent=2, sort_keys=True) + "\n" if args.json else render(snap))
            return 0
        if action == "set":
            stdout.write(apply_set(path, settings, args.key, args.value) + "\n"); return 0
        if not getattr(stdin, "isatty", lambda: False)():
            return _fail(stderr, "互動式控制中心需要在終端機中執行；也可以用 `mrh ctrl show` 或 `mrh ctrl set 項目 值`")
        menu = Menu(stdin, stdout, args.width or terminal_width(), color)
        return Session(path, menu, stdout, models=models, secrets_module=secrets_module).run()
    except logic.CtrlError as exc:
        return _fail(stderr, str(exc))
    except SettingsError as exc:
        return _fail(stderr, "設定在別處被改過，請重試" if exc.reason == "settings_conflict" else "設定錯誤：" + exc.reason)
