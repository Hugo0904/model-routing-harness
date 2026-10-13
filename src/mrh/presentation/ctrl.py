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
from mrh.presentation.terminal import sanitize_text, terminal_width

TOP_HELP = {"Main": "the main model keeps Top-tier work", "Fixed": "Top work is advised to the Fixed list"}


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


def render(snap, width=100):
    c = snap["classifier"]
    key = snap["api_key"]["jev"]
    key_text = "set in Keychain" if key["keychain"] else "set in environment" if key["environment"] else "NOT SET (mrh key set jev)"
    lines = ["MRH  /  control center", "",
             f"  Routing       " + ("ON    each delegation's task text is sent to the classifier" if snap["enabled"] and snap["task_export_permitted"]
                                    else "OFF   delegations are never touched"),
             f"  Classifier    {registry.LABELS[c['provider']]} · {c['model']} · timeout {c['timeout_seconds']:g}s",
             f"  Jev API key   {key_text}",
             f"  Confidence    advise at or above {snap['threshold']:.2f}",
             f"  Top tier      {snap['top_mode']} ({TOP_HELP[snap['top_mode']]})",
             f"  Applies to    {', '.join(snap['applies_to']) or '(nowhere)'}" + ("" if snap["applies_to_source"] == "settings" else f"   (list in {snap['applies_to_source']})"), "", "  Candidates, in order of preference"]
    def rows(label, lists):
        shown = [f"{p}: {logic.format_candidates(lists[p])}" for p in v2.PLATFORMS if lists.get(p)]
        lines.append(f"    {label:<6} " + ("  |  ".join(shown) if shown else "(none)"))
    for tier in v2.TIERS:
        rows(tier, snap["tiers"].get(tier, {}))
    rows("Top", snap["fixed"])
    if snap["top_mode"] == "Main" and snap["fixed"]:
        lines.append("           (the Top list is used only when Top is Fixed)")
    roles = "; ".join(f"{p}: {', '.join(r)}" for p, r in snap["generic_roles"].items() if r) or "(none)"
    lines += ["", f"  Treated as default roles   {roles}   (any other named role is left alone)"]
    lines += ["", f"  Settings      {snap['settings_path']}  (revision {snap['revision']})"]
    return "\n".join(sanitize_text(line) if i else line for i, line in enumerate(lines)) + "\n"


def apply_set(path, settings, key, value):
    """One write path for scripted and interactive changes. Returns a short confirmation."""
    if key == "allowed_workspaces" and "workspace_allowlist_file" in settings:
        roots = logic.changes_for(settings, key, value)["allowed_workspaces"]
        v2.write_allowlist_file(settings["workspace_allowlist_file"], roots)
        return f"{key} saved to {settings['workspace_allowlist_file']}"
    saved = v2.update(path, expected_revision=settings["revision"], **logic.changes_for(settings, key, value))
    return f"{key} saved (revision {saved['revision']})"


def stats_text(path, days, as_json=False):
    from mrh.advisory.store import AdviceStore
    from mrh.presentation import stats_view
    since = 0 if days is None else time.time() - days * 86400
    label = "全部紀錄" if days is None else ("過去 24 小時" if days == 1 else f"過去 {days:g} 天")
    db = path.parent / "advice.sqlite3"
    data = AdviceStore(db).stats(since) if db.exists() else {"decisions": {}, "per_platform": {}, "kept_unchanged": {},
        "tiers": {}, "classifier_usage": {}, "children_following_advice": 0, "followed_models": {}}
    if as_json:
        return json.dumps(data, indent=2, sort_keys=True)
    return stats_view.render(data, label, v2.read(path)["policy"]["threshold"])


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

    def save(self, changes, summary):
        current = self.settings()
        self.out.write(f"\n  Change: {summary}\n")
        if self.menu.pick("Save this change?", [("Save", True), ("Cancel", False)]) is not True:
            self.menu.note("Not saved.")
            return False
        try:
            v2.update(self.path, expected_revision=current["revision"], **changes)
        except SettingsError as exc:
            self.menu.note("Settings changed while you were editing; reopen and retry." if exc.reason == "settings_conflict"
                           else "That value was rejected; nothing was saved.")
            return False
        self.menu.note("Saved.")
        return True

    def set_key(self, key, value, summary):
        try:
            current = self.settings()
            if key == "allowed_workspaces" and "workspace_allowlist_file" in current:
                logic.changes_for(current, key, value)          # validate before asking
                self.out.write(f"\n  Change: {summary}\n")
                if self.menu.pick("Save this change?", [("Save", True), ("Cancel", False)]) is not True:
                    self.menu.note("Not saved."); return False
                self.menu.note(apply_set(self.path, current, key, value)); return True
            return self.save(logic.changes_for(current, key, value), summary)
        except logic.CtrlError as exc:
            self.menu.note(str(exc)); return False

    # -- screens ---------------------------------------------------------------------
    def routing(self):
        s = self.settings()
        on = self.menu.pick("Routing", [("ON: advise models for subagent delegations", True), ("OFF: never touch a delegation", False)], s["enabled"])
        if on and not s["task_export_permitted"]:
            self.menu.note(f"Turning routing on sends each delegation's task text to {registry.LABELS[s['classifier']['provider']]}.")
        self.save({"enabled": on, **({"task_export_permitted": True} if on else {})}, f"routing {'ON' if on else 'OFF'}")

    def classifier(self):
        s = self.settings()["classifier"]
        provider = self.menu.pick("Classifier", [(registry.LABELS[p] + ("  (needs an API key)" if registry.NEEDS_KEY[p] else ""), p)
                                                 for p in v2.PROVIDERS], s["provider"])
        if provider != s["provider"]:
            self.set_key("classifier.provider", provider, f"classifier -> {registry.LABELS[provider]}")
        s = self.settings()["classifier"]
        if s["provider"] != "jev":
            platform = "codex" if s["provider"] == "codex_subscription" else "claude"
            choices = [(f"{m}", m) for m, _ in self.models(platform)] + [("Type a model name", None)]
            model = self.menu.pick("Classifier model (a small, fast one is best)", choices, s["model"])
            model = model or self.menu.text("Model name")
            if model != s["model"]:
                self.set_key("classifier.model", model, f"classifier model -> {model}")
        timeout = self.menu.text(f"Timeout in seconds, 1-30 [now {s['timeout_seconds']:g}; Enter keeps]")
        if timeout:
            self.set_key("classifier.timeout", timeout, f"timeout -> {timeout}s")

    def edit_list(self, scope, platform):
        s = self.settings()
        items = list((s["policy"]["fixed"] if scope == "Top" else s["policy"]["tiers"].get(scope, {})).get(platform, []))
        key = f"fixed.{platform}" if scope == "Top" else f"tiers.{scope}.{platform}"
        while True:
            self.out.write(f"\n  {scope} / {platform}: {logic.format_candidates(items)}\n")
            action = self.menu.pick("Edit candidate list", [("Add from the installed tool's model list", "add"), ("Type a model (model or model:effort)", "type"),
                                    ("Remove one", "remove"), ("Move one to the top", "top"), ("Clear all", "clear"), ("Save and finish", "done")])
            try:
                if action == "add":
                    models = self.models(platform)
                    if not models:
                        self.menu.note("No model list available for this tool; use 'Type a model'."); continue
                    model, efforts = models[self.menu.pick("Model", [(m, n) for n, (m, _) in enumerate(models)])]
                    effort = self.menu.pick("Reasoning effort", [("No effort setting", None), *[(e, e) for e in efforts]]) if efforts else None
                    items.append({"model": model, **({"effort": effort} if effort else {})})
                elif action == "type":
                    items += logic.parse_candidates(self.menu.text("Model, e.g. gpt-5.6-luna:low"))
                elif action in ("remove", "top") and items:
                    index = self.menu.pick("Which one", [(logic.format_candidates([c]), n) for n, c in enumerate(items)])
                    items.insert(0, items.pop(index)) if action == "top" else items.pop(index)
                elif action == "clear":
                    items = []
                elif action == "done":
                    self.save(logic.changes_for(self.settings(), key, logic.format_candidates(items) if items else ""),
                              f"{scope}/{platform} -> {logic.format_candidates(items)}")
                    return
                if len(items) > v2.MAX_CANDIDATES:
                    items = items[:v2.MAX_CANDIDATES]; self.menu.note(f"Only the first {v2.MAX_CANDIDATES} are kept.")
            except logic.CtrlError as exc:
                self.menu.note(str(exc))
            except Back:
                continue

    def tiers(self):
        scope = self.menu.pick("Which tier", [(t, t) for t in (*v2.TIERS, "Top")])
        platform = self.menu.pick("Which tool is the parent model running in", [(p, p) for p in v2.PLATFORMS])
        self.edit_list(scope, platform)

    def top(self):
        mode = self.menu.pick("Top tier", [(f"Main: {TOP_HELP['Main']}", "Main"), (f"Fixed: {TOP_HELP['Fixed']}", "Fixed")], self.settings()["policy"]["top_mode"])
        self.set_key("top_mode", mode, f"Top tier -> {mode}")

    def threshold(self):
        value = self.menu.text("Confidence needed before advising, 0.50-0.99")
        self.set_key("threshold", value, f"threshold -> {value}")

    def where(self):
        value = self.menu.text("Folders where routing applies, comma separated (/ means everywhere)")
        self.set_key("allowed_workspaces", value, f"applies to -> {value}")

    def api_key(self):
        state = key_state("jev", self.secrets)
        self.menu.note(f"Jev API key: Keychain {'set' if state['keychain'] else 'not set'}, environment {'set' if state['environment'] else 'not set'}.")
        self.menu.note("To store or replace it, run in a terminal:  mrh key set jev   (the key is typed into macOS, never into MRH).")

    def stats(self):
        days = self.menu.pick("統計期間", [("過去 24 小時", 1), ("過去 7 天", 7), ("過去 30 天", 30), ("全部", None)])
        self.out.write("\n" + stats_text(self.path, days) + "\n")

    def run(self):
        screens = [("Routing on/off", self.routing), ("Classifier (Jev / Codex / Claude)", self.classifier), ("Tier models", self.tiers),
                   ("Top tier mode", self.top), ("Confidence threshold", self.threshold), ("Where it applies", self.where),
                   ("API key status", self.api_key), ("Statistics 統計", self.stats)]
        while True:
            self.out.write("\n" + render(snapshot(self.settings(), self.path, self.secrets), self.menu.width))
            try:
                screen = self.menu.pick("What do you want to change?", [*screens, ("Quit", None)])
                if screen is None:
                    return 0
                screen()
            except Back:
                continue
            except Cancelled:
                return 0


def _fail(stderr, message):
    stderr.write("mrh: " + message + "\n")
    return 2


def main(args, *, stdin, stdout, stderr, color=False, models=list_models, secrets_module=secrets):
    try:
        path = v2.resolve_settings_path(getattr(args, "settings", None))
    except SettingsError:
        return _fail(stderr, "no settings file: pass --settings, set MRH_SETTINGS, or run the installer")
    try:
        if not path.exists():
            v2.init(path)
        settings = v2.read(path)
        action = getattr(args, "ctrl_action", None)
        if action == "stats":
            stdout.write(stats_text(path, None if args.days == 0 else args.days, args.json) + "\n"); return 0
        if action == "keys":
            stdout.write("\n".join(logic.key_names()) + "\n"); return 0
        if action == "show":
            snap = snapshot(settings, path, secrets_module)
            stdout.write(json.dumps(snap, indent=2, sort_keys=True) + "\n" if args.json else render(snap))
            return 0
        if action == "set":
            stdout.write(apply_set(path, settings, args.key, args.value) + "\n"); return 0
        if not getattr(stdin, "isatty", lambda: False)():
            return _fail(stderr, "the interactive control center needs a terminal; use `mrh ctrl show` or `mrh ctrl set KEY VALUE`")
        menu = Menu(stdin, stdout, args.width or terminal_width(), color)
        return Session(path, menu, stdout, models=models, secrets_module=secrets_module).run()
    except logic.CtrlError as exc:
        return _fail(stderr, str(exc))
    except SettingsError as exc:
        return _fail(stderr, "settings conflict; retry" if exc.reason == "settings_conflict" else "settings error: " + exc.reason)
