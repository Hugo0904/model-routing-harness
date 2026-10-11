#!/usr/bin/env python3
"""D27: pinned public SDK, actual CLI, zero-message metadata under Seatbelt.

Registry access occurs only in preparation. The runtime and all descendants
have an OS profile, fresh roots, no credentials and a fifteen-second deadline.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import tarfile
import tempfile
import time
import urllib.request

SDK_URL = 'https://registry.npmjs.org/@anthropic-ai/claude-agent-sdk/-/claude-agent-sdk-0.3.296.tgz'
SDK_HASH = 'e966be99b6f047d56165e2ec03822f17a49beebd48ac8efb91dab1e48bcf69a7'
CLI = Path('/opt/homebrew/Caskroom/claude-code/2.1.267/claude')
CLI_HASH = 'a681f3008f0050029aeebcab3af51bb6a55ddeb625a3af3141a4416d43cd2558'
NODE = Path('/opt/homebrew/bin/node').resolve()
SANDBOX = Path('/usr/bin/sandbox-exec')

INERT = r'''import fs from 'node:fs';
import net from 'node:net';
import {spawnSync} from 'node:child_process';
const root=process.env.HOME;
const denied = fn => {try {fn();return false} catch(e) {return ['EPERM','EACCES'].includes(e.code)}};
fs.writeFileSync(root+'/allowed-write','inert');
const privateRead=denied(()=>fs.readFileSync(process.env.MRH_PRIVATE_CANARY));
const outsideWrite=denied(()=>fs.writeFileSync(process.env.MRH_OUTSIDE_CANARY,'inert'));
const keychainHelper=spawnSync('/usr/bin/security',['help'],{encoding:'utf8'});
const helperDenied=Boolean(keychainHelper.error && ['EPERM','EACCES'].includes(keychainHelper.error.code));
const socket=net.createConnection({host:'203.0.113.1',port:9});
const networkDenied=await new Promise(resolve=>{
 socket.on('error',e=>resolve(['EPERM','EACCES'].includes(e.code)));
 socket.on('connect',()=>resolve(false));setTimeout(()=>resolve(false),1000);
});socket.destroy();
console.log(JSON.stringify({ownWrite:true,privateReadDenied:privateRead,outsideWriteDenied:outsideWrite,
 keychainHelperDenied:helperDenied,networkDenied}));
'''

PROBE = r'''import {query} from './sdk.mjs';
let emitted=0;
let release;
const blocked = new Promise(resolve=>{release=resolve});
async function* noMessages() {await blocked;}
const abortController=new AbortController();
let q;
try {
 q=query({prompt:noMessages(),options:{pathToClaudeCodeExecutable:process.env.MRH_CLI,
 cwd:process.env.HOME,env:{...process.env},settingSources:[],settings:{},tools:[],
 mcpServers:{},plugins:[],hooks:{},permissionMode:'dontAsk',abortController}});
 const models=await q.supportedModels();
 console.log(JSON.stringify({status:'metadata',sdk:'0.3.296',models,userMessagesEmitted:emitted,
 scope:'isolated installed CLI defaults; account access and execution unconfirmed'}));
}catch(e){
 const safe = String(e?.message ?? '').slice(0,512);
 console.log(JSON.stringify({status:'sdk_error',errorName:String(e?.name ?? 'Error').slice(0,64),
 publicError:safe,userMessagesEmitted:emitted}));
}finally{
 abortController.abort();release();if(q)q.close();
}
'''


def profile(root, private_canary):
    # Read access is an allowlist of immutable OS/public runtime locations.
    # No user home, /Library/Keychains, managed prefs/settings or private state.
    quote = lambda path: json.dumps(str(path))
    reads = [root, '/System/Library', '/System/Applications', '/System/DriverKit',
             '/usr', '/bin', '/sbin', '/opt/homebrew/Cellar',
             '/opt/homebrew/opt', CLI.parent, '/dev/null', '/dev/urandom']
    return '\n'.join(['(version 1)', '(deny default)',
        '(allow process*)', '(allow sysctl-read)', '(allow signal)',
        '(allow file-read* '+ ' '.join('(subpath '+quote(p)+')' for p in reads)+')',
        '(allow file-write* (subpath '+quote(root)+') (literal "/dev/null"))',
        '(deny file-read* (subpath "/Users") (subpath "/System/Volumes/Data/Users"))',
        '(deny file-read* (subpath '+quote(private_canary)+'))',
        '(deny process-exec (literal "/usr/bin/security"))',
        '(deny mach-lookup)', '(deny network*)'])+'\n'


def run(command, env, root, deadline):
    started=time.monotonic()
    process=subprocess.Popen(command,cwd=root,env=env,text=True,stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE,start_new_session=True)
    timed_out=False
    try:
        stdout,stderr=process.communicate(timeout=deadline)
    except subprocess.TimeoutExpired:
        timed_out=True
        os.killpg(process.pid,signal.SIGTERM)
        try:stdout,stderr=process.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid,signal.SIGKILL);stdout,stderr=process.communicate(timeout=2)
    finally:
        # SDK close is not enough evidence that a descendant was reaped.
        try:os.killpg(process.pid,signal.SIGKILL)
        except ProcessLookupError:pass
    return {'exit':process.returncode,'timed_out':timed_out,'seconds':round(time.monotonic()-started,4),
            'stdout':stdout[:262144],'stderr':stderr[:4096], 'process_group':process.pid}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inert-only',action='store_true')
    args=parser.parse_args()
    if not SANDBOX.is_file() or not NODE.is_file() or not CLI.is_file():
        raise RuntimeError('isolation_or_pinned_runtime_missing')
    if hashlib.sha256(CLI.read_bytes()).hexdigest()!=CLI_HASH:
        raise RuntimeError('pinned_cli_changed')
    evidence={'sdk_version':'0.3.296','sdk_sha256':SDK_HASH,'cli_version':'2.1.267','cli_sha256':CLI_HASH,
              'node':str(NODE),'actual_probe_started':False,'actual_provider_calls':0}
    temporary=tempfile.TemporaryDirectory(prefix='mrh-e12-',dir='/private/tmp')
    parent=Path(temporary.name).resolve();root=parent/'runtime';root.mkdir(mode=0o700)
    private=root/'private-canary';private.mkdir();(private/'dummy').write_text('inert-noncredential')
    outside=parent/'outside-write-canary'
    try:
        for name in ('config','cache','tmp'): (root/name).mkdir(mode=0o700)
        env={'HOME':str(root),'TMPDIR':str(root/'tmp'),'XDG_CONFIG_HOME':str(root/'config'),
             'XDG_CACHE_HOME':str(root/'cache'),'CLAUDE_CONFIG_DIR':str(root/'config'),
             'PATH':'/usr/bin:/bin','NO_COLOR':'1','DISABLE_TELEMETRY':'1',
             'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC':'1','MRH_CLI':str(CLI),
             'MRH_PRIVATE_CANARY':str(private/'dummy'),'MRH_OUTSIDE_CANARY':str(outside)}
        sb=root/'isolation.sb';sb.write_text(profile(root,private))
        evidence['profile']=sb.read_text();evidence['environment_keys']=sorted(env)
        inert=root/'inert.mjs';inert.write_text(INERT)
        result=run([str(SANDBOX),'-f',str(sb),str(NODE),str(inert)],env,root,5)
        evidence['inert']=result
        try:checks=json.loads(result['stdout'])
        except ValueError:checks={}
        if result['exit']!=0 or not checks or not all(v is True for v in checks.values()):
            evidence['status']='isolation_unavailable'
        elif args.inert_only:
            evidence['status']='inert_passed'
        else:
            # No npm installation, lifecycle script or native optional package.
            data=urllib.request.urlopen(SDK_URL,timeout=20).read()
            if hashlib.sha256(data).hexdigest()!=SDK_HASH:raise RuntimeError('pinned_sdk_changed')
            with tarfile.open(fileobj=io.BytesIO(data),mode='r:gz') as archive:
                package=json.load(archive.extractfile('package/package.json'))
                evidence['dependency_requirements']={k:package.get(k) for k in ('engines','dependencies','optionalDependencies')}
                (root/'sdk.mjs').write_bytes(archive.extractfile('package/sdk.mjs').read())
            probe=root/'probe.mjs';probe.write_text(PROBE)
            evidence['actual_probe_started']=True
            evidence['probe']=run([str(SANDBOX),'-f',str(sb),str(NODE),str(probe)],env,root,15)
            evidence['status']='response_timeout' if evidence['probe']['timed_out'] else 'probe_completed'
    finally:
        outside_created=outside.exists()
        temporary.cleanup()
    evidence['cleanup']={'owned_root':str(parent),'root_absent':not parent.exists(),
                         'outside_canary_never_created':not outside_created}
    print(json.dumps(evidence,indent=2,sort_keys=True))


if __name__=='__main__':main()
