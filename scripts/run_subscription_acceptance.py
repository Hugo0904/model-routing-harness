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

from verify_host import Rpc

PROMPTS = {
 'ordinary':'Delegate exactly one generic subtask, without specifying its model or reasoning effort: sort the literal numbers [3, 1, 2] ascending and return only the sorted array. Wait for that result and report it. If a hook returns the unexecuted subtask to you, do it here without delegating again. Do not use files, commands, web access, or other tasks.',
 'tradeoff':'Delegate exactly one generic subtask, without specifying its model or reasoning effort: design a tiny hypothetical two-service reservation protocol when network partitions can occur and payment confirmation may be delayed. Explain the conflict between avoiding duplicate reservations and maintaining availability, choose a tradeoff, and state one recovery rule. Limit the answer to 150 words. Wait for the result; if a hook returns this unexecuted subtask to you, complete it in this same parent without a replacement child. Use no real data, files, commands, or web access.'
}


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
    if method in ('turn/completed','hook/started','hook/completed','thread/settings/updated'):
        return {'method':method,'params':params}
    return None


def run(pointer,scenario,output):
    info=json.loads(pointer.read_text());root=Path(info['root']);work=Path(info['workspace']);database=Path(info['settings']).parent/'events.sqlite3'
    assert root.stat().st_uid==os.getuid() and (root/'.mrh-e19-owned').read_text().startswith('MRH-001 E19')
    assert info['auth_status']=='chatgpt' and info['trust']=='reviewed_via_official_cli'
    assert info['test_turns']<3 and 1+current_attempts(database)<3
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
            if item.get('method')=='hook/started' and len([x for x in rpc.events[offset:] if x.get('method')=='hook/started' and str(x.get('params',{}).get('run',{}).get('eventName')).lower()=='pretooluse'])>1:
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
        info=json.loads(pointer.read_text());info['classifier_calls']=1+current_attempts(database)
        pointer.write_text(json.dumps(info,indent=2)+'\n')
        result.update(elapsed_seconds=round(time.monotonic()-started,3),classifier_calls_total=info['classifier_calls'],test_turns_total=info['test_turns'])
        output.write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps({'scenario':scenario,'proposals':result.get('proposals'),'child_metadata':result['child_metadata'],
                          'remaining':result['remaining'],'failure':result.get('failure'),'elapsed_seconds':result['elapsed_seconds']}),flush=True)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--pointer',type=Path,required=True)
    parser.add_argument('--scenario',choices=tuple(PROMPTS),required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();run(args.pointer,args.scenario,args.output)
