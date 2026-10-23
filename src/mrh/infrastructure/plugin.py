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


LAUNCHER = br'''"""Independent installed supervisor; failure output never imports the runtime."""
import time
started=time.monotonic()
import hashlib,json,os,signal,subprocess,sys,tempfile
from pathlib import Path
event=None
reason="runtime_load"
def failed():
    if isinstance(event,dict) and event.get("hook_event_name")=="PreToolUse" and event.get("tool_name") in ("spawn_agent","collaborationspawn_agent") and isinstance(event.get("tool_input"),dict) and str(event["tool_input"].get("task_name","")).startswith(("mrh_packet_","mrh_release_")):
        return {"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"MRH Codex packet: runtime unavailable; dispatch stopped, outcome unknown. Do not retry or fall back to title classification. Continue independent work and briefly inform the user."}}
    if not isinstance(event,dict) or event.get("hook_event_name") not in ("PreToolUse","PostToolUse") or event.get("tool_name") not in ("spawn_agent","collaborationspawn_agent","Agent","Task") or not isinstance(event.get("tool_input"),dict):
        return {}
    description={"runtime_integrity":"runtime integrity verification failed","settings_invalid":"settings unavailable","hook_timeout":"hook time budget exhausted"}.get(reason,"Hook runtime unavailable")
    text="MRH: "+description+"; original tool call preserved. Original work continues. "
    text+=("The tool already returned; do not repeat a successful tool. " if event["hook_event_name"]=="PostToolUse" else "Do not retry the original tool. ")
    text+="Briefly inform the user. Recording and warning deduplication are unavailable; this event may be absent from history and its result remains unknown."
    return {"systemMessage":text,"hookSpecificOutput":{"hookEventName":event["hook_event_name"],"additionalContext":text}}
try:
    data=sys.stdin.buffer.read(1048577)
    if len(data)>1048576:raise ValueError()
    event=json.loads(data)
    root=Path(__file__).resolve().parent
    binding=json.loads((root/"binding.json").read_bytes())
    base={"schema_version","python","settings_path","runtime_sha256"}
    if set(binding)-{"project_root","runtime_root","dev_source","editable_sha256"} not in (base,base|{"platform"},base|{"platform","codex_packets"}) or binding["schema_version"]!=1:raise ValueError()
    platform=sys.argv[1] if len(sys.argv)>1 else binding.get("platform","codex")
    if platform not in (None,"codex","claude"):raise ValueError()
    packets=binding.get("codex_packets",False)
    if "codex_packets" in binding and (packets is not True or platform!="codex" or binding.get("platform")!="codex"):raise ValueError()
    runtime=root/"runtime.pyz"
    reason="runtime_integrity"
    dev=binding.get("dev_source")
    if hashlib.sha256(runtime.read_bytes()).hexdigest()!=binding["runtime_sha256"]:raise ValueError()
    if dev is not None:
        if not isinstance(dev,str) or not Path(dev).is_absolute():raise ValueError()
        links=binding["editable_sha256"]
        if set(links)!={"model_routing_harness-editable.pth","model_routing_harness-editable.json"}:raise ValueError()
        for name,digest in links.items():
            if hashlib.sha256((root/"editable"/name).read_bytes()).hexdigest()!=digest:raise ValueError()
    python=binding["python"];settings=binding["settings_path"]
    if "runtime_root" in binding:
        area=Path(binding["runtime_root"])
        if not area.is_absolute() or area.resolve()!=area:raise ValueError()
        os.environ.pop("MRH_PROJECT_ROOT",None)
        os.environ["MRH_RUNTIME_ROOT"]=str(area)
    else:
        project=Path(binding.get("project_root") or os.environ["MRH_PROJECT_ROOT"])
        if not project.is_absolute() or project.resolve()!=project or not project.is_dir():raise ValueError()
        os.environ["MRH_PROJECT_ROOT"]=str(project)
    if not Path(python).is_absolute() or not Path(settings).is_absolute():raise ValueError()
    # No-op input still verifies the bound runtime; no CLI or hook child is needed.
    if not isinstance(event,dict) or event.get("hook_event_name") not in ("PreToolUse","PostToolUse"):
        result={}
    else:
        # The verified child uses the existing validator and reports only its
        # policy over a private pipe. The supervisor imports no runtime code.
        # Unvalidated/failed children never qualify for the long provider path.
        deadline=started+1.0
        reason="hook_timeout"
        code=("import sys;sys.path.insert(0,sys.argv[1]);"
              "from mrh.infrastructure.execution import activate_editable;"
              "activate_editable(sys.argv[7],sys.argv[8]) if sys.argv[8] else None;"
              "from mrh.application.advisory_runtime import run;"
              "raise SystemExit(run(sys.argv[2],sys.argv[3],sys.stdin,sys.stdout,sys.stderr,"
              "started=float(sys.argv[4]),control_fd=int(sys.argv[5]),codex_packets=sys.argv[6]=='1'))")
        reader,writer=os.pipe();os.set_blocking(reader,False)
        process=None
        try:
            args=[python,"-I","-B","-c",code,str(runtime),platform or "codex",settings,repr(started),str(writer),"1" if packets else "0",str(root/"editable"),dev or ""]
            process=subprocess.Popen(args,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,start_new_session=True,pass_fds=(writer,))
            os.close(writer);writer=None
            pending=data;buffer=b"";established=False
            while True:
                remaining=deadline-time.monotonic()
                if remaining<=0:raise TimeoutError()
                try:
                    raw,_=process.communicate(pending,timeout=min(.02,remaining))
                    break
                except subprocess.TimeoutExpired:
                    pending=None
                try:chunk=os.read(reader,1025)
                except BlockingIOError:chunk=b""
                buffer+=chunk
                if len(buffer)>1024:raise ValueError()
                while b"\n" in buffer:
                    line,buffer=buffer.split(b"\n",1);policy=json.loads(line)
                    seconds=policy.get("seconds") if isinstance(policy,dict) else None
                    if type(seconds) not in (int,float) or seconds not in (1.0,2.5,48.0):raise ValueError()
                    if event.get("hook_event_name")=="PostToolUse":seconds=min(seconds,1.0)
                    proposed=started+seconds
                    deadline=min(deadline,proposed) if established else proposed
                    established=True
        except BaseException:
            if process is not None:
                if process.poll() is None:
                    try:os.killpg(process.pid,signal.SIGKILL)
                    except ProcessLookupError:pass
                process.wait()
            raise
        finally:
            os.close(reader)
            if writer is not None:os.close(writer)
        reason="runtime_load"
        if process.returncode!=0 or len(raw)>1048576:raise ValueError()
        result=json.loads(raw)
        if not isinstance(result,dict) or set(result)-{"systemMessage","hookSpecificOutput"}:raise ValueError()
        specific=result.get("hookSpecificOutput")
        if specific is not None and (not isinstance(specific,dict) or specific.get("hookEventName")!=event.get("hook_event_name")):raise ValueError()
        if event.get("hook_event_name")=="PostToolUse" and specific and ("permissionDecision" in specific or "updatedInput" in specific):raise ValueError()
        if packets and event.get("hook_event_name")=="PreToolUse" and isinstance(event.get("tool_input"),dict) and str(event["tool_input"].get("task_name","")).startswith(("mrh_packet_","mrh_release_")) and result.get("hookSpecificOutput",{}).get("permissionDecision") not in ("allow","deny"):raise ValueError()
    print(json.dumps(result,separators=(",",":")))
except Exception:
    print(json.dumps(failed(),separators=(",",":")))
'''


def codex_hook_timeout(event, windows=None):
    """Host-side hook limit (seconds) written into the Codex plugin's hooks.json.

    Windows Post gets 5 s: the supervisor's 2.0 s deadline starts only after PowerShell and bootstrap
    (~1-1.5 s), so a 2 s host limit kills the hook first. Any other platform keeps 2 s exactly.
    Changing this value changes the hook definition, which Codex asks the user to trust again.
    """
    windows = os.name == 'nt' if windows is None else windows
    return 50 if event == "PreToolUse" else (5 if windows else 2)


def _windows_launcher():
    """Same protocol and deadlines; native Job and inherited-handle transport.

    Embed the stdlib-only process adapter so failure handling never needs to
    import application code. The POSIX supervisor remains byte-for-byte intact.
    """
    job = resources.files('mrh').joinpath('adapters/platforms/windows_process.py').read_bytes()
    source = LAUNCHER.decode()
    source = source.replace('import hashlib,json,os,signal,subprocess,sys,tempfile',
                            'import hashlib,json,os,signal,subprocess,sys,tempfile,msvcrt,queue,threading')
    source = source.replace('import sys;sys.path.insert', 'import sys,os;sys.path.insert')
    source = source.replace('control_fd=int(sys.argv[5])',
                            'control_fd=msvcrt.open_osfhandle(int(sys.argv[5]),os.O_WRONLY)')
    # msvcrt is imported in the child, not merely in the supervisor.
    source = source.replace('import sys,os;sys.path.insert', 'import sys,os,msvcrt;sys.path.insert')
    source = source.replace('reader,writer=os.pipe();os.set_blocking(reader,False)', '''reader,writer=os.pipe()
        controls=queue.Queue()
        def collect_control():
            try:
                while True:
                    chunk=os.read(reader,1025)
                    if not chunk:break
                    controls.put(chunk)
            except OSError:pass
        control_thread=threading.Thread(target=collect_control,daemon=True)
        control_thread.start()
        control_handle=msvcrt.get_osfhandle(writer)
        os.set_handle_inheritable(control_handle,True)
        startup=subprocess.STARTUPINFO()
        startup.lpAttributeList={"handle_list":[control_handle]}''')
    source = source.replace('str(writer),"1"', 'str(control_handle),"1"')
    source = source.replace('args=[python,"-I","-B",', 'args=[python,"-I","-B","-X","utf8",')
    # Windows process creation and runtime import routinely take 0.4-1.1 s, and the child can only
    # report its policy after that. The first policy line may therefore take up to 2.5 s for
    # PreToolUse and 2.0 s for PostToolUse, and a reported local-only Pre policy is 2.5 s (see
    # hook_budget.LOCAL_SECONDS/POST_SECONDS). The reported policy still replaces the first-stage
    # deadline; the Jev (2.5 s) and verified (48 s) policies, the integrity, settings and Job
    # checks, and the policy-value validation itself are unchanged.
    for old, new in (
        ('        deadline=started+1.0\n',
         '        deadline=started+(2.5 if event.get("hook_event_name")=="PreToolUse" else 2.0)\n'),
        ('seconds not in (1.0,2.5,48.0)', 'seconds not in (1.0,2.0,2.5,48.0)'),
        ('seconds=min(seconds,1.0)', 'seconds=min(seconds,2.0)'),
    ):
        if source.count(old) != 1:
            raise owned.OwnedError('windows_launcher_deadline_template_mismatch')
        source = source.replace(old, new, 1)
    source = source.replace('process=subprocess.Popen(args,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,start_new_session=True,pass_fds=(writer,))',
                            'process=popen_python(python,code,args[7:],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,startupinfo=startup,close_fds=True)')
    control_read = 'try:chunk=os.read(reader,1025)\n                except BlockingIOError:chunk=b""'
    if source.count(control_read) != 1:
        raise owned.OwnedError('windows_launcher_control_read_template_mismatch')
    source = source.replace(control_read,
                            'try:chunk=controls.get_nowait()\n                except queue.Empty:chunk=b""', 1)
    source = source.replace('try:os.killpg(process.pid,signal.SIGKILL)\n                    except ProcessLookupError:pass',
                            'process._mrh_job.close()')
    source = source.replace('            os.close(reader)\n            if writer is not None:os.close(writer)',
                            '            if writer is not None:os.close(writer)\n            if process is not None:finish(process)\n            control_thread.join(timeout=1)\n            os.close(reader)')
    return job + b'\n' + source.encode()


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
        directories = {parent.as_posix() for name in files for parent in Path(name).parents if str(parent) != "."}
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


def prepare(root, settings_path, python=None, *, advisory=False, codex_packets=False, project_root=None, dev_source=None,
            runtime_archive=None, editable_files=None, runtime_root=None):
    if not advisory:
        raise owned.OwnedError("advisory_required")
    if dev_source is not None:
        dev_source = owned.canonical_path(dev_source)
        if not (dev_source / "src/mrh").is_dir():
            raise owned.OwnedError("dev_source_invalid")
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
    runtime = _runtime_archive() if runtime_archive is None else runtime_archive
    from mrh.infrastructure import locations
    if runtime_root is not None or project_root is None:
        area = owned.canonical_path(runtime_root) if runtime_root is not None else locations.runtime_root()
        location = {'runtime_root': str(area)}
    else:
        bound_project = owned.canonical_path(project_root)
        if not bound_project.is_dir():raise owned.OwnedError('project_runtime_unavailable')
        location = {'project_root': str(bound_project)}
    editable = {}
    if dev_source is not None:
        from mrh.infrastructure.execution import DESCRIPTOR, PTH
        editable = dict(editable_files or {})
        if not {DESCRIPTOR, PTH} <= set(editable):
            raise owned.OwnedError('editable_link_missing')
        for name, data in editable.items():
            if Path(name).is_absolute() or '..' in Path(name).parts or not isinstance(data, bytes):
                raise owned.OwnedError('editable_link_invalid')
        link_hashes = {name: _hash(editable[name]) for name in (DESCRIPTOR, PTH)}
    prefix = "plugins/" + NAME + "/"
    if os.name == 'nt':
        from mrh.adapters.platforms.windows import codex_hook_command
        command = codex_hook_command(python)
    else:
        command = shlex.quote(python) + ' -I -B "${PLUGIN_ROOT}/launcher.py"'
    files = {
        ".agents/plugins/marketplace.json": _json({"name": MARKETPLACE, "plugins": [{"name": NAME,
            "source": {"source": "local", "path": "./plugins/" + NAME},
            "policy": {"installation": "AVAILABLE", "authentication": "ON_USE"}, "category": "Productivity"}]}),
        prefix + "plugin.json": _json({"$schema":"https://agent-plugins.org/schemas/1.0.0/plugin.schema.json", "name": NAME, "version": version,
            "description": "Default-off model routing with explicit workspace export permission",
            "extensions": {"com.openai": {"hooks": "./hooks/hooks.json"}}}),
        prefix + "hooks/hooks.json": _json({"hooks": {event: [{"matcher": "^(spawn_agent|collaborationspawn_agent)$", "hooks": [
            {"type": "command", "command": command, "timeout": codex_hook_timeout(event)}]}] for event in ("PreToolUse", "PostToolUse")}}),
        prefix + "launcher.py": _windows_launcher() if os.name == 'nt' else LAUNCHER,
        prefix + "runtime.pyz": runtime,
        prefix + "binding.json": _json({"schema_version": 1, "python": python, "settings_path": str(settings_path),
                                         "runtime_sha256": _hash(runtime), "platform": "codex",
                                         **location,
                                         **({"dev_source": str(dev_source), "editable_sha256": link_hashes} if dev_source is not None else {}),
                                         **({"codex_packets": True} if codex_packets else {})}),
    }
    files.update({prefix + 'editable/' + name: data for name, data in editable.items()})
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
