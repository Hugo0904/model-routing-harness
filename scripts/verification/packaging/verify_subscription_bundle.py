#!/usr/bin/env python3
"""Shipped entry: provider/CAS/history, allowlist and missing-auth guard, no model."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
import argparse
import hashlib
import json
import os
import subprocess
import tempfile
import time
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'src'))
from mrh_bundle import file_manifest, sha256


def inspect(bundle,binary):
    started=time.monotonic();commands=[]
    manifest=json.loads((bundle/'manifest.json').read_text())
    assert file_manifest(bundle)==manifest['files']
    source=Path(__file__).resolve().parents[3]
    with zipfile.ZipFile(bundle/'app/mrh.pyz') as archive:
        for name,digest in manifest['application_files'].items():
            assert hashlib.sha256(archive.read(name)).hexdigest()==digest
        modules=[name for name in archive.namelist() if name.startswith('mrh/') and name.endswith('.py')]
        source_modules={'mrh/'+path.relative_to(source/'src/mrh').as_posix()
                        for path in (source/'src/mrh').rglob('*.py')}
        assert set(modules)==source_modules, 'source_archive_module_paths_mismatch'
        for name in modules:assert archive.read(name)==(source/'src'/name).read_bytes()
    before=file_manifest(bundle)
    with tempfile.TemporaryDirectory(prefix='mrh-subscription-bundle-',dir='/private/tmp') as temp:
        root=Path(temp).resolve();home=root/'home';home.mkdir();work=root/'work';work.mkdir()
        state=root/'state/settings.json';plugin=root/'plugin';entry=bundle/'mrh'
        env={'HOME':str(root),'CODEX_HOME':str(home),'PATH':os.defpath,'TMPDIR':str(root),
             'LANG':'en_US.UTF-8','NO_COLOR':'1'}
        (home/'config.toml').write_text('model="gpt-6.1-sol"\nmodel_reasoning_effort="low"\n')
        def run(argv,*,data=None,extra=None,decode=True):
            proc=subprocess.run(list(map(str,argv)),input=data,cwd=work,env={**env,**(extra or {})},
                                text=True,capture_output=True,timeout=15)
            commands.append({'argv':list(map(str,argv)),'exit':proc.returncode})
            assert proc.returncode==0,proc.stderr
            return json.loads(proc.stdout) if decode else proc.stdout
        run([entry,'--help'],decode=False)
        prepared=run([entry,'plugin','prepare','--root',plugin,'--settings',state,
                      '--scope-workspace',work,'--codex-binary',binary])
        value=run([entry,'settings','show','--path',state])['settings']
        assert value['provider']=='codex_subscription' and value['classifier_model']=='gpt-6-luna'
        assert value['enabled'] is False and value['task_export_permitted'] is False and value['policy']['timeout_seconds']==20
        assert prepared['configuration_scope']['assurance']=='inspected-configuration'
        installed=plugin/'plugins/model-routing-harness';runtime=installed/'runtime.pyz';binding=installed/'binding.json'
        launcher=installed/'launcher.py';python=prepared['artifact']['python']
        event={'hook_event_name':'PreToolUse','tool_name':'collaborationspawn_agent','session_id':'s','turn_id':'t','tool_use_id':'c',
               'cwd':str(work),'model':'gpt-6.1-sol','tool_input':{'message':'Owned literal task','task_name':'owned_disabled','fork_turns':'none'}}
        assert run([python,'-I','-B',launcher],data=json.dumps(event))=={}
        assert not (state.parent/'events.sqlite3').exists()
        import_code="import sys,json;sys.path.insert(0,sys.argv[1]);"
        code=import_code+"from mrh.infrastructure.store import Store;from mrh.routing.types import Proposal;store=Store(sys.argv[2]);p=Proposal('codex','simulation','old','t','c',{'message':'owned legacy history'},True);store.claim(p);store.attempt(p.identity,'0','synthetic','requested',requested_model='jev-1.13.0');store.attempt(p.identity,'0','synthetic','started');store.attempt(p.identity,'0','synthetic','returned',response_model='jev-1.13.0',input_tokens=10,output_tokens=1);print(json.dumps(store.stats(True)))"
        old_stats=run([python,'-I','-B','-c',code,bundle/'app/mrh.pyz',state.parent/'events.sqlite3'])
        policy=root/'policy.json';policy.write_text(json.dumps({'top_mode':'Fixed','fixed':{'model':'gpt-5.6-luna','effort':'low'},'timeout_seconds':1,'tiers':{},'rates':{}}))
        legacy=run([entry,'settings','configure','--path',state,'--provider','typesafe','--policy',policy])['settings']
        now=run([entry,'settings','configure','--path',state,'--provider','codex_subscription',
                 '--expected-revision',legacy['revision']])['settings']
        for field in ('policy','enabled','task_export_permitted','allowed_workspaces'):assert legacy[field]==now[field]
        stats_code=import_code+"from mrh.infrastructure.store import Store;print(json.dumps(Store(sys.argv[2]).stats(True)))"
        assert run([python,'-I','-B','-c',stats_code,bundle/'app/mrh.pyz',state.parent/'events.sqlite3'])==old_stats
        # Exercise the shipped CLI/schema and its actual hot-read consumer.
        # Legacy roots deliberately match: invalid selected files must not fall back.
        legacy_roots=run([entry,'settings','configure','--path',state,'--allow-workspace',work])['settings']
        allowlist=root/'workspace-allowlist.json'
        allowlist.write_text(json.dumps({'schema_version':1,'roots':[str(work)]}))
        selected=run([entry,'settings','configure','--path',state,
                      '--workspace-allowlist-file',allowlist,
                      '--expected-revision',legacy_roots['revision']])['settings']
        assert selected['workspace_allowlist_file']==str(allowlist)
        preserved={key:value for key,value in legacy_roots.items() if key!='revision'}
        def check_preserved(value):
            assert {key:item for key,item in value.items()
                    if key not in ('revision','workspace_allowlist_file')}==preserved
        check_preserved(selected)
        assert run([entry,'settings','show','--path',state])['settings']==selected
        selected_bytes=state.read_bytes()
        allowance_code=import_code+"from mrh.infrastructure.settings import read,workspace_allowed;from mrh.infrastructure.settings_schema import SettingsError;\ntry: print(json.dumps({'allowed':workspace_allowed(read(sys.argv[2]),sys.argv[3])}))\nexcept SettingsError as e: print(json.dumps({'error':e.reason}))"
        def allowance():
            return run([python,'-I','-B','-c',allowance_code,bundle/'app/mrh.pyz',state,work])
        matching=allowance();assert matching=={'allowed':True}
        allowlist.write_text(json.dumps({'schema_version':1,'roots':[]}))
        empty=allowance();assert empty=={'allowed':False}
        assert state.read_bytes()==selected_bytes
        allowlist.write_text('{invalid')
        malformed=allowance();assert malformed=={'error':'workspace_allowlist_invalid'}
        assert state.read_bytes()==selected_bytes
        cleared=run([entry,'settings','configure','--path',state,
                     '--clear-workspace-allowlist-file',
                     '--expected-revision',selected['revision']])['settings']
        assert 'workspace_allowlist_file' not in cleared
        check_preserved(cleared)
        assert run([entry,'settings','show','--path',state])['settings']==cleared
        legacy_again=allowance();assert legacy_again=={'allowed':True}
        assert run([python,'-I','-B','-c',stats_code,bundle/'app/mrh.pyz',state.parent/'events.sqlite3'])==old_stats
        allowlist_delta={'selected_path_readback':True,'matching_root':matching,
                        'same_file_empty_roots_hot_reload':empty,'malformed_without_legacy_fallback':malformed,
                        'file_edits_preserve_settings_bytes':True,'clear_field_absent':True,
                        'clear_restores_legacy_roots':legacy_again,
                        'policy_permissions_provider_and_unrelated_fields_preserved':True,
                        'legacy_history_preserved':True}
        settings_bytes=state.read_bytes()
        run([entry,'plugin','prepare','--root',plugin,'--settings',state]);assert state.read_bytes()==settings_bytes
        detail=run([entry,'settings','view','--path',state,'--plain','--width','56'],decode=False)
        assert 'Codex subscription' in detail and 'gpt-6-luna' in detail
        (home/'AGENTS.md').write_text('Owned global-instruction canary')
        assert not (home/'auth.json').exists()
        code=import_code+"from mrh.adapters.providers.codex_subscription import CodexSubscriptionClassifier;from mrh.routing.core import ClassifierFailure;from mrh.routing.attempts import GuardedAttempts;events=[];r=GuardedAttempts(2,lambda *a,**k:events.append(a));\ntry: CodexSubscriptionClassifier(enabled=True,task_export_permitted=True,scope_binding=sys.argv[2]).classify('Sort literal numbers [3,1,2].',None,r)\nexcept ClassifierFailure as e: print(json.dumps({'reason':e.reason,'attempts':events}))\nfinally:r.cancel()"
        guard=run([python,'-I','-B','-c',code,bundle/'app/mrh.pyz',binding])
        assert guard=={'reason':'codex_subscription_auth_source_invalid','attempts':[]}
        run([entry,'settings','configure','--path',state,'--permit-task-export','--allow-workspace',work])
        run([entry,'settings','enable','--path',state])
        db_before=(state.parent/'events.sqlite3').read_bytes()
        assert run([python,'-I','-B',launcher],data=json.dumps(event),extra={'MRH_SUBSCRIPTION_CLASSIFIER_ACTIVE':'1'})=={}
        assert (state.parent/'events.sqlite3').read_bytes()==db_before
        run([entry,'settings','disable','--path',state]);assert run([entry,'settings','show','--path',state])['settings']['enabled'] is False
        from mrh.infrastructure.plugin import _runtime_archive
        expected=hashlib.sha256(_runtime_archive()).hexdigest();assert sha256(runtime)==expected
        result={'kind':'actual_shipped_entry_and_private_runtime_with_owned_scope_no_provider',
            'source_commit':manifest['source_commit'],'application_source_records':len(manifest['application_files']),
            'python_modules':len(modules),'verified_manifest_records':len(manifest['files']),
            'archive_source_identity_verified':True,'source_archive_module_paths_equal':True,
            'commands':commands,'prepared':prepared,
            'subscription_guard':guard,'missing_auth_source_zero_attempt_refusal':True,
            'workspace_allowlist_delta':allowlist_delta,
            'provider_switch_preserves_policy_permissions_and_legacy_history':True,
            'disabled_hook_zero_database':True,'recursion_launcher_zero_database_changes':True,
            'prepared_runtime_matches_current_source':expected,'real_classifier_calls':0,'real_test_turns':0,
            'formal_registration_or_trust':False,'login_or_status_calls':0,'owned_root':str(root)}
    result['cleanup']=not root.exists();assert result['cleanup']
    assert file_manifest(bundle)==before
    result['manifest_unchanged_after_entry']=True;result['elapsed_seconds']=round(time.monotonic()-started,3)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--bundle',type=Path,required=True)
    parser.add_argument('--binary',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();result=inspect(args.bundle.resolve(),args.binary.resolve())
    args.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ('verified_manifest_records','python_modules','subscription_guard','cleanup','elapsed_seconds')}))
