"""Checkout installer. No provider calls; persistent data is never a generation."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
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
from mrh.adapters.hosts.registry import REGISTRATIONS

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
    if manifest.get('schema_version') != 1 or manifest.get('files') != bundle.file_manifest(root):
        raise SetupError('manifest_invalid')
    for p in root.rglob('*'):
        if p.is_symlink() and not p.resolve().is_relative_to(root):
            raise SetupError('generation_link_escape')
    if not (root / manifest.get('private_interpreter', '')).is_file() or not (root / 'app/mrh.pyz').is_file():
        raise SetupError('generation_incomplete')
    return manifest


def source_fingerprint(hosts, packets, settings):
    files = list((ROOT / 'src/mrh').rglob('*.py')) + list((ROOT / 'src/mrh/resources').rglob('*'))
    files += [ROOT / n for n in ('setup', 'mrh_setup.py', 'mrh_bundle.py', 'mrh_build.py', 'pyproject.toml')]
    files += [bundle.LOCK]
    h = hashlib.sha256()
    for p in sorted(set(p for p in files if p.is_file())):
        h.update(p.relative_to(ROOT).as_posix().encode() + b'\0' + p.read_bytes())
    head = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    h.update(encoded({'head': head, 'hosts': hosts, 'packets': packets, 'settings': str(settings)}))
    return h.hexdigest()


def command(argv):
    try:
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
        st = self.executable.stat()
        if not stat.S_ISREG(st.st_mode) or st.st_mode & 0o022 or not os.access(self.executable, os.X_OK):
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
        if root and ours[0].get('marketplaceSource', {}).get('sourceType', 'local') != 'local':
            raise SetupError('codex_marketplace_unowned')
        if entries:
            registered = entries[0].get('marketplaceSource', {}).get('source')
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
            text=regular(self.path).decode()
            claude_hook.plan(text, 'model-routing-harness preflight claude')
            for rows in json.loads(text).get('hooks',{}).values():
                for entry in rows:
                    if not claude_hook._ours(entry): continue
                    for hook in entry.get('hooks',[]):
                        args=shlex.split(hook.get('command',''))
                        if not args or args[-1]!='claude': continue
                        try:
                            launcher=Path(args[-2]);root=launcher.parents[2]
                            info=plugin.show(root)['artifact']
                            if info['settings_path']!=str(settings) or shlex.split(claude_hook.command_for(root))!=args:
                                raise ValueError()
                        except (ValueError,IndexError,OSError,KeyError):
                            raise SetupError('claude_hook_unowned') from None
        return before

    def install(self, artifact, before, progress):
        text = regular(self.path).decode() if self.path.exists() else ''
        after = claude_hook.plan(text, claude_hook.command_for(artifact)).encode()
        if self.path.exists() and regular(self.path) == after:
            return {'configured': True, 'backup': None}
        if snapshot(self.path) != before:
            raise SetupError('claude_native_concurrent_change')
        backup = None
        if before is not None:
            backup = self.path.with_name(self.path.name + '.mrh-bak-' + uuid.uuid4().hex)
            fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'wb') as f:
                f.write(regular(self.path)); f.flush(); os.fsync(f.fileno())
        progress('claude_write_intent')
        write(self.path, after, before)
        if regular(self.path) != after:
            raise SetupError('claude_native_readback_failed')
        progress('claude_write_done')
        return {'configured': True, 'backup': str(backup) if backup else None}


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


def finish_generation(stage, destination, settings, selected, fingerprint):
    """Prepare inside private staging; publish only the complete final-path artifact."""
    for h, info in selected.items():
        artifact = stage / 'hosts' / h
        artifact.parent.mkdir(parents=True, exist_ok=True)
        plugin.prepare(artifact, settings, stage / 'runtime/bin/python3.11', advisory=True, codex_packets=info['packets'])
        # prepare verifies a real staging interpreter. Only owned JSON wiring is
        # rebased to the final immutable generation before its atomic rename.
        for p in artifact.rglob('*.json'):
            if p.name == 'artifact.json': continue
            data = p.read_bytes().replace(str(stage).encode(), str(destination).encode())
            p.write_bytes(data); p.chmod(0o600)
        meta = document(artifact/'artifact.json')
        meta['python'] = str(destination/'runtime/bin/python3.11')
        meta['files'] = {name:bundle.sha256(artifact/name) for name in meta['files']}
        write(artifact/'artifact.json',encoded(meta))
        plugin.show(artifact)
    write(stage/'generation.json',encoded({'owner':OWNER,'fingerprint':fingerprint,'reader':READER,'hosts':selected}))
    manifest=document(stage/'manifest.json');manifest['files']=bundle.file_manifest(stage)
    write(stage/'manifest.json',encoded(manifest));verify_bundle(stage)


def readiness(args, state, paths, hosts=None):
    prefix, config, bin_dir, pointer, settings = paths
    control = prefix / 'setup-state'
    result = {'status': 'pending', 'installed': False, 'configured': False, 'settings': str(settings),
              'enabled': False, 'export_permitted': False, 'credential_present': None, 'policy_ready': False,
              'trust': 'unverified', 'last_real_dispatch': None, 'last_real_dispatch_status': 'not_probed',
              'provider_probe_performed': False, 'hosts': {}, 'pending': []}
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
                    valid=False;result['policy_validation'][host]={'compatible':None,'reason':'catalog_unavailable','account_availability':'not_probed'}
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
    result['status'] = 'installed' if result['installed'] else 'pending'
    return result


def install(args, *, build=bundle.build):
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
        fingerprint = source_fingerprint(hosts, args.codex_packets, settings)
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
                with tempfile.TemporaryDirectory(prefix='.stage-', dir=control) as temporary:
                    temporary = Path(temporary); stage = temporary / 'bundle'
                    cache = canonical(args.cache_root or prefix / 'setup-cache')
                    if os.environ.get('MRH_SETUP_BOOTSTRAP_ASSET'):
                        assets = bundle.read_lock(); source = Path(os.environ['MRH_SETUP_BOOTSTRAP_ASSET'])
                        if source.stat().st_size != assets['runtime']['size'] or bundle.sha256(source) != assets['runtime']['sha256']:
                            raise SetupError('bootstrap_hash_mismatch')
                        cache=bundle.asset_cache(cache,assets)
                        if not (cache/assets['runtime']['name']).exists(): shutil.copyfile(source,cache/assets['runtime']['name'])
                    build(cache, stage, temporary / 'bundle.tar.gz', download=True)
                    verify_bundle(stage)
                    prepare_profile()
                    finish_generation(stage,generation,settings,selected,fingerprint)
                    stage.rename(generation)
            else:
                verify_bundle(generation)
                metadata=document(generation/'generation.json')
                if metadata.get('owner') != OWNER or metadata.get('fingerprint') != fingerprint:
                    raise SetupError('generation_unowned')
                prepare_profile()
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


def parser():
    p=argparse.ArgumentParser(description='Install/update this checkout; never git pull or call a classifier.')
    p.add_argument('--host',action='append',choices=tuple(REGISTRATIONS),default=[])
    mode=p.add_mutually_exclusive_group();mode.add_argument('--check',action='store_true');mode.add_argument('--dry-run',action='store_true');mode.add_argument('--rollback',action='store_true')
    p.add_argument('--json',action='store_true');p.add_argument('--codex-packets',action='store_true',help='explicit optional full-task packet artifact/skill; not default')
    for name in ('prefix','config-root','bin-dir','cache-root','settings','codex-cli','claude-cli','claude-settings'):
        p.add_argument('--'+name,type=Path)
    p.add_argument('--workspace',action='append',type=Path,default=[]);p.add_argument('--enable',action='store_true')
    return p


def main(argv=None):
    args=parser().parse_args(argv)
    try:
        result=install(args);code=0
    except (ValueError,OSError,subprocess.SubprocessError,KeyError) as exc:
        reason = str(exc) if isinstance(exc,(SetupError,owned.OwnedError,settings_v2.SettingsError,bundle.BundleError)) else type(exc).__name__
        result={'status':'incomplete','reason':reason,'provider_probe_performed':False,'recovery':'Correct the cause, then rerun the same setup arguments; retain setup-state/journal.json.'};code=2
    if args.json: print(json.dumps(result,indent=2,sort_keys=True))
    else:
        print('MRH setup: '+result['status'])
        if result.get('reason'):print(result['reason'])
        if result.get('settings'):print('Settings: '+result['settings'])
        if result.get('pending'):print('Pending: '+', '.join(result['pending']))
        print('No classifier/model request was made.')
    return code


if __name__=='__main__': raise SystemExit(main())
