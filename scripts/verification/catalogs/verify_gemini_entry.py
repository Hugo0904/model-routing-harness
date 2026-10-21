#!/usr/bin/env python3
"""E16's actual bundled Gemini select/back/save/cancel and failed-refresh UI."""
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
import shutil
import signal
import struct
import subprocess
import tempfile
import termios
import time


def inspect(bundle, gemini_package, node):
    started=time.monotonic();commands=[];pids=[];captures={}
    with tempfile.TemporaryDirectory(prefix='mrh-e16-entry-',dir='/private/tmp') as tmp:
        root=Path(tmp).resolve();home=root/'home';home.mkdir();work=root/'work';work.mkdir();tools=root/'bin';tools.mkdir()
        prefix=home/'.nvm/versions/node/e16-cli';package=prefix/'lib/node_modules/@google/gemini-cli';package.parent.mkdir(parents=True)
        original=Path(gemini_package).resolve()
        shutil.copytree(original,package,symlinks=True);(prefix/'bin').mkdir()
        shutil.copy2(Path(node).resolve(),prefix/'bin/node')
        (tools/'gemini').symlink_to(package/'bundle/gemini.js')
        env={'PATH':str(tools),'HOME':str(home),'TMPDIR':str(root),'LANG':'en_US.UTF-8','TERM':'xterm-256color','NO_COLOR':'1'}
        entry=bundle/'mrh';python=bundle/'runtime/bin/python3.11';registry=root/'bindings'
        def run(args):
            p=subprocess.Popen(list(map(str,args)),cwd=work,env=env,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True);pids.append(p.pid)
            try:out,err=p.communicate(timeout=30)
            except BaseException:
                if p.poll() is None and os.getpgid(p.pid)==p.pid:os.killpg(p.pid,signal.SIGKILL)
                p.wait();raise
            assert p.returncode==0,(p.returncode,err[:500]);commands.append({'argv':list(map(str,args)),'exit':0});return out
        identity=json.loads(run([python,'-I','-B','-c',"import sys,json;sys.path.insert(0,sys.argv[1]);import mrh.adapters.catalogs.gemini_catalog;print(json.dumps({'python':sys.executable,'module':mrh.adapters.catalogs.gemini_catalog.__file__,'path':sys.path}))",bundle/'app/mrh.pyz']))
        assert Path(identity['python']).is_relative_to(bundle) and all(Path(p).is_relative_to(bundle) for p in identity['path'])
        def terminal(args,answers):
            pid,fd=pty.fork()
            if pid==0:os.chdir(work);os.execve(str(args[0]),list(map(str,args)),env)
            pids.append(pid)
            data=bytearray();cursor=0;index=0;deadline=time.monotonic()+45;waited=False
            try:
                fcntl.ioctl(fd,termios.TIOCSWINSZ,struct.pack('HHHH',24,56,0,0))
                while True:
                    if time.monotonic()>deadline:raise TimeoutError('gemini_keyboard_deadline')
                    if not select.select([fd],[],[],.2)[0]:continue
                    try:chunk=os.read(fd,65536)
                    except OSError as e:
                        if e.errno==errno.EIO:break
                        raise
                    if not chunk:break
                    data.extend(chunk)
                    if index<len(answers):
                        heading,keys=answers[index];pos=data.find(heading.encode(),cursor)
                        if pos>=0:cursor=pos+len(heading);os.write(fd,keys);index+=1
                _,status=os.waitpid(pid,0);waited=True;assert os.waitstatus_to_exitcode(status)==0,(status,data[-1000:]);assert index==len(answers),(index,data[-1000:])
            finally:
                if not waited:
                    try:
                        if os.getpgid(pid)==pid:os.killpg(pid,signal.SIGKILL)
                    except ProcessLookupError:pass
                    os.waitpid(pid,0)
                os.close(fd)
            commands.append({'argv':list(map(str,args)),'exit':0,'geometry':[24,56],'keys':[k.decode() for _,k in answers]})
            text=re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]','',data.decode());return '\n'.join(line.rstrip() for line in text.splitlines()).rstrip()+'\n'
        down=b'\x1b[B';back=b'\x1b[D';enter=b'\r'
        args=[entry,'model','light','--root',registry,'--width','56','--plain']
        captures['save-back']=terminal(args,[('FIRST USE',enter),('CONFIRM MRH PROFILE',enter),('Light MODEL',down+enter),
            ('REASONING EFFORT',back),('Light MODEL',enter),('REASONING EFFORT',enter),('SAVE POLICY?',back),
            ('REASONING EFFORT',enter),('SAVE POLICY?',enter)])
        binding=json.loads((registry/'registry.json').read_text())['bindings'][0];path=Path(binding['settings_path']);value=json.loads(path.read_text())
        assert binding['tool']=='gemini' and binding['catalog']['assurance']=='tool-advertised'
        assert value['policy']['tiers']['Light']=={'model':'gemini-3.1-pro-preview-customtools'} and value['revision']==1
        assert not value['enabled'] and not value['task_export_permitted'] and value['allowed_workspaces']==[]
        assert 'inherit' in captures['save-back'] and 'Unsupported' not in captures['save-back']
        stats=json.loads(run([entry,'stats','--settings',path,'--json']));assert stats['proposals']==0 and stats['jev_attempts']==0
        history={n:(path.parent/n).read_bytes() if (path.parent/n).exists() else None for n in ('events.sqlite3','events.sqlite3.key','events.sqlite3.lock','events.sqlite3-wal','events.sqlite3-shm')}
        before=path.read_bytes()
        captures['cancel']=terminal(args,[('Light MODEL',down+enter),('REASONING EFFORT',enter),('SAVE POLICY?',down*2+enter)])
        assert path.read_bytes()==before
        assert history=={n:(path.parent/n).read_bytes() if (path.parent/n).exists() else None for n in history}
        # Only this owned CLI copy changes. The real vendor installation is
        # untouched; its stable stub remains equal while payload pin changes.
        stub=(package/'bundle/gemini.js').read_bytes();chunk=package/'bundle/chunk-AM7DMDAW.js';chunk.write_bytes(chunk.read_bytes()+b'\n// owned payload-update canary\n')
        captures['failure-cancel']=terminal(args,[('LIST UNAVAILABLE',down*2+enter)])
        assert path.read_bytes()==before and (package/'bundle/gemini.js').read_bytes()==stub
        assert 'tool_changed_rebind_required' in captures['failure-cancel'] and 'DISPLAY ONLY' in captures['failure-cancel']
        result={'bundle':str(bundle),'module_identity':identity,'commands':commands,'saved':value,'binding':binding,'stats':stats,
                'cancel_policy_and_history_bytes_unchanged':True,'failed_refresh_policy_unchanged':True,'stub_unchanged_payload_update_detected':True,
                'actual_model_id_kept':value['policy']['tiers']['Light']['model'],'reasoning_effort':'inherit only',
                'input_keys':'directions and Enter only','real_credential_or_provider':False,'formal_hook':False,
                'node_is_existing_cli_prerequisite':True,'owned_pids':pids,'owned_root':str(root),'captures':captures}
    result.update(owned_root_absent=not root.exists(),seconds=round(time.monotonic()-started,3));assert result['owned_root_absent'];return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--bundle',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--gemini-package',type=Path,required=True)
    parser.add_argument('--node',type=Path,required=True)
    args=parser.parse_args()
    result=inspect(args.bundle.resolve(),args.gemini_package,args.node)
    for name,text in result.pop('captures').items():(args.output.parent/('e16-'+name+'.txt')).write_text(text)
    args.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({'bundled_gemini':True,'keyboard_save_back_cancel':True,'payload_update_failure':True,'cleanup':result['owned_root_absent'],'seconds':result['seconds']}))
