"""Prepare only MRH-owned artifacts; native registration/trust stays explicit."""
import hashlib
from importlib import metadata, resources
import io
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import zipfile
from . import owned, settings

NAME = "model-routing-harness"
MARKETPLACE = "model-routing-harness-local"
PLUGIN_ID = NAME + "@" + MARKETPLACE


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _json(value):
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


def _runtime_archive():
    buffer = io.BytesIO()
    package = resources.files("mrh")
    files = {"mrh/" + p.name: p.read_bytes() for p in package.iterdir() if p.name.endswith(".py")}
    files["__main__.py"] = b"from mrh.cli import main\nraise SystemExit(main())\n"
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
    return buffer.getvalue()


LAUNCHER = b'''"""Installed launcher: fixed binding, isolated Python, no cwd discovery."""
import hashlib,json,os
from pathlib import Path
try:
    root=Path(__file__).resolve().parent
    binding=json.loads((root/"binding.json").read_bytes())
    if set(binding)!={"schema_version","python","settings_path","runtime_sha256"} or binding["schema_version"]!=1:raise ValueError()
    runtime=root/"runtime.pyz"
    if hashlib.sha256(runtime.read_bytes()).hexdigest()!=binding["runtime_sha256"]:raise ValueError()
    python=binding["python"];settings=binding["settings_path"]
    if not Path(python).is_absolute() or not Path(settings).is_absolute():raise ValueError()
    os.execv(python,[python,"-I",str(runtime),"hook","--settings",settings])
except Exception:
    print("{}")
'''


def _old_artifact(root):
    """Validate every old owned byte before updating; never restore a snapshot."""
    root = owned.verify(root, "bundle")
    if not (root / "artifact.json").exists():
        if set(p.name for p in root.iterdir()) <= {owned.MARKER, ".mrh.lock"}:
            return None
        raise owned.OwnedError("owned_source_changed")
    try:
        artifact = json.loads(owned.read_regular(root / "artifact.json"), object_pairs_hook=owned._unique)
        files = artifact["files"]
        if artifact["owner"] != owned.OWNER or not isinstance(files, dict):
            raise ValueError()
        allowed = {"artifact.json", owned.MARKER, ".mrh.lock"} | set(files)
        directories = {str(parent) for name in files for parent in Path(name).parents if str(parent) != "."}
        for path in root.rglob("*"):
            name = path.relative_to(root).as_posix()
            if path.is_symlink() or (path.is_dir() and name not in directories) or (not path.is_dir() and name not in allowed):
                raise ValueError()
        for name, digest in files.items():
            path = root / name
            if not isinstance(name, str) or Path(name).is_absolute() or ".." in Path(name).parts or path.resolve() != path:
                raise ValueError()
            if _hash(owned.read_regular(path, 16_000_000)) != digest:
                raise ValueError()
        return artifact
    except (KeyError, ValueError, OSError):
        raise owned.OwnedError("owned_source_changed") from None


def prepare(root, settings_path, python=None):
    root = owned.canonical_path(root)
    settings_path = owned.canonical_path(settings_path)
    if root == settings_path.parent or root in settings_path.parents or settings_path.parent in root.parents:
        raise owned.OwnedError("settings_code_overlap")
    # Reject unknown target contents before touching either root.
    if root.exists() and any(root.iterdir()):
        _old_artifact(root)
    python = str(Path(python or sys.executable).resolve())
    check = subprocess.run([python, "-I", "-c", "import sys; print('%d.%d'%sys.version_info[:2])"],
                           env={"PATH": os.defpath}, capture_output=True, text=True, timeout=5, check=True)
    if tuple(map(int, check.stdout.strip().split("."))) < (3, 11):
        raise owned.OwnedError("unsupported_python")
    try:
        version = metadata.version(NAME)
    except metadata.PackageNotFoundError:
        # Development callers are explicitly labeled; host proof uses installed
        # wheel metadata and records the packaged bytes independently.
        version = "0.3.0"
    runtime = _runtime_archive()
    prefix = "plugins/" + NAME + "/"
    command = shlex.quote(python) + ' -I "${PLUGIN_ROOT}/launcher.py"'
    files = {
        ".agents/plugins/marketplace.json": _json({"name": MARKETPLACE, "plugins": [{"name": NAME,
            "source": {"source": "local", "path": "./plugins/" + NAME},
            "policy": {"installation": "AVAILABLE", "authentication": "ON_USE"}, "category": "Productivity"}]}),
        prefix + "plugin.json": _json({"name": NAME, "version": version,
            "description": "Default-off model routing with explicit workspace export permission",
            "extensions": {"com.openai": {"hooks": "./hooks/hooks.json"}}}),
        prefix + "hooks/hooks.json": _json({"hooks": {event: [{"matcher": "^spawn_agent$", "hooks": [
            {"type": "command", "command": command, "timeout": 35}]}] for event in ("PreToolUse", "PostToolUse")}}),
        prefix + "launcher.py": LAUNCHER,
        prefix + "runtime.pyz": runtime,
        prefix + "binding.json": _json({"schema_version": 1, "python": python, "settings_path": str(settings_path),
                                         "runtime_sha256": _hash(runtime)}),
    }
    root = owned.initialize(root, "bundle")
    with owned.locked(root, "bundle"):
        old = _old_artifact(root)
        if old is not None and old.get("settings_path") != str(settings_path):
            raise owned.OwnedError("registered_settings_conflict")
        settings.init(settings_path)  # Non-overwriting, separate writable state.
        for name, data in files.items():
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and owned.read_regular(target, 16_000_000) == data:
                continue
            owned.replace_owned(target, data)
        artifact = {"schema_version": 1, "owner": owned.OWNER, "version": version,
                    "plugin_id": PLUGIN_ID, "python": python, "python_version": check.stdout.strip(),
                    "settings_path": str(settings_path), "files": {name: _hash(data) for name, data in files.items()}}
        encoded = _json(artifact)
        if not (root / "artifact.json").exists() or owned.read_regular(root / "artifact.json") != encoded:
            owned.replace_owned(root / "artifact.json", encoded)
    return show(root)


def show(root):
    root = owned.canonical_path(root)
    artifact = _old_artifact(root)
    if artifact is None:
        raise owned.OwnedError("artifact_incomplete")
    return {"status": "prepared", "native_registration": "unverified", "hook_trust": "unverified",
            "live_routing_ready": False, "readiness_reason": "missing_role_protection", "artifact": artifact,
            "native_commands": [["codex", "plugin", "marketplace", "add", str(root), "--json"],
                ["codex", "plugin", "add", PLUGIN_ID, "--json"], ["codex", "plugin", "list", "--json"],
                ["codex", "plugin", "remove", PLUGIN_ID, "--json"]],
            "next_trust_step": "Review the current definitions in the native /hooks UI",
            "removal_state_policy": "Native uninstall preserves separate MRH settings and telemetry; no automatic deletion"}
