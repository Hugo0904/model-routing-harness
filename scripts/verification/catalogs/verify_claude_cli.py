#!/usr/bin/env python3
"""E13: actual CLI-only initialization; public metadata, no user/task message."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
import hashlib
import json
import os
import selectors
import signal
import subprocess
import tempfile
import time
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'src'))
from mrh.adapters.catalogs.claude_catalog import isolation_profile

CLI=Path('/opt/homebrew/Caskroom/claude-code/2.1.267/claude')
SANDBOX=Path('/usr/bin/sandbox-exec')


def main():
    evidence={'sdk_runtime_used':False,'node_runtime_used':False,
              'request_source':'SDK0.3.296 published initialize envelope',
              'cli_sha256':hashlib.sha256(CLI.read_bytes()).hexdigest()}
    with tempfile.TemporaryDirectory(prefix='mrh-e13-cli-',dir='/private/tmp') as tmp:
        parent=Path(tmp).resolve();root=parent/'runtime';root.mkdir()
        private=root/'private-canary';private.mkdir()
        for name in ['config','cache','tmp']:(root/name).mkdir()
        conf=root/'config/openssl.cnf';conf.write_text('')
        settings_file=root/'config/settings.json';settings_file.write_text('{}')
        mcp_file=root/'config/mcp.json';mcp_file.write_text('{"mcpServers":{}}')
        env={'PATH':'/usr/bin:/bin','HOME':str(root),'TMPDIR':str(root/'tmp'),
             'CLAUDE_CODE_TMPDIR':str(root/'tmp'),
             'CLAUDE_CONFIG_DIR':str(root/'config'),'XDG_CONFIG_HOME':str(root/'config'),
             'XDG_CACHE_HOME':str(root/'cache'),'OPENSSL_CONF':str(conf),
             'DISABLE_TELEMETRY':'1','CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC':'1','NO_COLOR':'1'}
        sb=root/'isolation.sb';sb.write_text(isolation_profile(root,str(CLI)))
        evidence.update(profile=sb.read_text(),profile_sha256=hashlib.sha256(sb.read_bytes()).hexdigest(),
                        owned_root=str(parent),environment_keys=sorted(env))
        args=[str(CLI),'-p','--bare','--verbose','--output-format','stream-json',
              '--input-format','stream-json','--setting-sources','','--settings',str(settings_file),'--tools','',
              '--strict-mcp-config','--mcp-config',str(mcp_file),
              '--permission-mode','dontAsk','--disable-slash-commands','--no-session-persistence']
        evidence['arguments']=args
        ident='mrh_'+uuid.uuid4().hex
        request={'type':'control_request','request_id':ident,
                 'request':{'subtype':'initialize','hooks':{},'sdkMcpServers':[],'agents':{},'plugins':[]}}
        evidence.update(writes=[],frame_types=[],status='response_timeout',cleanup_errors=[])
        started=time.monotonic()
        with (root/'stderr').open('wb') as err:
            proc=subprocess.Popen([str(SANDBOX),'-f',str(sb),*args],cwd=root,env=env,
                                  stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=err,start_new_session=True)
            evidence.update(process_group=proc.pid,started_at=time.time())
            print(json.dumps({'owned_process_group':proc.pid,'owned_root':str(parent)}),flush=True)
            selector=selectors.DefaultSelector();selector.register(proc.stdout,selectors.EVENT_READ)
            buffer=b''
            try:
                proc.stdin.write((json.dumps(request)+'\n').encode());proc.stdin.flush()
                evidence['writes'].append(request)
                deadline=time.monotonic()+15;done=False
                while time.monotonic()<deadline and not done:
                    events=selector.select(max(0,deadline-time.monotonic()))
                    if not events:break
                    data=os.read(proc.stdout.fileno(),16384)
                    if not data:evidence['status']='cli_eof';break
                    buffer+=data
                    if len(buffer)>262144:evidence['status']='response_oversized';break
                    while b'\n' in buffer:
                        line,buffer=buffer.split(b'\n',1);item=json.loads(line)
                        evidence['frame_types'].append(item.get('type'))
                        if item.get('type')=='control_response' and item.get('response',{}).get('request_id')==ident:
                            response=item['response'];evidence['control_subtype']=response.get('subtype')
                            if response.get('subtype')=='success':
                                payload=response.get('response',{});evidence['models']=payload.get('models')
                                evidence['payload_keys']=sorted(payload);evidence['status']='metadata'
                            else:
                                evidence['status']='control_error';evidence['public_error']=str(response.get('error',''))[:400]
                            done=True;break
                        if item.get('type') not in ['system','keep_alive']:
                            evidence['status']='unexpected_frame';done=True;break
            except Exception as exc:
                evidence.update(status='harness_error',error_type=type(exc).__name__,error=str(exc)[:300])
            finally:
                selector.close()
                try:proc.stdin.close()
                except OSError as exc:evidence['cleanup_errors'].append('stdin:'+str(exc))
                # EOF first: metadata-only sessions should finish without a signal.
                try:proc.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    for sig in [signal.SIGTERM,signal.SIGKILL]:
                        try:os.killpg(proc.pid,sig)
                        except ProcessLookupError:break
                        except PermissionError as exc:evidence['cleanup_errors'].append('group:'+str(exc))
                        try:proc.wait(timeout=1);break
                        except subprocess.TimeoutExpired:continue
                evidence['exit_after_cleanup']=proc.poll()
                proc.stdout.close()
        evidence['stderr']=(root/'stderr').read_text(errors='replace')[:2000]
        evidence['seconds']=round(time.monotonic()-started,4)
    evidence['root_absent']=not parent.exists()
    destination=Path(__file__).resolve().parents[3]/'docs/evidence/e13-cli-probe.json'
    destination.write_text(json.dumps(evidence,indent=2)+'\n')
    print(json.dumps({k:v for k,v in evidence.items() if k not in ['profile','arguments']}))


if __name__=='__main__':main()
