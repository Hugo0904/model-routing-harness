"""Installation lifecycle through isolated roots and native-command format fixtures.

No model, login, HOME/CODEX_HOME substitution, or real host configuration writes.
The tiny interpreter wrapper is a fixture; the standalone build has its own proof.
"""
import copy
from contextlib import contextmanager
import hashlib
import io
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import mrh_setup as setup
import mrh_bundle as bundle
import mrh_build
from mrh.infrastructure import settings_v2


class SetupTests(unittest.TestCase):
    def test_moving_identical_checkout_changes_install_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Path(tmp) / 'profile/settings.json'
            fingerprints = []
            for name in ('first-clone', 'second-clone'):
                root = Path(tmp) / name; root.mkdir()
                (root / 'src/mrh').mkdir(parents=True)
                (root / 'src/mrh/example.py').write_text('same source\n')
                lock = root / 'runtime-lock.json'; lock.write_text('{}')
                result = subprocess.CompletedProcess([], 0, 'same-commit\n', '')
                with patch.object(setup, 'ROOT', root), patch.object(bundle, 'LOCK', lock), patch.object(setup.subprocess, 'run', return_value=result):
                    fingerprints.append(setup.source_fingerprint(['codex'], False, settings))
            self.assertNotEqual(*fingerprints)

    def test_only_program_changes_make_a_new_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'src/mrh').mkdir(parents=True); (root / 'docs').mkdir()
            (root / 'src/mrh/example.py').write_text('program\n'); (root / 'docs/README.md').write_text('text\n')
            lock = root / 'runtime-lock.json'; lock.write_text('{}')
            settings = root / 'profile/settings.json'
            def fingerprint():
                with patch.object(setup, 'ROOT', root), patch.object(bundle, 'LOCK', lock), \
                        patch.object(setup.subprocess, 'run', side_effect=AssertionError('the commit id must not matter')):
                    return setup.source_fingerprint(['codex'], False, settings)
            first = fingerprint()
            (root / 'docs/README.md').write_text('only words changed\n'); (root / 'README.md').write_text('new\n')
            self.assertEqual(fingerprint(), first)
            (root / 'src/mrh/example.py').write_text('program changed\n')
            self.assertNotEqual(fingerprint(), first)

    def test_dev_fingerprint_ignores_source_edits_but_differs_from_a_normal_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'src/mrh').mkdir(parents=True)
            (root / 'src/mrh/example.py').write_text('one\n')
            lock = root / 'runtime-lock.json'; lock.write_text('{}')
            settings = root / 'profile/settings.json'
            def fingerprint(dev):
                with patch.object(setup, 'ROOT', root), patch.object(bundle, 'LOCK', lock):
                    return setup.source_fingerprint(['codex'], False, settings, dev)
            normal, dev = fingerprint(False), fingerprint(True)
            (root / 'src/mrh/example.py').write_text('two\n')
            self.assertEqual(fingerprint(True), dev)
            self.assertNotEqual(fingerprint(False), normal)
            self.assertNotEqual(dev, normal)

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='mrh-setup-test-')
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve()
        p=patch.dict(os.environ, MRH_PROJECT_ROOT=str(self.root));p.start();self.addCleanup(p.stop)
        from mrh.adapters.platforms.macos_path import UserPath
        p=patch('mrh_setup.UserPath', side_effect=lambda bin_dir: UserPath(bin_dir, user_home=self.root/'home',
                environ={'PATH':'/usr/bin:/bin'}, login_shell='/bin/zsh'))
        p.start();self.addCleanup(p.stop)
        self.prefix=self.root/'install';self.config=self.root/'config';self.bin=self.root/'bin'
        self.native=self.root/'native.json'
        self.native.write_text(json.dumps({'root':None,'installed':False,'mutations':0}))
        self.cli=self.root/'codex'
        self.cli.write_text('#!'+sys.executable+'\n'+'''import json,sys
from pathlib import Path
path=Path('''+repr(str(self.native))+''')
v=json.loads(path.read_text());a=sys.argv[1:];action=None;out={}
if a[:3]==['plugin','marketplace','list']:
 out={'marketplaces':([{'name':'model-routing-harness-local','root':v['root'],'marketplaceSource':{'sourceType':'local','source':v['root']}}] if v['root'] else [])}
elif a[:2]==['plugin','list']:
 rows=([{'name':'model-routing-harness','pluginId':'model-routing-harness@model-routing-harness-local','installed':True,'enabled':True,'marketplaceSource':{'sourceType':'local','source':v['root']}}] if v['installed'] else [])
 if v.get('foreign'):rows.append({'name':'model-routing-harness','pluginId':'model-routing-harness@foreign'})
 out={'installed':rows,'available':[]}
elif a[:3]==['plugin','marketplace','add']:v['root']=a[3];action='marketplace-add'
elif a[:3]==['plugin','marketplace','remove']:v['root']=None;action='marketplace-remove'
elif a[:2]==['plugin','add']:
 v['installed']=True;action='plugin-add'
 if v.get('mutate_bin'):
  p=Path(v.pop('mutate_bin'));p.parent.mkdir(parents=True,exist_ok=True);p.write_text('foreign writer')
elif a[:2]==['plugin','remove']:v['installed']=False;action='plugin-remove'
else:raise SystemExit(2)
if action:
 v['mutations']+=1
 fail=v.get('fail_after')==action
 if fail:v.pop('fail_after')
 path.write_text(json.dumps(v))
 if fail:raise SystemExit(2)
print(json.dumps(out))
''')
        self.cli.chmod(0o700)
        from mrh.adapters.catalogs.claude_catalog import TESTED_VERSION
        self.claude=self.root/'claude-cli'
        self.claude.write_text('#!'+sys.executable+'\nimport sys\nif sys.argv[1:] != ["--version"]: raise SystemExit(9)\nprint('+repr(TESTED_VERSION)+')\n')
        self.claude.chmod(0o700)
        @contextmanager
        def fixture_isolation(executable):
            # Exercise the real describe/version parser on an owned executable,
            # without executing a live CLI or substituting HOME/CODEX_HOME.
            self.assertTrue(Path(executable).is_relative_to(self.root),'live Claude CLI forbidden in fixture')
            with tempfile.TemporaryDirectory(dir=self.root) as tmp:
                yield Path(tmp),dict(os.environ),[str(executable)],None,None
        p=patch('mrh.adapters.catalogs.claude_catalog.isolated_cli',fixture_isolation);p.start();self.addCleanup(p.stop)
        self.revision='one'
        for target,value in [('mrh_setup.platform.system','Darwin'),('mrh_setup.platform.machine','arm64'),('mrh_setup.secrets.is_set',False)]:
            p=patch(target,return_value=value);p.start();self.addCleanup(p.stop)
        from mrh.adapters.catalogs.catalog import Catalog,Model
        p=patch('mrh.adapters.catalogs.catalog.public_models',return_value=Catalog('fixture','codex','fixture','fixture-1','fixture',1,(Model('fixture-model','Fixture',('high',)),)))
        p.start();self.addCleanup(p.stop)
        p=patch.object(setup.CodexInstaller,'trust',return_value='unverified');p.start();self.addCleanup(p.stop)

    def args(self,*extra):
        return setup.parser().parse_args(['--host','codex','--prefix',str(self.prefix),'--config-root',str(self.config),'--bin-dir',str(self.bin),'--codex-cli',str(self.cli),*extra])

    def fake_build(self,cache,output,archive,**kwargs):
        output=Path(output);output.mkdir()
        python=output/'runtime/bin/python3.11';python.parent.mkdir(parents=True)
        python.write_text('#!/bin/sh\nexec '+json.dumps(sys.executable)+' "$@"\n');python.chmod(0o755)
        bundle.application_archive(output/'app/mrh.pyz')
        (output/'mrh').write_text('#!/bin/sh\nexit 0\n');(output/'mrh').chmod(0o755)
        manifest={'schema_version':1,'private_interpreter':'runtime/bin/python3.11','files':bundle.file_manifest(output)}
        (output/'manifest.json').write_text(json.dumps(manifest))
        Path(archive).write_bytes(b'fixture archive')

    def run_setup(self,args=None,build=None):
        fp=hashlib.sha256((self.revision+str((args or self.args()).codex_packets)+str((args or self.args()).host)).encode()).hexdigest()
        with patch('mrh_setup.source_fingerprint',return_value=fp):
            return setup.install(args or self.args(),build=build or self.fake_build)

    def state(self):return setup.document(self.prefix/'setup-state/state.json')
    def profile(self):return self.config/'profile/settings.json'
    def native_change(self,**fields):
        v=json.loads(self.native.read_text());v.update(fields);self.native.write_text(json.dumps(v))
    def disk(self):
        return {str(p.relative_to(self.root)):('link:'+os.readlink(p) if p.is_symlink() else p.read_bytes()) for p in self.root.rglob('*') if p.is_file() or p.is_symlink()}

    def test_claude_fake_cli_minimum_and_new_catalog_failure_do_not_block_hook(self):
        from mrh.adapters.catalogs.catalog import CatalogError
        def version(text):
            self.claude.write_text('#!'+sys.executable+'\nimport sys\nif sys.argv[1:] != ["--version"]: raise SystemExit(9)\nprint('+repr(text)+')\n')
            self.claude.chmod(0o700)
        for text in ('2.1.296', '2.1.300', '2.2.0', '3.0.0'):
            version(text + ' (Claude Code)')
            self.assertEqual(setup.ClaudeInstaller(self.root/'claude.json', self.claude).cli['version'], text + ' (Claude Code)')
        for text in ('2.1.295 (Claude Code)', 'unknown'):
            version(text)
            with self.assertRaises(setup.SetupError):setup.ClaudeInstaller(self.root/'claude.json', self.claude)
        version('2.2.0 (Claude Code)')
        cp = self.root/'claude-settings.json'
        args = self.args('--claude-settings', str(cp), '--claude-cli', str(self.claude)); args.host = ['claude']
        with patch('mrh.adapters.catalogs.catalog.public_models', side_effect=CatalogError('claude_catalog_protocol_incompatible')):
            self.assertTrue(self.run_setup(args)['hosts']['claude']['configured'])
            settings_v2.update(self.profile(), policy={'tiers': {tier: {'claude': [{'model': 'manual-model'}]} for tier in ('Light', 'Small', 'Mid')}})
            out = setup.readiness(args, self.state(), setup.resolve_paths(args))
        self.assertTrue(out['policy_ready'])
        self.assertIsNone(out['policy_validation']['claude']['compatible'])
        self.assertTrue(out['policy_validation']['claude']['manual_configuration'])
        self.assertNotIn('policy_ready', out['pending'])

    def test_same_generation_repairs_fake_shell_path_without_reregistering_or_installing_skills(self):
        first=self.run_setup()
        state=self.state();mutations=json.loads(self.native.read_text())['mutations']
        self.assertTrue(first['command_path']['future_terminal_ready'])
        self.assertFalse(first['optional_skills']['automatically_installed'])
        self.assertEqual(first['optional_skills']['commands'],['mrh skill install --host codex'])
        for name in ('.zprofile','.zshrc'):(self.root/'home'/name).unlink()
        preview=self.run_setup(self.args('--dry-run'))
        self.assertFalse(preview['command_path']['future_terminal_ready'])
        self.assertFalse((self.root/'home/.zshrc').exists())
        again=self.run_setup()
        self.assertTrue(again['command_path']['future_terminal_ready'])
        self.assertEqual(self.state(),state)
        self.assertEqual(json.loads(self.native.read_text())['mutations'],mutations)
        self.assertFalse((self.root/'home/.agents').exists())

    def test_fresh_disabled_complete_generation_and_separate_readiness(self):
        out=self.run_setup()
        self.assertTrue(out['installed']);self.assertTrue(out['configured'])
        self.assertFalse(out['enabled']);self.assertFalse(out['export_permitted']);self.assertFalse(out['policy_ready'])
        self.assertIn('native_trust_or_unverified',out['pending']);self.assertIsNone(out['last_real_dispatch'])
        state=self.state();generation=self.prefix/'setup-state/generations'/state['current']
        setup.verify_bundle(generation,state['generations'][state['current']])
        self.assertFalse((self.profile().parent/'advice.sqlite3').exists())
        self.assertFalse((generation/'hosts/codex/plugins/model-routing-harness/skills').exists())

    def test_repeat_update_and_rollback_preserve_new_profile_facts_and_legacy_app(self):
        legacy=self.prefix/'app';legacy.mkdir(parents=True);(legacy/'keep').write_bytes(b'Claude interpreter anchor')
        self.run_setup();first=self.state()['current']
        db=self.profile().parent/'advice.sqlite3';db.write_bytes(b'actual persisted facts fixture')
        policy={'tiers':{t:{'codex':[{'model':'fixture-model','effort':'high'}]} for t in ('Light','Small','Mid')}}
        settings_v2.update(self.profile(),policy=policy)
        profile=self.profile().read_bytes();pointer=(self.config/'active-settings').read_bytes()
        mutations=json.loads(self.native.read_text())['mutations']
        self.assertEqual(self.run_setup()['operation'],'unchanged')
        self.assertEqual(json.loads(self.native.read_text())['mutations'],mutations)
        self.revision='two';self.run_setup();second=self.state()['current'];self.assertNotEqual(first,second)
        db.write_bytes(b'new facts after update')
        self.run_setup(self.args('--rollback'))
        self.assertEqual(self.state()['current'],first)
        self.assertEqual(db.read_bytes(),b'new facts after update');self.assertEqual(self.profile().read_bytes(),profile)
        self.assertEqual((self.config/'active-settings').read_bytes(),pointer)
        self.assertEqual((legacy/'keep').read_bytes(),b'Claude interpreter anchor')

    def test_unknown_reader_rollback_refuses_before_native_mutation(self):
        self.run_setup();self.revision='two';self.run_setup();state=self.state()
        previous=state['previous']['current'];root=self.prefix/'setup-state/generations'/previous
        meta=setup.document(root/'generation.json');meta['reader']={};(root/'generation.json').write_text(json.dumps(meta))
        manifest=setup.document(root/'manifest.json');manifest['files']=bundle.file_manifest(root);(root/'manifest.json').write_text(json.dumps(manifest))
        state['generations'][previous]=bundle.sha256(root/'manifest.json');(self.prefix/'setup-state/state.json').write_text(json.dumps(state))
        before=json.loads(self.native.read_text())['mutations']
        with self.assertRaisesRegex(setup.SetupError,'reader_incompatible'):self.run_setup(self.args('--rollback'))
        self.assertEqual(json.loads(self.native.read_text())['mutations'],before)
        self.assertEqual(self.state()['current'],state['current'])

    def test_codex_hook_bytes_stay_stable_and_execute_selected_generation_after_update_and_rollback(self):
        trace=self.root/'interpreter-trace.jsonl'
        def traced_build(*args,**kwargs):
            self.fake_build(*args,**kwargs)
            stage=Path(args[1]);python=stage/'runtime/bin/python3.11'
            python.write_text('#!'+sys.executable+'\n'+
                'import json,os,sys\nfrom pathlib import Path\n'+
                'with Path('+repr(str(trace))+').open("a") as log:\n'+
                ' log.write(json.dumps({"python":str(Path(__file__).resolve()),"args":sys.argv[1:]})+"\\n")\n'+
                'os.execv(sys.executable,[sys.executable,*sys.argv[1:]])\n')
            manifest=setup.document(stage/'manifest.json');manifest['files']=bundle.file_manifest(stage)
            (stage/'manifest.json').write_text(json.dumps(manifest))
        def current_hooks():
            root=Path(self.state()['hosts']['codex']['artifact'])/'plugins/model-routing-harness'
            return root,(root/'hooks/hooks.json').read_bytes()
        def exercise(root,raw):
            generation=(self.prefix/'current').resolve()
            for event in ('PreToolUse','PostToolUse'):
                command=json.loads(raw)['hooks'][event][0]['hooks'][0]['command']
                self.assertIn('"${PLUGIN_ROOT}/launcher.py"',command)
                self.assertEqual(shlex.split(command)[0],str(self.prefix/'current/runtime/bin/python3.11'))
                trace.write_text('')
                run=subprocess.run(command,shell=True,env={**os.environ,'PLUGIN_ROOT':str(root)},
                    input=json.dumps({'hook_event_name':event,'tool_name':'Bash','tool_input':{'command':'ls'},'cwd':str(self.root)}),
                    capture_output=True,text=True,timeout=10)
                self.assertEqual(run.returncode,0,run.stderr);self.assertEqual(json.loads(run.stdout),{})
                calls=[json.loads(line) for line in trace.read_text().splitlines()]
                self.assertEqual([c['python'] for c in calls],[str(generation/'runtime/bin/python3.11')]*2)
                self.assertEqual(calls[0]['args'],['-I','-B',str(root/'launcher.py')])
                self.assertIn(str(root/'runtime.pyz'),calls[1]['args'])
        self.run_setup(self.args('--codex-packets'),build=traced_build)
        first=self.state()['current'];first_root,first_hooks=current_hooks()
        self.revision='two';self.run_setup(self.args('--codex-packets'),build=traced_build)
        second=self.state()['current'];second_root,second_hooks=current_hooks()
        self.assertNotEqual(first,second)
        self.assertEqual(hashlib.sha256(first_hooks).hexdigest(),hashlib.sha256(second_hooks).hexdigest())
        self.assertEqual(first_hooks,second_hooks)
        exercise(second_root,second_hooks)
        self.run_setup(self.args('--rollback'))
        self.assertEqual(self.state()['current'],first)
        self.assertEqual(current_hooks(),(first_root,first_hooks))
        exercise(first_root,first_hooks)

    def test_bin_conflict_and_foreign_marketplace_reject_before_profile_or_build(self):
        self.bin.mkdir();(self.bin/'mrh').write_text('user file')
        with self.assertRaisesRegex(setup.SetupError,'bin_conflict'):self.run_setup(build=lambda *a,**k:self.fail('build'))
        self.assertFalse(self.profile().exists());self.assertEqual((self.bin/'mrh').read_text(),'user file')
        (self.bin/'mrh').unlink();self.native_change(foreign=True)
        with self.assertRaisesRegex(setup.SetupError,'name_conflict'):self.run_setup(build=lambda *a,**k:self.fail('build'))
        self.assertFalse(self.profile().exists())

    def test_bad_stage_hash_rejects_before_profile_or_code_switch(self):
        def corrupt(*a,**k):
            self.fake_build(*a,**k);(Path(a[1])/'mrh').write_text('corrupt')
        with self.assertRaisesRegex(setup.SetupError,'manifest_invalid'):self.run_setup(build=corrupt)
        self.assertFalse(self.profile().exists());self.assertFalse((self.prefix/'current').exists())

    def test_modified_complete_generation_is_not_replaced(self):
        self.run_setup();state=self.state();entry=self.prefix/'setup-state/generations'/state['current']/'mrh';entry.write_text('local change')
        with self.assertRaisesRegex(setup.SetupError,'manifest_invalid'):self.run_setup()
        self.assertEqual(entry.read_text(),'local change')

    def cached_build(self, *args, **kwargs):
        self.fake_build(*args, **kwargs)
        root = Path(args[1]); lib = root/'runtime/lib/python3.11'
        (lib/'__pycache__').mkdir(parents=True)
        (lib/'sample.py').write_text('value = 1\n')
        (lib/'__pycache__/sample.cpython-311.pyc').write_bytes(b'original bytecode')
        manifest = setup.document(root/'manifest.json')
        manifest['files'] = bundle.file_manifest(root)
        (root/'manifest.json').write_text(json.dumps(manifest))

    def test_runtime_cache_drift_allows_check_repeat_update_and_rollback_without_repair(self):
        self.run_setup(build=self.cached_build)
        first = self.state()['current']; root = self.prefix/'setup-state/generations'/first
        cache = root/'runtime/lib/python3.11/__pycache__'
        manifest = (root/'manifest.json').read_bytes()
        (cache/'sample.cpython-311.pyc').write_bytes(b'rewritten bytecode')
        added = cache/'sample.cpython-311.opt-1.pyc'; added.write_bytes(b'new bytecode')
        legacy = cache.parent/'sample.pyc'; legacy.write_bytes(b'legacy sibling cache')
        self.assertNotEqual(setup.document(root/'manifest.json')['files'], bundle.file_manifest(root))
        before = self.disk()
        self.run_setup(self.args('--check'))
        self.assertEqual(self.disk(), before)
        self.assertEqual(self.run_setup()['operation'], 'unchanged')
        self.assertEqual((root/'manifest.json').read_bytes(), manifest)
        (cache/'sample.cpython-311.pyc').unlink()
        self.revision = 'two'; self.run_setup(build=self.cached_build)
        self.run_setup(self.args('--rollback'))
        self.assertEqual(self.state()['current'], first)
        self.assertEqual(added.read_bytes(), b'new bytecode')
        self.assertFalse((cache/'sample.cpython-311.pyc').exists())
        self.assertEqual((root/'manifest.json').read_bytes(), manifest)

    def test_cache_exception_does_not_hide_source_or_noncache_changes(self):
        self.run_setup(build=self.cached_build)
        root = self.prefix/'setup-state/generations'/self.state()['current']
        for relative in ('runtime/lib/python3.11/sample.py',
                         'runtime/lib/python3.11/__pycache__/foreign.cpython-311.pyc',
                         'runtime/lib/python3.11/__pycache__/payload.py',
                         'app/foreign.pyc', 'runtime/bin/python3.11'):
            with self.subTest(path=relative):
                path = root/relative
                original = path.read_bytes() if path.exists() else None
                path.write_bytes(b'changed')
                before = self.disk()
                with self.assertRaisesRegex(setup.SetupError, 'manifest_invalid'):
                    self.run_setup()
                self.assertEqual(self.disk(), before)
                if original is None: path.unlink()
                else: path.write_bytes(original)
        cache = root/'runtime/lib/python3.11/__pycache__/sample.cpython-311.pyc'
        cache.unlink(); cache.symlink_to('../sample.py')
        with self.assertRaisesRegex(setup.SetupError, 'manifest_invalid'):
            setup.verify_bundle(root)

    def test_cache_drift_does_not_bypass_manifest_digest(self):
        self.run_setup(build=self.cached_build)
        state = self.state(); root = self.prefix/'setup-state/generations'/state['current']
        with (root/'manifest.json').open('a') as f: f.write(' ')
        with self.assertRaisesRegex(setup.SetupError, 'manifest_changed'):
            setup.verify_bundle(root, state['generations'][state['current']])

    def test_read_only_modes_create_nothing_and_do_not_download(self):
        before=self.disk()
        self.assertEqual(self.run_setup(self.args('--check'))['status'],'pending')
        self.assertEqual(self.run_setup(self.args('--dry-run'))['status'],'planned')
        self.assertEqual(self.disk(),before)
        self.run_setup();before=self.disk();self.run_setup(self.args('--check'));self.assertEqual(self.disk(),before)

    def test_registration_lost_ack_resumes_same_generation_without_duplicates(self):
        self.native_change(fail_after='marketplace-add')
        with self.assertRaisesRegex(setup.SetupError,'native_command_failed'):self.run_setup()
        self.assertFalse((self.prefix/'current').exists())
        pending=setup.document(self.prefix/'setup-state/journal.json');self.assertEqual(pending['native_step']['step'],'add_marketplace_intent')
        self.run_setup();self.assertEqual(self.state()['current'],pending['target'])
        self.assertEqual(json.loads(self.native.read_text())['mutations'],2)

    def test_foreign_bin_written_during_registration_is_preserved_and_recoverable(self):
        self.native_change(mutate_bin=str(self.bin/'mrh'))
        with self.assertRaisesRegex(setup.SetupError,'concurrent_change'):self.run_setup()
        self.assertEqual((self.bin/'mrh').read_text(),'foreign writer')
        self.assertFalse((self.prefix/'setup-state/state.json').exists())
        (self.bin/'mrh').unlink();self.run_setup();self.assertTrue(self.state())

    def test_registration_concurrent_other_root_does_not_get_removed(self):
        original=setup.CodexInstaller.install
        def race(adapter,*args):
            self.native_change(root=str(self.root/'foreign-source'))
            return original(adapter,*args)
        with patch.object(setup.CodexInstaller,'install',race):
            with self.assertRaisesRegex(setup.SetupError,'native_concurrent_change'):self.run_setup()
        self.assertEqual(json.loads(self.native.read_text())['root'],str(self.root/'foreign-source'))
        self.assertFalse((self.prefix/'current').exists())

    def test_dual_hosts_preserve_foreign_configuration_without_routine_backup(self):
        cp=self.root/'claude/settings.json';cp.parent.mkdir();before=b'{"custom": 1, "hooks":{"PreToolUse":[{"matcher":"Other","hooks":[{"command":"other-hook"}]}]}}\n';cp.write_bytes(before)
        args=self.args('--host','claude','--claude-settings',str(cp),'--claude-cli',str(self.claude));self.run_setup(args)
        after=json.loads(cp.read_text());self.assertEqual(after['custom'],1)
        self.assertEqual(after['hooks']['PreToolUse'][0]['hooks'][0]['command'],'other-hook')
        self.assertEqual(len(after['hooks']['PreToolUse']),2)
        self.assertEqual(list(cp.parent.glob('settings.json.mrh-bak-*')), [])
        exact=cp.read_bytes();self.run_setup(args);self.assertEqual(cp.read_bytes(),exact)
        self.assertEqual(len(list(cp.parent.glob('settings.json.mrh-bak-*'))),0)

    def test_claude_hook_command_stays_stable_across_generations_updates_and_rollback(self):
        cp=self.root/'claude/settings.json';cp.parent.mkdir()
        args=self.args('--host','claude','--claude-settings',str(cp),'--claude-cli',str(self.claude))
        def command():
            hooks=json.loads(cp.read_text())['hooks']
            found=[h['command'] for event in ('PreToolUse','PostToolUse') for e in hooks[event] for h in e['hooks']]
            self.assertEqual(len(found),2);self.assertEqual(found[0],found[1]);return found[0]
        self.run_setup(args);first=self.state()['current'];first_command=command();first_bytes=cp.read_bytes()
        self.revision='two';self.run_setup(args);second=self.state()['current']
        self.assertNotEqual(first,second)
        self.assertEqual(command(),first_command);self.assertEqual(cp.read_bytes(),first_bytes)   # settings.json untouched by an update
        parts=shlex.split(first_command)
        self.assertEqual(parts[0],str(self.prefix/'current/runtime/bin/python3.11'))
        self.assertEqual(parts[-2],str(self.prefix/'current/hosts/claude/plugins/model-routing-harness/launcher.py'))
        self.assertEqual(parts[-1],'claude');self.assertNotIn('generations',first_command)
        launcher=Path(parts[-2]).resolve()
        self.assertIn(second,str(launcher))                                                         # `current` selects the active generation
        self.run_setup(self.args('--host','claude','--rollback','--claude-settings',str(cp),'--claude-cli',str(self.claude)))
        self.assertEqual(self.state()['current'],first);self.assertEqual(command(),first_command)
        self.assertIn(first,str(Path(parts[-2]).resolve()))
        self.assertEqual(len(list(cp.parent.glob('settings.json.mrh-bak-*'))),0)                    # nothing rewritten after the first install

    def test_unselected_claude_configuration_is_byte_exact(self):
        cp=self.root/'claude/settings.json';cp.parent.mkdir();cp.write_bytes(b'not even parsed by a codex-only installation')
        self.run_setup(self.args('--claude-settings',str(cp)))
        self.assertEqual(cp.read_bytes(),b'not even parsed by a codex-only installation')

    def test_explicit_packet_only_artifact_contains_one_packaged_skill(self):
        self.run_setup(self.args('--codex-packets'))
        artifact=Path(self.state()['hosts']['codex']['artifact'])/'plugins/model-routing-harness'
        self.assertTrue(json.loads((artifact/'binding.json').read_text())['codex_packets'])
        skills=list(artifact.glob('skills/*/SKILL.md'));self.assertEqual(len(skills),1)
        self.assertIn('one protocol owner per task',skills[0].read_text())
        self.assertNotIn(str(self.root/'install/setup-state/.stage'),(artifact/'hooks/hooks.json').read_text())
        wheel=mrh_build.build_wheel(self.root/'wheels')
        with zipfile.ZipFile(self.root/'wheels'/wheel) as z:self.assertIn('mrh/resources/skills/mrh-codex-packet/SKILL.md',z.namelist())

    def test_codex_setup_exposes_hooks_in_native_compatibility_manifest(self):
        self.run_setup(self.args('--codex-packets'))
        artifact=Path(self.state()['hosts']['codex']['artifact'])
        root=artifact/'plugins/model-routing-harness'
        manifest=setup.document(root/'.codex-plugin/plugin.json')
        self.assertEqual(manifest['name'],'model-routing-harness')
        self.assertEqual(manifest['hooks'],'./hooks/hooks.json')
        self.assertFalse((root/'plugin.json').exists(),'standard manifest would shadow native compatibility hooks')
        self.assertEqual(set(setup.document(root/manifest['hooks'])['hooks']),{'PreToolUse','PostToolUse'})
        setup.plugin.show(artifact)  # the published manifest is part of owned integrity verification

    def test_dev_install_binds_the_hook_and_mrh_to_the_checkout_and_normal_install_goes_back(self):
        out = self.run_setup(self.args('--dev'))
        generation = self.prefix / 'setup-state/generations' / self.state()['current']
        binding = json.loads((generation / 'hosts/codex/plugins/model-routing-harness/binding.json').read_text())
        self.assertEqual(binding['dev_source'], str(setup.ROOT))
        self.assertEqual(out['dev_source'], str(setup.ROOT))
        self.assertIn(str(setup.ROOT / 'src'), (generation / 'app/dev_main.py').read_text())
        self.assertTrue((generation / 'app/dev_main.py').exists())
        self.revision = 'normal'
        again = self.run_setup()
        self.assertNotIn('dev_source', again)
        normal = self.prefix / 'setup-state/generations' / self.state()['current']
        hooks = 'hosts/codex/plugins/model-routing-harness/hooks/hooks.json'
        self.assertEqual((generation / hooks).read_bytes().replace(str(generation).encode(), b''), (normal / hooks).read_bytes().replace(str(normal).encode(), b''))
        self.assertEqual((generation / hooks).read_bytes(), (normal / hooks).read_bytes())    # Codex trust covers this file
        self.assertNotIn('dev_source', json.loads((normal / 'hosts/codex/plugins/model-routing-harness/binding.json').read_text()))

    def test_dev_cannot_be_combined_with_rollback_packets_or_uninstall(self):
        for extra in (['--rollback'], ['--codex-packets']):
            with self.assertRaises(setup.SetupError):
                self.run_setup(self.args('--dev', *extra))
        with self.assertRaises(setup.SetupError):
            setup.uninstall(setup.parser().parse_args(['--uninstall', '--dev', '--prefix', str(self.prefix), '--config-root', str(self.config), '--bin-dir', str(self.bin)]))

    def test_unsupported_platform_and_unknown_host_do_not_write(self):
        with patch('mrh_setup.platform.system',return_value='Linux'):
            with self.assertRaisesRegex(setup.SetupError,'unsupported_platform'):self.run_setup()
        with patch('sys.stderr',io.StringIO()):
            with self.assertRaises(SystemExit):setup.parser().parse_args(['--host','invented'])
        self.assertFalse(self.prefix.exists())

    def test_policy_requires_complete_current_declared_profiles(self):
        self.run_setup()
        value=settings_v2.read(self.profile())
        policy={'tiers':{t:{'codex':[{'model':'fixture-model','effort':'high'}]} for t in ('Light','Small','Mid')}}
        settings_v2.update(self.profile(),policy=policy)
        out=self.run_setup(self.args('--check'));self.assertTrue(out['policy_ready'])
        self.assertEqual(out['policy_validation']['codex']['account_availability'],'not_probed')
        policy['tiers']['Small']['codex'][0]['effort']='unsupported'
        settings_v2.update(self.profile(),policy=policy)
        self.assertFalse(self.run_setup(self.args('--check'))['policy_ready'])

    def test_explicit_opt_in_updates_an_ordinary_artifact_without_touching_data(self):
        self.run_setup();before=self.profile().read_bytes()
        self.run_setup(self.args('--codex-packets'))
        self.assertTrue(self.state()['hosts']['codex']['packets'])
        self.assertEqual(self.profile().read_bytes(),before)
        with self.assertRaisesRegex(setup.SetupError,'packet_mode_conflict'):self.run_setup()
        self.run_setup(self.args('--rollback'))
        self.assertFalse(self.state()['hosts']['codex']['packets'])

    def test_retired_installer_does_not_replace_the_shared_app(self):
        p=self.prefix/'app';p.mkdir(parents=True);(p/'preserve').write_bytes(b'existing')
        r=subprocess.run([sys.executable,str(setup.ROOT/'scripts/packaging/install_local.py'),'--bundle','unused','--prefix',str(self.prefix)],capture_output=True,text=True)
        self.assertEqual(r.returncode,2);self.assertIn('No files were changed',r.stderr)
        self.assertEqual((p/'preserve').read_bytes(),b'existing')

    def test_state_commit_lost_ack_recovers_without_losing_previous_generation(self):
        self.run_setup();first=self.state()['current'];self.revision='two'
        original=setup.write;once=[]
        def fail_receipt(path,data,*args):
            if Path(path).name=='journal.json' and json.loads(data).get('phase')=='complete' and not once:
                once.append(True);raise OSError('fixture lost completion acknowledgement')
            return original(path,data,*args)
        with patch('mrh_setup.write',side_effect=fail_receipt):
            with self.assertRaises(OSError):self.run_setup()
        self.assertEqual(self.state()['previous']['current'],first)
        count=json.loads(self.native.read_text())['mutations']
        self.assertEqual(self.run_setup()['operation'],'recovered')
        self.assertEqual(self.state()['previous']['current'],first)
        self.assertEqual(json.loads(self.native.read_text())['mutations'],count)

    def test_legacy_pointer_and_v1_profile_bytes_are_preserved(self):
        from mrh.infrastructure import settings as legacy
        old=self.root/'legacy-profile/settings.json';old.parent.parent.mkdir(exist_ok=True)
        legacy.init(old);before=old.read_bytes()
        self.config.mkdir();(self.config/'active-settings').write_text(str(old)+'\n')
        self.run_setup()
        self.assertEqual(old.read_bytes(),before)
        self.assertEqual((self.config/'active-settings').read_text(),str(old)+'\n')
        self.assertFalse(self.profile().exists())

    def test_busy_lock_does_not_create_a_profile(self):
        import fcntl
        control=self.prefix/'setup-state';control.mkdir(parents=True)
        (control/'owner.json').write_bytes(setup.encoded({'owner':setup.OWNER,'version':1}))
        with (control/'lock').open('w') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with self.assertRaisesRegex(setup.SetupError,'setup_busy'):self.run_setup()
        self.assertFalse(self.profile().exists())

    def test_pointer_change_between_path_resolution_and_lock_is_preserved(self):
        from contextlib import contextmanager
        original=setup.locked
        @contextmanager
        def race(control):
            self.config.mkdir();(self.config/'active-settings').write_text(str(self.root/'external/settings.json')+'\n')
            with original(control):yield
        with patch('mrh_setup.locked',race):
            with self.assertRaisesRegex(setup.SetupError,'active_settings_concurrent_change'):self.run_setup()
        self.assertEqual((self.config/'active-settings').read_text(),str(self.root/'external/settings.json')+'\n')
        self.assertFalse(self.profile().exists())

    def test_completed_native_step_is_revalidated_after_interruption(self):
        with patch('mrh_setup.link',side_effect=OSError('fixture interrupt before current switch')):
            with self.assertRaises(OSError):self.run_setup()
        self.native_change(root=str(self.root/'external-source'))
        with self.assertRaisesRegex(setup.SetupError,'native_registration_concurrent_change'):self.run_setup()
        self.assertFalse((self.prefix/'current').exists());self.assertFalse((self.bin/'mrh').exists())

    def test_selected_claude_missing_broken_or_unsupported_cli_refuses_before_any_install_write(self):
        cp=self.root/'selected-claude/settings.json'
        def arguments(path=None):
            args=self.args('--claude-settings',str(cp),*(['--claude-cli',str(path)] if path else []));args.host=['claude'];return args
        with patch('mrh.adapters.catalogs.catalog.discover',return_value=[]):
            with self.assertRaisesRegex(setup.SetupError,'claude_cli_missing'):
                self.run_setup(arguments(),build=lambda *a,**k:self.fail('build before prerequisite'))
        for label,body in [('missing',None),('broken','raise SystemExit(7)'),('unsupported','print("0.0.0 (Claude Code)")')]:
            with self.subTest(label=label):
                cli=self.root/('claude-'+label)
                if body is not None:cli.write_text('#!'+sys.executable+'\n'+body+'\n');cli.chmod(0o700)
                with self.assertRaisesRegex(setup.SetupError,'claude_cli_unavailable'):
                    self.run_setup(arguments(cli),build=lambda *a,**k:self.fail('build before prerequisite'))
                self.assertFalse(self.prefix.exists());self.assertFalse(self.config.exists());self.assertFalse(cp.exists())

    def test_selected_claude_valid_version_fixture_installs_without_live_cli(self):
        cp=self.root/'selected-claude/settings.json'
        args=self.args('--claude-settings',str(cp),'--claude-cli',str(self.claude));args.host=['claude']
        out=self.run_setup(args)
        self.assertTrue(out['hosts']['claude']['cli_available'])
        self.assertEqual(out['hosts']['claude']['cli']['source'],'explicit_cli_override')
        self.assertTrue(out['hosts']['claude']['configured']);self.assertTrue(cp.exists())
        self.assertEqual(json.loads(self.native.read_text())['mutations'],0)

    def test_claude_prerequisite_check_and_dryrun_are_readonly(self):
        cp=self.root/'selected-claude/settings.json';before=self.disk()
        args=self.args('--check','--claude-settings',str(cp),'--claude-cli',str(self.root/'absent'));args.host=['claude']
        out=self.run_setup(args)
        self.assertEqual(out['status'],'pending');self.assertFalse(out['hosts']['claude']['cli_available']);self.assertIn('claude_cli',out['pending'])
        args=self.args('--dry-run','--claude-settings',str(cp),'--claude-cli',str(self.claude));args.host=['claude']
        self.assertEqual(self.run_setup(args)['status'],'planned');self.assertEqual(self.disk(),before)
        args=self.args('--check','--claude-settings',str(cp),'--claude-cli',str(self.claude));args.host=['claude']
        self.assertTrue(self.run_setup(args)['hosts']['claude']['cli_available']);self.assertEqual(self.disk(),before)

    def test_codex_only_does_not_discover_or_execute_claude_override(self):
        marker=self.root/'forbidden-claude-launch'
        bomb=self.root/'claude-bomb';bomb.write_text('#!'+sys.executable+'\nfrom pathlib import Path\nPath('+repr(str(marker))+').write_text("unexpected")\nraise SystemExit(9)\n');bomb.chmod(0o700)
        with patch('mrh.adapters.catalogs.catalog.describe_tool',side_effect=AssertionError('Claude metadata must not run')):
            self.run_setup(self.args('--claude-cli',str(bomb)))
            self.run_setup(self.args('--check','--claude-cli',str(bomb)))
        self.assertFalse(marker.exists())

    def test_codex_only_update_does_not_probe_an_existing_managed_claude_host(self):
        cp=self.root/'selected-claude/settings.json'
        both=self.args('--host','claude','--claude-settings',str(cp),'--claude-cli',str(self.claude));self.run_setup(both)
        before=cp.read_bytes();profile=self.profile().read_bytes()
        with patch('mrh.adapters.catalogs.catalog.describe_tool',side_effect=AssertionError('unselected Claude probe')):
            out=self.run_setup(self.args('--claude-cli',str(self.root/'absent')))
            checked=self.run_setup(self.args('--check','--claude-cli',str(self.root/'absent')))
        self.assertEqual(set(out['hosts']),{'codex'})
        self.assertEqual(set(checked['hosts']),{'codex'})
        self.assertEqual(cp.read_bytes(),before);self.assertEqual(self.profile().read_bytes(),profile)
        self.assertIn('claude',self.state()['hosts'])

    def test_missing_claude_cli_check_does_not_fall_back_to_model_metadata(self):
        cp=self.root/'selected-claude/settings.json'
        args=self.args('--claude-settings',str(cp),'--claude-cli',str(self.claude));args.host=['claude'];self.run_setup(args)
        settings_v2.update(self.profile(),policy={'tiers':{t:{'claude':[{'model':'fixture-model','effort':'high'}]} for t in ('Light','Small','Mid')}})
        before=self.disk();args=self.args('--check','--claude-settings',str(cp),'--claude-cli',str(self.root/'absent'));args.host=['claude']
        with patch('mrh.adapters.catalogs.catalog.public_models',side_effect=AssertionError('model metadata must not run without prerequisite')):
            out=self.run_setup(args)
        self.assertFalse(out['hosts']['claude']['cli_available']);self.assertFalse(out['policy_ready']);self.assertEqual(self.disk(),before)

    def test_bootstrap_readonly_and_bad_pinned_asset_do_not_initialize_installation(self):
        env={**os.environ,'PATH':'/bin'}
        cmd=[str(setup.ROOT/'setup'),'--host','codex','--prefix',str(self.prefix),'--config-root',str(self.config),'--bin-dir',str(self.bin)]
        r=subprocess.run(cmd+['--dry-run','--json'],capture_output=True,text=True,env=env)
        self.assertEqual(r.returncode,0,r.stderr);self.assertFalse(self.prefix.exists())
        cache=self.root/'cache';cache.mkdir();(cache/bundle.read_lock()['runtime']['name']).write_bytes(b'wrong hash')
        r=subprocess.run(cmd+['--cache-root',str(cache),'--json'],capture_output=True,text=True,env=env)
        self.assertNotEqual(r.returncode,0);self.assertIn('hash/size mismatch',r.stderr);self.assertFalse(self.prefix.exists())


class ModelsTests(unittest.TestCase):
    def test_models_public_json_uses_catalog_metadata_and_explicit_stream(self):
        from mrh.adapters.catalogs.catalog import Catalog,Model
        from mrh.presentation.cli import main
        data=Catalog('fixture','codex','tool-picker','fixture-1','public-rpc',1,(Model('fixture-model','Fixture',('high',)),))
        out=io.StringIO()
        with patch('mrh.adapters.catalogs.catalog.discover',return_value=[{'tool':'codex','supported':True}]),patch('mrh.adapters.catalogs.catalog.describe_tool',return_value={}),patch('mrh.adapters.catalogs.catalog.ToolCatalog.refresh',return_value=data):
            self.assertEqual(main(['models','--host','codex','--json'],stdout=out),0)
        value=json.loads(out.getvalue());self.assertEqual(value['assurance'],'tool-advertised');self.assertEqual(value['models'][0]['efforts'],['high'])


if __name__=='__main__':unittest.main()
