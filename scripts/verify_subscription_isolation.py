#!/usr/bin/env python3
"""Official pinned exec process; owned loopback response, no credentials/model use."""
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from mrh.codex_subscription import invocation, SCHEMA, parse_stream


def inspect(binary, output):
    from_path = Path(__file__).resolve().parents[1] / 'build/e17-public/models.json'
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_): pass
        def do_POST(self):
            assert self.headers.get('Authorization') is None
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            text = json.dumps(body)
            requests.append({'model': body.get('model'), 'reasoning': body.get('reasoning'),
                'tools': body.get('tools', []), 'user_config_leaked': 'MRH_OWNED_CONFIG_CANARY' in text,
                'project_instructions_leaked': 'MRH_OWNED_AGENTS_CANARY' in text,
                'home_instructions_leaked': 'MRH_OWNED_HOME_CANARY' in text,
                'workspace_path_leaked': str(work) in text, 'request_keys': sorted(body)})
            item = {'id':'owned-message', 'type':'message', 'role':'assistant',
                    'content':[{'type':'output_text', 'text':'{"tier":"Light","confidence":0.9}'}]}
            events = [{'type':'response.created','response':{'id':'owned-response','status':'in_progress','output':[]}},
                {'type':'response.output_item.added','output_index':0,'item':item},
                {'type':'response.output_item.done','output_index':0,'item':item},
                {'type':'response.completed','response':{'id':'owned-response','status':'completed','output':[item],
                  'usage':{'input_tokens':1,'output_tokens':1,'total_tokens':2,'input_tokens_details':{'cached_tokens':0}}}}]
            data = ''.join('data: '+json.dumps(e)+'\n\n' for e in events).encode()
            self.send_response(200); self.send_header('Content-Type','text/event-stream')
            self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)
    server = ThreadingHTTPServer(('127.0.0.1',0), Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    started=time.monotonic()
    try:
        with tempfile.TemporaryDirectory(prefix='mrh-e19-isolation-') as root:
            root=Path(root); home=root/'home'; home.mkdir(); work=root/'work'; work.mkdir()
            (home/'config.toml').write_text('developer_instructions="MRH_OWNED_CONFIG_CANARY"\n')
            (home/'AGENTS.md').write_text('MRH_OWNED_HOME_CANARY')
            (work/'AGENTS.md').write_text('MRH_OWNED_AGENTS_CANARY')
            schema=root/'answer.json'; schema.write_text(json.dumps(SCHEMA))
            catalog=root/'models.json'; catalog.write_bytes(from_path.read_bytes())
            argv=invocation(binary,work,schema)[:-1]
            overrides=('model_provider="mrh_isolation_fixture"',
                'model_catalog_json='+json.dumps(str(catalog)),
                'model_providers.mrh_isolation_fixture={name="Owned loopback",base_url="http://127.0.0.1:'+str(server.server_port)+'/v1",wire_api="responses",requires_openai_auth=false,request_max_retries=0,stream_max_retries=0}')
            for value in overrides:argv+=['-c',value]
            argv+=['-']
            env={'HOME':str(root),'CODEX_HOME':str(home),'PATH':os.defpath,'LANG':'en_US.UTF-8','NO_COLOR':'1'}
            result=subprocess.run(argv,input='{"task":"Sort literal numbers [3,1,2]."}',text=True,capture_output=True,env=env,cwd=work,timeout=25)
            classification,usage=parse_stream(result.stdout.encode())
            assert result.returncode==0 and len(requests)==1 and requests[0]['tools']==[]
            assert requests[0]['home_instructions_leaked'] and not requests[0]['user_config_leaked']
            assert not requests[0]['project_instructions_leaked'] and not requests[0]['workspace_path_leaked']
            (home/'AGENTS.md').unlink()  # Owned canary only; never the user's file.
            clean=subprocess.run(argv,input='{"task":"Sort literal numbers [3,1,2]."}',text=True,capture_output=True,env=env,cwd=work,timeout=25)
            parse_stream(clean.stdout.encode())
            assert clean.returncode==0 and len(requests)==2 and requests[1]['tools']==[]
            assert not any(requests[1][k] for k in ('user_config_leaked','project_instructions_leaked','home_instructions_leaked','workspace_path_leaked'))
            evidence={'evidence_kind':'official_unmodified_exec_with_scripted_loopback_response',
                'real_subscription_calls':0,'credentials_used':False,'binary_sha256':hashlib.sha256(binary.read_bytes()).hexdigest(),
                'catalog_sha256':hashlib.sha256(catalog.read_bytes()).hexdigest(), 'exit':result.returncode,
                'elapsed_seconds':round(time.monotonic()-started,3), 'requests':requests,
                'stdout':result.stdout,'stderr':result.stderr, 'argv':argv,'owned_root_removed':True,
                'scripted_answer':{'tier':classification.tier,'confidence':classification.confidence},
                'scripted_usage':usage,'production_rejects_home_instructions_before_spawn':True}
        output.write_text(json.dumps(evidence,indent=2)+'\n')
        print(json.dumps({'exit':evidence['exit'],'requests':requests,'elapsed_seconds':evidence['elapsed_seconds']}))
    finally:server.shutdown();server.server_close()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--binary',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args();inspect(args.binary,args.output)
