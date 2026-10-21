#!/usr/bin/env python3
"""Actual owned CLI/PTY walkthrough; no installed Hook, credentials or provider."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
import argparse
import errno
import fcntl
import hashlib
import json
import os
import pty
import re
import select
import struct
import subprocess
import tempfile
import termios
import time

PROJECT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(PROJECT/'src'))
from mrh.infrastructure import settings
from mrh.infrastructure.store import Store
from mrh.routing.types import Proposal, Decision


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output-prefix',type=Path,required=True)
    args=parser.parse_args(); prefix=args.output_prefix.resolve();prefix.parent.mkdir(parents=True,exist_ok=True)
    started=time.monotonic();record={}
    with tempfile.TemporaryDirectory(prefix='mrh-e9-',dir='/private/tmp') as temporary:
        root=Path(temporary).resolve();path=root/'settings/settings.json'
        (root/'home').mkdir();(root/'tmp').mkdir()
        env={'PATH':os.defpath,'HOME':str(root/'home'),'TMPDIR':str(root/'tmp'),'PYTHONPATH':str(PROJECT/'src'),
             'PYTHONDONTWRITEBYTECODE':'1','TERM':'xterm-256color','LANG':'en_US.UTF-8'}
        def run(argv,text=''):
            result=subprocess.run([sys.executable, "-B",'-m','mrh',*argv],input=text,text=True,capture_output=True,cwd=PROJECT,env=env,timeout=10)
            assert result.returncode==0,(argv,result.returncode,result.stderr)
            return result.stdout
        def terminal(argv,answers=(),width=120,interrupt=False):
            pid,fd=pty.fork()
            if pid==0:
                os.chdir(PROJECT)
                os.execve(sys.executable,[sys.executable, "-B",'-m','mrh',*argv],env)
            fcntl.ioctl(fd,termios.TIOCSWINSZ,struct.pack('HHHH',60,width,0,0))
            captured=bytearray();consumed=0;next_answer=0;deadline=time.monotonic()+10;waited=False
            try:
                while True:
                    if time.monotonic()>deadline:
                        os.write(fd,b'\x03');raise TimeoutError('owned CLI PTY deadline')
                    ready,_,_=select.select([fd],[],[],.2)
                    if not ready:continue
                    try:data=os.read(fd,65536)
                    except OSError as exc:
                        if exc.errno==errno.EIO:break
                        raise
                    if not data:break
                    captured.extend(data)
                    prompt=captured.find(b'  > ',consumed)
                    if prompt>=0:
                        consumed=prompt+4
                        if interrupt:
                            os.write(fd,b'\x03');interrupt=False
                        elif next_answer<len(answers):
                            os.write(fd,(answers[next_answer]+'\n').encode());next_answer+=1
                _,status=os.waitpid(pid,0)
                waited=True
                assert os.waitstatus_to_exitcode(status)==0,status
            finally:
                os.close(fd)
                if not waited:os.waitpid(pid,0)
            return captured.decode().replace('\r\n','\n')
        run(['settings','init','--path',str(path)])
        before=path.read_bytes()
        editor=terminal(['settings','edit','--path',str(path)],
                        ['light-choice','inherit','small-choice','low','mid-choice','high','Fixed','fixed-choice','inherit','save'])
        saved=json.loads(run(['settings','show','--path',str(path)]))['settings']
        assert saved['revision']==1 and not saved['enabled'] and not saved['task_export_permitted']
        assert saved['policy']['fixed']=={'model':'fixed-choice'}
        assert saved['policy']['tiers']=={'Light':{'model':'light-choice'},'Small':{'model':'small-choice','effort':'low'},'Mid':{'model':'mid-choice','effort':'high'}}
        stable=path.read_bytes(); assert stable!=before
        for case,text in [('cancel','cancel\n'),('eof','')]:
            assert 'Cancelled' in run(['settings','edit','--path',str(path),'--plain'],text)
            assert path.read_bytes()==stable
        interrupted=terminal(['settings','edit','--path',str(path)],interrupt=True)
        assert 'Cancelled' in interrupted and path.read_bytes()==stable
        # One explicit old synthetic proposal proves the settings-associated DB
        # path. It is history, not the fixed demo or this current configuration.
        store=Store(path.parent/'events.sqlite3')
        prior=Proposal('codex','simulation','old-session','old-turn','old-call',{'message':'owned prior fixture','model':'historical-choice'},True)
        store.claim(prior);store.complete(prior.identity,Decision(reason='explicit_model',synthetic=True))
        history=json.loads(run(['stats','--settings',str(path),'--synthetic','--json']))
        assert history['proposals']==1 and history['synthetic_attempts']==0 and history['actual_models']=={}
        assert json.loads(run(['stats','--settings',str(path),'--json']))['proposals']==0
        dashboard=terminal(['status','--settings',str(path),'--synthetic'],width=56)
        assert 'CURRENT CONFIGURATION' in dashboard and 'SYNTHETIC HISTORY' in dashboard
        assert 'SYNTHETIC DEMO' not in dashboard and 'fixed-choice' in dashboard
        assert json.loads(run(['stats','--settings',str(path),'--synthetic','--json']))==history
        run(['demo','--plain','--width','56'])
        assert path.read_bytes()==stable
        for name,text in [('editor-120',editor),('status-56',dashboard),('cancel-pty',interrupted)]:
            Path(str(prefix)+'-'+name+'.ansi').write_text(text)
            plain=re.sub(r'\x1b\[[0-9;]*m','',text)
            Path(str(prefix)+'-'+name+'.txt').write_text('\n'.join(line.rstrip() for line in plain.splitlines()).rstrip()+'\n')
        record={'kind':'actual Python CLI in POSIX PTY; native macOS Terminal window not observed','python':sys.executable,
                'current_policy':saved,'associated_history':history,'save_readback':True,'cancel_eof_ctrl_c_no_write':True,
                'repeated_stats_unchanged':True,'demo_isolated':True,'real_provider_calls':0,'settings_sha256':hashlib.sha256(stable).hexdigest(),
                'pty_widths':[120,56],'owned_temporary_root':str(root),'installed_host_changed':False,'review':'A0 parent; A visible acceptance pending'}
    assert not root.exists()
    record.update(cleanup_removed=True,elapsed_seconds=round(time.monotonic()-started,3))
    Path(str(prefix)+'-walkthrough.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps({'actual_cli_save':True,'pty_ctrl_c_cancel':True,'history_proposals':1,'real_provider_calls':0,
                      'temporary_removed':True,'elapsed_seconds':record['elapsed_seconds']}))


if __name__=='__main__':main()
