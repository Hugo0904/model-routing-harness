#!/usr/bin/env python3
"""Actual copied-Node canaries under Gemini's unchanged deny-private profile."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
import argparse
import json
import subprocess
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'src'))
from mrh.adapters.catalogs.gemini_catalog import installation, isolated_install

CODE = r'''const fs=require('fs'),cp=require('child_process'),net=require('net');
const [inside,outside]=process.argv.slice(1);let read=false,write=false,security=false;
try{fs.readFileSync(inside)}catch(e){read=e.code==='EPERM'||e.code==='EACCES'}
try{fs.writeFileSync(outside,'must-not-exist')}catch(e){write=e.code==='EPERM'||e.code==='EACCES'}
try{cp.execFileSync('/usr/bin/security',['help'],{stdio:'ignore'})}catch(e){security=e.code==='EPERM'||e.code==='EACCES'}
const socket=net.connect(9,'127.0.0.1');socket.once('error',e=>{console.log(JSON.stringify({private_read_denied:read,outside_write_denied:write,keychain_program_denied:security,outbound_denied:e.code==='EPERM'||e.code==='EACCES'}));socket.destroy()});
setTimeout(()=>{socket.destroy();process.exit(2)},2000).unref();'''

if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--entry',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    info=installation(args.entry.resolve())
    with tempfile.TemporaryDirectory(prefix='mrh-e16-outside-',dir='/private/tmp') as outer:
        outside=Path(outer)/'outside-write'
        with isolated_install(info) as (root,work,env,prefix,entry):
            private=root/'private-canary';private.write_text('NONSECRET_PRIVATE_CANARY')
            result=subprocess.run(prefix+['-e',CODE,str(private),str(outside)],cwd=work,env=env,capture_output=True,text=True,timeout=5)
            assert result.returncode==0,(result.returncode,result.stderr[:500])
            checks=json.loads(result.stdout);assert all(checks.values()),checks
            assert not outside.exists()
            evidence={'checks':checks,'profile':(root/'isolation.sb').read_text(),'owned_root':str(root),'outer_root':outer,
                      'node_sha256':info['node_sha256'],'installation_sha256':info['sha256'],'npm_files':len(info['files']),
                      'entry':str(args.entry),'node':str(info['node']),'real_credentials_or_provider':False}
    evidence.update(owned_root_absent=not Path(evidence['owned_root']).exists(),outside_root_absent=not Path(outer).exists())
    args.output.write_text(json.dumps(evidence,indent=2)+'\n');print(json.dumps(evidence['checks']))
