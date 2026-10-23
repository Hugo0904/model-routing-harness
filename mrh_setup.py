"""Checkout installer. No provider calls; persistent data is never a generation."""
from __future__ import annotations

import argparse
from contextlib import contextmanager, nullcontext
if __import__('os').name != 'nt':
    import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import queue
import shutil
import shlex
import stat
import subprocess
import sys
import tempfile
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
import mrh_bundle as bundle
from mrh.infrastructure import owned, plugin, settings_v2, claude_hook, secrets
from mrh.infrastructure import execution, locations
from mrh.infrastructure import temporary as project_temporary
from mrh.adapters.hosts.registry import REGISTRATIONS
from mrh.application import skills
from mrh.adapters.platforms.macos_path import UserPath, PathError, plan_removal as plan_path_removal, apply_removal as apply_path_removal

OWNER = 'org.model-routing-harness.setup.v1'
READER = {'settings': [1, 2], 'packet_statistics': 1}


class SetupError(ValueError):
    pass


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()


def regular(path):
    return owned.read_regular(path, 16_000_000)


def document(path):
    return json.loads(regular(path), object_pairs_hook=owned._unique)


def canonical(path):
    p = Path(path).expanduser().absolute()
    if p != p.resolve() or any(ord(c) < 32 for c in str(p)):
        raise SetupError('unsafe_path')
    if os.name == 'nt':
        from mrh.adapters.platforms.windows import assert_safe
        # Native ACL verification replaces, rather than drops, POSIX mode bits.
        if p.exists(): assert_safe(p, p.is_dir())
        return p
    for parent in (p, *p.parents):
        if parent.exists():
            st = parent.stat()
            if st.st_mode & 0o022 and parent != Path('/private/tmp'):
                # Sticky system temporary parents are safe for owner-only roots.
                if not st.st_mode & stat.S_ISVTX:
                    raise SetupError('writable_parent')
    return p


def snapshot(path):
    p = Path(path)
    if p.is_symlink():
        return {'symlink': os.readlink(p)}
    if p.exists():
        return {'sha256': hashlib.sha256(regular(p)).hexdigest(), 'mode': stat.S_IMODE(p.stat().st_mode)}
    return None


def write(path, data, expected='unchecked'):
    path = Path(path)
    if expected != 'unchecked' and snapshot(path) != expected:
        raise SetupError('concurrent_change:' + path.name)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    owned.replace_owned(path, data, limit=16_000_000)


def link(path, target, expected):
    path = Path(path)
    if snapshot(path) != expected:
        raise SetupError('concurrent_change:' + path.name)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_name('.mrh-link-' + uuid.uuid4().hex)
    try:
        temp.symlink_to(target)
        if snapshot(path) != expected:
            raise SetupError('concurrent_change:' + path.name)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def verify_bundle(root, digest=None):
    root = canonical(root)
    manifest = document(root / 'manifest.json')
    if digest and bundle.sha256(root / 'manifest.json') != digest:
        raise SetupError('manifest_changed')
    expected = manifest.get('files')
    actual = bundle.file_manifest(root)
    if manifest.get('schema_version') != 1 or not isinstance(expected, dict):
        raise SetupError('manifest_invalid')
    # Older manifests include bytecode. Keep their bytes/digest intact, but
    # compare only immutable files on both sides. Never exempt symlinks or
    # source-less bytecode: only runtime caches backed by a recorded .py file.
    def immutable(files):
        result = {}
        for name, entry in files.items():
            path = Path(name)
            source = None
            if path.parts[:1] == ('runtime',) and path.suffix == '.pyc' and isinstance(entry, dict) and 'symlink' not in entry:
                try:
                    source = (Path(importlib.util.source_from_cache(name)) if path.parent.name == '__pycache__'
                              else path.with_suffix('.py'))
                except ValueError:
                    pass
            source_entry = expected.get(source.as_posix()) if source else None
            if isinstance(source_entry, dict) and 'sha256' in source_entry and 'symlink' not in source_entry:
                continue
            result[name] = entry
        return result
    if immutable(expected) != immutable(actual):
        raise SetupError('manifest_invalid')
    for p in root.rglob('*'):
        if p.is_symlink() and not p.resolve().is_relative_to(root):
            raise SetupError('generation_link_escape')
    if not (root / manifest.get('private_interpreter', '')).is_file() or not (root / 'app/mrh.pyz').is_file():
        raise SetupError('generation_incomplete')
    return manifest


def source_fingerprint(hosts, packets, settings, dev=False):
    # A developer install runs the checkout's src directly, so editing it must not make a new version.
    files = ([ROOT / 'src/mrh/infrastructure' / name for name in ('execution.py', 'owned.py', 'plugin.py')]
             + list((ROOT / 'src/mrh/adapters/platforms').glob('*.py'))) if dev else (
             list((ROOT / 'src/mrh').rglob('*.py')) + list((ROOT / 'src/mrh/resources').rglob('*')))
    files += [ROOT / n for n in ('setup', 'mrh_setup.py', 'mrh_bundle.py', 'mrh_build.py', 'pyproject.toml', 'LICENSE')]
    files += [bundle.LOCK]
    files += [p for p in (ROOT/'packaging/macos-arm64/license-snapshot').rglob('*') if p.is_file()]
    h = hashlib.sha256()
    for p in sorted(set(p for p in files if p.is_file())):
        h.update(p.relative_to(ROOT).as_posix().encode() + b'\0' + p.read_bytes())
    # Only what goes into the installation counts: a commit that changes docs or tests must not make a new version.
    h.update(encoded({'hosts': hosts, 'packets': packets, 'settings': str(settings),
                      'runtime_root': str(locations.default_runtime_root()),
                      **({'dev_source': str(ROOT)} if dev else {})}))
    return h.hexdigest()


def command(argv):
    try:
        if os.name == 'nt':
            from mrh.adapters.platforms.windows_process import run
            r = run([str(x) for x in argv], timeout=40)
        else:
            r = subprocess.run([str(x) for x in argv], capture_output=True, text=True, timeout=40)
    except (OSError, subprocess.SubprocessError):
        raise SetupError('native_command_unavailable') from None
    if r.returncode:
        raise SetupError('native_command_failed:' + ':'.join(str(x) for x in argv[1:3]) + ':exit_' + str(r.returncode))
    try:
        return json.loads(r.stdout)
    except ValueError:
        raise SetupError('native_response_invalid') from None


class CodexInstaller:
    def __init__(self, executable=None):
        if executable is None:
            from mrh.adapters.catalogs.catalog import discover
            executable = next((x['executable'] for x in discover() if x['tool'] == 'codex' and x['supported']), None)
        if not executable:
            raise SetupError('codex_cli_missing')
        self.executable = canonical(executable)
        if os.name == 'nt':
            from mrh.adapters.platforms.windows import verify_codex_bundle
            verify_codex_bundle(self.executable)
        st = self.executable.stat()
        if not stat.S_ISREG(st.st_mode) or (os.name != 'nt' and st.st_mode & 0o022) or not os.access(self.executable, os.X_OK):
            raise SetupError('codex_cli_untrusted')

    def call(self, *args):
        return command([self.executable, 'plugin', *args, '--json'])

    def observe(self):
        markets = self.call('marketplace', 'list').get('marketplaces', [])
        listing = self.call('list')
        rows = listing.get('installed', [])
        ours = [m for m in markets if m.get('name') == plugin.MARKETPLACE]
        if len(ours) > 1 or any(r.get('name') == plugin.NAME and r.get('pluginId') != plugin.PLUGIN_ID for r in rows + listing.get('available', [])):
            raise SetupError('codex_name_conflict')
        entries = [r for r in rows if r.get('pluginId') == plugin.PLUGIN_ID]
        if len(entries) > 1:
            raise SetupError('codex_registration_conflict')
        root = ours[0].get('root') if ours else None
        if os.name == 'nt' and isinstance(root, str):
            root = str(Path(root.removeprefix('\\\\?\\')))
        if root and ours[0].get('marketplaceSource', {}).get('sourceType', 'local') != 'local':
            raise SetupError('codex_marketplace_unowned')
        if entries:
            registered = entries[0].get('marketplaceSource', {}).get('source')
            if os.name == 'nt' and isinstance(registered, str):
                registered = str(Path(registered.removeprefix('\\\\?\\')))
            if registered and registered != root:
                raise SetupError('codex_registration_conflict')
        return {'root': root, 'installed': bool(entries), 'enabled': entries[0].get('enabled') if entries else None}

    def preflight(self, settings, packets):
        before = self.observe()
        if before['installed'] and before['enabled'] is False:
            raise SetupError('codex_disabled_plugin_preserved:review_in_native_ui')
        if before['root']:
            info = plugin.show(Path(before['root']))['artifact']
            if info['settings_path'] != str(settings):
                raise SetupError('codex_settings_conflict')
            if info.get('codex_packets') and not packets:
                raise SetupError('codex_packet_mode_conflict:use_explicit_matching_mode')
        return before

    def trust(self, workspace):
        """Read the public hook definitions. Never write a private trust store."""
        process=None
        try:
            if os.name == 'nt':
                from mrh.adapters.platforms.windows_process import popen
                process=popen([str(self.executable),'--no-daemon','app-server','--listen','stdio://'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True)
            else:
                process=subprocess.Popen([str(self.executable),'--no-daemon','app-server','--listen','stdio://'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True)
            inbox=queue.Queue()
            def collect():
                for line in iter(lambda:process.stdout.readline(262145),''):
                    try:
                        if len(line)>262144:break
                        inbox.put(json.loads(line))
                    except ValueError:break
            threading.Thread(target=collect,daemon=True).start()
            def request(serial,method,params):
                process.stdin.write(json.dumps({'id':serial,'method':method,'params':params})+'\n');process.stdin.flush()
                deadline=time.monotonic()+6
                while time.monotonic()<deadline:
                    try:row=inbox.get(timeout=.1)
                    except queue.Empty:
                        if process.poll() is not None:raise SetupError('native_rpc_unavailable')
                        continue
                    if row.get('id')==serial:
                        if 'error'in row:raise SetupError('native_rpc_unavailable')
                        return row['result']
                raise SetupError('native_rpc_timeout')
            request(1,'initialize',{'clientInfo':{'name':'mrh_setup_readiness','version':'1'},'capabilities':{'experimentalApi':True}})
            process.stdin.write('{"method":"initialized"}\n');process.stdin.flush()
            reply=request(2,'hooks/list',{'cwd':str(workspace)})
            hooks=[h for row in reply['data'] for h in row['hooks'] if h.get('pluginId')==plugin.PLUGIN_ID]
            if len(hooks)<2:return 'unverified'
            if all(h.get('trustStatus')=='trusted' for h in hooks):return 'trusted'
            return 'untrusted' if any(h.get('trustStatus')=='untrusted' for h in hooks) else 'unverified'
        except (OSError,ValueError,KeyError,subprocess.SubprocessError):
            return 'unverified'
        finally:
            if process:
                if os.name == 'nt':
                    from mrh.adapters.platforms.windows_process import finish
                    finish(process)
                else:
                    try:process.stdin.close()
                    except OSError:pass
                    try:process.wait(timeout=1)
                    except subprocess.TimeoutExpired:process.kill();process.wait()
                    process.stdout.close()

    def install(self, artifact, before, progress):
        target = str(artifact)
        current = self.observe()
        if current['root'] not in (before['root'], target, None):
            raise SetupError('codex_native_concurrent_change')
        if current['root'] == target and current['installed']:
            return current
        if current['root'] and current['root'] != target:
            if current['installed']:
                progress('remove_plugin_intent')
                self.call('remove', plugin.PLUGIN_ID)
                progress('remove_plugin_done')
            if self.observe()['root'] != current['root']:
                raise SetupError('codex_native_concurrent_change')
            progress('remove_marketplace_intent')
            self.call('marketplace', 'remove', plugin.MARKETPLACE)
            progress('remove_marketplace_done')
        current = self.observe()
        if current['root'] not in (None, target):
            raise SetupError('codex_native_concurrent_change')
        if current['root'] is None:
            progress('add_marketplace_intent')
            self.call('marketplace', 'add', target)
            progress('add_marketplace_done')
        if self.observe()['root'] != target:
            raise SetupError('codex_native_readback_failed')
        progress('add_plugin_intent')
        self.call('add', plugin.PLUGIN_ID)
        progress('add_plugin_done')
        result = self.observe()
        if result['root'] != target or not result['installed']:
            raise SetupError('codex_native_readback_failed')
        return result


def verify_hook_owner(text, settings):
    """Every MRH hook in this settings.json must belong to an MRH artifact bound to `settings`; otherwise it is not ours."""
    claude_hook.plan(text, 'model-routing-harness preflight claude')
    for rows in json.loads(text).get('hooks',{}).values():
        for entry in rows:
            if not claude_hook._ours(entry): continue
            for hook in entry.get('hooks',[]):
                args=shlex.split(hook.get('command',''))
                if not args or args[-1]!='claude': continue
                # A hook written through <prefix>/current has a symlinked root, which plugin.show refuses; its
                # resolved generation path spells the same stable command.
                for resolve in (False,True):
                    try:
                        launcher=Path(args[-2]);root=(launcher.resolve() if resolve else launcher).parents[2]
                        info=plugin.show(root)['artifact']
                        if info['settings_path']!=str(settings) or shlex.split(claude_hook.command_for(root))!=args:
                            raise ValueError()
                        break
                    except Exception:
                        if resolve:raise SetupError('claude_hook_unowned') from None


class ClaudeInstaller:
    def __init__(self, path, executable=None):
        self.path = canonical(path)
        from mrh.adapters.catalogs.catalog import discover,describe_tool,CatalogError
        if executable is None:
            candidate=next((x for x in discover() if x['tool']=='claude' and x['supported']),None)
            source='catalog_discovery'
        else:
            candidate={'tool':'claude','executable':str(canonical(executable)),'supported':True}
            source='explicit_cli_override'
        if candidate is None:
            raise SetupError('claude_cli_missing')
        try:
            # Reuse the catalog's existing executable/working/version contract.
            # describe performs --version metadata only, not initialize/login/model.
            binding=describe_tool(candidate)
        except CatalogError as exc:
            raise SetupError('claude_cli_unavailable:'+str(exc)) from None
        except (OSError,subprocess.SubprocessError):
            raise SetupError('claude_cli_unavailable') from None
        self.cli={'executable':binding['executable'],'version':binding['version'],'source':source}

    def preflight(self, settings, packets=False):
        before = snapshot(self.path)
        if self.path.exists():
            verify_hook_owner(regular(self.path).decode(), settings)
        return before

    def install(self, artifact, before, progress):
        text = regular(self.path).decode() if self.path.exists() else ''
        after = claude_hook.plan(text, claude_hook.command_for(artifact)).encode()
        if self.path.exists() and regular(self.path) == after:
            return {'configured': True, 'backup': None}
        if snapshot(self.path) != before:
            raise SetupError('claude_native_concurrent_change')
        progress('claude_write_intent')
        write(self.path, after, before)
        if regular(self.path) != after:
            raise SetupError('claude_native_readback_failed')
        progress('claude_write_done')
        return {'configured': True, 'backup': None}


def host_configured(host, adapter, artifact):
    if host=='codex':
        value=adapter.observe()
        return value['root']==str(artifact) and value['installed'] and value['enabled'] is not False
    text=regular(adapter.path).decode() if adapter.path.exists() else ''
    return text==claude_hook.plan(text,claude_hook.command_for(artifact))


def resolve_paths(args):
    home = Path.home()
    prefix = canonical(args.prefix or home / '.local/share/model-routing-harness')
    config = canonical(args.config_root or home / '.config/model-routing-harness')
    bin_dir = canonical(args.bin_dir or home / '.local/bin')
    pointer = config / 'active-settings'
    current = regular(pointer).decode().strip() if pointer.exists() else None
    if args.settings and current and str(canonical(args.settings)) != current:
        raise SetupError('active_settings_conflict')
    settings = canonical(args.settings or current or config / 'profile/settings.json')
    if settings.name != 'settings.json' or settings.is_relative_to(prefix):
        raise SetupError('settings_code_overlap')
    return prefix, config, bin_dir, pointer, settings


def profile_preflight(path):
    if path.exists():
        return settings_v2.read(path)
    if path.parent.exists() and any(path.parent.iterdir()):
        owned.verify(path.parent, 'settings', settings_v2.FILES)
        if {p.name for p in path.parent.iterdir()} - {owned.MARKER, '.mrh.lock'}:
            raise SetupError('profile_incomplete_or_unowned')
    return None


def read_state(control):
    if not control.exists():
        return None
    st=control.lstat()
    if control.is_symlink() or not stat.S_ISDIR(st.st_mode) or st.st_uid!=os.getuid() or st.st_mode&0o022 or document(control / 'owner.json') != {'owner': OWNER, 'version': 1}:
        raise SetupError('setup_root_unowned')
    if (control / 'state.json').exists():
        value = document(control / 'state.json')
        if value.get('owner') != OWNER or value.get('version') != 1:
            raise SetupError('setup_state_invalid')
        def identifier(s):return isinstance(s,str) and len(s)==24 and all(c in '0123456789abcdef' for c in s)
        if not identifier(value.get('current')) or value['current'] not in value.get('generations',{}):
            raise SetupError('setup_state_invalid')
        if any(not identifier(k) or not isinstance(v,str) or len(v)!=64 for k,v in value['generations'].items()):
            raise SetupError('setup_state_invalid')
        for h,info in value.get('hosts',{}).items():
            if h not in REGISTRATIONS or not identifier(info.get('generation')) or info.get('artifact')!=str(control/'generations'/info['generation']/'hosts'/h):
                raise SetupError('setup_state_invalid')
        previous=value.get('previous')
        if previous:
            if not identifier(previous.get('current')) or previous['current'] not in value['generations']:
                raise SetupError('setup_state_invalid')
            for h,info in previous.get('hosts',{}).items():
                if h not in REGISTRATIONS or not identifier(info.get('generation')) or info.get('artifact')!=str(control/'generations'/info['generation']/'hosts'/h):
                    raise SetupError('setup_state_invalid')
        return value
    return None


@contextmanager
def locked(control):
    if control.exists():
        read_state(control)
    else:
        control.mkdir(parents=True, mode=0o700)
        write(control / 'owner.json', encoded({'owner': OWNER, 'version': 1}), None)
    fd = os.open(control / 'lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        st = os.fstat(fd)
        if st.st_uid != os.getuid() or not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
            raise SetupError('setup_lock_unowned')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SetupError('setup_busy') from None
        yield
    finally:
        os.close(fd)


def compatible(generation, settings):
    metadata = document(generation / 'generation.json')
    contract = metadata.get('reader', {})
    schema = json.loads(regular(settings))['schema_version'] if settings.exists() else 2
    if schema not in contract.get('settings', []) or contract.get('packet_statistics') != 1:
        raise SetupError('rollback_reader_incompatible')
    return metadata


def finish_generation(stage, destination, settings, selected, fingerprint, prefix, dev=False):
    """Prepare inside private staging; publish only the complete final-path artifact."""
    archive = regular(stage / 'app/mrh.pyz')
    editable = bundle.editable_files() if dev else None
    runtime = locations.default_runtime_root()
    if editable is not None:
        for name, data in editable.items():
            write(stage / 'app/editable' / name, data)
    for h, info in selected.items():
        artifact = stage / 'hosts' / h
        artifact.parent.mkdir(parents=True, exist_ok=True)
        plugin.prepare(artifact, settings, stage / 'runtime/bin/python3.11', advisory=True,
                       codex_packets=info['packets'], runtime_archive=archive, editable_files=editable,
                       runtime_root=runtime, dev_source=ROOT if dev else None)
        meta = document(artifact/'artifact.json')
        if h == 'codex':
            # Codex 0.162.1 discovers skills from the portable manifest but silently
            # omits its hooks. Use its supported compatibility manifest instead;
            # keeping both would let the portable manifest shadow these hooks.
            portable = Path('plugins') / plugin.NAME / 'plugin.json'
            native = portable.parent / '.codex-plugin/plugin.json'
            definition = document(artifact/portable)
            compatibility = {k:definition[k] for k in ('name','version','description')}
            compatibility['hooks'] = definition['extensions']['com.openai']['hooks']
            write(artifact/native,encoded(compatibility))
            (artifact/portable).unlink()
            del meta['files'][portable.as_posix()]
            meta['files'][native.as_posix()] = bundle.sha256(artifact/native)
        # prepare verifies a real staging interpreter. Only owned JSON wiring is
        # rebased to the final immutable generation before its atomic rename.
        for p in artifact.rglob('*.json'):
            if p.name == 'artifact.json': continue
            data = p.read_bytes().replace(str(stage).encode(), str(destination).encode())
            if h == 'codex' and p == artifact / 'plugins' / plugin.NAME / 'hooks/hooks.json':
                # Native trust covers this command. Keep it stable across updates;
                # PLUGIN_ROOT and binding.json still select the registered artifact.
                # Do not resolve current: it may point to the previous generation.
                data = data.replace(str(destination).encode(), str(prefix / 'current').encode())
            p.write_bytes(data); p.chmod(0o600)
        meta['python'] = str(destination/'runtime/bin/python3.11')
        meta['files'] = {name:bundle.sha256(artifact/name) for name in meta['files']}
        write(artifact/'artifact.json',encoded(meta))
        plugin.show(artifact)
    write(stage/'generation.json',encoded({'owner':OWNER,'fingerprint':fingerprint,'reader':READER,
          'hosts':selected,'runtime_root':str(runtime),**({'dev_source':str(ROOT)} if dev else {})}))
    manifest=document(stage/'manifest.json');manifest['files']=bundle.file_manifest(stage)
    write(stage/'manifest.json',encoded(manifest));verify_bundle(stage)


def readiness(args, state, paths, hosts=None):
    prefix, config, bin_dir, pointer, settings = paths
    control = prefix / 'setup-state'
    result = {'status': 'pending', 'installed': False, 'configured': False, 'settings': str(settings),
              'enabled': False, 'export_permitted': False, 'credential_present': None, 'policy_ready': False,
              'trust': 'unverified', 'last_real_dispatch': None, 'last_real_dispatch_status': 'not_probed',
              'provider_probe_performed': False, 'hosts': {}, 'pending': [],
              'execution_mode': None, 'source': None, 'runtime_root': None}
    journal = control / 'journal.json'
    result['transaction_pending'] = journal.exists() and document(journal).get('phase') != 'complete'
    if result['transaction_pending']:
        result['pending'].append('installation_recovery')
    selected=hosts or args.host or list((state or {}).get('hosts',{}))
    claude_adapter=None
    if 'claude' in selected:
        try:
            claude_adapter=ClaudeInstaller(args.claude_settings or Path.home()/'.claude/settings.json',args.claude_cli)
            result['hosts']['claude']={'configured':False,'trust':'unverified','cli_available':True,'cli':claude_adapter.cli}
        except (ValueError,OSError) as exc:
            result['hosts']['claude']={'configured':False,'trust':'unverified','cli_available':False,'reason':str(exc)}
            result['pending'].append('claude_cli')
    if state:
        root = control / 'generations' / state['current']
        verify_bundle(root, state['generations'][state['current']])
        result['installed'] = snapshot(prefix / 'current') == {'symlink': str(root)} and snapshot(bin_dir / 'mrh') == {'symlink': str(prefix / 'current/mrh')}
        result['generation'] = state['current']
        metadata = document(root / 'generation.json')
        dev_source = metadata.get('dev_source')
        runtime, source = execution.runtime_binding(metadata)
        result.update(execution_mode='development' if dev_source else 'installed', source=source, runtime_root=runtime)
        if dev_source:
            try:
                execution.editable_source(root / 'app/editable', dev_source)
                result['source_ready'] = True
            except (OSError, ValueError) as exc:
                result.update(source_ready=False, source_error=str(exc))
                result['pending'].append('development_source')
            result['dev_source'] = dev_source
    if settings.exists():
        value = settings_v2.read(settings)
        result.update(configured=True, enabled=value['enabled'], export_permitted=value['task_export_permitted'])
        p = value['policy']
        complete = bool(selected) and all(p.get('tiers', {}).get(t, {}).get(h) for h in selected for t in ('Light', 'Small', 'Mid')) and (p.get('top_mode', 'Main') == 'Main' or all(p.get('fixed', {}).get(h) for h in selected))
        result['policy_configured']=complete
        result['policy_validation']={}
        valid=complete
        if complete:
            from mrh.adapters.catalogs.catalog import public_models,CatalogError
            for host in selected:
                if host=='claude' and claude_adapter is None:
                    valid=False;result['policy_validation'][host]={'compatible':None,'reason':'claude_cli_unavailable','account_availability':'not_probed'}
                    continue
                try:
                    catalog=public_models(host)
                    candidates=[c for tier in ('Light','Small','Mid') for c in p['tiers'][tier][host]]
                    if p.get('top_mode','Main')=='Fixed':candidates+=p['fixed'][host]
                    supported=all(catalog.option(c['model'],c.get('effort')) for c in candidates)
                    valid=valid and supported
                    result['policy_validation'][host]={'compatible':bool(supported),'assurance':catalog.assurance,'source':catalog.source,'fetched_at':catalog.fetched_at,'account_availability':'not_probed'}
                except (ValueError,OSError,subprocess.SubprocessError):
                    if host != 'claude':valid=False
                    result['policy_validation'][host]={'compatible':None,'reason':'catalog_unavailable','manual_configuration':host=='claude','account_availability':'not_probed'}
        result['policy_ready']=bool(valid)
        provider = value['classifier']['provider']
        result['credential_present'] = bool(os.environ.get('TYPESAFE_API_KEY')) or secrets.is_set('jev') if provider == 'jev' else None
        result['classifier'] = {'provider': provider, 'model': value['classifier']['model']}
        result['workspace_ready'] = bool(settings_v2.effective_roots(value)[0])
    else:
        result['workspace_ready'] = False
    for h, info in (state or {}).get('hosts', {}).items():
        if h not in selected:continue
        if h == 'codex':
            try:
                adapter=CodexInstaller(args.codex_cli);observed=adapter.observe()
                result['hosts'][h] = {'configured': observed['root'] == info['artifact'] and observed['installed'], 'trust': adapter.trust(Path.cwd()), 'packets': info['packets']}
            except (ValueError, OSError):
                result['hosts'][h] = {'configured': False, 'trust': 'unverified', 'reason': 'native_readback_unavailable'}
        else:
            if claude_adapter is None:continue
            cp = Path(info['config'])
            text = regular(cp).decode() if cp.exists() else ''
            expected = claude_hook.plan(text, claude_hook.command_for(info['artifact']))
            result['hosts'][h] = {**result['hosts'][h],'configured': text == expected, 'trust': 'not_applicable_native_settings'}
    for key in ('installed', 'configured', 'enabled', 'export_permitted', 'credential_present', 'policy_ready', 'workspace_ready'):
        if not result[key]: result['pending'].append(key)
    if any(not x['configured'] for x in result['hosts'].values()): result['pending'].append('host_configuration')
    trusts=[h['trust'] for h in result['hosts'].values()]
    result['trust']='trusted' if trusts and all(t in ('trusted','not_applicable_native_settings') for t in trusts) else 'untrusted' if 'untrusted'in trusts else 'unverified'
    if result['trust']!='trusted':result['pending'].append('native_trust_or_unverified')
    result['status'] = 'installed' if result['installed'] and not result['transaction_pending'] else 'pending'
    return result


def _install(args, *, build=bundle.build):
    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        raise SetupError('unsupported_platform:macOS_arm64_only')
    paths = resolve_paths(args)
    prefix, config, bin_dir, pointer, settings = paths
    control = prefix / 'setup-state'
    state = read_state(control)
    if args.check:
        return readiness(args, state, paths)
    hosts = list(dict.fromkeys(args.host or list((state or {}).get('hosts', {}))))
    if not hosts:
        raise SetupError('host_required')
    if args.codex_packets and 'codex' not in hosts:
        raise SetupError('codex_packets_requires_codex')
    if args.enable and not args.workspace:
        raise SetupError('enable_requires_explicit_workspace')
    if args.dev and args.rollback:
        raise SetupError('dev_cannot_combine_with_rollback')
    if args.rollback and (args.enable or args.workspace or args.codex_packets):
        raise SetupError('rollback_does_not_change_policy_or_packet_mode')
    value = profile_preflight(settings)
    before_bin = snapshot(bin_dir / 'mrh')
    allowed_links = {str(prefix / 'current/mrh'), str(prefix / 'app/mrh')}
    if before_bin and ('symlink' not in before_bin or before_bin['symlink'] not in allowed_links):
        raise SetupError('bin_conflict')
    before_current = snapshot(prefix / 'current')
    pending = document(control/'journal.json') if (control/'journal.json').exists() else None
    pending_current = {'symlink':str(control/'generations'/pending['target'])} if pending and pending.get('phase')=='committing' and pending.get('target') else None
    if before_current and before_current != pending_current and (not state or before_current != {'symlink': str(control / 'generations' / state['current'])}):
        raise SetupError('current_generation_conflict')
    adapters = {h: CodexInstaller(args.codex_cli) if REGISTRATIONS[h].installation == 'official-plugin' else ClaudeInstaller(args.claude_settings or Path.home() / '.claude/settings.json',args.claude_cli) for h in hosts}
    if args.dry_run:
        for h, adapter in adapters.items(): adapter.preflight(settings, (state or {}).get('hosts',{}).get(h,{}).get('packets',False) if args.rollback else args.codex_packets if h == 'codex' else False)
        return {'status': 'planned', 'writes': False, 'downloads': False, 'hosts': hosts, 'settings': str(settings), 'packet_opt_in': args.codex_packets, 'rollback': args.rollback}
    with locked(control):
        state = read_state(control)
        if snapshot(bin_dir / 'mrh') != before_bin or snapshot(prefix / 'current') != before_current:
            raise SetupError('preflight_concurrent_change')
        before_pointer = snapshot(pointer)
        if pointer.exists() and regular(pointer).decode().strip()!=str(settings):
            raise SetupError('active_settings_concurrent_change')
        before_profile = snapshot(settings)
        journal_path = control / 'journal.json'
        journal = document(journal_path) if journal_path.exists() else None
        fingerprint = source_fingerprint(hosts, args.codex_packets, settings, args.dev)
        intent={'enable':args.enable,'workspaces':[str(canonical(p)) for p in args.workspace]}
        if journal and journal.get('phase') != 'complete':
            if journal['fingerprint'] != fingerprint or journal['hosts'] != hosts or journal['rollback'] != args.rollback or journal.get('intent') != intent:
                raise SetupError('pending_operation_conflict')
            if state and state.get('last_operation') == journal['operation']:
                verify_bundle(control/'generations'/state['current'],state['generations'][state['current']])
                journal['phase']='complete';write(journal_path,encoded(journal))
                return {**readiness(args,state,paths,hosts),'operation':'recovered'}
        else:
            native = {h: a.preflight(settings, (state or {}).get('hosts',{}).get(h,{}).get('packets',False) if args.rollback else args.codex_packets if h == 'codex' else False) for h,a in adapters.items()}
            journal = {'owner': OWNER, 'operation': uuid.uuid4().hex, 'phase': 'preflight', 'fingerprint': fingerprint,
                       'hosts': hosts, 'rollback': args.rollback, 'before_hosts': native, 'completed_hosts': [],
                       'before_bin': before_bin, 'before_pointer': before_pointer, 'before_current': before_current,
                       'before_profile': before_profile,'intent':intent}
        if state:
            verify_bundle(control / 'generations' / state['current'], state['generations'][state['current']])
        if args.rollback:
            previous = (state or {}).get('previous')
            if not previous or any(h not in previous['hosts'] for h in hosts):
                raise SetupError('rollback_history_missing')
            identifier = previous['current']
            generation = control / 'generations' / identifier
            verify_bundle(generation, state['generations'][identifier]); compatible(generation, settings)
            selected = {h: previous['hosts'][h] for h in hosts}
        else:
            identifier = fingerprint[:24]
            generation = control / 'generations' / identifier
            selected = {h: {'artifact': str(generation / 'hosts' / h), 'generation': identifier,
                            'packets': args.codex_packets if h == 'codex' else False,
                            **({'config': str(adapters[h].path)} if h == 'claude' else {})} for h in hosts}
            if state and state['current'] == identifier and all(state['hosts'].get(h) == selected[h] for h in hosts) and journal.get('phase') in ('preflight','complete') and not args.enable and not args.workspace:
                for h,a in adapters.items():
                    if not host_configured(h,a,Path(selected[h]['artifact'])):raise SetupError('native_registration_changed')
                return {**readiness(args,state,paths,hosts), 'operation': 'unchanged'}
            journal['target'] = identifier; journal['phase'] = 'building'
            write(journal_path, encoded(journal))
            def prepare_profile():
                if snapshot(settings) != journal['before_profile']:
                    if journal['before_profile'] is not None or settings_v2.read(settings) != settings_v2.default_settings():
                        raise SetupError('profile_concurrent_change')
                profile_preflight(settings)
                settings.parent.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
                settings_v2.init(settings)
                journal['before_profile']=snapshot(settings);write(journal_path,encoded(journal))
            if not generation.exists():
                generations = control / 'generations'; generations.mkdir(exist_ok=True, mode=0o700)
                with tempfile.TemporaryDirectory(prefix='.stage-', dir=generations) as temporary:
                    temporary = Path(temporary); stage = temporary / 'bundle'
                    cache = canonical(args.cache_root or project_temporary.area('cache') / 'installer-assets')
                    if os.environ.get('MRH_SETUP_BOOTSTRAP_ASSET'):
                        assets = bundle.read_lock(); source = Path(os.environ['MRH_SETUP_BOOTSTRAP_ASSET'])
                        if source.stat().st_size != assets['runtime']['size'] or bundle.sha256(source) != assets['runtime']['sha256']:
                            raise SetupError('bootstrap_hash_mismatch')
                        cache=bundle.asset_cache(cache,assets)
                        if not (cache/assets['runtime']['name']).exists(): shutil.copyfile(source,cache/assets['runtime']['name'])
                    build(cache, stage, temporary / 'bundle.tar.gz', download=True)
                    verify_bundle(stage)
                    prepare_profile()
                    finish_generation(stage,generation,settings,selected,fingerprint,prefix,args.dev)
                    stage.rename(generation)
            else:
                verify_bundle(generation)
                metadata=document(generation/'generation.json')
                if metadata.get('owner') != OWNER or metadata.get('fingerprint') != fingerprint:
                    raise SetupError('generation_unowned')
                prepare_profile()
        changed_binding = state and any(
            execution.runtime_binding(document(control / 'generations' / old_id / 'generation.json'))
            != execution.runtime_binding(document(generation / 'generation.json'))
            for old_id in {state['current'], *(item['generation'] for item in state['hosts'].values())})
        profiles = [settings]
        if state:
            profiles.append(Path(state['settings']))
            profiles.extend(Path(document(Path(item['artifact']) / 'artifact.json')['settings_path'])
                            for item in state['hosts'].values())
        admission = execution.packet_mode_transition(profiles) if changed_binding else nullcontext()
        with admission:
            journal['target'] = identifier; journal['phase'] = 'registering'; write(journal_path,encoded(journal))
            for h,adapter in adapters.items():
                if h in journal['completed_hosts']: continue
                def progress(step):
                    journal['native_step'] = {'host':h,'step':step}; write(journal_path,encoded(journal))
                adapter.install(Path(selected[h]['artifact']), journal['before_hosts'][h], progress)
                journal['completed_hosts'].append(h); write(journal_path,encoded(journal))
            for h,adapter in adapters.items():
                if not host_configured(h,adapter,Path(selected[h]['artifact'])):
                    raise SetupError('native_registration_concurrent_change')
            journal['phase'] = 'committing'; write(journal_path,encoded(journal))
            if snapshot(pointer) != journal['before_pointer'] and not (journal['before_pointer'] is None and pointer.is_file() and regular(pointer)==(str(settings)+'\n').encode()):
                raise SetupError('active_pointer_concurrent_change')
            # A fresh profile was initialized above; existing bytes are preserved unless explicitly configured.
            if args.enable or args.workspace:
                if snapshot(settings) != journal['before_profile']:
                    raise SetupError('profile_concurrent_change')
                current_profile = settings_v2.read(settings)
                changes = {'allowed_workspaces':[str(canonical(p)) for p in args.workspace],'workspace_allowlist_file':None} if args.workspace else {}
                if args.enable: changes.update(enabled=True,task_export_permitted=True)
                settings_v2.update(settings,expected_revision=current_profile['revision'],**changes)
            old = {'current':state['current'],'hosts':state['hosts']} if state else None
            history = dict((state or {}).get('generations',{})); history[identifier] = bundle.sha256(generation/'manifest.json')
            new = {'owner':OWNER,'version':1,'last_operation':journal['operation'],'current':identifier,'hosts':{**(state or {}).get('hosts',{}),**selected},
                   'generations':history,'previous':old,'settings':str(settings)}
            if snapshot(prefix/'current') != {'symlink':str(generation)}:
                link(prefix/'current',str(generation),journal['before_current'])
            if snapshot(bin_dir/'mrh') != {'symlink':str(prefix/'current/mrh')}:
                link(bin_dir/'mrh',str(prefix/'current/mrh'),journal['before_bin'])
            if not pointer.exists(): write(pointer,(str(settings)+'\n').encode(),None)
            write(control/'state.json',encoded(new))
            journal['phase']='complete'; write(journal_path,encoded(journal))
            return {**readiness(args,new,paths,hosts),'operation':'rollback' if args.rollback else 'installed',
                    'legacy_app_preserved':(prefix/'app').exists(),'receipt':str(journal_path)}



def install(args, *, build=bundle.build, path_manager=None):
    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        return _install(args, build=build)
    paths = resolve_paths(args)
    manager = path_manager or UserPath(paths[2])
    plan = None if args.check else manager.plan()
    result = _install(args, build=build)
    change = None
    if not args.check and not args.dry_run:change = manager.apply(plan)
    result['command_path'] = manager.report()
    if change:result['command_path']['change'] = change
    if not result['command_path']['future_terminal_ready']:
        result.setdefault('pending', []).append('command_path')
    if result.get('installed'):
        from mrh.adapters.hosts.skill_registry import install_suggestions
        result['optional_skills'] = install_suggestions(result.get('hosts', {}))
    return result


# ---- uninstall -------------------------------------------------------------------------------------------------
# Everything is planned first (ownership checks, nothing written) and applied only with --yes. Host registrations go
# first and the generations they point to go last, so a failure leaves a state the same command can finish.

CONTROL_ENTRIES = {'owner.json', 'state.json', 'journal.json', 'lock', 'generations'}


def _step(phase, id, target, detail, run):
    return {'phase': phase, 'id': id, 'target': str(target), 'detail': detail, 'run': run}


def _note(id, target, reason, **extra):
    return {'id': id, 'target': str(target), 'reason': reason, **extra}


def _reason(exc):
    known = (SetupError, owned.OwnedError, settings_v2.SettingsError, bundle.BundleError, PathError, claude_hook.ClaudeHookError)
    return str(exc) if isinstance(exc, known) else type(exc).__name__


def _plan_claude(args, state, settings, plan):
    configured = (state or {}).get('hosts', {}).get('claude', {}).get('config')
    wanted = args.claude_settings or configured or Path.home() / '.claude/settings.json'
    try:
        path = canonical(wanted)
        if not path.exists():
            return
        text = regular(path).decode()
        document = json.loads(text)
        hooks = document.get('hooks', {}) if isinstance(document, dict) else None
        if not isinstance(hooks, dict):
            raise SetupError('claude_settings_shape_unexpected')
        if not any(claude_hook._ours(e) for rows in hooks.values() if isinstance(rows, list) for e in rows):
            return
        verify_hook_owner(text, settings)
    except (ValueError, OSError) as exc:
        plan['blocked'].append(_note('claude_hook', wanted, _reason(exc) if not isinstance(exc, json.JSONDecodeError) else 'claude_settings_not_json'))
        return
    before = snapshot(path)

    def run():
        if snapshot(path) != before:
            raise SetupError('claude_native_concurrent_change')
        after = claude_hook.plan(text, '', remove=True).encode()
        write(path, after, before)
        if regular(path) != after:
            raise SetupError('claude_native_readback_failed')
    plan['steps'].append(_step('hosts', 'claude_hook', path, '移除 MRH 的 PreToolUse／PostToolUse Hook；其他 Hook 與設定保留', run))


def _plan_codex(args, settings, plan, required):
    try:
        adapter = CodexInstaller(args.codex_cli)
        observed = adapter.observe()
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        if required:
            plan['blocked'].append(_note('codex_plugin', args.codex_cli or 'codex', _reason(exc),
                                         hint='找不到可用的 Codex CLI；可用 --codex-cli 指定，或自行執行 codex plugin remove ' + plugin.PLUGIN_ID))
        return
    if observed['root'] is None and not observed['installed']:
        return
    try:
        if observed['root'] is None or plugin.show(Path(observed['root']))['artifact']['settings_path'] != str(settings):
            raise SetupError('codex_registration_unowned')
    except (ValueError, OSError) as exc:
        plan['blocked'].append(_note('codex_plugin', observed['root'] or 'codex', 'codex_registration_unowned' if not isinstance(exc, SetupError) else str(exc)))
        return

    def remove_plugin():
        now = adapter.observe()
        if now['root'] != observed['root']:
            raise SetupError('codex_native_concurrent_change')
        if now['installed']:
            adapter.call('remove', plugin.PLUGIN_ID)
        if adapter.observe()['installed']:
            raise SetupError('codex_native_readback_failed')

    def remove_marketplace():
        now = adapter.observe()
        if now['root'] is None:
            return
        if now['root'] != observed['root'] or now['installed']:
            raise SetupError('codex_native_concurrent_change')
        adapter.call('marketplace', 'remove', plugin.MARKETPLACE)
        if adapter.observe()['root'] is not None:
            raise SetupError('codex_native_readback_failed')
    if observed['installed']:
        plan['steps'].append(_step('hosts', 'codex_plugin', plugin.PLUGIN_ID, '以 Codex 原生指令移除 MRH 外掛（其 Hook 隨外掛移除；Codex 自己的信任紀錄與 config.toml 不由 MRH 直接修改）', remove_plugin))
    plan['steps'].append(_step('hosts', 'codex_marketplace', observed['root'], '以 Codex 原生指令移除 MRH 的本機 marketplace', remove_marketplace))


def _plan_skills(hosts, plan):
    for host in hosts:
        try:
            info = skills.status(host)
        except (ValueError, OSError) as exc:
            plan['keep'].append(_note('skill_' + host, host, 'skill_location_unverified'))
            continue
        if info['status'] == 'not_installed':
            continue
        if info['status'] in ('latest', 'outdated'):
            plan['steps'].append(_step('skills', 'skill_' + host, info['path'], '移除選配派工 skill（內容與發行版相同）',
                                       lambda host=host: skills.run('remove', host)))
        else:
            plan['keep'].append(_note('skill_' + host, info['path'], 'skill_' + info['status'],
                                      hint='mrh skill remove --host ' + host + ' --force --backup-dir <專案外的備份目錄>'))


def _plan_path(bin_dir, plan):
    try:
        found = plan_path_removal(bin_dir)
    except (OSError, ValueError) as exc:
        plan['blocked'].append(_note('shell_path', bin_dir, _reason(exc)))
        return
    for item in found['blocked']:
        plan['blocked'].append(_note('shell_path', item['path'], item['reason'], hint='區塊被改過或無法安全讀取；請自行檢查並刪除 MRH 標記的區塊'))
    for row in found['remove']:
        plan['steps'].append(_step('path', 'shell_path', row['path'], '移除 MRH 標記的 PATH 區塊（檔案其餘內容保留）', lambda row=row: apply_path_removal([row])))


def _remove_tree(path):
    """Delete a directory tree without following links; generations may hold read-only directories."""
    os.chmod(path, 0o700)
    with os.scandir(path) as entries:
        children = list(entries)
    for child in children:
        if child.is_symlink() or not child.is_dir(follow_symlinks=False):
            os.unlink(child.path)
        else:
            _remove_tree(child.path)
    os.rmdir(path)


def remove_setup_state(control, prefix):
    names = {p.name for p in control.iterdir()}
    if names - CONTROL_ENTRIES:
        raise SetupError('setup_state_unexpected_entry:' + sorted(names - CONTROL_ENTRIES)[0])
    generations = control / 'generations'
    if generations.exists():
        children = sorted(generations.iterdir())
        for child in children:
            known = (len(child.name) == 24 and all(c in '0123456789abcdef' for c in child.name)) or child.name.startswith('.stage-')
            if not known or child.is_symlink() or not child.is_dir():
                raise SetupError('setup_state_unexpected_entry:generations/' + child.name)
        for child in children:
            _remove_tree(child)
        generations.rmdir()
    for name in ('state.json', 'journal.json', 'lock', 'owner.json'):
        (control / name).unlink(missing_ok=True)
    control.rmdir()
    try:
        prefix.rmdir()    # only when nothing else (the legacy app directory) lives there
    except OSError:
        pass


def _plan_installation(prefix, bin_dir, control, plan):
    link = bin_dir / 'mrh'
    try:
        found = snapshot(link)
    except (ValueError, OSError):
        found = {'unreadable': True}
    if found == {'symlink': str(prefix / 'current/mrh')}:
        def drop_entry():
            if snapshot(link) != found:
                raise SetupError('concurrent_change:mrh')
            link.unlink()
        plan['steps'].append(_step('links', 'bin_entry', link, '移除 mrh 命令入口（符號連結）', drop_entry))
    elif found == {'symlink': str(prefix / 'app/mrh')}:
        plan['keep'].append(_note('bin_entry', link, 'legacy_app_entry', hint='舊版 app 的入口，不是這個安裝程式建立的'))
    elif found:
        plan['keep'].append(_note('bin_entry', link, 'not_an_mrh_link'))
    current = prefix / 'current'
    try:
        shape = snapshot(current)
    except (ValueError, OSError):
        shape = {'unreadable': True}
    if shape:
        target = shape.get('symlink')
        if target and Path(target).parent == control / 'generations':
            def drop_current():
                if snapshot(current) != shape:
                    raise SetupError('concurrent_change:current')
                current.unlink()
            plan['steps'].append(_step('links', 'current_link', current, '移除 current 連結', drop_current))
        else:
            plan['blocked'].append(_note('current_link', current, 'current_generation_conflict'))
            return
    if control.exists():
        plan['steps'].append(_step('state', 'setup_state', control, '移除安裝代、安裝狀態與紀錄（程式本體；不含設定與統計）',
                                   lambda: remove_setup_state(control, prefix)))


def verify_profile(settings):
    """The profile directory must be exactly what MRH created: marker plus known files, nothing else."""
    return owned.verify(settings.parent, 'settings', settings_v2.FILES)


def remove_profile(settings):
    root = verify_profile(settings)
    with owned.locked(root, 'settings', settings_v2.FILES):
        for child in list(root.iterdir()):
            if child.name not in (owned.MARKER, '.mrh.lock'):
                child.unlink()
    for name in ('.mrh.lock', owned.MARKER):
        (root / name).unlink(missing_ok=True)
    root.rmdir()


def _plan_data(paths, plan, purge):
    """User data stays unless --purge-data; it is also never purged while anything else could not be removed."""
    prefix, config, bin_dir, pointer, settings = paths
    found = []
    if settings.parent.exists():
        try:
            verify_profile(settings)
            found.append(('profile_data', settings.parent, '設定、分級與派工統計資料庫', lambda: remove_profile(settings)))
        except (ValueError, OSError) as exc:
            plan['keep'].append(_note('profile_data', settings.parent, 'profile_not_verified_as_mrh_owned:' + _reason(exc)))
    expected = (str(settings) + '\n').encode()
    if pointer.is_file() and not pointer.is_symlink() and regular(pointer) == expected:
        def drop_pointer():
            if regular(pointer) != expected:
                raise SetupError('concurrent_change:active-settings')
            pointer.unlink()
            try:
                config.rmdir()
            except OSError:
                pass
        found.append(('settings_pointer', pointer, '指向設定檔的指標', drop_pointer))
    if secrets.is_set('jev'):
        def drop_key():
            if not secrets.delete('jev'):
                raise SetupError('keychain_delete_failed')
        found.append(('keychain_jev', 'macOS 鑰匙圈：model-routing-harness／typesafe', 'Jev API 金鑰', drop_key))
    if (prefix / 'app').exists():
        plan['keep'].append(_note('legacy_app', prefix / 'app', 'legacy_app_preserved', hint='舊版 app 目錄，不是這個安裝程式建立的；確認沒有程序使用後可自行刪除'))
    for id, target, detail, run in found:
        if purge and not plan['blocked']:
            plan['steps'].append(_step('purge', id, target, '（--purge-data）刪除' + detail, run))
        elif purge:
            plan['keep'].append(_note(id, target, 'skipped_uninstall_incomplete', hint=detail))
        else:
            plan['keep'].append(_note(id, target, 'user_data_kept', hint=detail + '；加 --purge-data 才會刪除'))


def uninstall(args):
    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        raise SetupError('unsupported_platform:macOS_arm64_only')
    if args.enable or args.workspace or args.codex_packets or args.dev:
        raise SetupError('uninstall_does_not_change_policy_or_packet_mode')
    paths = resolve_paths(args)
    prefix, config, bin_dir, pointer, settings = paths
    control = prefix / 'setup-state'
    state = read_state(control)
    if args.host:
        hosts, required = list(dict.fromkeys(args.host)), True
    elif state and state.get('hosts'):
        hosts, required = list(state['hosts']), True
    else:
        hosts, required = ['claude', 'codex'], False
    plan = {'steps': [], 'keep': [], 'blocked': []}
    if 'claude' in hosts:
        _plan_claude(args, state, settings, plan)
    if 'codex' in hosts:
        _plan_codex(args, settings, plan, required)
    if plan['blocked']:
        # A host registration that cannot be removed still points at the installation: change nothing else until it is fixed.
        plan['keep'].append(_note('everything_else', control, 'skipped_host_registrations_remain', hint='Hook 仍指向安裝代；先解決阻擋項目，再重跑同一個指令'))
    else:
        _plan_skills(args.host or ['claude', 'codex'], plan)
        _plan_path(bin_dir, plan)
        _plan_installation(prefix, bin_dir, control, plan)
    _plan_data(paths, plan, args.purge_data)
    return _finish_uninstall(args, plan, hosts, control)


def _finish_uninstall(args, plan, hosts, control):
    def public(step):
        return {k: step[k] for k in ('id', 'target', 'detail')}
    result = {'hosts': hosts, 'purge_data': args.purge_data, 'writes': False, 'provider_probe_performed': False}
    steps = plan['steps']
    if not args.yes:
        result.update(mode='preview', remove=[public(s) for s in steps], keep=plan['keep'], blocked=plan['blocked'])
        result['status'] = 'blocked' if plan['blocked'] else 'planned' if steps else 'not_installed'
        result['next'] = '預覽，尚未變更任何東西；確認後加 --yes 執行' if steps else None
        return result
    removed, blocked, keep = [], list(plan['blocked']), list(plan['keep'])
    halted = set()
    with (locked(control) if control.exists() else nullcontext()):
        for phase in ('hosts', 'skills', 'path', 'links', 'state', 'purge'):
            for step in [s for s in steps if s['phase'] == phase]:
                if phase in halted or (phase == 'purge' and blocked):
                    keep.append(_note(step['id'], step['target'], 'skipped_uninstall_incomplete'))
                    continue
                try:
                    step['run']()
                    removed.append(public(step))
                    result['writes'] = True
                except (ValueError, OSError, subprocess.SubprocessError, KeyError) as exc:
                    blocked.append(_note(step['id'], step['target'], _reason(exc)))
                    if phase == 'hosts':
                        halted.update(('skills', 'path', 'links', 'state'))
                    result['writes'] = True
    result.update(mode='apply', removed=removed, keep=keep, blocked=blocked)
    result['status'] = 'incomplete' if blocked else 'uninstalled' if removed else 'not_installed'
    if blocked:
        result['recovery'] = '處理 blocked 內的原因後，重跑同一個指令；已移除的項目不會再動。'
    return result


def parser():
    p=argparse.ArgumentParser(description='Install/update this checkout; never git pull or call a classifier.')
    p.add_argument('--host',action='append',choices=tuple(REGISTRATIONS),default=[])
    mode=p.add_mutually_exclusive_group();mode.add_argument('--check',action='store_true');mode.add_argument('--dry-run',action='store_true');mode.add_argument('--rollback',action='store_true');mode.add_argument('--uninstall',action='store_true',help='preview (default) or, with --yes, remove MRH; user data is kept unless --purge-data')
    p.add_argument('--json',action='store_true');p.add_argument('--codex-packets',action='store_true',help='explicit optional full-task packet artifact/skill; not default')
    for name in ('prefix','config-root','bin-dir','cache-root','settings','codex-cli','claude-cli','claude-settings'):
        p.add_argument('--'+name,type=Path)
    p.add_argument('--workspace',action='append',type=Path,default=[]);p.add_argument('--enable',action='store_true')
    p.add_argument('--dev',action='store_true',help='developer install: the hook and mrh run this checkout\'s src directly (no reinstall after edits; skips the runtime integrity hash). Rerun without --dev to go back')
    p.add_argument('--yes',action='store_true',help='with --uninstall: actually remove (otherwise preview only)')
    p.add_argument('--purge-data',action='store_true',help='with --uninstall --yes: also delete settings, statistics and the Jev key')
    return p


def print_uninstall(result):
    apply = result['mode'] == 'apply'
    print('MRH setup --uninstall: ' + result['status'] + ('' if apply else '（預覽，尚未變更任何東西）'))
    rows = result['removed'] if apply else result['remove']
    if rows:
        print('已移除：' if apply else '將移除：')
        for row in rows:
            print('  - ' + row['target'] + '　' + row['detail'])
    if result['keep']:
        print('保留：')
        for row in result['keep']:
            print('  - ' + row['target'] + '　' + row['reason'] + ('　' + row['hint'] if row.get('hint') else ''))
    if result['blocked']:
        print('未能處理：')
        for row in result['blocked']:
            print('  - ' + row['target'] + '　' + row['reason'] + ('　' + row['hint'] if row.get('hint') else ''))
    if result.get('recovery'):
        print(result['recovery'])
    if result.get('next'):
        print(result['next'])
    print('No classifier/model request was made.')


def main(argv=None):
    args=parser().parse_args(argv)
    try:
        if (args.yes or args.purge_data) and not args.uninstall:
            raise SetupError('yes_and_purge_data_require_uninstall')
        result=uninstall(args) if args.uninstall else install(args)
        code=2 if result.get('status') in ('blocked','incomplete') else 0
    except (ValueError,OSError,subprocess.SubprocessError,KeyError) as exc:
        reason = str(exc) if isinstance(exc,(SetupError,owned.OwnedError,settings_v2.SettingsError,bundle.BundleError,PathError)) else type(exc).__name__
        result={'status':'incomplete','reason':reason,'provider_probe_performed':False,'recovery':'Correct the cause, then rerun the same setup arguments; retain setup-state/journal.json.'};code=2
    if args.json: print(json.dumps(result,indent=2,sort_keys=True))
    elif args.uninstall and result.get('mode'): print_uninstall(result)
    else:
        print('MRH setup: '+result['status'])
        if result.get('reason'):print(result['reason'])
        if result.get('settings'):print('Settings: '+result['settings'])
        if result.get('pending'):print('Pending: '+', '.join(result['pending']))
        if result.get('command_path'):
            print('PATH: '+('new login/interactive shell ready' if result['command_path']['future_terminal_ready'] else 'not ready'))
            print('Existing parent processes were not refreshed; open a new shell and run: mrh status')
        if result.get('optional_skills'):
            print('選配派工 skill（不會自動安裝；由你選擇）：')
            for command in result['optional_skills']['commands']:print('  '+command)
            print(result['optional_skills']['host_restart'])
        print('No classifier/model request was made.')
    return code


if __name__=='__main__': raise SystemExit(main())
