"""Read-only resolution of persistent configuration and disposable runtime roots."""
import json
import os
from pathlib import Path
import sys

from mrh.infrastructure import owned
from mrh.infrastructure.settings_schema import SettingsError


def _root(value):
    try:
        path = owned.canonical_path(value)
        if path.exists() and not path.is_dir():
            raise owned.OwnedError("unsafe_path")
        return path
    except (TypeError, OSError, RuntimeError, ValueError) as exc:
        if isinstance(exc, owned.OwnedError):
            raise
        raise owned.OwnedError("unsafe_path") from None


def _windows_base(environ):
    # Import native APIs only on Windows, retaining the per-user ProgramData
    # location used by the installer and its private ownership boundary.
    from mrh.adapters.platforms.windows import current_sid
    return _root(Path(environ.get("PROGRAMDATA", "C:/ProgramData")) /
                 ("ModelRoutingHarness-" + current_sid()))


def default_config_root(environ=None, home=None):
    environ = os.environ if environ is None else environ
    if sys.platform == "win32":
        return _root(_windows_base(environ) / "config")
    return _root(Path(home or Path.home()) / ".config" / "model-routing-harness")


def default_runtime_root(environ=None, home=None):
    environ = os.environ if environ is None else environ
    if sys.platform == "win32":
        return _root(_windows_base(environ) / "runtime")
    base = Path(home or Path.home())
    if sys.platform == "darwin":
        return _root(base / "Library" / "Caches" / "model-routing-harness")
    return _root(base / ".cache" / "model-routing-harness")


def _generation():
    for parent in Path(__file__).absolute().parents:
        path = parent / "generation.json"
        if path.exists() or path.is_symlink():
            try:
                value = json.loads(owned.read_regular(path), object_pairs_hook=owned._unique)
            except (OSError, ValueError):
                raise owned.OwnedError("generation_metadata_invalid") from None
            if type(value) is not dict:
                raise owned.OwnedError("generation_metadata_invalid")
            return value
    return {}


def _legacy_runtime(value):
    project = _root(value)
    if not project.is_dir():
        raise owned.OwnedError("project_runtime_unavailable:請指定有效的 MRH_PROJECT_ROOT")
    return _root(project / "runtime")


def runtime_root():
    """Use installed binding, explicit source binding, or the user cache root.

    No source checkout or current working directory is discovered implicitly.
    Old generations keep their explicit project binding until reinstalled.
    """
    generation = _generation()
    if "runtime_root" in generation:
        return _root(generation["runtime_root"])
    if "MRH_RUNTIME_ROOT" in os.environ:
        return _root(os.environ["MRH_RUNTIME_ROOT"])
    if "project_root" in generation:
        return _legacy_runtime(generation["project_root"])
    if "MRH_PROJECT_ROOT" in os.environ:
        return _legacy_runtime(os.environ["MRH_PROJECT_ROOT"])
    return default_runtime_root()


def resolve_settings_path(explicit=None, environ=None, home=None):
    """--settings > MRH_SETTINGS > the default config's active-settings pointer."""
    environ = os.environ if environ is None else environ
    raw = str(explicit) if explicit else environ.get("MRH_SETTINGS", "").strip()
    if not raw:
        try:
            pointer = default_config_root(environ, home) / "active-settings"
            raw = pointer.read_text(encoding="utf-8").strip()
        except owned.OwnedError:
            raise SettingsError("settings_path_invalid") from None
        except OSError:
            raw = ""
    if not raw:
        raise SettingsError("settings_path_invalid")
    path = Path(raw)
    if not path.is_absolute() or path.name != "settings.json":
        raise SettingsError("settings_path_invalid")
    return path
