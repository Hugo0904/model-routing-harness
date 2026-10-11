#!/usr/bin/env python3
"""E17: installed official Hook, real config inspector, scripted Jev/provider."""
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import threading
import time

from verify_host import OwnedScratch,Rpc,Fixture,trust_fixture,curate_events,CATALOG_HASHES

BOOTSTRAP=r'''import io,json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from mrh.cli import main
from mrh.typesafe import HttpResponse
from mrh.typesafe_protocol import PINNED_MODEL
scenario=Path(sys.argv[4]).read_text().strip()
event=json.load(sys.stdin)
class HTTP:
 synthetic=True
 calls=0
 def request(self,body,headers,deadline,enter):
  enter();self.calls+=1
  assert body['model']==PINNED_MODEL
  if scenario=='failure':raise OSError('owned scripted failure')
  tier='light' if scenario=='light' else 'top'
  return HttpResponse(200,json.dumps({'model':PINNED_MODEL,'usage':{'input_tokens':1,'output_tokens':1},
   'answers':{'tier':{'type':'choice','choice':tier,'confidence':.9,
    'probabilities':{x:.7 if x==tier else .1 for x in ('light','small','mid','top')}}}}).encode())
http=HTTP();keys=[]
import os,subprocess
ancestry=[];pid=os.getppid()
for _ in range(8):
 if pid<=1:break
 r=subprocess.run(['/bin/ps','-p',str(pid),'-o','ppid=','-o','comm=','-o','args='],capture_output=True,text=True)
 parts=r.stdout.strip().split(None,2);ancestry.append({'pid':pid,'exit':r.returncode,'row':r.stdout.strip(),'error':r.stderr.strip()})
 if r.returncode or len(parts)!=3:break
 pid=int(parts[0])
def key():keys.append(1);return 'owned-scripted-key'
out,err=io.StringIO(),io.StringIO()
main(['hook','--settings',sys.argv[2],'--scope-binding',sys.argv[3]],stdin=io.StringIO(json.dumps(event)),stdout=out,stderr=err,
 runtime_dependencies={'transport':http,'credential_resolver':key})
with Path(sys.argv[5]).open('a') as f:f.write(json.dumps({'event':event,'output':json.loads(out.getvalue()),'scripted_jev_calls':http.calls,
 'key_resolutions':len(keys),'host_dependency_injected':False,'diagnostic':err.getvalue().strip(),'owned_process_ancestry':ancestry})+'\n')
print(out.getvalue(),end='')
'''


class NativeFixture(Fixture):
    def response(self,body,headers):
        tools=body.get('tools',[])
        namespaces={x['name']:[t['name'] for t in x['tools']] for x in tools if x.get('type')=='namespace'}
        is_parent='MRH_PARENT_' in json.dumps(body.get('input',[]))
        self.requests.append({'model':body.get('model'),'reasoning':body.get('reasoning'),'is_parent':is_parent,
            'native_namespace_tools':namespaces,'request_keys':list(body),'tool_types':[(x.get('type'),x.get('name')) for x in tools],'function_outputs':[x for x in body.get('input',[]) if x.get('type')=='function_call_output']})
        if is_parent and self.step<1:
            self.step+=1
            # This is a scripted public V2 call, not autonomous tool selection.
            # Stock code-mode/lite requests do not expose the legacy namespace
            # table used by E4. Let the actual dispatcher accept/refuse its
            # documented collaboration surface; do not fabricate a tool table.
            namespace=next((name for name,functions in namespaces.items() if 'spawn_agent' in functions),'collaboration')
            arguments={'message':'MRH_CHILD_'+self.scenario,'task_name':'owned_'+self.scenario.replace('-','_'),'fork_turns':'none'}
            if self.scenario=='explicit-model':arguments['model']='gpt-6.1-sol'
            if self.scenario=='explicit-effort':arguments['reasoning_effort']='high'
            if self.scenario=='special-role':arguments['agent_type']='explorer'
            return [{'id':'fc-owned-'+str(len(self.requests)),'type':'function_call','namespace':namespace,'name':'spawn_agent',
                     'call_id':'call-owned-'+str(len(self.requests)),'arguments':json.dumps(arguments),'status':'completed'}]
        return [{'id':'message-owned','type':'message','role':'assistant','content':[{'type':'output_text','text':'MRH scripted parent/child complete.'}]}]


def inspect(binary,catalog_path,failure_path=None):
    started=time.monotonic();fixture=NativeFixture('light');commands=[];cases=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*_):pass
        def do_POST(self):
            assert self.path.endswith('/responses') and self.headers.get('Authorization') is None
            size=int(self.headers['Content-Length']);assert size<=2_000_000
            output=fixture.response(json.loads(self.rfile.read(size)),self.headers)
            rid='response-owned-'+str(len(fixture.requests))
            events=[{'type':'response.created','response':{'id':rid,'status':'in_progress','output':[]}}]
            for i,item in enumerate(output):events.extend([{'type':'response.output_item.added','output_index':i,'item':item},
                                                         {'type':'response.output_item.done','output_index':i,'item':item}])
            events.append({'type':'response.completed','response':{'id':rid,'status':'completed','output':output,
                'usage':{'input_tokens':1,'output_tokens':1,'total_tokens':2,'input_tokens_details':{'cached_tokens':0}}}})
            payload=''.join('data: '+json.dumps(x)+'\n\n' for x in events).encode()
            self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Content-Length',str(len(payload)))
            self.end_headers();self.wfile.write(payload)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True
    serving=threading.Thread(target=server.serve_forever,daemon=True);serving.start();scope=OwnedScratch()
    result={'evidence_kind':'official_installed_hook_real_config_inspection_scripted_jev_and_responses',
            'real_jev_or_provider':False,'formal_global_changes':False,'host_binary_modified':False,'commands':commands,'cases':cases}
    try:
      with scope as temp:
        root=temp.resolve();home=root/'home';home.mkdir();work=root/'workspace';work.mkdir()
        result['owned_root']=str(root)
        env={'PATH':str(Path(binary).parent)+':/usr/bin:/bin:/usr/sbin:/sbin','HOME':str(root),'CODEX_HOME':str(home),
             'LANG':'en_US.UTF-8','TERM':'xterm-256color','NO_COLOR':'1'}
        original_binary=hashlib.sha256(Path(binary).read_bytes()).hexdigest()
        data=catalog_path.read_bytes();assert hashlib.sha256(data).hexdigest()==CATALOG_HASHES['0.159.3']
        catalog=root/'models.json';catalog.write_bytes(data) # Unmodified official stock model metadata; no aliases/mode override.
        config=home/'config.toml';config.write_text('model="gpt-6.1-sol"\nmodel_reasoning_effort="low"\nmodel_provider="mrh_fixture"\nmodel_catalog_json='+json.dumps(str(catalog))+'\nsandbox_mode="workspace-write"\napproval_policy="never"\n[model_providers.mrh_fixture]\nname="Owned scripted Responses"\nbase_url="http://127.0.0.1:'+str(server.server_address[1])+'/v1"\nrequires_openai_auth=false\nwire_api="responses"\nrequest_max_retries=0\nstream_max_retries=0\n[analytics]\nenabled=false\n')
        config.write_text(config.read_text()+'\n[agents]\nenabled=true\n[features]\nmulti_agent=true\ncode_mode=true\n')
        def command(args):
            run=subprocess.run(list(map(str,args)),cwd=work,env=env,capture_output=True,text=True,timeout=30)
            commands.append({'argv':list(map(str,args)),'exit':run.returncode,'stdout':run.stdout,'stderr':run.stderr})
            if run.returncode:raise RuntimeError('owned_native_command_failed:'+run.stderr[-1000:])
            return json.loads(run.stdout) if run.stdout.strip().startswith(('{','[')) else run.stdout
        source=Path(__file__).resolve().parents[1]
        state=root/'state/settings.json';bundle=root/'plugin'
        code="import sys,json;sys.path.insert(0,sys.argv[1]);from mrh.plugin import prepare;print(json.dumps(prepare(sys.argv[2],sys.argv[3],scope_workspace=sys.argv[4],codex_binary=sys.argv[5])))"
        prepared=command([sys.executable,'-I','-c',code,source/'src',bundle,state,work,binary]);result['prepared']=prepared
        plugin_id='model-routing-harness@model-routing-harness-local'
        command([binary,'--no-daemon','plugin','marketplace','add',bundle,'--json'])
        installed=command([binary,'--no-daemon','plugin','add',plugin_id,'--json']);installed_path=Path(installed['installedPath'])
        runtime=installed_path/'runtime.pyz';binding=installed_path/'binding.json'
        assert hashlib.sha256(runtime.read_bytes()).hexdigest()==prepared['artifact']['files']['plugins/model-routing-harness/runtime.pyz']
        result['installed_runtime_sha256']=hashlib.sha256(runtime.read_bytes()).hexdigest()
        completion=(b'Ask Codex to do anything',b'GPT-6.1-Sol')
        result['initial_trust']=trust_fixture(binary,env,work,scope,completion=completion)
        bootstrap=root/'scripted-jev.py';bootstrap.write_text(BOOTSTRAP);control=root/'scenario';control.write_text('light');log=root/'events.jsonl'
        hooks=installed_path/'hooks/hooks.json';definition=json.loads(hooks.read_text())
        command_line=shlex.join([prepared['artifact']['python'],'-I',str(bootstrap),str(runtime),str(state),str(binding),str(control),str(log)])
        for rows in definition['hooks'].values():
            rows[0]['hooks'][0]['command']=command_line
        hooks.write_text(json.dumps(definition));result['scripted_transport_trust']=trust_fixture(binary,env,work,scope,completion=completion)
        rate=lambda n:{'currency':'test-unit','unit':'token','service':'owned-scripted-provider','source_ref':'scripted-config-cost','components':{'input':n,'output':n}}
        policy={'top_mode':'Main','timeout_seconds':1,'fixed':{'model':'gpt-5.6-luna','effort':'low'},
                'tiers':{'Light':{'model':'gpt-5.6-luna','effort':'low'}},'rates':{'gpt-6.1-sol':rate(2),'gpt-5.6-luna':rate(1)}}
        configure="import sys,json;sys.path.insert(0,sys.argv[1]);from mrh.settings import update;print(json.dumps(update(sys.argv[2],enabled=True,task_export_permitted=True,allowed_workspaces=[sys.argv[3]],policy=json.loads(sys.argv[4]))))"
        command([sys.executable,'-I','-c',configure,source/'src',state,work,json.dumps(policy)])
        rpc=Rpc(binary,env,work,scope)
        try:
            rpc.request('initialize',{'clientInfo':{'name':'mrh-e17','version':'1'},'capabilities':{'experimentalApi':True}});rpc.write({'method':'initialized'})
            result['trusted_hooks']=rpc.request('hooks/list',{'cwd':str(work)})
            def one(name):
                fixture.scenario=name;fixture.step=0;control.write_text(name)
                a,b=len(rpc.events),len(fixture.requests);offset=len(log.read_text().splitlines()) if log.exists() else 0
                reply=rpc.request('thread/start',{'cwd':str(work)})
                if 'error' in reply:raise ValueError(reply['error'])
                parent=reply['result']['thread']['id']
                reply=rpc.request('turn/start',{'threadId':parent,'input':[{'type':'text','text':'MRH_PARENT_'+name}]})
                if 'error' in reply:raise ValueError(reply['error'])
                deadline=time.monotonic()+20;done=None
                while time.monotonic()<deadline:
                    item=rpc.inbox.get(timeout=max(.01,deadline-time.monotonic()));rpc.events.append(item)
                    if item.get('method')=='turn/completed' and item.get('params',{}).get('threadId')==parent:done=item;break
                if done is None:raise TimeoutError('native_parent_turn_timeout')
                ids={i for e in rpc.events[a:] if e.get('method')=='item/completed' for i in e.get('params',{}).get('item',{}).get('receiverThreadIds',[])}
                rpc.await_children(ids)
                if name!='main':
                    deadline=time.monotonic()+5
                    while time.monotonic()<deadline and not any(not r['is_parent'] for r in fixture.requests[b:]):time.sleep(.01)
                rows=[json.loads(x) for x in log.read_text().splitlines()[offset:]] if log.exists() else []
                requests=fixture.requests[b:];pre=[x for x in rows if x['event']['hook_event_name']=='PreToolUse'];assert len(pre)==1,(name,rows)
                children=[r for r in requests if not r['is_parent']]
                assert all(r['model']=='gpt-6.1-sol' and r['reasoning']['effort']=='low' for r in requests if r['is_parent'])
                case={'scenario':name,'parent_id':parent,'parent_completed':done,'child_ids':sorted(ids),'requests':requests,
                      'installed_runtime_events':rows,'native_events':curate_events(rpc.events[a:])}
                cases.append(case)
                if name=='light':
                    output=pre[0]['output']['hookSpecificOutput'];assert output['permissionDecision']=='allow'
                    original=pre[0]['event']['tool_input'];updated=output['updatedInput']
                    assert updated=={**original,'model':'gpt-5.6-luna','reasoning_effort':'low'}
                    assert len(children)==1 and children[0]['model']=='gpt-5.6-luna' and children[0]['reasoning']['effort']=='low'
                    assert pre[0]['scripted_jev_calls']==1
                elif name=='main':
                    assert not ids and not children
                    assert pre[0]['output']['hookSpecificOutput']['permissionDecision']=='deny'
                    assert 'Continue its original unexecuted subtask' in json.dumps(requests)
                elif name in ('explicit-model','explicit-effort','special-role'):
                    assert pre[0]['output']=={} and pre[0]['scripted_jev_calls']==0 and pre[0]['key_resolutions']==0
                else:
                    assert 'systemMessage' in pre[0]['output'] and 'hookSpecificOutput' not in pre[0]['output']
                    if name=='invalidated':assert pre[0]['scripted_jev_calls']==0 and pre[0]['key_resolutions']==0
                return case
            one('light');one('main');one('explicit-model');one('explicit-effort');one('special-role');one('failure')
            config.write_text(config.read_text().replace('[agents]\nenabled=true','[agents]\nenabled=true\ndefault_subagent_reasoning_effort="high"'))
            one('invalidated')
        finally:rpc.close()
        command([binary,'--no-daemon','plugin','remove',plugin_id,'--json'])
        result['native_remove']=command([binary,'--no-daemon','plugin','list','--json'])
        assert state.exists() and hashlib.sha256(Path(binary).read_bytes()).hexdigest()==original_binary
        result.update(binary=str(binary),binary_sha256=original_binary,catalog_sha256=hashlib.sha256(data).hexdigest(),
                      owned_root=str(root),owned_pids=[p.pid for p in scope.processes],host_dependency_injected=False,
                      stock_model_metadata_unchanged=True,session_turn_overrides=False)
    except BaseException as exc:
        result.update(failure_type=type(exc).__name__,failure=str(exc)[:3000],owned_pids=[p.pid for p in scope.processes],
                      captured_requests=fixture.requests)
        if failure_path is not None:failure_path.write_text(json.dumps(result,indent=2)+'\n')
        raise
    finally:server.shutdown();server.server_close();serving.join(timeout=2)
    result.update(cleanup=not root.exists(),seconds=round(time.monotonic()-started,3));assert result['cleanup'];return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--binary',type=Path,required=True);p.add_argument('--catalog',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    result=inspect(a.binary.resolve(),a.catalog.resolve(),a.output.with_suffix('.failure.json'));a.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'native_scoped_hook':True,'cases':len(result['cases']),'real_jev_or_provider':False,'cleanup':result['cleanup'],'seconds':result['seconds']}))
