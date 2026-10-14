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
from mrh.infrastructure import owned

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
    files = {}

    def collect(folder, prefix):
        for resource in sorted(folder.iterdir(), key=lambda item: item.name):
            name = prefix + resource.name
            if resource.is_dir():
                collect(resource, name + "/")
            elif resource.is_file() and (resource.name.endswith(".py") or prefix.startswith('mrh/resources/')):
                files[name] = resource.read_bytes()

    collect(package, "mrh/")
    files["__main__.py"] = b"from mrh.cli import main\nraise SystemExit(main())\n"
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
    return buffer.getvalue()


LAUNCHER = b'''"""Independent installed supervisor; never imports the runtime to report its failure."""
import hashlib,json,os,signal,subprocess,sys,tempfile
from pathlib import Path
event=None
reason="runtime_load"
def failed():
    if isinstance(event,dict) and event.get("hook_event_name")=="PreToolUse" and event.get("tool_name") in ("spawn_agent","collaborationspawn_agent") and isinstance(event.get("tool_input"),dict) and str(event["tool_input"].get("task_name","")).startswith(("mrh_packet_","mrh_release_")):
        return {"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"MRH Codex packet: runtime unavailable; dispatch stopped, outcome unknown. Do not retry or fall back to title classification."}}
    if isinstance(event,dict) and event.get("hook_event_name")=="PreToolUse" and event.get("tool_name") in ("spawn_agent","collaborationspawn_agent","Agent","Task") and isinstance(event.get("tool_input"),dict):
        description="runtime integrity verification failed" if reason=="runtime_integrity" else "the Hook runtime could not be loaded or completed"
        return {"systemMessage":"MRH: "+description+"; original tool call preserved. Use mrh stats with this profile's --settings. Recording and warning deduplication are unavailable; this fault may be absent from history."}
    return {}
try:
    data=sys.stdin.buffer.read(1048577)
    if len(data)>1048576:raise ValueError()
    event=json.loads(data)
    root=Path(__file__).resolve().parent
    binding=json.loads((root/"binding.json").read_bytes())
    base={"schema_version","python","settings_path","runtime_sha256"}
    if set(binding) not in (base,base|{"platform"},base|{"platform","codex_packets"}) or binding["schema_version"]!=1:raise ValueError()
    platform=sys.argv[1] if len(sys.argv)>1 else binding.get("platform","codex")
    if platform not in (None,"codex","claude"):raise ValueError()
    packets=binding.get("codex_packets",False)
    if "codex_packets" in binding and (packets is not True or platform!="codex" or binding.get("platform")!="codex"):raise ValueError()
    runtime=root/"runtime.pyz"
    reason="runtime_integrity"
    if hashlib.sha256(runtime.read_bytes()).hexdigest()!=binding["runtime_sha256"]:raise ValueError()
    reason="runtime_load"
    python=binding["python"];settings=binding["settings_path"]
    if not Path(python).is_absolute() or not Path(settings).is_absolute():raise ValueError()
    # Captured stderr is discarded, including Python import tracebacks. A file
    # bounds readback without holding arbitrary failed-runtime output in memory.
    with tempfile.TemporaryFile() as output:
        args=[python,"-I","-B",str(runtime),"hook","--settings",settings]
        if platform:args += ["--platform",platform]
        if packets:args += ["--codex-packets"]
        process=subprocess.Popen(args,stdin=subprocess.PIPE,stdout=output,stderr=subprocess.DEVNULL,start_new_session=True)
        try:
            process.communicate(data,timeout=48)
        except BaseException:
            if process.poll() is None and os.getpgid(process.pid)==process.pid:
                os.killpg(process.pid,signal.SIGKILL)
            process.wait()
            raise
        output.seek(0);raw=output.read(1048577)
    if process.returncode!=0 or len(raw)>1048576:raise ValueError()
    result=json.loads(raw)
    if not isinstance(result,dict) or set(result)-{"systemMessage","hookSpecificOutput"}:raise ValueError()
    if packets and isinstance(event,dict) and event.get("hook_event_name")=="PreToolUse" and isinstance(event.get("tool_input"),dict) and str(event["tool_input"].get("task_name","")).startswith(("mrh_packet_","mrh_release_")) and result.get("hookSpecificOutput",{}).get("permissionDecision") not in ("allow","deny"):raise ValueError()
    print(json.dumps(result,separators=(",",":")))
except Exception:
    print(json.dumps(failed(),separators=(",",":")))
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


def prepare(root, settings_path, python=None, *, advisory=False, codex_packets=False):
    if not advisory:
        raise owned.OwnedError("advisory_required")
    root = owned.canonical_path(root)
    settings_path = owned.canonical_path(settings_path)
    if root == settings_path.parent or root in settings_path.parents or settings_path.parent in root.parents:
        raise owned.OwnedError("settings_code_overlap")
    # Reject unknown target contents before touching either root.
    old_artifact = _old_artifact(root) if root.exists() and any(root.iterdir()) else None
    python = str(Path(python or sys.executable).resolve())
    check = subprocess.run([python, "-I", "-B", "-c", "import sys; print('%d.%d'%sys.version_info[:2])"],
                           env={"PATH": os.defpath}, capture_output=True, text=True, timeout=5, check=True)
    if tuple(map(int, check.stdout.strip().split("."))) < (3, 11):
        raise owned.OwnedError("unsupported_python")
    try:
        version = metadata.version(NAME)
    except metadata.PackageNotFoundError:
        # Development callers are explicitly labeled; host proof uses installed
        # wheel metadata and records the packaged bytes independently.
        version = "0.4.0"
    runtime = _runtime_archive()
    prefix = "plugins/" + NAME + "/"
    command = shlex.quote(python) + ' -I -B "${PLUGIN_ROOT}/launcher.py"'
    files = {
        ".agents/plugins/marketplace.json": _json({"name": MARKETPLACE, "plugins": [{"name": NAME,
            "source": {"source": "local", "path": "./plugins/" + NAME},
            "policy": {"installation": "AVAILABLE", "authentication": "ON_USE"}, "category": "Productivity"}]}),
        prefix + "plugin.json": _json({"$schema":"https://agent-plugins.org/schemas/1.0.0/plugin.schema.json", "name": NAME, "version": version,
            "description": "Default-off model routing with explicit workspace export permission",
            "extensions": {"com.openai": {"hooks": "./hooks/hooks.json"}}}),
        prefix + "hooks/hooks.json": _json({"hooks": {event: [{"matcher": "^(spawn_agent|collaborationspawn_agent)$", "hooks": [
            {"type": "command", "command": command, "timeout": 50}]}] for event in ("PreToolUse", "PostToolUse")}}),
        prefix + "launcher.py": LAUNCHER,
        prefix + "runtime.pyz": runtime,
        prefix + "binding.json": _json({"schema_version": 1, "python": python, "settings_path": str(settings_path),
                                         "runtime_sha256": _hash(runtime), "platform": "codex",
                                         **({"codex_packets": True} if codex_packets else {})}),
    }
    if codex_packets:
        skill = resources.files('mrh').joinpath('resources/skills/mrh-codex-packet/SKILL.md').read_bytes()
        files[prefix+'skills/mrh-codex-packet/SKILL.md'] = skill
    root = owned.initialize(root, "bundle")
    with owned.locked(root, "bundle"):
        old = _old_artifact(root)
        if old is not None and old.get("settings_path") != str(settings_path):
            raise owned.OwnedError("registered_settings_conflict")
        from mrh.infrastructure import settings_v2
        settings_v2.init(settings_path)  # v1/v2 read compatibility, no existing-file rewrite
        for name, data in files.items():
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and owned.read_regular(target, 16_000_000) == data:
                continue
            owned.replace_owned(target, data, limit=16_000_000 if name.endswith('/runtime.pyz') else 65536)
        artifact = {"schema_version": 1, "owner": owned.OWNER, "version": version,
                    "plugin_id": PLUGIN_ID, "python": python, "python_version": check.stdout.strip(),
                    "settings_path": str(settings_path), "files": {name: _hash(data) for name, data in files.items()}}
        if codex_packets:
            artifact["codex_packets"] = True
        encoded = _json(artifact)
        if not (root / "artifact.json").exists() or owned.read_regular(root / "artifact.json") != encoded:
            owned.replace_owned(root / "artifact.json", encoded)
    return show(root)


def show(root):
    root = owned.canonical_path(root)
    artifact = _old_artifact(root)
    if artifact is None:
        raise owned.OwnedError("artifact_incomplete")
    result={"status": "prepared", "native_registration": "unverified", "hook_trust": "unverified",
            "live_routing_ready": False, "readiness_reason": "missing_role_protection", "artifact": artifact,
            "native_commands": [["codex", "plugin", "marketplace", "add", str(root), "--json"],
                ["codex", "plugin", "add", PLUGIN_ID, "--json"], ["codex", "plugin", "list", "--json"],
                ["codex", "plugin", "remove", PLUGIN_ID, "--json"]],
            "next_trust_step": "Review the current definitions in the native /hooks UI",
            "removal_state_policy": "Native uninstall preserves separate MRH settings and telemetry; no automatic deletion"}
    return result
