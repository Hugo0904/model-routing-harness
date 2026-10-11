"""Explicit MRH-owned settings; no task-relative discovery or credentials."""
import json
from pathlib import Path
from mrh.infrastructure import owned
from mrh.infrastructure.settings_schema import SettingsError, default_settings, parse_settings, validate_settings

FILES = {"settings.json", "model-profile.json", "events.sqlite3", "events.sqlite3.lock", "events.sqlite3.key", "events.sqlite3-wal", "events.sqlite3-shm"}


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
        return parse_settings(owned.read_regular(path))
    except (owned.OwnedError, OSError):
        raise SettingsError("settings_read_failed") from None


def init(path):
    path = Path(path)
    if path.name != "settings.json":
        raise SettingsError("settings_path_invalid")
    try:
        root = owned.initialize(path.parent, "settings", FILES)
        with owned.locked(root, "settings", FILES):
            if path.exists():
                return read(path)  # Initialization never resets or re-enables.
            value = default_settings()
            owned.replace_owned(path, _encode(value))
            return read(path)
    except (owned.OwnedError, OSError):
        raise SettingsError("settings_unowned") from None


def _encode(value):
    data = (json.dumps(validate_settings(value), sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    parse_settings(data)  # Reject oversized output before replacing old bytes.
    return data


def update(path, *, expected_revision=None, **changes):
    path = _location(path, check_contents=False)
    if set(changes) - {"enabled", "task_export_permitted", "allowed_workspaces", "workspace_allowlist_file", "policy", "provider", "classifier_model"}:
        raise SettingsError("settings_invalid")
    try:
        with owned.locked(path.parent, "settings", FILES):
            value = read(path)
            if expected_revision is not None and (type(expected_revision) is not int or value["revision"] != expected_revision):
                raise SettingsError("settings_conflict")
            if "allowed_workspaces" in changes:
                # Only explicit operator mutations can register roots. Scope at
                # runtime uses host cwd metadata, never tool-input declarations.
                changes["allowed_workspaces"] = [str(owned.canonical_path(p)) for p in changes["allowed_workspaces"]]
            candidate = {**value, **changes}
            if "workspace_allowlist_file" in changes:
                if changes["workspace_allowlist_file"] is None:
                    candidate.pop("workspace_allowlist_file", None)
                else:
                    candidate["workspace_allowlist_file"] = str(owned.canonical_path(changes["workspace_allowlist_file"]))
            candidate = validate_settings(candidate)
            if candidate == value:
                return value
            candidate["revision"] += 1
            owned.replace_owned(path, _encode(candidate))
            return read(path)
    except (owned.OwnedError, OSError):
        raise SettingsError("settings_write_failed") from None


def workspace_allowed(value, cwd):
    roots = value["allowed_workspaces"]
    if "workspace_allowlist_file" in value:
        try:
            from mrh.infrastructure.settings_schema import _reject_duplicate_keys, _reject_nonfinite_constant
            path = owned.canonical_path(value["workspace_allowlist_file"])
            document = json.loads(owned.read_regular(path, 65536).decode("utf-8"),
                                  object_pairs_hook=_reject_duplicate_keys, parse_constant=_reject_nonfinite_constant)
            if (type(document) is not dict or set(document) != {"schema_version", "roots"}
                    or type(document["schema_version"]) is not int or document["schema_version"] != 1
                    or type(document["roots"]) is not list):
                raise ValueError()
            roots = document["roots"]
            if any(type(root) is not str or str(owned.canonical_path(root)) != root for root in roots):
                raise ValueError()
            if len(roots) != len(set(roots)):
                raise ValueError()
        except (ValueError, OSError, UnicodeError, RecursionError, TypeError):
            raise SettingsError("workspace_allowlist_invalid") from None
    if not isinstance(cwd, str):
        return False
    try:
        path = owned.canonical_path(cwd)
        return any(path == Path(root) or Path(root) in path.parents for root in roots)
    except (ValueError, OSError):
        return False
