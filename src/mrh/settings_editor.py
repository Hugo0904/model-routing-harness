"""Interactive policy editing; persistence belongs to the owned settings writer."""
import copy
import textwrap

from . import settings
from .settings_schema import SettingsError, validate_settings
from .terminal import policy_rows, render_configuration, render_policy_review, sanitize_text
from .types import safe_id


class Cancelled(Exception):
    pass


def edit(path, *, stdin, stdout, width, color):
    def note(text):
        stdout.write(textwrap.fill(sanitize_text(text), width=max(24, min(140, width)) - 4,
                                   initial_indent="  ", subsequent_indent="  ") + "\n")

    def ask(prompt):
        note(prompt)
        stdout.write("  > "); stdout.flush()
        raw = stdin.readline(1026)
        if not getattr(stdin, "isatty", lambda: False)():
            stdout.write("\n")
        if not raw or raw.strip().lower() == "cancel":
            raise Cancelled()
        if len(raw) > 1024:
            raise SettingsError()
        return raw.strip()

    def mapping(label, current):
        while True:
            model = ask(label + " model [Enter keep / unset remove]")
            if model.lower() == "unset":
                return None
            if not model and current is None:
                return None
            model = model or current["model"]
            if safe_id(model):
                break
            note("Use a model identifier (letters, digits, . _ : / -).")
        result = {**(current or {}), "model": model}
        while True:
            effort = ask(label + " effort [Enter keep / inherit]")
            if effort.lower() == "inherit":
                result.pop("effort", None)
                return result
            if not effort:
                return result
            if safe_id(effort):
                result["effort"] = effort
                return result
            note("Use an effort identifier, or inherit.")

    try:
        initial = settings.read(path)
        stdout.write(render_configuration(initial, width=width, color=color))
        note("Enter keeps a value. unset removes a tier mapping. cancel exits without saving.")
        policy = copy.deepcopy(initial["policy"])
        for tier in ("Light", "Small", "Mid"):
            chosen = mapping(tier, policy.get("tiers", {}).get(tier))
            if chosen is not None:
                policy.setdefault("tiers", {})[tier] = chosen
            elif tier in policy.get("tiers", {}):
                del policy["tiers"][tier]
        while True:
            mode = ask("Top mode [Enter keep / Main / Fixed]")
            if not mode:
                break
            if mode.lower() in ("main", "fixed"):
                policy["top_mode"] = mode.title()
                break
            note("Choose Main or Fixed.")
        if policy.get("top_mode", "Main") == "Fixed":
            while True:
                chosen = mapping("Top Fixed", policy.get("fixed"))
                if chosen is not None:
                    policy["fixed"] = chosen
                    break
                note("Fixed needs a model. Enter one, or cancel.")
        candidate = validate_settings({**initial, "policy": policy})
        before, after = dict(policy_rows(initial["policy"])), dict(policy_rows(policy))
        changes = [f"{tier}: {before[tier]} -> {after[tier]}" for tier in before if before[tier] != after[tier]]
        stdout.write(render_policy_review(changes, width=width, color=color))
        while True:
            choice = ask("Save changes? [save / cancel]").lower()
            if choice == "save":
                break
            note("Type save to commit, or cancel to leave the file unchanged.")
    except (Cancelled, KeyboardInterrupt):
        stdout.write("\n"); note("Cancelled. No changes saved.")
        return 0
    # Confirmation ends editing. The existing atomic writer checks the initial
    # revision under its lock; never adopt a concurrent revision as our own.
    try:
        saved = settings.update(path, expected_revision=initial["revision"], policy=candidate["policy"])
    except SettingsError as exc:
        if exc.reason == "settings_conflict":
            note("Settings changed while you edited. Reopen the editor; your changes were not saved.")
        raise
    stdout.write("Saved.\n" if saved != initial else "Unchanged. No file rewrite.\n")
    stdout.write(render_configuration(saved, width=width, color=color))
    return 0
