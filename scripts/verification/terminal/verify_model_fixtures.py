#!/usr/bin/env python3
"""Actual PTY error/recovery fixtures; synthetic only, no install/provider."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
import argparse
import errno
import fcntl
import json
import os
import pty
import re
import select
import struct
import tempfile
import termios
import time

PROJECT=Path(__file__).resolve().parents[3]


def main():
    p=argparse.ArgumentParser();p.add_argument('--output-prefix',required=True,type=Path)
    prefix=p.parse_args().output_prefix.resolve();started=time.monotonic();results=[]
    with tempfile.TemporaryDirectory(prefix='mrh-e10-keyboard-fixtures-',dir='/private/tmp') as tmp:
        root=Path(tmp).resolve();(root/'home').mkdir();(root/'work').mkdir()
        env={'PATH':os.defpath,'HOME':str(root/'home'),'TMPDIR':str(root),
             'PYTHONPATH':str(PROJECT/'src'),'PYTHONDONTWRITEBYTECODE':'1','TERM':'xterm-256color'}
        def run(scenario,width,answers,cancel=False):
            registry=root/scenario
            argv=[sys.executable,str(PROJECT/'scripts/fixtures/model_selector_fixture.py'),'--root',str(registry),'--scenario',scenario,'--width',str(width)]
            pid,fd=pty.fork()
            if pid==0:os.chdir(root/'work');os.execve(sys.executable,argv,env)
            fcntl.ioctl(fd,termios.TIOCSWINSZ,struct.pack('HHHH',70,width,0,0))
            data=bytearray();i=0;offset=0;deadline=time.monotonic()+15;before=None;path=None;waited=False
            try:
                while True:
                    if time.monotonic()>deadline:os.kill(pid,9);raise TimeoutError('E10 fixture PTY')
                    if not select.select([fd],[],[],.2)[0]:continue
                    try:chunk=os.read(fd,65536)
                    except OSError as exc:
                        if exc.errno==errno.EIO:break
                        raise
                    if not chunk:break
                    data.extend(chunk)
                    if i<len(answers):
                        heading,keys=answers[i];found=data.find(heading.encode(),offset)
                        if found>=0:
                            if before is None:
                                b=json.loads((registry/'registry.json').read_text())['bindings'][0]
                                path=Path(b['settings_path']);before=path.read_bytes()
                            offset=found+len(heading);os.write(fd,keys.encode());i+=1
                _,status=os.waitpid(pid,0);waited=True
                assert os.waitstatus_to_exitcode(status)==0,(status,data[-800:])
            finally:
                os.close(fd)
                if not waited:os.waitpid(pid,0)
            text=data.decode().replace('\r\n','\n')
            plain=re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]','',text)
            normalized=' '.join(plain.split());saved=json.loads(path.read_text())
            assert not saved['enabled'] and not saved['task_export_permitted'] and saved['allowed_workspaces']==[]
            if cancel:assert path.read_bytes()==before
            else:assert saved['policy']['tiers']['Light']=={'model':'fixture-top-id','effort':'high'}
            if scenario=='retired':assert 'confirmed retired: synthetic:retirement-notice' in normalized
            if scenario=='unavailable':assert 'global retirement is unconfirmed' in normalized
            if scenario in ('offline','recovery','partial'):
                assert 'display only; cannot select or save' in normalized and 'No model is marked retired by this failure' in normalized
            prefix.with_name(prefix.name+'-'+scenario+'-'+str(width)+'.ansi').write_text(text)
            prefix.with_name(prefix.name+'-'+scenario+'-'+str(width)+'.txt').write_text('\n'.join(l.rstrip() for l in plain.splitlines()).rstrip()+'\n')
            results.append({'scenario':scenario,'width':width,'exit_code':0,'synthetic':True,
                            'keyboard_only':True,'cancellation_bytes_preserved':cancel,'saved_profile':saved})
        save=[('Light MODEL','\x1b[B\n'),('REASONING EFFORT','\x1b[B\n'),('SAVE POLICY?','\n')]
        run('retired',56,save)
        run('unavailable',120,[('Light MODEL','\x1b')],True)
        run('recovery',56,[('LIST UNAVAILABLE','\n'),*save])
        run('partial',56,[('LIST UNAVAILABLE','\n'),*save])
        run('offline',120,[('LIST UNAVAILABLE','\x1b[B\x1b[B\n')],True)
    evidence={'kind':'E10-synthetic-error-keyboard-PTY','cases':results,'owned_root':str(root),
              'cleanup_removed':not root.exists(),'elapsed_seconds':round(time.monotonic()-started,3),
              'real_catalog_or_model_requests':0,'native_mac_terminal_observed':False}
    assert evidence['cleanup_removed']
    prefix.with_name(prefix.name+'-fixture-pty.json').write_text(json.dumps(evidence,indent=2)+'\n')
    print(json.dumps({'cases':len(results),'elapsed_seconds':evidence['elapsed_seconds'],'cleanup_removed':True}))


if __name__=='__main__':main()
