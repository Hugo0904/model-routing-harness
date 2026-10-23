"""Native Windows checkout lifecycle. No downloads or provider requests.

The local Python installation is an explicit dependency. Its identity is bound
to every immutable generation; settings and statistics live outside generations.
"""
from __future__ import annotations

import argparse
from contextlib import nullcontext
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from mrh.infrastructure import owned, plugin, settings_v2, claude_hook, secrets
from mrh.infrastructure import execution, locations
import mrh_bundle as bundle

OWNER = "org.model-routing-harness.windows-setup.v1"
READER = {"settings": [1, 2], "packet_statistics": 1, "windows_all_workspaces": 1}
CLAUDE_VERSIONS = ("2.1.303 (Claude Code)",)
LIMIT = 16_000_000


class SetupError(ValueError):
    pass


def native():
    from mrh.adapters.platforms import windows
    return windows


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode()


def regular(path):
    return owned.read_regular(Path(path), LIMIT)


def document(path):
    return json.loads(regular(path), object_pairs_hook=owned._unique)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    path = Path(value).expanduser().absolute()
    if any(ord(c) < 32 for c in str(path)) or path != path.resolve():
        raise SetupError("unsafe_path")
    for item in (path, *path.parents):
        if item.exists() and getattr(item.lstat(), "st_file_attributes", 0) & 0x400:
            raise SetupError("unsafe_path")
    return path


def snapshot(path):
    path = Path(path)
    if not path.exists():
        # Broken links and reparse points must never look like free destinations.
        if path.is_symlink():
            raise SetupError("unsafe_path")
        return None
    native().assert_safe(path)
    return {"sha256": digest(regular(path))}


def write(path, data, expected="unchecked"):
    path = Path(path)
    if expected != "unchecked" and snapshot(path) != expected:
        raise SetupError("concurrent_change:" + path.name)
    owned.replace_owned(path, data, limit=LIMIT)


def mkdir(path):
    """Protect only directories this operation actually creates."""
    path = Path(path)
    if path.exists():
        native().assert_safe(path, directory=True, ancestor=True)
        return
    mkdir(path.parent)
    try:
        path.mkdir()
    except FileExistsError:
        native().assert_safe(path, directory=True)
    else:
        native().protect(path)


def initialize(path, kind):
    mkdir(Path(path).parent)
    return owned.initialize(Path(path), kind)


def python_metadata(executable=None):
    if os.name != "nt" or platform.machine().lower() not in ("amd64", "x86_64") or sys.maxsize <= 2**32:
        raise SetupError("unsupported_platform:Windows_x64_required")
    if sys.version_info < (3, 11):
        raise SetupError("unsupported_python:install_native_Windows_x64_Python_3.11_or_newer")
    executable = canonical(executable or sys.executable)
    if executable == Path(sys.executable):
        version, base_prefix = platform.python_version(), sys.base_prefix
    else:
        from mrh.adapters.platforms.windows_process import run
        code = ("import json,os,platform,sys; print(json.dumps({'native':os.name=='nt',"
                "'x64':platform.machine().lower() in ('amd64','x86_64') and sys.maxsize>2**32,"
                "'version':list(sys.version_info[:3]),'base_prefix':sys.base_prefix}))")
        response = run([str(executable), "-I", "-B", "-c", code], timeout=10)
        try:
            metadata = json.loads(response.stdout)
            if response.returncode or not metadata["native"] or not metadata["x64"] or tuple(metadata["version"]) < (3, 11):
                raise ValueError()
            version, base_prefix = ".".join(map(str, metadata["version"])), metadata["base_prefix"]
        except (ValueError, KeyError, TypeError):
            raise SetupError("unsupported_python:install_native_Windows_x64_Python_3.11_or_newer") from None
    license_path = canonical(Path(base_prefix) / "LICENSE.txt")
    if not license_path.is_file():
        raise SetupError("python_license_missing")
    return {"executable": str(executable), "sha256": digest(regular(executable)),
            "version": version, "base_prefix": str(canonical(base_prefix)),
            "architecture": "x64", "platform": "win32", "license_sha256": digest(regular(license_path))}


def source_identity(hosts, packets, settings, python, dev=False):
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                            text=True, check=True, timeout=10)
    head = result.stdout.strip()
    if len(head) != 40 or any(c not in "0123456789abcdef" for c in head):
        raise SetupError("source_commit_unavailable")
    files = ([ROOT / 'src/mrh/infrastructure' / name for name in ('execution.py', 'owned.py', 'plugin.py')]
             + list((ROOT / 'src/mrh/adapters/platforms').glob('*.py'))) if dev else [
             p for p in (ROOT / "src/mrh").rglob("*")
             if p.is_file() and "__pycache__" not in p.parts and (p.suffix == ".py" or "resources" in p.parts)]
    files += [ROOT / name for name in ("mrh_windows_setup.py", "mrh_setup.py", "setup.ps1", "mrh_build.py",
                                      "mrh_bundle.py", "pyproject.toml", "LICENSE")]
    h = hashlib.sha256()
    for path in sorted(set(p for p in files if p.is_file())):
        # The checkout is a user-editable input, not an installed artifact.
        # The second source identity check before publication catches changes.
        h.update(path.relative_to(ROOT).as_posix().encode() + b"\0" + path.read_bytes())
    # The commit id is recorded for display only: a docs-only commit must not make a new version.
    h.update(encoded({"hosts": hosts, "packets": packets, "settings": str(settings), "python": python,
                      "runtime_root": str(locations.default_runtime_root()),
                      "execution_mode": "development" if dev else "installed",
                      **({"dev_source": str(canonical(ROOT))} if dev else {})}))
    return {"head": head, "fingerprint": h.hexdigest(),
            **({"dev_source": str(canonical(ROOT))} if dev else {})}


def project_root(value):
    try:
        if not isinstance(value, str) or not Path(value).is_absolute():
            raise ValueError('invalid_binding')
        root = canonical(value)
        native().assert_safe(root, directory=True)
        return root
    except (OSError, ValueError) as exc:
        reason = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        raise SetupError('project_root_not_ready:' + reason) from None


def runtime_root(value):
    path = owned.canonical_path(value)
    canonical(path)
    if path.exists():
        native().assert_safe(path, directory=True)
    return path


def project_root_readiness(meta, generation=None):
    if 'runtime_root' in meta:
        try:
            runtime_root(meta['runtime_root'])
            if 'dev_source' in meta:
                execution.editable_source(generation / 'app/editable', meta['dev_source'])
            return {'status': 'development' if 'dev_source' in meta else 'not_required', 'ready': True}
        except (OSError, ValueError, TypeError) as exc:
            return {'status': 'not_ready', 'ready': False, 'reason': str(exc)}
    if 'project_root' not in meta:
        return {'status': 'legacy_unbound', 'ready': True}
    try:
        project_root(meta['project_root'])
        return {'status': 'bound', 'ready': True}
    except SetupError as exc:
        return {'status': 'not_ready', 'ready': False, 'reason': str(exc)}


def execution_fields(meta):
    root = meta.get('runtime_root')
    if root is None and meta.get('project_root'):
        root = str(Path(meta['project_root']) / 'runtime')
    return {'execution_mode': 'development' if 'dev_source' in meta else 'installed',
            'source': meta.get('dev_source'),
            'runtime_root': root or str(locations.default_runtime_root())}


def file_manifest(root):
    files, directories = {}, []
    for path in sorted(Path(root).rglob("*")):
        native().assert_safe(path, directory=path.is_dir())
        name = path.relative_to(root).as_posix()
        if path.is_dir():
            directories.append(name)
        elif name != "manifest.json":
            files[name] = digest(regular(path))
    return {"files": files, "directories": directories}


def verify_generation(root, expected=None):
    root = canonical(root)
    raw = regular(root / "manifest.json")
    if expected is not None and digest(raw) != expected:
        raise SetupError("manifest_changed")
    manifest = json.loads(raw, object_pairs_hook=owned._unique)
    if manifest.get("owner") != OWNER or manifest.get("schema_version") != 1:
        raise SetupError("manifest_invalid")
    actual = file_manifest(root)
    if actual != {key: manifest.get(key) for key in ("files", "directories")}:
        raise SetupError("generation_integrity_failed")
    meta = document(root / "generation.json")
    source = meta.get("source", {})
    python = meta.get("python", {})
    if (meta.get("owner") != OWNER or len(source.get("fingerprint", "")) != 64
            or len(source.get("head", "")) != 40 or not (root / "app/mrh.pyz").is_file()
            or python.get("platform") != "win32" or python.get("architecture") != "x64"):
        raise SetupError("provenance_invalid")
    executable = canonical(python.get("executable", ""))
    native().assert_safe(executable)
    if digest(regular(executable)) != python.get("sha256"):
        raise SetupError("python_dependency_changed")
    if digest(regular(root / "licenses/Python-LICENSE.txt")) != python.get("license_sha256"):
        raise SetupError("python_license_changed")
    for host in meta.get("hosts", {}):
        plugin.show(root / "hosts" / host)
    return meta


def compatible(root, settings):
    meta = document(root / "generation.json")
    schema = document(settings).get("schema_version") if settings.exists() else 2
    if schema not in meta.get("reader", {}).get("settings", []) or meta.get("reader", {}).get("packet_statistics") != 1:
        raise SetupError("rollback_reader_incompatible")
    if settings.exists() and '*' in settings_v2.effective_roots(settings_v2.read(settings))[0] and meta.get('reader', {}).get('windows_all_workspaces') != 1:
        raise SetupError('rollback_workspace_scope_incompatible')


def build_generation(stage, destination, settings, selected, source, python, dev=False):
    initialize(stage, "windows-generation")
    mkdir(stage / "app")
    mkdir(stage / "licenses")
    bundle.application_archive(stage / "app/mrh.pyz")
    native().protect(stage / "app/mrh.pyz")
    archive = regular(stage / "app/mrh.pyz")
    editable = bundle.editable_files() if dev else None
    if editable is not None:
        for name, data in editable.items():
            target = stage / 'app/editable' / name
            mkdir(target.parent)
            write(target, data, None)
    runtime = runtime_root(locations.default_runtime_root())
    write(stage / "licenses/LICENSE", (ROOT / "LICENSE").read_bytes(), None)
    write(stage / "licenses/Python-LICENSE.txt", regular(Path(python["base_prefix"]) / "LICENSE.txt"), None)
    for host, info in selected.items():
        artifact = stage / "hosts" / host
        mkdir(artifact.parent)
        host_settings = Path(info.get('settings', settings))
        if host_settings != settings:
            mkdir(host_settings.parent.parent)
        plugin.prepare(artifact, host_settings, python["executable"], advisory=True, codex_packets=info["packets"],
                       runtime_archive=archive, editable_files=editable, runtime_root=runtime,
                       dev_source=ROOT if dev else None)
        meta = document(artifact / "artifact.json")
        if host == "codex":
            portable = Path("plugins") / plugin.NAME / "plugin.json"
            target = portable.parent / ".codex-plugin/plugin.json"
            definition = document(artifact / portable)
            compatibility = {k: definition[k] for k in ("name", "version", "description")}
            compatibility["hooks"] = definition["extensions"]["com.openai"]["hooks"]
            mkdir((artifact / target).parent)
            write(artifact / target, encoded(compatibility), None)
            (artifact / portable).unlink()
            del meta["files"][portable.as_posix()]
            meta["files"][target.as_posix()] = digest(regular(artifact / target))
            hooks=portable.parent/'hooks/hooks.json'
            definition=document(artifact/hooks)
            for entries in definition['hooks'].values():
                for entry in entries:
                    for hook in entry['hooks']:
                        hook['command']=native().codex_hook_command(python['executable'], destination.parents[2]/'bootstrap.py')
            write(artifact/hooks,encoded(definition))
            meta['files'][hooks.as_posix()]=digest(regular(artifact/hooks))
            write(artifact / "artifact.json", encoded(meta))
        elif info.get('cli', {}).get('registration') == 'native_plugin':
            portable = Path('plugins')/plugin.NAME/'plugin.json'
            definition = document(artifact/portable)
            target = portable.parent/'.claude-plugin/plugin.json'
            mkdir((artifact/target).parent)
            write(artifact/target, encoded({k:definition[k] for k in ('name','version','description')}), None)
            mkdir(artifact/'.claude-plugin')
            write(artifact/'.claude-plugin/marketplace.json', encoded({'name':plugin.MARKETPLACE,
                'owner':{'name':'MRH'},'plugins':[{'name':plugin.NAME,'source':'./plugins/'+plugin.NAME}]}), None)
            hooks = portable.parent/'hooks/hooks.json'
            command = native().codex_hook_command(python['executable'],destination.parents[2]/'bootstrap.py','claude')
            write(artifact/hooks, encoded({'hooks':{event:[{'matcher':'Agent|Task','hooks':[{'type':'command','command':command,'shell':'powershell',
                # Post: the 2.0 s supervisor deadline starts after PowerShell and bootstrap (~1-1.5 s), so the
                # host's own limit must leave room. Codex's hooks file is untouched (a change forces re-trust).
                'timeout':50 if event=='PreToolUse' else 5}]}] for event in ('PreToolUse','PostToolUse')}}))
            (artifact/portable).unlink()
            del meta['files'][portable.as_posix()]
            for name in (target.as_posix(), '.claude-plugin/marketplace.json', hooks.as_posix()):
                meta['files'][name] = digest(regular(artifact/name))
            write(artifact/'artifact.json', encoded(meta))
        # Plugin wiring uses only the external interpreter and persistent settings,
        # so publishing does not require rewriting any staging paths.
        plugin.show(artifact)
    write(stage / "generation.json", encoded({"owner": OWNER, "reader": READER,
          "source": source, "python": python, "hosts": selected, "runtime_root": str(runtime),
          **({"dev_source": str(canonical(ROOT))} if dev else {})}), None)
    write(stage / "manifest.json", encoded({"owner": OWNER, "schema_version": 1, **file_manifest(stage)}), None)
    verify_generation(stage)


BOOTSTRAP = b'''"""MRH-owned native entrypoint; current state is the atomic generation pointer."""
import hashlib,json,os,runpy,sys
from pathlib import Path
root=Path(__file__).absolute().parent
native_hook=len(sys.argv)>1 and sys.argv[1]=='--native-hook'
os.environ.pop('MRH_PROJECT_ROOT',None)
os.environ.pop('MRH_RUNTIME_ROOT',None)

class ProjectRootError(ValueError):pass

def hook_failure(message):
    # Before the verified launcher runs, stdin still belongs to this bootstrap.
    # Failure handling uses only stdlib and never trusts generation packet flags.
    if len(sys.argv)>2 and sys.argv[2]=='codex':
        try:
            event=json.loads(sys.stdin.buffer.read(1048576))
            if (isinstance(event,dict) and event.get('hook_event_name')=='PreToolUse'
                and event.get('tool_name') in ('spawn_agent','collaborationspawn_agent')
                and isinstance(event.get('tool_input'),dict)
                and str(event['tool_input'].get('task_name','')).startswith(('mrh_packet_','mrh_release_'))):
                return {'hookSpecificOutput':{'hookEventName':'PreToolUse','permissionDecision':'deny',
                    'permissionDecisionReason':'MRH Codex packet: runtime unavailable; dispatch stopped, outcome unknown. Do not retry or fall back to title classification. Continue independent work and briefly inform the user.'}}
        except (OSError,ValueError,TypeError):pass
    return {'systemMessage':message}

def bind_runtime(meta,runtime,generation,manifest):
    if 'runtime_root' not in meta and 'project_root' not in meta:return
    try:
        modern='runtime_root' in meta
        value=meta['runtime_root'] if modern else meta['project_root']
        if not isinstance(value,str) or not value or any(ord(c)<32 for c in value):raise ValueError()
        path=Path(value)
        if not path.is_absolute() or path!=path.resolve():raise ValueError()
        for item in (path,*path.parents):
            if modern and not item.exists():continue
            if getattr(item.lstat(),'st_file_attributes',0)&0x400:raise ValueError()
        sys.path.insert(0,str(runtime))
        try:
            from mrh.adapters.platforms.windows import assert_safe
            if not modern or path.exists():assert_safe(path,directory=True)
            if 'dev_source' in meta:
                for name in ('model_routing_harness-editable.pth','model_routing_harness-editable.json'):
                    relative='app/editable/'+name
                    if hashlib.sha256(read(generation/relative)).hexdigest()!=manifest['files'][relative]:raise ValueError()
                from mrh.infrastructure.execution import editable_source
                editable_source(generation/'app/editable',meta['dev_source'])
        finally:sys.path.pop(0)
        os.environ['MRH_RUNTIME_ROOT' if modern else 'MRH_PROJECT_ROOT']=str(path)
    except (OSError,ValueError,TypeError):raise ProjectRootError() from None
def read(path):
    if path.is_symlink() or getattr(path.lstat(),"st_file_attributes",0)&0x400:
        raise ValueError("reparse point")
    return path.read_bytes()
try:
    state=json.loads(read(root/"setup-state/state.json"))
    identifier=state["current"]
    if len(identifier)!=24 or any(c not in "0123456789abcdef" for c in identifier):raise ValueError()
    generation=root/"setup-state/generations"/identifier
    manifest_raw=read(generation/"manifest.json")
    if hashlib.sha256(manifest_raw).hexdigest()!=state["generations"][identifier]:raise ValueError()
    manifest=json.loads(manifest_raw)
    for name in ("generation.json","app/mrh.pyz"):
        if hashlib.sha256(read(generation/name)).hexdigest()!=manifest["files"][name]:raise ValueError()
    meta=json.loads(read(generation/"generation.json"))
    python=meta["python"]
    if Path(sys.executable).resolve()!=Path(python["executable"]).resolve():raise ValueError()
    if hashlib.sha256(read(Path(sys.executable))).hexdigest()!=python["sha256"]:raise ValueError()
    os.environ.setdefault('MRH_SETTINGS',state['settings'])
    if native_hook:
        host=sys.argv[2]
        if host not in ('codex','claude'):raise ValueError()
        info=state['hosts'][host];identifier=info['generation']
        if len(identifier)!=24 or any(c not in '0123456789abcdef' for c in identifier):raise ValueError()
        generation=root/'setup-state/generations'/identifier
        raw=read(generation/'manifest.json')
        if hashlib.sha256(raw).hexdigest()!=state['generations'][identifier]:raise ValueError()
        manifest=json.loads(raw)
        relative='hosts/'+host+'/plugins/model-routing-harness/'
        if hashlib.sha256(read(generation/'generation.json')).hexdigest()!=manifest['files']['generation.json']:raise ValueError()
        host_meta=json.loads(read(generation/'generation.json'))
        for name in ('launcher.py','runtime.pyz','binding.json'):
            if hashlib.sha256(read(generation/(relative+name))).hexdigest()!=manifest['files'][relative+name]:raise ValueError()
        bind_runtime(host_meta,generation/(relative+'runtime.pyz'),generation,manifest)
        sys.argv=[str(generation/(relative+'launcher.py')),host]
        runpy.run_path(sys.argv[0],run_name='__main__')
    else:
        bind_runtime(meta,generation/'app/mrh.pyz',generation,manifest)
        sys.argv[0]=str(generation/"app/mrh.pyz")
        runpy.run_path(sys.argv[0],run_name="__main__")
except ProjectRootError:
    if native_hook:
        print(json.dumps(hook_failure('MRH: bound runtime or development source is not ready; original tool call preserved. Inform the user; no system temporary-directory fallback was used.')))
        raise SystemExit(0)
    print('MRH bound runtime or development source is not ready; rerun setup.ps1 --check --json. No system temporary-directory fallback was used.',file=sys.stderr)
    raise SystemExit(2)
except (OSError,ValueError,KeyError,TypeError):
    if native_hook:
        print(json.dumps(hook_failure('MRH: installed Hook integrity check failed; original tool call preserved. Inform the user; do not retry a successful tool.')))
        raise SystemExit(0)
    print("MRH installation integrity check failed; rerun setup.ps1 --check --json.",file=sys.stderr)
    raise SystemExit(2)
'''


def launcher_bytes(prefix, python):
    def argument(value):
        text = str(value)
        if any(c in text for c in ('"', "\r", "\n", "\0")):
            raise SetupError("unsafe_command_path")
        return '"' + text.replace("%", "%%") + '"'
    return ("@echo off\r\nsetlocal DisableDelayedExpansion\r\n" + argument(python["executable"])
            + " -I -B -X utf8 " + argument(prefix / "bootstrap.py") + " %*\r\nexit /b %errorlevel%\r\n").encode()


class ClaudeInstaller:
    def __init__(self, path, executable=None):
        self.path = canonical(path)
        candidate = executable or shutil.which("claude.exe") or shutil.which("claude.cmd") or shutil.which("claude")
        if not candidate:
            raise SetupError("claude_cli_missing")
        executable = canonical(candidate)
        from mrh.adapters.platforms.windows_process import run
        result = run([str(executable), "--version"], timeout=10)
        version = result.stdout.strip() if result.returncode == 0 else ""
        if version not in CLAUDE_VERSIONS:
            raise SetupError("claude_cli_unsupported_version")
        self.cli = {"executable": str(executable), "version": version, "source": "native_version_metadata",
                    "catalog": "isolated_initialize", "account_availability": "not_probed"}

    def _validate_hooks(self, settings):
        text = regular(self.path).decode("utf-8") if self.path.exists() else ""
        claude_hook.plan(text, "model-routing-harness preflight claude")
        hooks = json.loads(text or "{}").get("hooks", {})
        for rows in hooks.values():
            if not isinstance(rows, list):
                raise SetupError("claude_settings_invalid")
            for entry in rows:
                if not claude_hook._ours(entry):
                    continue
                for hook in entry.get("hooks", []):
                    command = hook.get("command", "")
                    # Resolve only already owned generation artifacts; a command
                    # merely containing MRH's name cannot establish ownership.
                    prefix = command.find("setup-state")
                    if prefix < 0:
                        raise SetupError("claude_hook_unowned")
                    found = False
                    import re
                    for match in re.finditer(r'([A-Za-z]:[\\/][^"\r\n]*[\\/]launcher\.py)', command):
                        launcher = Path(match.group(1))
                        try:
                            artifact = launcher.parents[2]
                            info = plugin.show(artifact)["artifact"]
                            if info["settings_path"] == str(settings) and claude_hook.command_for(artifact) == command:
                                found = True
                        except (ValueError, OSError, KeyError):
                            pass
                    if not found:
                        raise SetupError("claude_hook_unowned")
        return text

    def preflight(self, settings, packets=False):
        self._validate_hooks(settings)
        return snapshot(self.path)

    def install(self, artifact, before, progress):
        text = regular(self.path).decode("utf-8") if self.path.exists() else ""
        after = claude_hook.plan(text, claude_hook.command_for(artifact)).encode()
        if text.encode() == after:
            return {"configured": True, "backup": None}
        if snapshot(self.path) != before:
            raise SetupError("claude_native_concurrent_change")
        backup = None
        mkdir(self.path.parent)
        if before is not None:
            backup = self.path.with_name(self.path.name + ".mrh-bak-" + uuid.uuid4().hex)
            write(backup, text.encode(), None)
            if snapshot(self.path) != before:
                raise SetupError("claude_native_concurrent_change")
        progress("claude_write_intent")
        write(self.path, after, before)
        if regular(self.path) != after:
            raise SetupError("claude_native_readback_failed")
        progress("claude_write_done")
        return {"configured": True, "backup": str(backup) if backup else None}

    def configured(self, artifact):
        text = regular(self.path).decode("utf-8") if self.path.exists() else ""
        return text == claude_hook.plan(text, claude_hook.command_for(artifact))


def adapters_for(args, hosts, state=None):
    result = {}
    for host in hosts:
        if host == "codex":
            from mrh_setup import CodexInstaller
            previous = (state or {}).get("hosts", {}).get("codex", {})
            result[host] = CodexInstaller(args.codex_executable or previous.get("cli", {}).get("executable"))
        else:
            previous = (state or {}).get("hosts", {}).get("claude", {})
            from mrh.adapters.hosts.claude_windows_install import ClaudeWindowsInstaller
            if args.claude_settings:
                raise SetupError('claude_settings_override_not_supported:native_plugin_owns_registration')
            result[host] = ClaudeWindowsInstaller(args.claude_executable or previous.get('cli', {}).get('executable'))
    return result


def configured(host, adapter, artifact):
    if host == "codex":
        value = adapter.observe()
        return value["root"] == str(artifact) and value["installed"] and value["enabled"] is not False
    return adapter.configured(artifact)


def host_settings(host, adapter, main_settings, state=None):
    previous = (state or {}).get('hosts', {}).get(host, {})
    if previous.get('settings'): return Path(previous['settings'])
    if host == 'claude' and (adapter is None or getattr(adapter, 'cli', {}).get('registration') == 'native_plugin'):
        return main_settings.parent.with_name('claude-profile')/'settings.json'
    return main_settings


def resolve_paths(args):
    # A shared/writable profile ancestor cannot protect installed code from a
    # second local account. ProgramData permits creating a private child but
    # doesn't grant Users delete/rename access to somebody else's child.
    base = Path(os.environ.get('PROGRAMDATA', 'C:/ProgramData')) / ('ModelRoutingHarness-' + native().current_sid())
    prefix = canonical(args.prefix or base / 'install')
    config = canonical(args.config_root or base / 'config')
    bin_dir = canonical(args.bin_dir or prefix / "bin")
    pointer = config / "active-settings"
    current = regular(pointer).decode().strip() if pointer.exists() else None
    settings = canonical(args.settings or current or config / "profile/settings.json")
    if current and str(settings) != current:
        raise SetupError("active_settings_conflict")
    if settings.name != "settings.json" or settings.is_relative_to(prefix) or prefix.is_relative_to(settings.parent):
        raise SetupError("settings_code_overlap")
    if config == prefix or config.is_relative_to(prefix) or prefix.is_relative_to(config):
        raise SetupError("config_code_overlap")
    return prefix, config, bin_dir, pointer, settings


def read_state(control):
    if not control.exists():
        return None
    owned.verify(control, "windows-setup")
    path = control / "state.json"
    if not path.exists():
        return None
    value = document(path)
    def identifier(item):
        return isinstance(item, str) and len(item) == 24 and all(c in "0123456789abcdef" for c in item)
    if (value.get("owner") != OWNER or value.get("version") != 1 or not identifier(value.get("current"))
            or value["current"] not in value.get("generations", {})):
        raise SetupError("setup_state_invalid")
    if any(not identifier(k) or not isinstance(v, str) or len(v) != 64 for k, v in value["generations"].items()):
        raise SetupError("setup_state_invalid")
    for snapshot_value in (value, value.get("previous")):
        if snapshot_value is None:
            continue
        if not identifier(snapshot_value.get("current")) or snapshot_value["current"] not in value["generations"]:
            raise SetupError("setup_state_invalid")
        for host, info in snapshot_value.get("hosts", {}).items():
            if (host not in ("codex", "claude") or not identifier(info.get("generation"))
                    or info["generation"] not in value["generations"]
                    or info.get("artifact") != str(control / "generations" / info["generation"] / "hosts" / host)):
                raise SetupError("setup_state_invalid")
    return value


def profile_preflight(settings):
    if settings.exists():
        return settings_v2.read(settings)
    if settings.parent.exists() and any(settings.parent.iterdir()):
        owned.verify(settings.parent, "settings", settings_v2.FILES)
        if {p.name for p in settings.parent.iterdir()} - {owned.MARKER, ".mrh.lock"}:
            raise SetupError("profile_incomplete_or_unowned")
    return None


def key_status(value):
    if not value or value["classifier"]["provider"] != "jev":
        return None
    # Status APIs only; no credential value is retrieved.
    return bool(os.environ.get("TYPESAFE_API_KEY")) or secrets.is_set("jev")


def catalog_validation(host, catalogs):
    """One public query per host for this readiness/enable operation."""
    if host in catalogs:
        return catalogs[host]
    from mrh.adapters.catalogs.catalog import public_models
    try:
        catalog = public_models(host)
        result = (catalog, {"status": "verified", "verified": True, "source": catalog.source,
                            "assurance": catalog.assurance, "fetched_at": catalog.fetched_at,
                            "account_availability": "not_probed"})
    except (ValueError, OSError, subprocess.SubprocessError):
        result = (None, {"status": "unavailable", "verified": False,
                         "reason": "catalog_unavailable", "account_availability": "not_probed"})
    catalogs[host] = result
    return result


def policy_ready(value, hosts, *, catalogs=None):
    if not value or not hosts:
        return False
    catalogs = {} if catalogs is None else catalogs
    policy = value["policy"]
    valid = True
    for host in hosts:
        catalog, _ = catalog_validation(host, catalogs)
        tiers = [policy.get("tiers", {}).get(tier, {}).get(host, []) for tier in ("Light", "Small", "Mid")]
        candidates = [candidate for tier in tiers for candidate in tier]
        complete = all(tiers)
        if policy.get("top_mode", "Main") == "Fixed":
            fixed = policy.get("fixed", {}).get(host, [])
            complete = complete and bool(fixed)
            candidates += fixed
        valid = bool(catalog and complete and all(catalog.option(c["model"], c.get("effort")) for c in candidates)) and valid
    return valid


def readiness(args, state, paths, adapters=None, operation=None, path_manager=None, path_change=None, *, catalogs=None):
    prefix, config, bin_dir, pointer, settings = paths
    result = {"status": "pending", "installed": False, "generation_integrity": "not_installed",
              "settings": str(settings), "hosts": {}, "key_present": None, "routing": "disabled",
              "idempotent": False, "provider_probe_performed": False, "macos": "not_verified",
              "downloads": False, "pending": []}
    result['project_root'] = {'status':'not_installed', 'ready':False}
    result.update(execution_mode=None, source=None, runtime_root=None)
    if operation:
        result["operation"] = operation
    selected = list(dict.fromkeys(args.host or list((state or {}).get("hosts", {}))))
    adapters = {} if adapters is None else adapters
    catalogs = {} if catalogs is None else catalogs
    for host in selected:
        profile = host_settings(host, adapters.get(host), settings, state)
        value = settings_v2.read(profile) if profile.exists() else None
        _, catalog = catalog_validation(host, catalogs)
        result["hosts"][host] = {"registration": "missing", "trust": "unknown", "settings": str(profile),
            "project_root": {"status": "not_installed", "ready": False}, "catalog": catalog,
            "execution_mode": None, "source": None, "runtime_root": None,
            "classifier": value["classifier"] if value else None, "key_present": key_status(value),
            "policy_ready": policy_ready(value, [host], catalogs=catalogs),
            "enabled": bool(value and value["enabled"]),
            "export_permitted": bool(value and value["task_export_permitted"]),
            "workspace_ready": bool(value and settings_v2.effective_roots(value)[0])}
    if state:
        generation = prefix / "setup-state/generations" / state["current"]
        meta = verify_generation(generation, state["generations"][state["current"]])
        result['project_root'] = project_root_readiness(meta, generation)
        result.update(execution_fields(meta))
        result.update(generation=state["current"], commit=meta["source"]["head"], generation_integrity="verified")
        result["installed"] = (snapshot(bin_dir / "mrh.cmd") == {"sha256": digest(launcher_bytes(prefix, meta["python"]))}
                               and snapshot(prefix / "bootstrap.py") == {"sha256": digest(BOOTSTRAP)}
                               and pointer.exists() and regular(pointer) == (str(settings) + "\n").encode())
        for host in selected:
            info = state["hosts"].get(host)
            if not info:
                continue
            host_meta = meta if info['generation'] == state['current'] else verify_generation(
                prefix/'setup-state/generations'/info['generation'], state['generations'][info['generation']])
            try:
                adapter = adapters.get(host) or adapters_for(args, [host], state)[host]
                observed = configured(host, adapter, Path(info["artifact"]))
                trust = adapter.trust(Path.cwd()) if host == "codex" else "not_applicable_native_settings"
                result["hosts"][host].update({"registration": "observed" if observed else "missing", "trust": trust,
                    'project_root': project_root_readiness(host_meta, prefix/'setup-state/generations'/info['generation']),
                    **execution_fields(host_meta),
                    **({"cli": adapter.cli} if host == "claude" else {})})
            except (ValueError, OSError, subprocess.SubprocessError):
                result["hosts"][host].update(registration="unknown", trust="unknown")
        journal = prefix / "setup-state/pending.json"
        result["transaction_pending"] = journal.exists() and document(journal).get("phase") != "complete"
        result["idempotent"] = bool(result["installed"] and not result["transaction_pending"]
            and all(info["registration"] == "observed" for info in result["hosts"].values()))
        result["status"] = "installed" if result["installed"] and not result["transaction_pending"] else "pending"
        if result['transaction_pending']:
            result['pending'].append('installation_recovery')
    host_results = list(result["hosts"].values())
    for key in ("enabled", "export_permitted", "workspace_ready", "policy_ready", "key_present"):
        result[key] = bool(host_results) and all(info[key] for info in host_results)
    for info in host_results:
        info["routing"] = "disabled"
        if info["enabled"]:
            info["routing"] = "ready" if (result["installed"] and not result.get("transaction_pending", False)
                and info["registration"] == "observed" and info["export_permitted"] and info["workspace_ready"]
                and info["policy_ready"] and info["key_present"] and info["project_root"]["ready"]
                and info["trust"] in ("trusted", "not_applicable_native_settings")) else "not_ready"
    if any(info["enabled"] for info in host_results):
        result["routing"] = "ready" if all(info["routing"] == "ready" for info in host_results) else "not_ready"
        if any(info["enabled"] and not info["policy_ready"] for info in host_results):
            result["pending"].append("policy_catalog_validation")
        if any(info["enabled"] and info["trust"] not in ('trusted','not_applicable_native_settings') for info in host_results):
            result['pending'].append('native_hook_trust')
    for key in ("installed", "workspace_ready", "policy_ready"):
        if not result[key]:
            result["pending"].append(key)
    if not result['project_root']['ready'] or any(not h.get('project_root',{}).get('ready') for h in result['hosts'].values()):
        result['pending'].append('project_root')
    if path_manager is None:
        from mrh.adapters.platforms.windows_path import UserPath
        path_manager = UserPath(bin_dir)
    result['command_path'] = path_manager.report()
    if path_change is not None:
        result['command_path']['change'] = path_change
    if not result['command_path']['future_terminal_ready']:
        result['pending'].append('command_path')
    return result


def install(args, *, adapters=None, build=build_generation, path_manager=None):
    if os.name != 'nt' or platform.machine().lower() not in ('amd64', 'x86_64') or sys.maxsize <= 2**32:
        raise SetupError('unsupported_platform:Windows_x64_required')
    paths = resolve_paths(args)
    prefix, config, bin_dir, pointer, settings = paths
    if path_manager is None:
        from mrh.adapters.platforms.windows_path import UserPath
        path_manager = UserPath(bin_dir)
    control = prefix / "setup-state"
    state = read_state(control)
    installed_python = (document(control / "generations" / state["current"] / "generation.json")["python"]["executable"]
                        if state else None)
    if state and state.get("settings") != str(settings):
        raise SetupError("active_settings_conflict")
    if args.check:
        return readiness(args, state, paths, adapters, path_manager=path_manager)
    hosts = list(dict.fromkeys(args.host or list((state or {}).get("hosts", {}))))
    if not hosts:
        raise SetupError("host_required")
    if args.codex_packets and 'codex' not in hosts:
        raise SetupError("codex_packets_requires_codex_host")
    if args.rollback and (args.enable or args.workspace or args.all_workspaces or args.codex_packets or args.dev):
        raise SetupError("rollback_does_not_change_policy_or_packet_mode")
    if args.enable and not (args.workspace or args.all_workspaces):
        raise SetupError("enable_requires_explicit_workspace")
    if not args.rollback:
        project_root(str(ROOT))
    path_plan = path_manager.plan()
    path_manager.validate(path_plan)
    for path in args.workspace:
        canonical(path)  # explicit operator opt-in; no embedded project name
    profiles = {host: host_settings(host, (adapters or {}).get(host), settings, state) for host in hosts}
    profile_paths = list(dict.fromkeys([settings, *profiles.values()]))
    profile_snapshots = {str(path): snapshot(path) for path in profile_paths}
    profile_values = {path: profile_preflight(path) for path in profile_paths}
    if any(snapshot(path) != profile_snapshots[str(path)] for path in profile_paths):
        raise SetupError("profile_concurrent_change")
    catalogs = {}
    if args.enable:
        for host, profile in profiles.items():
            value = profile_values[profile]
            if not value or value["classifier"]["provider"] != "jev" or not key_status(value):
                raise SetupError("enable_requires_configured_classifier_key:" + host)
            if not policy_ready(value, [host], catalogs=catalogs):
                raise SetupError("enable_requires_validated_model_policy:" + host)
    if adapters is None and not args.dry_run:
        initialize(prefix, 'windows-install')
        if not args.python and not installed_python:
            from mrh.adapters.platforms.windows_runtime import snapshot_python
            args.python = snapshot_python(sys.executable, prefix/'python-runtimes')
        for host in hosts:
            attr = host + '_executable'
            prior = (state or {}).get('hosts', {}).get(host, {}).get('cli', {}).get('executable')
            if not getattr(args, attr) and prior:
                setattr(args, attr, Path(prior))
                if host == 'codex' and Path(prior).parent == prefix/'host-tools':
                    original = shutil.which('codex.exe')
                    from mrh.adapters.platforms.windows_runtime import digest as file_digest
                    if not original or file_digest(original) != file_digest(prior):
                        raise SetupError('codex_bundle_migration_requires_matching_source')
                    args.codex_executable = native().snapshot_codex_bundle(original,prefix/'host-tools')
            if not getattr(args, attr):
                source_exe = shutil.which(host + '.exe')
                if not source_exe: raise SetupError(host + '_cli_missing')
                if host == 'codex':
                    args.codex_executable = native().snapshot_codex_bundle(source_exe,prefix/'host-tools')
                else:
                    setattr(args, attr, native().snapshot_executable(source_exe, prefix/'host-tools','Anthropic, PBC'))
    python = python_metadata(args.python or installed_python)
    launcher = launcher_bytes(prefix, python)
    before_bin, before_bootstrap = snapshot(bin_dir / "mrh.cmd"), snapshot(prefix / "bootstrap.py")
    old_entries = (state or {}).get('entrypoints', {})
    valid_bins = [{"sha256": digest(launcher)}]
    valid_bootstraps = [{"sha256":digest(BOOTSTRAP)}]
    if state:
        if old_entries:
            valid_bins.append({'sha256':old_entries.get('mrh.cmd')})
            valid_bootstraps.append({'sha256':old_entries.get('bootstrap.py')})
        else:
            # Exact migration from the first native installer template only.
            old_python = document(control/'generations'/state['current']/'generation.json')['python']
            valid_bins.append({'sha256':digest(launcher_bytes(prefix,old_python).replace(b' -X utf8 ',b' '))})
    if before_bin is not None and before_bin not in valid_bins:
        raise SetupError("bin_conflict")
    if before_bootstrap is not None and before_bootstrap not in valid_bootstraps:
        raise SetupError("bootstrap_conflict")
    adapters = adapters if adapters is not None else adapters_for(args, hosts, state)
    adapters = {host: adapters[host] for host in hosts}
    source = source_identity(hosts, args.codex_packets, settings, python, args.dev)
    intent = {"hosts": hosts, "rollback": args.rollback, "source": source, "enable": args.enable,
              "dev": args.dev,
              "workspaces": ['*'] if args.all_workspaces else [str(canonical(path)) for path in args.workspace], "settings": str(settings),
              "claude_settings": str(host_settings('claude',adapters['claude'],settings,state)) if 'claude' in adapters else None}
    if args.dry_run:
        for host, adapter in adapters.items():
            adapter.preflight(host_settings(host,adapter,settings,state), args.codex_packets if host == "codex" else False)
        return {"status": "planned", "writes": False, "downloads": False, "hosts": hosts,
                "execution_mode": "development" if args.dev else "installed",
                "source": str(canonical(ROOT)) if args.dev else None,
                "runtime_root": str(locations.default_runtime_root()),
                "settings": str(settings), "rollback": args.rollback, "provider_probe_performed": False,
                "command_path": {**path_manager.report(), 'planned_change': path_plan['action']}}
    initialize(prefix, "windows-install")
    initialize(control, "windows-setup")
    with owned.locked(control, "windows-setup"):
        state_now = read_state(control)
        if state_now != state or snapshot(bin_dir / "mrh.cmd") != before_bin or snapshot(prefix / "bootstrap.py") != before_bootstrap:
            raise SetupError("preflight_concurrent_change")
        pending_path = control / "pending.json"
        pending = document(pending_path) if pending_path.exists() else None
        if pending and pending.get("phase") != "complete":
            if pending.get("owner") != OWNER or pending.get("intent") != intent:
                raise SetupError("pending_operation_conflict:rerun_original_arguments")
            if state and state.get("last_operation") == pending["operation"]:
                verify_generation(control / "generations" / state["current"], state["generations"][state["current"]])
                path_change = path_manager.apply(path_plan)
                pending["phase"] = "complete"
                write(pending_path, encoded(pending))
                return readiness(args, state, paths, adapters, "recovered", path_manager, path_change, catalogs=catalogs)
        else:
            native_before = {host: adapter.preflight(host_settings(host,adapter,settings,state), (state or {}).get("hosts", {}).get(host, {}).get("packets", False)
                if args.rollback else args.codex_packets if host == "codex" else False) for host, adapter in adapters.items()}
            pending = {"owner": OWNER, "operation": uuid.uuid4().hex, "phase": "preflight", "intent": intent,
                       "before_hosts": native_before, "completed_hosts": [], "before_bin": before_bin,
                       "before_bootstrap": before_bootstrap, "before_pointer": snapshot(pointer),
                       "before_profile": profile_snapshots[str(settings)], "before_profiles": profile_snapshots,
                       "before_state": snapshot(control / "state.json")}
        # Older journals recorded only the main profile. Keep that comparison
        # while tracking independent host profiles for new transactions.
        pending.setdefault("before_profiles", {**profile_snapshots, str(settings): pending["before_profile"]})
        if state:
            verify_generation(control / "generations" / state["current"], state["generations"][state["current"]])
        if args.rollback:
            previous = (state or {}).get("previous")
            if not previous or any(host not in previous["hosts"] for host in hosts):
                raise SetupError("rollback_history_missing")
            identifier = previous["current"]
            selected = {host: previous["hosts"][host] for host in hosts}
            generation = control / "generations" / identifier
            rolled = verify_generation(generation, state["generations"][identifier])
            python = rolled['python']
            launcher = launcher_bytes(prefix, python)
            compatible(generation, settings)
            if not project_root_readiness(rolled, generation)['ready']:
                raise SetupError('project_root_not_ready:rollback_binding')
        else:
            identifier = source["fingerprint"][:24]
            generation = control / "generations" / identifier
            selected = {host: {"generation": identifier, "artifact": str(generation / "hosts" / host),
                "packets": args.codex_packets if host == "codex" else False,
                **({"settings":str(host_settings(host,adapters[host],settings,state)), 'cli':adapters[host].cli,
                    **({'config':str(adapters[host].path)} if hasattr(adapters[host],'path') else {})} if host == "claude"
                   else {"cli": {"executable": str(adapters[host].executable)}} if hasattr(adapters[host], "executable") else {})} for host in hosts}
            if (state and state["current"] == identifier and all(state["hosts"].get(h) == selected[h] for h in hosts)
                    and pending["phase"] in ("preflight", "complete") and not args.enable and not args.workspace and not args.all_workspaces):
                if not all(configured(h, adapters[h], Path(selected[h]["artifact"])) for h in hosts):
                    raise SetupError("native_registration_changed")
                path_change = path_manager.apply(path_plan)
                return readiness(args, state, paths, adapters, "unchanged", path_manager, path_change, catalogs=catalogs)
            pending.update(target=identifier, phase="building")
            write(pending_path, encoded(pending))
            initialize(config, "windows-config")
            for profile_name, before in pending["before_profiles"].items():
                profile = Path(profile_name)
                if snapshot(profile) != before:
                    if before is not None or settings_v2.read(profile) != settings_v2.default_settings():
                        raise SetupError("profile_concurrent_change")
                mkdir(profile.parent.parent)
                settings_v2.init(profile)
                pending["before_profiles"][profile_name] = snapshot(profile)
            pending["before_profile"] = snapshot(settings)
            write(pending_path, encoded(pending))
            if not generation.exists():
                mkdir(control / "generations")
                # Interrupted staging is retained as evidence. A rerun builds in
                # a fresh owned leaf instead of deleting or adopting partial bytes.
                stage = control / (".stage-" + pending["operation"] + "-" + uuid.uuid4().hex)
                build(stage, generation, settings, selected, source, python, args.dev)
                verify_generation(stage)
                stage.rename(generation)
            else:
                meta = verify_generation(generation, pending.get("manifest"))
                if meta.get("source") != source or meta.get("python") != python:
                    raise SetupError("generation_unowned")
            if source_identity(hosts, args.codex_packets, settings, python, args.dev) != source:
                raise SetupError("source_concurrent_change")
            project_root(str(ROOT))
        changed_binding = state and any(
            execution.runtime_binding(document(control / 'generations' / old_id / 'generation.json'))
            != execution.runtime_binding(document(generation / 'generation.json'))
            for old_id in {state['current'], *(item['generation'] for item in state['hosts'].values())})
        all_profiles = [*profile_paths, *(Path(info.get('settings', settings)) for info in (state or {}).get('hosts', {}).values())]
        admission = execution.packet_mode_transition(all_profiles) if changed_binding else nullcontext()
        with admission:
            pending.update(target=identifier, manifest=digest(regular(generation / "manifest.json")), phase="registering")
            write(pending_path, encoded(pending))
            for host, adapter in adapters.items():
                if host in pending["completed_hosts"]:
                    continue
                def progress(step):
                    pending["native_step"] = {"host": host, "step": step}
                    write(pending_path, encoded(pending))
                adapter.install(Path(selected[host]["artifact"]), pending["before_hosts"][host], progress)
                pending["completed_hosts"].append(host)
                write(pending_path, encoded(pending))
            if not all(configured(h, adapters[h], Path(selected[h]["artifact"])) for h in hosts):
                raise SetupError("native_registration_concurrent_change")
            pending["phase"] = "committing"
            write(pending_path, encoded(pending))
            expected_pointer = (str(settings) + "\n").encode()
            if snapshot(pointer) != pending["before_pointer"] and not (pointer.exists() and regular(pointer) == expected_pointer):
                raise SetupError("active_pointer_concurrent_change")
            if args.enable or args.workspace or args.all_workspaces:
                for profile in dict.fromkeys(profiles.values()):
                    if snapshot(profile) != pending["before_profiles"][str(profile)]:
                        raise SetupError("profile_concurrent_change")
                changes = {"allowed_workspaces": intent["workspaces"], "workspace_allowlist_file": None} if args.workspace or args.all_workspaces else {}
                if args.enable:
                    changes.update(enabled=True, task_export_permitted=True)
                for profile in dict.fromkeys(profiles.values()):
                    current_profile = settings_v2.read(profile)
                    if args.enable and current_profile != profile_values[profile]:
                        raise SetupError("profile_concurrent_change")
                    settings_v2.update(profile, expected_revision=current_profile["revision"], **changes)
                    pending["before_profiles"][str(profile)] = snapshot(profile)
                    pending["before_profile"] = pending["before_profiles"][str(settings)]
                    write(pending_path, encoded(pending))
                pending["before_profile"] = snapshot(settings)
                write(pending_path, encoded(pending))
            initialize(config, "windows-config")
            mkdir(bin_dir)
            if not pointer.exists():
                write(pointer, expected_pointer, pending["before_pointer"])
            if snapshot(prefix / "bootstrap.py") != {"sha256": digest(BOOTSTRAP)}:
                write(prefix / "bootstrap.py", BOOTSTRAP, pending["before_bootstrap"])
            if snapshot(bin_dir / "mrh.cmd") != {"sha256": digest(launcher)}:
                write(bin_dir / "mrh.cmd", launcher, pending["before_bin"])
            history = dict((state or {}).get("generations", {}))
            history[identifier] = pending["manifest"]
            new = {"owner": OWNER, "version": 1, "last_operation": pending["operation"], "current": identifier,
                   "hosts": {**(state or {}).get("hosts", {}), **selected}, "settings": str(settings), "generations": history,
                   "entrypoints":{'mrh.cmd':digest(launcher),'bootstrap.py':digest(BOOTSTRAP)},
                   "previous": {"current": state["current"], "hosts": state["hosts"]} if state else None}
            # One replace both records the receipt and selects the active generation.
            write(control / "state.json", encoded(new), pending["before_state"])
            path_change = path_manager.apply(path_plan)
            pending["phase"] = "complete"
            write(pending_path, encoded(pending))
            return readiness(args, new, paths, adapters, "rollback" if args.rollback else "installed", path_manager, path_change, catalogs=catalogs)



def parser():
    result = argparse.ArgumentParser(description="Install this checkout with an existing native Windows x64 Python >=3.11.")
    result.add_argument("--host", action="append", choices=("codex", "claude"), default=[])
    modes = result.add_mutually_exclusive_group()
    for name in ("check", "dry-run", "rollback"):
        modes.add_argument("--" + name, action="store_true")
    result.add_argument("--json", action="store_true")
    result.add_argument("--codex-packets", action="store_true")
    result.add_argument("--dev", action="store_true", help="explicitly run this editable checkout from the managed installation")
    for name in ("prefix", "config-root", "settings", "bin-dir", "claude-settings", "codex-executable", "claude-executable", "python"):
        aliases = ["--" + name]
        if name.endswith("-executable"):
            aliases.append("--" + name.replace("-executable", "-cli"))
        result.add_argument(*aliases, type=Path)
    scopes = result.add_mutually_exclusive_group()
    scopes.add_argument("--workspace", action="append", type=Path, default=[])
    scopes.add_argument('--all-workspaces', action='store_true', help='explicitly permit Jev export for every absolute Windows project on all drives and UNC shares')
    result.add_argument("--enable", action="store_true")
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        result, code = install(args), 0
        if result.get('installed'):
            from mrh.adapters.hosts.skill_registry import install_suggestions
            result['optional_skills'] = install_suggestions(result.get('hosts', {}))
    except (ValueError, OSError, subprocess.SubprocessError, KeyError) as exc:
        result = {"status": "incomplete", "reason": str(exc) if isinstance(exc, ValueError) else type(exc).__name__,
                  "provider_probe_performed": False,
                  "recovery": "Correct the cause and rerun the original arguments; retain setup-state/pending.json and generations."}
        code = 2
    if args.json:
        print(json.dumps(result, sort_keys=True, indent=2))
    else:
        print("MRH Windows setup: " + result["status"])
        if result.get("reason"):
            print(result["reason"])
        if result.get("settings"):
            print("Settings: " + result["settings"])
        command_path = result.get('command_path')
        if command_path:
            print('Command: ' + command_path['entrypoint'])
            if command_path['terminal_refresh'] == 'new_terminal_required':
                print('User PATH is saved for new processes. Existing parent processes were not refreshed.')
                print('Start a new shell from a process with the updated environment, then check:')
                print('  where.exe mrh')
                print('  mrh status --json')
        if result.get('optional_skills'):
            print('Optional delegation skills; install only if you choose to:')
            for command in result['optional_skills']['commands']:print('  '+command)
            print(result['optional_skills']['host_restart'])
        print("No classifier/model request was made.")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
