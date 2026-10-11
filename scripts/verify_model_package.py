#!/usr/bin/env python3
"""E10 single offline install plus real PTY short-command/catalog walkthrough.

Native catalog observations are credential-free advertised options. The one
offline/recovery provider injection is explicitly synthetic, not a real API.
"""
import argparse
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pty
import re
import select
import struct
import subprocess
import sys
import tempfile
import termios
import time
import zipfile

PROJECT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output-prefix',type=Path,required=True)
    prefix=parser.parse_args().output_prefix.resolve();prefix.parent.mkdir(parents=True,exist_ok=True)
    started=time.monotonic();commands=[];captures={}
    hashes={str(p.relative_to(PROJECT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((PROJECT/'src/mrh').rglob('*.py'))}
    base=subprocess.check_output(['git','rev-parse','HEAD'],cwd=PROJECT,text=True).strip()
    with tempfile.TemporaryDirectory(prefix='mrh-e10-installed-',dir='/private/tmp') as tmp:
        root=Path(tmp).resolve();work=root/'work';work.mkdir();(root/'home').mkdir();(root/'tmp').mkdir()
        env={'PATH':os.defpath,'HOME':str(root/'home'),'TMPDIR':str(root/'tmp'),'LANG':'en_US.UTF-8',
             'TERM':'xterm-256color','PYTHONDONTWRITEBYTECODE':'1'}
        def run(argv,text='',expected=0):
            t=time.monotonic();r=subprocess.run(list(map(str,argv)),input=text,text=True,capture_output=True,cwd=work,env=env,timeout=30)
            commands.append({'argv':list(map(str,argv)),'exit_code':r.returncode,'elapsed_seconds':round(time.monotonic()-t,3)})
            assert r.returncode==expected,(r.returncode,r.stderr[:400]);return r.stdout
        run([sys.executable,'-m','venv',root/'venv']);python=root/'venv/bin/python';exe=root/'venv/bin/mrh'
        build="import sys;sys.path.insert(0,sys.argv[1]);import mrh_build;print(mrh_build.build_wheel(sys.argv[2]))"
        wheel=root/'wheel'/run([sys.executable,'-c',build,PROJECT,root/'wheel']).strip()
        wheel_hash=hashlib.sha256(wheel.read_bytes()).hexdigest()
        with zipfile.ZipFile(wheel) as z:
            for n,h in hashes.items():assert hashlib.sha256(z.read(n.removeprefix('src/'))).hexdigest()==h
        run([python,'-m','pip','--no-cache-dir','install','--no-index','--no-deps','--no-build-isolation',wheel])
        identity=json.loads(run([python,'-I','-c',"import json,os,mrh,mrh.model_selector,mrh.bindings,mrh.catalog;print(json.dumps({'module':mrh.__file__,'selector':mrh.model_selector.__file__,'bindings':mrh.bindings.__file__,'catalog':mrh.catalog.__file__,'cwd':os.getcwd()}))"]))
        for n,h in hashes.items():assert hashlib.sha256((Path(identity['module']).parent/n.removeprefix('src/mrh/')).read_bytes()).hexdigest()==h
        assert identity['cwd']==str(work) and Path(identity['selector']).is_relative_to(root/'venv') and 'PYTHONPATH' not in env
        def terminal(argv,answers,width):
            pid,fd=pty.fork()
            if pid==0:os.chdir(work);os.execve(str(argv[0]),list(map(str,argv)),env)
            fcntl.ioctl(fd,termios.TIOCSWINSZ,struct.pack('HHHH',60,width,0,0))
            data=bytearray();consumed=0;i=0;deadline=time.monotonic()+30;waited=False
            try:
                while True:
                    if time.monotonic()>deadline:os.kill(pid,9);raise TimeoutError('owned E10 PTY deadline')
                    ready,_,_=select.select([fd],[],[],.2)
                    if not ready:continue
                    try:chunk=os.read(fd,65536)
                    except OSError as exc:
                        if exc.errno==errno.EIO:break
                        raise
                    if not chunk:break
                    data.extend(chunk)
                    if i<len(answers):
                        heading,keys=answers[i];prompt=data.find(heading.encode(),consumed)
                        if prompt>=0:
                            consumed=prompt+len(heading)
                            os.write(fd,keys.encode());i+=1
                _,status=os.waitpid(pid,0);waited=True
                assert os.waitstatus_to_exitcode(status)==0,(status,data[-1000:])
            finally:
                os.close(fd)
                if not waited:os.waitpid(pid,0)
            commands.append({'argv':list(map(str,argv)),'exit_code':0,'pty_width':width})
            return data.decode().replace('\r\n','\n')
        registry=root/'bindings'
        assert 'interactive terminal' in run([exe,'model','light','--root',registry],expected=2)
        captures['first-use-120']=terminal([exe,'model','light','--root',registry,'--width','120','--color'],
            [('FIRST USE','\n'),('CONFIRM MRH PROFILE','\n'),('Light MODEL','\n'),('REASONING EFFORT','\x1b[B\n'),('SAVE POLICY?','\n')],120)
        data=json.loads((registry/'registry.json').read_text());binding=data['bindings'][0];path=Path(binding['settings_path'])
        light=json.loads(run([exe,'settings','show','--path',path]))['settings']
        native_snapshot=binding['catalog']
        assert native_snapshot['assurance']=='tool-advertised' and native_snapshot['complete'] is True
        assert light['policy']['tiers']['Light']['model']==native_snapshot['models'][0]['id']
        assert light['policy']['tiers']['Light']['effort']==native_snapshot['models'][0]['efforts'][0]
        assert not light['enabled'] and not light['task_export_permitted']
        # Known old mapping is explicitly synthetic preview data, not a claim
        # that any real model or account was retired.
        seed="import sys;from mrh import settings;p=sys.argv[1];s=settings.read(p);s['policy']['tiers']['Small']={'model':'synthetic-missing-old-target'};settings.update(p,expected_revision=s['revision'],policy=s['policy'])"
        run([python,'-I','-c',seed,path])
        captures['unavailable-56']=terminal([exe,'model','small','--root',registry,'--width','56','--color'],
            [('Small MODEL','\n'),('REASONING EFFORT','\n'),('SAVE POLICY?','\n')],56)
        recovered=json.loads(run([exe,'settings','show','--path',path]))['settings']
        assert recovered['policy']['tiers']['Small']['model']==native_snapshot['models'][0]['id']
        plain_unavailable=re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]','',captures['unavailable-56'])
        assert 'global retirement is unconfirmed' in ' '.join(plain_unavailable.split())
        captures['top-main-120']=terminal([exe,'model','top','--root',registry,'--width','120','--color'],
            [('TOP MODE','\n'),('SAVE POLICY?','\n')],120)
        # Actual PTY through the installed CLI public parser, with a labeled
        # synthetic provider at its existing in-process dependency seam.
        recovery="""import sys,time
from mrh import cli
from mrh.bindings import Registry
from mrh.catalog import Catalog,CatalogError
class Provider:
 def __init__(self):self.n=0
 def refresh(self,b):
  self.n+=1
  if self.n==1:raise CatalogError('synthetic_offline')
  c=Catalog.from_dict(Registry(sys.argv[1]).read()['bindings'][0]['catalog'])
  return Catalog(**{**c.__dict__,'fetched_at':time.time(),'source':'synthetic:refresh-recovery','assurance':'synthetic'})
raise SystemExit(cli.main(['model','light','--root',sys.argv[1],'--width','56','--color'],model_dependencies={'provider':Provider()}))
"""
        captures['offline-recovery-56']=terminal([python,'-I','-c',recovery,registry],
            [('LIST UNAVAILABLE','\n'),('Light MODEL','\n'),('REASONING EFFORT','\n'),('SAVE POLICY?','\n')],56)
        assert 'display only' in captures['offline-recovery-56'] and 'synthetic:refresh-recovery' in captures['offline-recovery-56']
        final=json.loads(run([exe,'settings','show','--path',path]))['settings']
        assert final==recovered # Main is already the default; recovery preserves mapping.
        stats=json.loads(run([exe,'stats','--settings',path,'--json']))
        assert stats['proposals']==0 and stats['jev_attempts']==0
        assert not final['enabled'] and not final['task_export_permitted'] and final['allowed_workspaces']==[]
        source_current=all(hashlib.sha256((PROJECT/n).read_bytes()).hexdigest()==h for n,h in hashes.items())
        assert source_current
        evidence={'kind':'E10-offline-installed-entry-and-PTY','source_base':base,'source_sha256':hashes,
                  'wheel_sha256':wheel_hash,'installed_identity':identity,'all_installed_bytes_match_source':True,
                  'no_pythonpath':True,'outside_source_cwd':True,'owned_root':str(root),'commands':commands,
                  'native_advertised_catalog_observation':native_snapshot,'synthetic_recovery_provider':True,
                  'first_saved_profile':light,'final_profile':final,'stats':stats,
                  'actual_model_requests':0,'account_confirmation':False,'global_install':False,
                  'native_mac_terminal_observed':False}
        evidence['keyboard_inputs']='Only Up/Down arrow sequences and Enter; no typed IDs/effort/paths/bind/save'
    evidence.update(cleanup_removed=not root.exists(),elapsed_seconds=round(time.monotonic()-started,3))
    assert evidence['cleanup_removed']
    prefix.with_name(prefix.name+'-package.json').write_text(json.dumps(evidence,indent=2)+'\n')
    for name,text in captures.items():
        prefix.with_name(prefix.name+'-'+name+'.ansi').write_text(text)
        plain=re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]','',text)
        plain='\n'.join(l.rstrip() for l in plain.splitlines()).rstrip()+'\n'
        prefix.with_name(prefix.name+'-'+name+'.txt').write_text(plain)
    print(json.dumps({'elapsed_seconds':evidence['elapsed_seconds'],'cleanup_removed':True,'wheel_sha256':wheel_hash}))


if __name__=='__main__':main()
