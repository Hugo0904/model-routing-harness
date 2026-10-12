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
from mrh.infrastructure import owned; from mrh.infrastructure import settings

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
            elif resource.is_file() and resource.name.endswith(".py"):
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
    if isinstance(event,dict) and event.get("hook_event_name")=="PreToolUse" and event.get("tool_name") in ("spawn_agent","collaborationspawn_agent") and isinstance(event.get("tool_input"),dict):
        description="runtime integrity verification failed" if reason=="runtime_integrity" else "the Hook runtime could not be loaded or completed"
        return {"systemMessage":"MRH: "+description+"; original tool call preserved. Use mrh stats --details with this profile's --settings or --db. Recording and warning deduplication are unavailable; this fault may be absent from history."}
    return {}
try:
    data=sys.stdin.buffer.read(1048577)
    if len(data)>1048576:raise ValueError()
    event=json.loads(data)
    root=Path(__file__).resolve().parent
    binding=json.loads((root/"binding.json").read_bytes())
    base={"schema_version","python","settings_path","runtime_sha256"}
    if set(binding) not in (base,base|{"codex_scope"}) or binding["schema_version"]!=1:raise ValueError()
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
        if "codex_scope" in binding:args += ["--scope-binding",str(root/"binding.json")]
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


def prepare(root, settings_path, python=None, *, scope_workspace=None, codex_binary=None, scope_contract=None):
    root = owned.canonical_path(root)
    settings_path = owned.canonical_path(settings_path)
    if root == settings_path.parent or root in settings_path.parents or settings_path.parent in root.parents:
        raise owned.OwnedError("settings_code_overlap")
    # Reject unknown target contents before touching either root.
    old_artifact = _old_artifact(root) if root.exists() and any(root.iterdir()) else None
    python = str(Path(python or sys.executable).resolve())
    scope=old_artifact.get('codex_scope') if old_artifact is not None else None
    if scope_workspace is not None:
        from mrh.adapters.hosts.codex_scope import prepare as prepare_scope, ScopeError
        from mrh.adapters.catalogs.catalog import discover
        if codex_binary is None:
            found=next((c['executable'] for c in discover() if c['tool']=='codex'),None)
            if found is None:raise ScopeError('scope_unsupported')
            codex_binary=found
        if scope_contract == 'fresh-root-cli':
            from mrh.adapters.hosts.fresh_cli_scope import prepare as prepare_fresh
            scope=prepare_fresh(codex_binary,Path(os.environ.get('CODEX_HOME',Path.home()/'.codex')),
                                scope_workspace,settings_path.parent/'fresh-cli-sessions',python)
        else:
            scope=prepare_scope(codex_binary,Path(os.environ.get('CODEX_HOME',Path.home()/'.codex')),scope_workspace)
    elif scope_contract is not None:
        from mrh.adapters.hosts.codex_scope import ScopeError
        raise ScopeError('scope_unsupported')
    elif scope is not None:
        from mrh.adapters.hosts.codex_scope import check
        check(scope)
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
        version = "0.3.0"
    runtime = _runtime_archive()
    prefix = "plugins/" + NAME + "/"
    command = shlex.quote(python) + ' -I -B "${PLUGIN_ROOT}/launcher.py"'
    files = {
        ".agents/plugins/marketplace.json": _json({"name": MARKETPLACE, "plugins": [{"name": NAME,
            "source": {"source": "local", "path": "./plugins/" + NAME},
            "policy": {"installation": "AVAILABLE", "authentication": "ON_USE"}, "category": "Productivity"}]}),
        prefix + "plugin.json": _json({"name": NAME, "version": version,
            "description": "Default-off model routing with explicit workspace export permission",
            "extensions": {"com.openai": {"hooks": "./hooks/hooks.json"}}}),
        prefix + "hooks/hooks.json": _json({"hooks": {event: [{"matcher": "^(spawn_agent|collaborationspawn_agent)$", "hooks": [
            {"type": "command", "command": command, "timeout": 50}]}] for event in ("PreToolUse", "PostToolUse")}}),
        prefix + "launcher.py": LAUNCHER,
        prefix + "runtime.pyz": runtime,
        prefix + "binding.json": _json({"schema_version": 1, "python": python, "settings_path": str(settings_path),
                                         "runtime_sha256": _hash(runtime)}),
    }
    if scope is not None:
        from mrh.adapters.hosts.fresh_cli_scope import CONTRACT as fresh_contract
        if scope['contract'] == fresh_contract:
            hooks=json.loads(files[prefix+'hooks/hooks.json'])
            hooks['hooks']['SessionStart']=[{'matcher':'.*','hooks':[{'type':'command','command':command,'timeout':50}]}]
            files[prefix+'hooks/hooks.json']=_json(hooks)
        files[prefix+'binding.json']=_json({'schema_version':1,'python':python,'settings_path':str(settings_path),
                                         'runtime_sha256':_hash(runtime),'codex_scope':scope})
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
            owned.replace_owned(target, data, limit=16_000_000 if name.endswith('/runtime.pyz') else 65536)
        artifact = {"schema_version": 1, "owner": owned.OWNER, "version": version,
                    "plugin_id": PLUGIN_ID, "python": python, "python_version": check.stdout.strip(),
                    "settings_path": str(settings_path), "files": {name: _hash(data) for name, data in files.items()}}
        if scope is not None:artifact['codex_scope']=scope
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
    if artifact.get('codex_scope') is not None:
        from mrh.adapters.hosts.codex_scope import check, ScopeError
        try:
            result['configuration_scope']=check(artifact['codex_scope'])
            result['readiness_reason']='native_trust_and_activation_unverified'
        except (ScopeError,OSError,ValueError):
            result['configuration_scope']={'status':'invalidated'}
            result['readiness_reason']='scope_changed'
    return result
