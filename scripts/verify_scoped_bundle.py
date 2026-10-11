#!/usr/bin/env python3
"""Owned E17 package entry, disabled/update/readback and immutable runtime."""
import argparse,json,subprocess,tempfile,hashlib
from pathlib import Path


def inspect(bundle,binary,native):
 commands=[]
 with tempfile.TemporaryDirectory(prefix='mrh-e17-bundle-',dir='/private/tmp') as tmp:
  root=Path(tmp).resolve();home=root/'home';home.mkdir();work=root/'workspace';work.mkdir();state=root/'state/settings.json';plugin=root/'plugin'
  (home/'config.toml').write_text('model="gpt-6.1-sol"\nmodel_reasoning_effort="low"\n')
  env={'HOME':str(root),'CODEX_HOME':str(home),'PATH':'/usr/bin:/bin','TMPDIR':str(root),'NO_COLOR':'1','LANG':'en_US.UTF-8'}
  def run(args):
   p=subprocess.run(list(map(str,args)),cwd=work,env=env,capture_output=True,text=True,timeout=15);commands.append({'argv':list(map(str,args)),'exit':p.returncode});assert p.returncode==0,p.stderr
   return json.loads(p.stdout)
  entry=bundle/'mrh'
  show=run([entry,'plugin','prepare','--root',plugin,'--settings',state,'--scope-workspace',work,'--codex-binary',binary])
  assert show['configuration_scope']['assurance']=='inspected-configuration' and show['live_routing_ready'] is False
  value=json.loads(state.read_text());assert value['enabled'] is False and value['task_export_permitted'] is False
  policy=root/'policy.json';policy.write_text(json.dumps({'top_mode':'Fixed','fixed':{'model':'gpt-5.6-luna','effort':'low'},'tiers':{},'rates':{}}))
  run([entry,'settings','configure','--path',state,'--policy',policy]);before=state.read_bytes()
  run([entry,'plugin','prepare','--root',plugin,'--settings',state]);assert state.read_bytes()==before
  installed=plugin/'plugins/model-routing-harness';runtime_hash=hashlib.sha256((installed/'runtime.pyz').read_bytes()).hexdigest()
  assert runtime_hash==native['installed_runtime_sha256']
  event={'hook_event_name':'PreToolUse','tool_name':'collaborationspawn_agent','session_id':'s','turn_id':'t','tool_use_id':'c','cwd':str(work),'model':'gpt-6.1-sol','tool_input':{'message':'owned disabled fixture','task_name':'owned_disabled','fork_turns':'none'}}
  p=subprocess.run([show['artifact']['python'],'-I','-B',str(installed/'launcher.py')],input=json.dumps(event),cwd=work,env=env,capture_output=True,text=True,timeout=10)
  assert p.returncode==0 and json.loads(p.stdout)=={} and not (state.parent/'events.sqlite3').exists() and state.read_bytes()==before
  (home/'config.toml').write_text((home/'config.toml').read_text()+'\n[agents]\ndefault_subagent_reasoning_effort="high"\n')
  invalid=run([entry,'plugin','show','--root',plugin]);assert invalid['readiness_reason']=='scope_changed' and state.read_bytes()==before
  result={'bundle':str(bundle),'commands':commands,'prepared':show,'update_preserves_policy_permissions_and_disabled':True,'v2_disabled_launcher_neutral_zero_database':True,'public_scope_invalidation_readback':invalid['configuration_scope'],'runtime_matches_actual_native_chain':runtime_hash,'own_root':str(root),'no_real_key_or_provider':True}
 result['cleanup']=not root.exists();assert result['cleanup'];return result


if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--bundle',type=Path,required=True);p.add_argument('--binary',type=Path,required=True);p.add_argument('--native',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 result=inspect(a.bundle.resolve(),a.binary.resolve(),json.loads(a.native.read_text()));a.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({'entry':True,'disabled_update_scope':True,'native_runtime_match':True,'cleanup':result['cleanup']}))
