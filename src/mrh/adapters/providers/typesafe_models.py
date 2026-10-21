"""The Jev versions TypeSafe offers (`GET /v1/models`), cached for a day. Used only by the control center's model menu.

Nothing here runs in the hook. The API key is read through the caller's resolver, sent only in the Authorization header to the
fixed TypeSafe host, and never written to the cache file.
"""
from __future__ import annotations

import http.client
import json
import os
import ssl
import time
from pathlib import Path

from mrh.routing.classification_spec import JEV_ALIASES, TYPESAFE_MODEL, is_jev_model

CACHE_NAME = "jev-models.json"
STATE_ENV = "MRH_STATE_DIR"
FRESH_SECONDS = 24 * 3600
MAX_BODY = 65536
MAX_MODELS = 50
BUILT_IN = ({"name": "jev-latest", "description": "最新的正式穩定版（內建項目，沒有查到官方清單）", "release_date": ""},
            {"name": "jev-preview", "description": "最新版，含非正式版（內建項目，沒有查到官方清單）", "release_date": ""},
            {"name": TYPESAFE_MODEL, "description": "MRH 分級標準驗證過的版本（內建項目）", "release_date": ""})


class ModelsError(Exception):
    pass


def cache_path(environ=None):
    """Kept outside the settings directory on purpose: that directory only accepts the files MRH's readers know, and an
    unknown file would make an older generation (after a rollback) refuse the whole profile."""
    environ = os.environ if environ is None else environ
    from mrh.infrastructure import temporary
    base = temporary.area("cache")
    return base / CACHE_NAME


def _clip(value, limit):
    return " ".join(value.split())[:limit] if isinstance(value, str) else ""


def parse(body):
    """Keep only well-formed Jev entries; the cache never holds anything else."""
    try:
        data = json.loads(body)
    except (ValueError, UnicodeError):
        raise ModelsError("malformed") from None
    rows = data.get("models") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise ModelsError("malformed")
    models, seen = [], set()
    for row in rows[:MAX_MODELS * 2]:
        name = row.get("name") if isinstance(row, dict) else None
        if is_jev_model(name) and name not in seen:
            seen.add(name)
            models.append({"name": name, "description": _clip(row.get("description"), 200), "release_date": _clip(row.get("release_date"), 40)})
    if not models:
        raise ModelsError("malformed")
    return models[:MAX_MODELS]


class HttpModelsTransport:
    """GET https://api.typesafe.ai/v1/models; fixed origin and path, no redirects followed."""

    def get(self, headers, timeout):
        connection = http.client.HTTPSConnection("api.typesafe.ai", port=443, timeout=timeout, context=ssl.create_default_context())
        try:
            connection.request("GET", "/v1/models", headers=headers)
            response = connection.getresponse()
            body = response.read(MAX_BODY + 1)
            return response.status, body
        finally:
            connection.close()


def fetch(credential_resolver, transport=None, timeout=5.0):
    try:
        key = credential_resolver()
    except Exception:
        raise ModelsError("no_credentials") from None
    if not isinstance(key, str) or not 0 < len(key) <= 2048 or any(not 33 <= ord(c) <= 126 for c in key):
        raise ModelsError("no_credentials")
    try:
        status, body = (transport or HttpModelsTransport()).get({"Authorization": "Bearer " + key, "Accept": "application/json"}, timeout)
    except Exception:
        raise ModelsError("network") from None
    if status != 200 or not isinstance(body, bytes) or len(body) > MAX_BODY:
        raise ModelsError(f"http_{status}")
    return parse(body)


def _load(path):
    try:
        data = json.loads(Path(path).read_text())
        if (isinstance(data, dict) and isinstance(data.get("fetched_at"), (int, float)) and isinstance(data.get("models"), list)
                and all(isinstance(m, dict) and is_jev_model(m.get("name")) for m in data["models"])):
            return data
    except (OSError, ValueError):
        pass
    return None


def _save(path, models, now):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    from mrh.infrastructure import owned
    from contextlib import nullcontext
    from mrh.infrastructure import temporary
    managed = temporary.area('cache')
    guard = owned.locked(managed, 'disposable_cache', blocking=False) if path.parent == managed else nullcontext()
    with guard:
        owned.replace_owned(path, json.dumps({'fetched_at': now, 'models': models}, ensure_ascii=False).encode())


def known_models(cache_path, now, fetcher=None):
    """(models, note). A fresh cache is used as is; otherwise one fetch is attempted; a failure falls back to an older cache,
    then to the built-in list, and the note says so."""
    cached = _load(cache_path)
    if cached and now - cached["fetched_at"] < FRESH_SECONDS:
        return cached["models"], f"官方清單（快取，{int((now - cached['fetched_at']) // 3600)} 小時前更新）"
    if fetcher is not None:
        try:
            models = fetcher()
            _save(cache_path, models, now)
            return models, "官方清單（剛更新）"
        except Exception:
            pass
    if cached:
        return cached["models"], f"清單未更新：沿用 {max(1, int((now - cached['fetched_at']) // 86400))} 天前的快取"
    return [dict(m) for m in BUILT_IN], "清單未更新：查不到官方清單（沒有金鑰或沒有網路），只列內建項目"


def choices(models, current):
    """Menu entries in a sensible order: the aliases first, then exact versions newest first. The current setting is always present."""
    names = [m["name"] for m in models]
    ordered = [n for n in JEV_ALIASES if n in names] + sorted((n for n in names if n not in JEV_ALIASES), reverse=True)
    if current not in ordered:
        ordered.append(current)
    by_name = {m["name"]: m for m in models}
    result = []
    for name in ordered:
        info = by_name.get(name, {})
        note = {"jev-latest": "最新的正式穩定版；官方推出新版時會自己換，答案可能跟著改變",
                "jev-preview": "最新版，含非正式版；會自己換版本"}.get(name) or info.get("description") or ""
        date = f"（{info['release_date']}）" if info.get("release_date") else ""
        result.append((name, f"{name}{date}" + (f"　{note}" if note else "")))
    return result
