#!/usr/bin/env python3
"""Same owned E19 native subscription session. No scripted inference/facts."""
import argparse
import json
import os
from pathlib import Path
import queue
import sqlite3
import sys
import time

from verify_host import Rpc, require_goal

PROMPTS = {
 'ordinary':'Delegate exactly one generic subtask, without specifying its model or reasoning effort: sort the literal numbers [3, 1, 2] ascending and return only the sorted array. Wait for that result and report it. If a hook returns the unexecuted subtask to you, do it here without delegating again. Do not use files, commands, web access, or other tasks.',
 'tradeoff':'Delegate exactly one generic subtask, without specifying its model or reasoning effort: design a tiny hypothetical two-service reservation protocol when network partitions can occur and payment confirmation may be delayed. Explain the conflict between avoiding duplicate reservations and maintaining availability, choose a tradeoff, and state one recovery rule. Limit the answer to 150 words. Wait for the result; if a hook returns this unexecuted subtask to you, complete it in this same parent without a replacement child. Use no real data, files, commands, or web access.'
}

D47_TASKS = (
 'Design a bounded hypothetical protocol for two regions sharing limited inventory, an asynchronous payment service and a shipping service. Messages may duplicate, reorder and arrive after a network partition. Strict no-oversell, accepting reservations in both isolated regions, and immediate irreversible shipping conflict. State an invariant, which requirement must be relaxed, ownership and commit rules, and recovery. Limit the answer to 220 words.',
 'Analyze one new failure in the hypothetical design just completed: payment confirms after lease expiry while the other region reallocates inventory and the shipping acknowledgement is lost. Choose compensation and reconciliation rules and explain what evidence can justify each irreversible action. Limit the answer to 180 words.'
)


def d47_prompt(task):
    return ('Delegate exactly one generic subtask without specifying its model or reasoning effort. '
            'Give the child this complete work description: '+task+
            ' Wait for its result and report it. If a Hook returns the unexecuted subtask, '
            'complete it in this same parent without another delegation. '
            'Use no commands, files, web access, real orders or external actions.')


def proposal_rows(path):
    if not path.exists():return []
    db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
    try:
        query="""SELECT id,session_id,turn_id,tool_call_id,state,
           json_extract(decision,'$.action') action,json_extract(decision,'$.reason') reason,
           json_extract(decision,'$.tier') tier,json_extract(decision,'$.confidence') confidence,
           json_extract(decision,'$.patch.model') requested_model,
           json_extract(decision,'$.patch.reasoning_effort') requested_effort
           FROM proposals WHERE synthetic=0 ORDER BY occurred_at"""
        return [dict(row) for row in db.execute(query)]
    finally:db.close()


def current_attempts(path):
    if not path.exists():return 0
    with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as db:
        return db.execute("SELECT count(*) FROM attempts WHERE kind='codex_subscription' AND phase!='requested'").fetchone()[0]


def thread_metadata(reply):
    if 'error' in reply:return {'error':reply['error']}
    thread=reply['result']['thread']
    return {k:thread.get(k) for k in ('id','parentThreadId','model','reasoningEffort','modelProvider','status')}


def curate(event):
    method=event.get('method');params=event.get('params',{})
    if method=='thread/started':return {'method':method,'thread':thread_metadata({'result':params})}
    if method in ('item/started','item/completed'):
        item=params.get('item',{})
        if item.get('type') in ('agentMessage','collabAgentToolCall','subAgentActivity','codeExecution'):
            return {'method':method,'threadId':params.get('threadId'),'turnId':params.get('turnId'),'item':item}
    if method in ('turn/completed','hook/started','hook/completed','thread/settings/updated','thread/tokenUsage/updated','thread/goal/updated','error'):
        return {'method':method,'params':params}
    return None


def d47_native_turn(rpc, info, pointer, database, parent, prompt, unit='d47'):
    """One new real delegation. No observer, scope facts or inferred answer."""
    assert current_attempts(database)-info[unit+'_classifier_baseline']<info.get(unit+'_classifier_limit',3)
    baseline=len(proposal_rows(database));before_calls=current_attempts(database);offset=len(rpc.events)
    result={'task':prompt,'events':[],'child_metadata':[],'remaining':[]}
    reply=rpc.request('turn/start',{'threadId':parent,'input':[{'type':'text','text':prompt}]})
    assert 'error' not in reply,'native_turn_start_failed'
    turn=reply['result']['turn']['id'];result['turn_id']=turn
    info[unit+'_native_turns']+=1;pointer.write_text(json.dumps(info,indent=2)+'\n')
    print(json.dumps({'d47_native_turn_started':turn,'parent':parent}),flush=True)
    done=False;children=set();early=set();reads={};deadline=time.monotonic()+120
    def read_active_child(child):
        if child in early or reads.get(child,0)>=3:return
        reads[child]=reads.get(child,0)+1
        metadata=thread_metadata(rpc.request('thread/read',{'threadId':child,'includeTurns':False}))
        result.setdefault('child_loaded_readbacks',[]).append(metadata)
        if metadata.get('status',{}).get('type')=='active':
            early.add(child);result.setdefault('child_while_native_active',[]).append(metadata)
    try:
        while time.monotonic()<deadline:
            finished=next((e for e in rpc.events[offset:] if e.get('method')=='turn/completed' and e.get('params',{}).get('threadId')==parent and e.get('params',{}).get('turn',{}).get('id')==turn),None)
            if finished is not None:result['parent_completed']=finished;done=True;break
            try:item=rpc.inbox.get(timeout=.25)
            except queue.Empty:
                if rpc.proc.poll() is not None:raise RuntimeError('native_server_exited')
                for child in sorted(children-early):read_active_child(child)
                continue
            rpc.events.append(item);activity=item.get('params',{}).get('item',{})
            if activity.get('type')=='subAgentActivity' and activity.get('agentThreadId'):
                child=activity['agentThreadId'];children.add(child)
                read_active_child(child)
            if activity.get('type')=='collabAgentToolCall':
                for child in activity.get('receiverThreadIds',[]):
                    children.add(child);read_active_child(child)
            if 'id' in item and 'method' in item:
                result['remaining'].append('unexpected_native_approval:'+item['method']);break
            pre=[x for x in rpc.events[offset:] if x.get('method')=='hook/started' and str(x.get('params',{}).get('run',{}).get('eventName')).lower()=='pretooluse']
            if len(pre)>1:result['remaining'].append('unexpected_extra_delegation');break
        if not done:
            result['remaining'].append('parent_not_completed_within_bounded_observation')
            result['interrupt']=rpc.request('turn/interrupt',{'threadId':parent,'turnId':turn})
        result['events']=[value for event in rpc.events[offset:] if (value:=curate(event)) is not None]
        for event in rpc.events[offset:]:
            params=event.get('params',{});thread=params.get('thread',{});item=params.get('item',{})
            if event.get('method')=='thread/started' and thread.get('parentThreadId')==parent:children.add(thread['id'])
            if item.get('type')=='collabAgentToolCall':children.update(item.get('receiverThreadIds',[]))
            if item.get('type')=='subAgentActivity' and item.get('agentThreadId'):children.add(item['agentThreadId'])
        for child in sorted(children):
            result['child_metadata'].append(thread_metadata(rpc.request('thread/read',{'threadId':child,'includeTurns':False})))
            detail=rpc.request('thread/read',{'threadId':child,'includeTurns':True})
            if 'error' in detail:result['remaining'].append('child_result_readback_failed')
            else:result.setdefault('child_turns',{})[child]=detail['result']['thread'].get('turns')
        result['parent_after']=thread_metadata(rpc.request('thread/read',{'threadId':parent,'includeTurns':False}))
        detail=rpc.request('thread/read',{'threadId':parent,'includeTurns':True})
        if 'error' not in detail:result['parent_turns']=detail['result']['thread'].get('turns')
        result['proposals']=proposal_rows(database)[baseline:]
        result['classifier_invocations']=current_attempts(database)-before_calls
        result['native_methods']=sorted({e.get('method') for e in rpc.events[offset:] if e.get('method')})
        return result
    except Exception as exc:
        result['failure']={'type':type(exc).__name__,'reason':str(exc)[:200]}
        result['remaining'].append('native_turn_incomplete')
        result['events']=[value for event in rpc.events[offset:] if (value:=curate(event)) is not None]
        result['proposals']=proposal_rows(database)[baseline:]
        result['classifier_invocations']=current_attempts(database)-before_calls
        return result
    finally:
        if not done:
            try:rpc.request('turn/interrupt',{'threadId':parent,'turnId':turn})
            except Exception:pass
        info[unit+'_classifier_calls']=current_attempts(database)-info[unit+'_classifier_baseline']
        pointer.write_text(json.dumps(info,indent=2)+'\n')


def run_d47(pointer, scenario, output):
    info=json.loads(pointer.read_text());root=Path(info['root']);work=Path(info['workspace']);database=Path(info['settings']).parent/'events.sqlite3'
    unit='d48' if scenario=='main-luna' else 'd47'
    assert root.stat().st_uid==os.getuid() and (root/'.mrh-e19-owned').read_text().startswith('MRH-001 E19')
    assert info['auth_status']=='chatgpt' and info['trust']=='reviewed_via_official_cli'
    assert info[unit+'_classifier_calls']<info.get(unit+'_classifier_limit',3) and not info['observer_registered']
    if unit=='d47' and info.get('d47_classifier_limit',3)>3:
        assert scenario=='fixed' and info.get('d47_corrective_readback_reason')=='legacy_child_identity_not_read_while_active'
    env={'HOME':str(root),'CODEX_HOME':info['home'],'PATH':os.defpath,'TMPDIR':str(root/'tmp'),'LANG':'en_US.UTF-8','NO_COLOR':'1','TERM':'xterm-256color'}
    class Scope:processes=[]
    rpc=Rpc(info['binary'],env,work,Scope)
    result={'kind':'real_subscription_remaining_policy_acceptance','scenario':scenario,'scripted_provider':False,'host_facts_injected':False,'private_rollout_read':False,'turns':[],'remaining':[]}
    parent=None;goal_identity=None;started=time.monotonic()
    try:
        reply=rpc.request('initialize',{'clientInfo':{'name':'mrh-d47-real-acceptance','version':'1'},'capabilities':{'experimentalApi':True}});assert 'error' not in reply
        rpc.write({'method':'initialized'});result['hooks']=rpc.request('hooks/list',{'cwd':str(work)})
        hooks=[h for row in result['hooks']['result']['data'] for h in row.get('hooks',[])]
        assert len(hooks)==2 and all(h.get('pluginId')=='model-routing-harness@model-routing-harness-local' and h.get('trustStatus')=='trusted' for h in hooks)
        reply=rpc.request('thread/start',{'cwd':str(work)});assert 'error' not in reply
        parent=reply['result']['thread']['id'];result['parent_id']=parent;result['parent_before']=thread_metadata(reply)
        expected='gpt-6.1-sol' if scenario=='goal-main' else 'gpt-5.6-luna'
        assert result['parent_before']['model']==expected and result['parent_before']['reasoningEffort']=='low','configured_parent_mismatch'
        info.setdefault(unit+'_thread_refs',[]).append(parent);pointer.write_text(json.dumps(info,indent=2)+'\n')
        if scenario=='goal-main':
            before=rpc.request('thread/goal/get',{'threadId':parent});assert 'error' not in before and before['result']['goal'] is None
            created=rpc.request('thread/goal/set',{'threadId':parent,'objective':'Complete the bounded hypothetical inventory/payment/shipping design and a subsequent recovery analysis through two explicitly requested fresh delegation turns.','status':'active','origin':'user'})
            goal=require_goal(created,parent,'active');goal_identity={k:goal[k] for k in ('threadId','createdAt','objective')}
            result['goal']={'identity':goal_identity,'create_response':created,'readbacks':[{'stage':'before','response':before}], 'continuation_initiator':'harness_turn_start','autonomous_scheduling_proven':False}
            info['d47_goal_thread_id']=parent;info['d47_goal_state']='active';pointer.write_text(json.dumps(info,indent=2)+'\n')
        tasks=(info['d48_public_fixed_prompt'],) if scenario=='main-luna' else D47_TASKS if scenario=='goal-main' else D47_TASKS[:1]
        for index,task in enumerate(tasks):
            if goal_identity:
                state=rpc.request('thread/goal/get',{'threadId':parent});require_goal(state,parent,'active',goal_identity)
                result['goal']['readbacks'].append({'stage':'before_turn_'+str(index+1),'response':state})
            prompt=('Delegate the following message verbatim exactly once to a generic child, without specifying its model or reasoning effort. If the Hook returns the unexecuted task, complete it in this same parent without any replacement delegation. Otherwise wait for the result and report it. Use no commands, files, web or external actions. Verbatim message:\n'+task) if scenario=='main-luna' else d47_prompt(task)
            turn=d47_native_turn(rpc,info,pointer,database,parent,prompt,unit=unit);result['turns'].append(turn)
            complete=turn.get('parent_completed',{}).get('params',{}).get('turn',{})
            answers=[item.get('text','') for item in complete.get('items',[]) if item.get('type')=='agentMessage']
            turn['parent_substantive_completion']=complete.get('status')=='completed' and any(len(t.split())>=15 for t in answers)
            if turn['remaining'] or not turn['parent_substantive_completion'] or turn['classifier_invocations']!=1:
                result['remaining'].append('affected_turn_or_fresh_classification_incomplete');break
        if goal_identity:
            after=rpc.request('thread/goal/get',{'threadId':parent})
            status=after.get('result',{}).get('goal',{}).get('status')
            assert status in ('active','complete'),'unexpected_goal_terminal_state'
            require_goal(after,parent,status,goal_identity);result['goal']['readbacks'].append({'stage':'after_turns','response':after})
            fulfilled=len(result['turns'])==2 and all(t['parent_substantive_completion'] and t['classifier_invocations']==1 and not t['remaining'] for t in result['turns'])
            if fulfilled:
                completed=rpc.request('thread/goal/set',{'threadId':parent,'status':'complete','origin':'user'}) if status=='active' else after
                require_goal(completed,parent,'complete',goal_identity)
                read=rpc.request('thread/goal/get',{'threadId':parent});require_goal(read,parent,'complete',goal_identity)
                result['goal']['readbacks'].append({'stage':'complete','response':read})
                cleared=rpc.request('thread/goal/clear',{'threadId':parent});assert cleared.get('result',{}).get('cleared') is True
                empty=rpc.request('thread/goal/get',{'threadId':parent});assert 'error' not in empty and empty['result']['goal'] is None
                result['goal'].update(completed_and_cleared=True,complete_response=completed,clear_response=cleared)
                result['goal']['readbacks'].append({'stage':'cleared','response':empty});info['d47_goal_state']='cleared'
            else:result['goal']['completed_and_cleared']=False;info['d47_goal_state']='active'
        result['parent_after']=thread_metadata(rpc.request('thread/read',{'threadId':parent,'includeTurns':False}))
    except Exception as exc:
        result['failure']={'type':type(exc).__name__,'reason':str(exc)[:200]};result['remaining'].append('native_unit_incomplete')
        if goal_identity:
            try:result.setdefault('goal',{})['state_on_failure']=rpc.request('thread/goal/get',{'threadId':parent})
            except Exception:result.setdefault('goal',{})['state_on_failure']='unknown'
    finally:
        result['native_process_exit']=rpc.close();info[unit+'_classifier_calls']=current_attempts(database)-info[unit+'_classifier_baseline'];pointer.write_text(json.dumps(info,indent=2)+'\n')
        result.update(elapsed_seconds=round(time.monotonic()-started,3),all_batches_classifier_calls=info['prior_batch_classifier_calls']+current_attempts(database));result['classifier_calls_'+unit+'_total']=info[unit+'_classifier_calls']
        output.write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps({'scenario':scenario,'classifications':[t.get('proposals') for t in result['turns']],'remaining':result['remaining'],'failure':result.get('failure'),'elapsed_seconds':result['elapsed_seconds']}),flush=True)
    return result


def run(pointer,scenario,output):
    info=json.loads(pointer.read_text());root=Path(info['root']);work=Path(info['workspace']);database=Path(info['settings']).parent/'events.sqlite3'
    assert root.stat().st_uid==os.getuid() and (root/'.mrh-e19-owned').read_text().startswith('MRH-001 E19')
    assert info['auth_status']=='chatgpt' and info['trust']=='reviewed_via_official_cli'
    base=info.get('classifier_base_calls',1);limit=info.get('classifier_call_limit',3)
    assert info['test_turns']<info.get('native_turn_limit',3) and base+current_attempts(database)<limit
    env={'HOME':str(root),'CODEX_HOME':info['home'],'PATH':os.defpath,'TMPDIR':str(root/'tmp'),
         'LANG':'en_US.UTF-8','NO_COLOR':'1','TERM':'xterm-256color'}
    class Scope:processes=[]
    rpc=Rpc(info['binary'],env,work,Scope)
    result={'kind':'real_official_subscription_native_hook_acceptance','scenario':scenario,
            'scripted_provider':False,'host_facts_injected':False,'formal_home_changed':False,
            'task':PROMPTS[scenario],'events':[],'child_metadata':[],'remaining':[]}
    started=time.monotonic();parent=None;turn=None;done=False
    try:
        init=rpc.request('initialize',{'clientInfo':{'name':'mrh-e19-live','version':'1'},'capabilities':{'experimentalApi':True}})
        assert 'error' not in init,init
        rpc.write({'method':'initialized'})
        hooks=rpc.request('hooks/list',{'cwd':str(work)});result['hooks']=hooks
        assert 'error' not in hooks,hooks
        reply=rpc.request('thread/start',{'cwd':str(work)});assert 'error' not in reply,reply
        parent=reply['result']['thread']['id'];result['parent_before']=thread_metadata(reply)
        assert result['parent_before']['model']=='gpt-6.1-sol' and result['parent_before']['reasoningEffort']=='low'
        if info.get('observer_control'):
            control=Path(info['observer_control'])
            control.write_text(json.dumps({'workspace':str(work),'session_id':parent})+'\n');os.chmod(control,0o600)
        baseline=len(proposal_rows(database));offset=len(rpc.events)
        info['test_turns']+=1;pointer.write_text(json.dumps(info,indent=2)+'\n')
        reply=rpc.request('turn/start',{'threadId':parent,'input':[{'type':'text','text':PROMPTS[scenario]}]})
        assert 'error' not in reply,reply
        turn=reply['result']['turn']['id'];result.update(parent_id=parent,turn_id=turn)
        print(json.dumps({'native_turn_started':True,'scenario':scenario,'parent_id':parent}),flush=True)
        deadline=time.monotonic()+120;children=set();early_read=set()
        while time.monotonic()<deadline:
            finished=next((e for e in rpc.events[offset:] if e.get('method')=='turn/completed' and e.get('params',{}).get('threadId')==parent),None)
            if finished is not None:result['parent_completed']=finished;done=True;break
            try:item=rpc.inbox.get(timeout=.25)
            except queue.Empty:
                if rpc.proc.poll() is not None:raise RuntimeError('native_server_exited')
                continue
            rpc.events.append(item)
            activity=item.get('params',{}).get('item',{})
            if activity.get('type')=='subAgentActivity' and activity.get('agentThreadId'):
                child=activity['agentThreadId'];children.add(child)
                if child not in early_read:
                    early_read.add(child)
                    result.setdefault('child_while_native_active',[]).append(thread_metadata(rpc.request('thread/read',{'threadId':child,'includeTurns':False})))
            if 'id' in item and 'method' in item:
                # This literal workflow grants no shell/files/web approvals.
                result['remaining'].append('unexpected_native_approval:'+item['method'])
                break
            if item.get('method')=='turn/completed' and item.get('params',{}).get('threadId')==parent:
                result['parent_completed']=item;done=True;break
            if item.get('method')=='hook/started' and len([x for x in rpc.events[offset:] if x.get('method')=='hook/started' and str(x.get('params',{}).get('run',{}).get('eventName')).lower()=='pretooluse' and '/model-routing-harness/' in str(x.get('params',{}).get('run',{}).get('sourcePath',''))])>1:
                result['remaining'].append('unexpected_extra_delegation');break
        if not done:
            result['remaining'].append('parent_not_completed_within_bounded_observation')
            if turn:result['interrupt']=rpc.request('turn/interrupt',{'threadId':parent,'turnId':turn})
        result['events']=[value for event in rpc.events[offset:] if (value:=curate(event)) is not None]
        for event in rpc.events[offset:]:
            params=event.get('params',{});thread=params.get('thread',{})
            if event.get('method')=='thread/started' and thread.get('parentThreadId')==parent:children.add(thread['id'])
            item=params.get('item',{})
            if item.get('type')=='collabAgentToolCall':children.update(item.get('receiverThreadIds',[]))
            if item.get('type')=='subAgentActivity' and item.get('agentThreadId'):children.add(item['agentThreadId'])
        for child in sorted(children):
            result['child_metadata'].append(thread_metadata(rpc.request('thread/read',{'threadId':child,'includeTurns':False})))
            detail=rpc.request('thread/read',{'threadId':child,'includeTurns':True})
            if 'error' in detail:result['remaining'].append('child_result_readback_failed')
            else:result.setdefault('child_turns',{})[child]=detail['result']['thread'].get('turns')
        result['parent_after']=thread_metadata(rpc.request('thread/read',{'threadId':parent,'includeTurns':False}))
        detail=rpc.request('thread/read',{'threadId':parent,'includeTurns':True})
        if 'error' not in detail:result['parent_turns']=detail['result']['thread'].get('turns')
        result['proposals']=proposal_rows(database)[baseline:]
        if info.get('observer_capture'):
            capture=Path(info['observer_capture'])
            rows=[json.loads(line) for line in capture.read_text().splitlines()] if capture.exists() else []
            result['observed_native_inputs']=[r for r in rows if r['session_id']==parent and r['turn_id']==turn]
            result['input_identity_matches']=[{'proposal_id':p['id'],'matched':sum(
                r['session_id']==p['session_id'] and r['turn_id']==p['turn_id'] and r['tool_use_id']==p['tool_call_id']
                for r in result['observed_native_inputs'])==1} for p in result['proposals']]
            if not result['observed_native_inputs'] or not all(m['matched'] for m in result['input_identity_matches']):
                result['remaining'].append('bounded_original_input_not_verified')
        if not children and any(p.get('action')=='request_child' for p in result['proposals']):
            result['remaining'].append('v2_child_identity_missing_from_receiver_and_thread_started_events')
        result['event_methods']=sorted({e.get('method') for e in rpc.events[offset:] if e.get('method')})
    except Exception as exc:
        result['failure']={'type':type(exc).__name__,'reason':str(exc)[:1000]}
        result['remaining'].append('native_chain_not_verified')
        if parent and turn and not done:
            try:result['interrupt']=rpc.request('turn/interrupt',{'threadId':parent,'turnId':turn})
            except Exception:result['interrupt_unknown']=True
        result['events']=[value for event in rpc.events if (value:=curate(event)) is not None]
        result['proposals']=proposal_rows(database)
    finally:
        result['native_process_exit']=rpc.close()
        info=json.loads(pointer.read_text());info['classifier_calls']=base+current_attempts(database)
        pointer.write_text(json.dumps(info,indent=2)+'\n')
        result.update(elapsed_seconds=round(time.monotonic()-started,3),classifier_calls_total=info['classifier_calls'],test_turns_total=info['test_turns'],
                      prior_batch_classifier_calls=info.get('prior_batch_classifier_calls',0),
                      all_batches_classifier_calls=info.get('prior_batch_classifier_calls',0)+info['classifier_calls'])
        output.write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps({'scenario':scenario,'proposals':result.get('proposals'),'child_metadata':result['child_metadata'],
                          'remaining':result['remaining'],'failure':result.get('failure'),'elapsed_seconds':result['elapsed_seconds']}),flush=True)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--pointer',type=Path,required=True)
    parser.add_argument('--scenario',choices=tuple(PROMPTS)+('goal-main','fixed','main-luna'),required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    (run_d47 if args.scenario in ('goal-main','fixed','main-luna') else run)(args.pointer,args.scenario,args.output)
