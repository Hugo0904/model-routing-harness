"""Settings v2: selectable classifier plus per-tier, per-platform candidate lists.

Same owned directory, lock and revision CAS as v1. A v1 file is migrated in
memory on read and always rewritten as v2, so legacy commands keep working until
the file is first saved by the control center.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from mrh.infrastructure import owned, settings as legacy
from mrh.infrastructure.settings_schema import (
    SettingsError, _is_finite_number, _reject_duplicate_keys, _reject_nonfinite_constant,
    _validate_rates, _validate_workspace_path, parse_settings as parse_v1,
)
from mrh.routing.classification_spec import TYPESAFE_MODEL
from mrh.routing.types import safe_id, safe_model_id

SCHEMA_VERSION = 2
OWNER = "org.model-routing-harness.settings.v1"
PLATFORMS = ("codex", "claude", "gemini")
TIERS = ("Light", "Small", "Mid")
PROVIDERS = {"jev": TYPESAFE_MODEL, "codex_subscription": "gpt-6-luna", "claude_subscription": "haiku"}
MAX_CANDIDATES = 5
DEFAULT_RETENTION_DAYS = 365          # statistics older than this are removed automatically; 0 keeps everything
MAX_RETENTION_DAYS = 3650
# Roles a parent attaches by habit, not a specialised role with its own model settings.
# Codex's built-in `worker` is sent on almost every spawn; `default` / `general-purpose` are implicit.
DEFAULT_GENERIC_ROLES = {"codex": ["worker"], "claude": [], "gemini": []}
THRESHOLD_RANGE = (0.5, 0.99)
FILES = legacy.FILES
MAX_BYTES = 65_536
_TOP = {"schema_version", "owner", "revision", "enabled", "task_export_permitted",
        "allowed_workspaces", "classifier", "policy"}
_PROVIDER_ALIAS = {"typesafe": "jev"}


def _invalid():
    raise SettingsError("settings_invalid") from None


def _candidate(value):
    if type(value) is not dict or set(value) - {"model", "effort"} or not safe_model_id(value.get("model")):
        _invalid()
    if "effort" in value and not safe_id(value["effort"]):
        _invalid()
    return dict(value)


def _candidates(value):
    if type(value) is not dict or set(value) - set(PLATFORMS):
        _invalid()
    result = {}
    for platform, items in value.items():
        if type(items) is not list or len(items) > MAX_CANDIDATES:
            _invalid()
        result[platform] = [_candidate(item) for item in items]
    return result


def _classifier(value):
    if type(value) is not dict or set(value) - {"rich_input"} != {"provider", "model", "timeout_seconds"}:
        _invalid()
    if "rich_input" in value and type(value["rich_input"]) is not bool:
        _invalid()
    provider, model, timeout = value["provider"], value["model"], value["timeout_seconds"]
    if type(provider) is not str or provider not in PROVIDERS or type(model) is not str:
        _invalid()
    if provider == "jev" and model != TYPESAFE_MODEL or not safe_model_id(model):
        _invalid()
    if not _is_finite_number(timeout) or not 0 < timeout <= 30:
        _invalid()
    result = {"provider": provider, "model": model, "timeout_seconds": timeout}
    if value.get("rich_input") is True:       # off is the default and is simply not stored
        result["rich_input"] = True
    return result


def rich_input(settings):
    """Whether a Jev classification also receives the delegation's title and the sub-agent role."""
    return settings["classifier"].get("rich_input", False) is True


TIERS_ORDER = ("Light", "Small", "Mid", "Top")
MAX_GEARS = 8
SCORE_MAX = 3.0          # difficulty score: 0 (certainly Light) .. 3 (certainly Top)


def _gears(value):
    """Ordered gears from easiest to hardest. Each starts at a difficulty score (`from`); the first starts at 0, the rest
    strictly increase. A gear either lists candidates per platform or hands the work back to the main model."""
    if type(value) is not list or not 1 <= len(value) <= MAX_GEARS:
        _invalid()
    result, previous = [], None
    for gear in value:
        if type(gear) is not dict or "from" not in gear or set(gear) - {"from", "candidates", "main"} or (
                ("candidates" in gear) == ("main" in gear)):
            _invalid()
        start = gear["from"]
        if not _is_finite_number(start) or not 0 <= start <= SCORE_MAX or (previous is None and start != 0) or (
                previous is not None and start <= previous):
            _invalid()
        previous = start
        if "main" in gear:
            if gear["main"] is not True:
                _invalid()
            result.append({"from": start, "main": True})
        else:
            result.append({"from": start, "candidates": _candidates(gear["candidates"])})
    return result


def difficulty_score(tier, probabilities=None):
    """0..3. With the four per-tier probabilities it is their expectation; otherwise the chosen tier's own weight."""
    weight = {name: i for i, name in enumerate(TIERS_ORDER)}
    if isinstance(probabilities, dict) and set(probabilities) == set(TIERS_ORDER):
        return sum(weight[name] * float(p) for name, p in probabilities.items())
    return float(weight[tier])


def gear_for(gears, score):
    """(1-based number, gear) of the last gear whose `from` is at or below the score."""
    number = max(i for i, gear in enumerate(gears, 1) if gear["from"] <= score + 1e-9)
    return number, gears[number - 1]


def mode(policy):
    return policy.get("mode", "tiers")


def _policy(value):
    if type(value) is not dict or set(value) - {"threshold", "top_mode", "tiers", "fixed", "rates", "generic_roles", "mode", "gears"}:
        _invalid()
    threshold = value.get("threshold", 0.5)
    if not _is_finite_number(threshold) or not THRESHOLD_RANGE[0] <= threshold <= THRESHOLD_RANGE[1]:
        _invalid()
    top_mode = value.get("top_mode", "Main")
    if type(top_mode) is not str or top_mode not in ("Main", "Fixed"):
        _invalid()
    tiers = value.get("tiers", {})
    if type(tiers) is not dict or set(tiers) - set(TIERS):
        _invalid()
    fixed = _candidates(value.get("fixed", {}))
    if top_mode == "Fixed" and not any(fixed.values()):
        _invalid()
    result = {"threshold": threshold, "top_mode": top_mode,
              "tiers": {tier: _candidates(items) for tier, items in tiers.items()},
              "fixed": fixed, "rates": _validate_rates(value.get("rates", {}))}
    if "generic_roles" in value:
        roles = value["generic_roles"]
        if type(roles) is not dict or set(roles) - set(PLATFORMS) or any(
                type(v) is not list or len(v) > 8 or not all(safe_id(r) for r in v) for v in roles.values()):
            _invalid()
        result["generic_roles"] = {p: list(v) for p, v in roles.items()}
    chosen = value.get("mode", "tiers")
    if chosen not in ("tiers", "gears") or type(chosen) is not str:
        _invalid()
    if chosen == "gears":                          # stored only when on, so existing settings are byte-for-byte unchanged
        result["mode"] = "gears"
        result["gears"] = _gears(value.get("gears"))
    elif "gears" in value:
        result["gears"] = _gears(value["gears"])    # a draft kept while the mode is tiers
    return result


def generic_roles(policy, platform):
    return set(policy.get("generic_roles", DEFAULT_GENERIC_ROLES).get(platform, []))


def validate(value):
    """Validate and return a fresh v2 document."""
    if type(value) is not dict or set(value) - _TOP - {"workspace_allowlist_file", "retention_days"} or _TOP - set(value):
        _invalid()
    if value["schema_version"] != SCHEMA_VERSION or type(value["schema_version"]) is not int or value["owner"] != OWNER:
        _invalid()
    if type(value["revision"]) is not int or value["revision"] < 0:
        _invalid()
    if type(value["enabled"]) is not bool or type(value["task_export_permitted"]) is not bool:
        _invalid()
    roots = value["allowed_workspaces"]
    if type(roots) is not list:
        _invalid()
    roots = [_validate_workspace_path(path) for path in roots]
    if len(roots) != len(set(roots)):
        _invalid()
    result = {"schema_version": SCHEMA_VERSION, "owner": OWNER, "revision": value["revision"],
              "enabled": value["enabled"], "task_export_permitted": value["task_export_permitted"],
              "allowed_workspaces": roots, "classifier": _classifier(value["classifier"]),
              "policy": _policy(value["policy"])}
    if "workspace_allowlist_file" in value:
        result["workspace_allowlist_file"] = _validate_workspace_path(value["workspace_allowlist_file"])
    if "retention_days" in value:
        days = value["retention_days"]
        if type(days) is not int or not 0 <= days <= MAX_RETENTION_DAYS:
            _invalid()
        result["retention_days"] = days
    return result


def default_settings():
    return validate({"schema_version": SCHEMA_VERSION, "owner": OWNER, "revision": 0, "enabled": False,
                     "task_export_permitted": False, "allowed_workspaces": [],
                     "classifier": {"provider": "jev", "model": TYPESAFE_MODEL, "timeout_seconds": 10},
                     "policy": {}})


def migrate_v1(old):
    """Map a validated v1 document to v2; single selections become Codex lists."""
    policy = old["policy"]
    single = lambda mapping: {"codex": [dict(mapping)]}
    provider = _PROVIDER_ALIAS.get(old["provider"], old["provider"])
    result = {"schema_version": SCHEMA_VERSION, "owner": OWNER, "revision": old["revision"],
              "enabled": old["enabled"], "task_export_permitted": old["task_export_permitted"],
              "allowed_workspaces": list(old["allowed_workspaces"]),
              "classifier": {"provider": provider, "model": old["classifier_model"],
                             "timeout_seconds": min(policy.get("timeout_seconds", 10), 30)},
              "policy": {"threshold": 0.5, "top_mode": policy.get("top_mode", "Main"),
                         "tiers": {tier: single(m) for tier, m in policy.get("tiers", {}).items() if tier in TIERS},
                         "fixed": single(policy["fixed"]) if "fixed" in policy else {},
                         "rates": policy.get("rates", {})}}
    if "workspace_allowlist_file" in old:
        result["workspace_allowlist_file"] = old["workspace_allowlist_file"]
    return validate(result)


def parse(data):
    """Parse bytes of either schema version; always returns v2."""
    if not isinstance(data, bytes):
        _invalid()
    if len(data) > MAX_BYTES:
        raise SettingsError("settings_oversized") from None
    try:
        document = json.loads(data.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys,
                              parse_constant=_reject_nonfinite_constant)
    except SettingsError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError, RecursionError):
        _invalid()
    if type(document) is dict and document.get("schema_version") == 1:
        return migrate_v1(parse_v1(data))
    return validate(document)


def _encode(value):
    data = (json.dumps(validate(value), sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    parse(data)
    return data


def _location(path, *, check_contents=True):
    try:
        path = owned.canonical_path(path)
        if path.name != "settings.json":
            raise SettingsError("settings_path_invalid")
        owned.verify(path.parent, "settings", FILES if check_contents else None)
        return path
    except (owned.OwnedError, OSError):
        raise SettingsError("settings_unowned") from None


def read(path):
    path = _location(path)
    try:
        return parse(owned.read_regular(path))
    except (owned.OwnedError, OSError):
        raise SettingsError("settings_read_failed") from None


def init(path):
    path = Path(path)
    if path.name != "settings.json":
        raise SettingsError("settings_path_invalid")
    try:
        root = owned.initialize(path.parent, "settings", FILES)
        with owned.locked(root, "settings", FILES):
            if not path.exists():
                owned.replace_owned(path, _encode(default_settings()))
        return read(path)
    except (owned.OwnedError, OSError):
        raise SettingsError("settings_unowned") from None


_CHANGEABLE = {"retention_days", "enabled", "task_export_permitted", "allowed_workspaces", "workspace_allowlist_file",
               "classifier", "policy"}


def update(path, *, expected_revision=None, **changes):
    """Atomic read-modify-write. Always writes v2 and bumps the revision."""
    path = _location(path, check_contents=False)
    if set(changes) - _CHANGEABLE:
        _invalid()
    try:
        with owned.locked(path.parent, "settings", FILES):
            value = read(path)
            if expected_revision is not None and (type(expected_revision) is not int or value["revision"] != expected_revision):
                raise SettingsError("settings_conflict")
            if "allowed_workspaces" in changes:
                changes["allowed_workspaces"] = [str(owned.canonical_path(p)) for p in changes["allowed_workspaces"]]
            candidate = {**value, **changes}
            if candidate.get("workspace_allowlist_file") is None:
                candidate.pop("workspace_allowlist_file", None)
            elif "workspace_allowlist_file" in changes:
                candidate["workspace_allowlist_file"] = str(owned.canonical_path(changes["workspace_allowlist_file"]))
            candidate = validate(candidate)
            # A v1 file differs on disk even when the migrated content is equal.
            on_disk_v1 = json.loads(owned.read_regular(path)).get("schema_version") == 1
            if candidate == value and not on_disk_v1:
                return value
            candidate["revision"] += 1
            owned.replace_owned(path, _encode(candidate))
            return read(path)
    except (owned.OwnedError, OSError):
        raise SettingsError("settings_write_failed") from None


workspace_allowed = legacy.workspace_allowed


def retention_days(settings):
    return settings.get("retention_days", DEFAULT_RETENTION_DAYS)


def effective_roots(settings):
    """Where routing applies and where that list lives: the allowlist file wins when one is set."""
    if "workspace_allowlist_file" not in settings:
        return list(settings["allowed_workspaces"]), "settings"
    path = settings["workspace_allowlist_file"]
    try:
        roots = json.loads(Path(path).read_text(encoding="utf-8"))["roots"]
        return [r for r in roots if isinstance(r, str)], path
    except (OSError, ValueError, KeyError, TypeError):
        return [], path


def write_allowlist_file(path, roots):
    """Atomic rewrite of the operator's (unversioned) allowlist file."""
    path = Path(path)
    data = json.dumps({"schema_version": 1, "roots": list(roots)}, indent=2) + "\n"
    tmp = path.with_name("." + path.name + ".mrh-tmp")
    tmp.write_text(data, encoding="utf-8")
    os.replace(tmp, path)


def resolve_settings_path(explicit=None, environ=None, home=None):
    """--settings > MRH_SETTINGS > ~/.config/model-routing-harness/active-settings."""
    environ = os.environ if environ is None else environ
    raw = str(explicit) if explicit else environ.get("MRH_SETTINGS", "").strip()
    if not raw:
        pointer = Path(home or Path.home()) / ".config" / "model-routing-harness" / "active-settings"
        try:
            raw = pointer.read_text(encoding="utf-8").strip()
        except OSError:
            raw = ""
    if not raw:
        raise SettingsError("settings_path_invalid")
    path = Path(raw)
    if not path.is_absolute() or path.name != "settings.json":
        raise SettingsError("settings_path_invalid")
    return path
