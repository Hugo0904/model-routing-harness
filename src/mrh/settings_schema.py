"""Strict, side-effect-free validation for persisted MRH settings."""

from __future__ import annotations

import json
import math
import unicodedata
from pathlib import Path
from typing import Any

from .types import safe_id, safe_model_id
from .typesafe_protocol import PINNED_MODEL


_MAX_SETTINGS_BYTES = 65_536
_TOP_LEVEL_KEYS = {
    "schema_version",
    "owner",
    "revision",
    "enabled",
    "task_export_permitted",
    "allowed_workspaces",
    "provider",
    "classifier_model",
    "policy",
}
_OWNER = "org.model-routing-harness.settings.v1"
_PROVIDER = "typesafe"
_POLICY_KEYS = {"top_mode", "timeout_seconds", "tiers", "fixed", "rates"}
_RATE_KEYS = {"currency", "unit", "service", "source_ref", "components"}
_TIERS = {"Light", "Small", "Mid", "Top"}


class SettingsError(ValueError):
    """A settings validation failure with a fixed, safe reason code."""

    def __init__(self, reason: str = "settings_invalid") -> None:
        if type(reason) is not str or reason not in {"settings_invalid", "settings_oversized", "settings_path_invalid",
                "settings_unowned", "settings_read_failed", "settings_write_failed", "settings_conflict"}:
            reason = "settings_invalid"
        self.reason = reason
        super().__init__(reason)


def _invalid() -> None:
    raise SettingsError("settings_invalid") from None


def _is_finite_number(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except (OverflowError, TypeError, ValueError):
        return False


def _require_exact_keys(value: dict, required: set[str], optional: set[str] = frozenset()) -> None:
    keys = set(value)
    if not required <= keys or keys - required - optional:
        _invalid()


def _validate_mapping(value: Any) -> dict:
    if type(value) is not dict:
        _invalid()
    _require_exact_keys(value, {"model"}, {"effort"})
    if not safe_model_id(value.get("model")):
        _invalid()
    if "effort" in value and not safe_id(value["effort"]):
        _invalid()
    return {key: value[key] for key in value}


def _validate_rates(value: Any) -> dict:
    if type(value) is not dict:
        _invalid()
    result = {}
    for model, rate in value.items():
        if not safe_model_id(model) or type(rate) is not dict:
            _invalid()
        _require_exact_keys(rate, _RATE_KEYS)
        for field in ("currency", "unit", "service"):
            if type(rate[field]) is not str or not rate[field]:
                _invalid()
        if not safe_id(rate["source_ref"]):
            _invalid()
        components = rate["components"]
        if type(components) is not dict or not components:
            _invalid()
        copied_components = {}
        for name, amount in components.items():
            if not safe_id(name) or not _is_finite_number(amount) or amount < 0:
                _invalid()
            copied_components[name] = amount
        result[model] = {
            "currency": rate["currency"],
            "unit": rate["unit"],
            "service": rate["service"],
            "source_ref": rate["source_ref"],
            "components": copied_components,
        }
    return result


def _validate_policy(value: Any) -> dict:
    if type(value) is not dict:
        _invalid()
    if set(value) - _POLICY_KEYS:
        _invalid()

    result = {}
    if "top_mode" in value:
        if type(value["top_mode"]) is not str or value["top_mode"] not in ("Main", "Fixed"):
            _invalid()
        result["top_mode"] = value["top_mode"]
    if "timeout_seconds" in value:
        timeout = value["timeout_seconds"]
        if not _is_finite_number(timeout) or not 0 < timeout <= 30:
            _invalid()
        result["timeout_seconds"] = timeout
    if "tiers" in value:
        tiers = value["tiers"]
        if type(tiers) is not dict or set(tiers) - _TIERS:
            _invalid()
        result["tiers"] = {tier: _validate_mapping(mapping) for tier, mapping in tiers.items()}
    if "fixed" in value:
        result["fixed"] = _validate_mapping(value["fixed"])
    if value.get("top_mode", "Main") == "Fixed" and "fixed" not in result:
        _invalid()
    if "rates" in value:
        result["rates"] = _validate_rates(value["rates"])
    return result


def _validate_workspace_path(value: Any) -> str:
    if type(value) is not str or not value or any(unicodedata.category(char) == "Cc" for char in value):
        _invalid()
    try:
        path = Path(value)
    except (TypeError, ValueError, OSError):
        _invalid()
    if not path.is_absolute() or str(path) != value or ".." in path.parts:
        _invalid()
    return value


def validate_settings(value: dict) -> dict:
    """Validate and return a fresh copy of a settings mapping."""
    if type(value) is not dict:
        _invalid()
    _require_exact_keys(value, _TOP_LEVEL_KEYS)
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        _invalid()
    if type(value["owner"]) is not str or value["owner"] != _OWNER:
        _invalid()
    if type(value["revision"]) is not int or value["revision"] < 0:
        _invalid()
    if type(value["enabled"]) is not bool or type(value["task_export_permitted"]) is not bool:
        _invalid()
    workspaces = value["allowed_workspaces"]
    if type(workspaces) is not list:
        _invalid()
    copied_workspaces = [_validate_workspace_path(path) for path in workspaces]
    if len(copied_workspaces) != len(set(copied_workspaces)):
        _invalid()
    if type(value["provider"]) is not str or value["provider"] != _PROVIDER:
        _invalid()
    if type(value["classifier_model"]) is not str or value["classifier_model"] != PINNED_MODEL:
        _invalid()

    return {
        "schema_version": 1,
        "owner": _OWNER,
        "revision": value["revision"],
        "enabled": value["enabled"],
        "task_export_permitted": value["task_export_permitted"],
        "allowed_workspaces": copied_workspaces,
        "provider": _PROVIDER,
        "classifier_model": PINNED_MODEL,
        "policy": _validate_policy(value["policy"]),
    }


def default_settings() -> dict:
    """Return a fresh, disabled settings document."""
    return {
        "schema_version": 1,
        "owner": _OWNER,
        "revision": 0,
        "enabled": False,
        "task_export_permitted": False,
        "allowed_workspaces": [],
        "provider": _PROVIDER,
        "classifier_model": PINNED_MODEL,
        "policy": {"top_mode": "Main", "timeout_seconds": 1.0, "tiers": {}, "rates": {}},
    }


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            _invalid()
        result[key] = value
    return result


def _reject_nonfinite_constant(_: str) -> None:
    _invalid()


def parse_settings(data: bytes) -> dict:
    """Parse a bounded UTF-8 JSON settings document and validate its schema."""
    if not isinstance(data, bytes):
        _invalid()
    if len(data) > _MAX_SETTINGS_BYTES:
        raise SettingsError("settings_oversized") from None
    try:
        value = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite_constant,
        )
    except SettingsError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError, RecursionError):
        _invalid()
    return validate_settings(value)
