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
            "generic_roles": settings["policy"].get("generic_roles", v2.DEFAULT_GENERIC_ROLES)}


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


def stats_text(path, days, as_json=False, color=False):
    from mrh.advisory.store import AdviceStore
    from mrh.presentation import stats_view
    since = 0 if days is None else time.time() - days * 86400
    label = "全部紀錄" if days is None else ("過去 24 小時" if days == 1 else f"過去 {days:g} 天")
    db = path.parent / "advice.sqlite3"
    data = AdviceStore(db).stats(since) if db.exists() else {"decisions": {}, "per_platform": {}, "kept_unchanged": {},
        "tiers": {}, "classifier_usage": {}, "children_following_advice": 0, "followed_models": {}}
    if as_json:
        return json.dumps(data, indent=2, sort_keys=True)
    return stats_view.render(data, label, v2.read(path)["policy"]["threshold"], color)


def report_html_page(path, days):
    """Standalone dashboard page from the settings and the decision log."""
    from mrh.advisory.store import AdviceStore
    from mrh.presentation import report_html as page
    since = 0 if days is None else time.time() - days * 86400
    label = "全部紀錄" if days is None else ("過去 24 小時" if days == 1 else f"過去 {days:g} 天")
    db = path.parent / "advice.sqlite3"
    data = AdviceStore(db).stats(since) if db.exists() else {"decisions": {}, "per_platform": {}, "kept_unchanged": {}, "tiers": {},
        "classifier_usage": {}, "children_following_advice": 0, "followed_models": {}}
    return page.render(v2.read(path), data, label)


def dashboard_text(path, days, width, color):
    """The card layout: routing flow + tier table + proportion bars."""
    from mrh.advisory.store import AdviceStore
    from mrh.presentation import dashboard
    since = 0 if days is None else time.time() - days * 86400
    label = "全部紀錄" if days is None else ("過去 24 小時" if days == 1 else f"過去 {days:g} 天")
    db = path.parent / "advice.sqlite3"
    data = AdviceStore(db).stats(since) if db.exists() else {"decisions": {}, "per_platform": {}, "kept_unchanged": {}, "tiers": {},
        "classifier_usage": {}, "children_following_advice": 0, "followed_models": {}}
    return dashboard.render(v2.read(path), data, label, width, color)


def list_models(platform, cache={}):
    """Models from the installed CLI's own catalog; empty means 'type it in'."""
    if platform in cache:
        return cache[platform]
    models = []
    try:
        from mrh.adapters.catalogs import catalog
        found = next((c for c in catalog.discover() if c["tool"] == platform), None)
        if found:
            binding = {**catalog.describe_tool(found), "id": "ctrl-" + platform}
            models = [(m.id, m.efforts) for m in catalog.ToolCatalog().refresh(binding).models if m.state == "available"]
    except Exception:
        models = []
    if not models:
        models = [(m, ()) for m in logic.FALLBACK_MODELS.get(platform, ())]
    cache[platform] = models
    return models


class Session:
    def __init__(self, path, menu, stdout, *, models=list_models, secrets_module=secrets):
        self.path, self.menu, self.out, self.models, self.secrets = path, menu, stdout, models, secrets_module

    def settings(self):
        return v2.read(self.path)

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
                    choices = [(f"{m}", m) for m, _ in self.models(platform)] + [("自己輸入模型名稱", None)]
                    model = self.menu.pick("分級器用的模型（小而快的最合適）", choices, s["model"])
                    model = model or self.menu.text("模型名稱")
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

    def edit_list(self, scope, platform):
        s = self.settings()
        items = list((s["policy"]["fixed"] if scope == "Top" else s["policy"]["tiers"].get(scope, {})).get(platform, []))
        original = list(items)
        key = f"fixed.{platform}" if scope == "Top" else f"tiers.{scope}.{platform}"
        while True:
            self.out.write(f"\n  {scope} / {platform}: {logic.format_candidates(items)}\n")
            try:
                action = self.menu.pick("編輯候選清單", [("從已安裝工具的模型清單加入", "add"), ("直接輸入模型（模型 或 模型:推理強度）", "type"),
                                        ("移除其中一個", "remove"), ("把其中一個移到最前面（最優先）", "top"), ("全部清空", "clear"), ("儲存並完成", "done")])
            except Back:
                if items != original:
                    self.menu.note("尚未儲存的修改已放棄。")
                raise                                  # one step back: the platform choice
            try:
                if action == "add":
                    models = self.models(platform)
                    if not models:
                        self.menu.note("這個工具沒有可用的模型清單，請改用「直接輸入模型」。"); continue
                    model, efforts = models[self.menu.pick("模型", [(m, n) for n, (m, _) in enumerate(models)])]
                    effort = self.menu.pick("推理強度（effort）", [("不指定推理強度", None), *[(e, e) for e in efforts]]) if efforts else None
                    items.append({"model": model, **({"effort": effort} if effort else {})})
                elif action == "type":
                    items += logic.parse_candidates(self.menu.text("模型，例如 gpt-5.6-luna:low"))
                elif action in ("remove", "top") and items:
                    index = self.menu.pick("要選哪一個", [(logic.format_candidates([c]), n) for n, c in enumerate(items)])
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
        step, scope, platform = 0, None, None
        while True:
            try:
                if step == 0:
                    scope = self.menu.pick("要設定哪個難度", [(t, t) for t in (*v2.TIERS, "Top")]); step = 1
                elif step == 1:
                    platform = self.menu.pick("主模型是在哪個工具裡執行（codex / claude / gemini）", [(p, p) for p in v2.PLATFORMS]); step = 2
                else:
                    self.edit_list(scope, platform); return
            except Back:
                if step == 0:
                    raise
                step = step - 1 if step < 2 else 1

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
                   ("API 金鑰狀態", self.api_key), ("儀表板（圖表版面）", self.dashboard), ("統計（文字）", self.stats), ("網頁報表（選用）", self.report)]
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
        if not path.exists():
            v2.init(path)
        settings = v2.read(path)
        action = getattr(args, "ctrl_action", None)
        if action == "dashboard":
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
