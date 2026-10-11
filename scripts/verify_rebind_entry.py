#!/usr/bin/env python3
"""E16R's owned installed-CLI update and same-profile keyboard recovery."""
import argparse
import errno
import fcntl
import json
import os
from pathlib import Path
import pty
import re
import select
import shutil
import signal
import sqlite3
import struct
import subprocess
import tempfile
import termios
import time


def inspect(bundle, failure_output=None):
    started=time.monotonic();commands=[];pids=[];captures={};readbacks=[]
    with tempfile.TemporaryDirectory(prefix='mrh-e16r-entry-',dir='/private/tmp') as tmp:
        root=Path(tmp).resolve();home=root/'home';home.mkdir();work=root/'work';work.mkdir();tools=root/'bin';tools.mkdir()
        prefix=home/'.nvm/versions/node/e16r-cli';package=prefix/'lib/node_modules/@google/gemini-cli';package.parent.mkdir(parents=True)
        original=Path('/Users/shawn/.nvm/versions/node/v20.19.4/lib/node_modules/@google/gemini-cli')
        shutil.copytree(original,package,symlinks=True);(prefix/'bin').mkdir()
        shutil.copy2('/Users/shawn/.nvm/versions/node/v20.19.4/bin/node',prefix/'bin/node')
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

        identity=json.loads(run([python,'-I','-B','-c',
            "import sys,json;sys.path.insert(0,sys.argv[1]);import mrh.bindings,mrh.model_selector;print(json.dumps({'python':sys.executable,'modules':[mrh.bindings.__file__,mrh.model_selector.__file__],'path':sys.path}))",bundle/'app/mrh.pyz']))
        assert Path(identity['python']).is_relative_to(bundle) and all(Path(p).is_relative_to(bundle) for p in identity['path'])
        vendor_script="import sys,json;sys.path.insert(0,sys.argv[1]);from mrh.gemini_catalog import installation;print(json.dumps({'sha256':installation(sys.argv[2])['sha256']}))"
        vendor_identity=json.loads(run([python,'-I','-B','-c',vendor_script,bundle/'app/mrh.pyz',original/'bundle/gemini.js']))

        def terminal(args,answers):
            pid,fd=pty.fork()
            if pid==0:os.chdir(work);os.execve(str(args[0]),list(map(str,args)),env)
            pids.append(pid);data=bytearray();cursor=0;index=0;deadline=time.monotonic()+60;waited=False
            try:
                fcntl.ioctl(fd,termios.TIOCSWINSZ,struct.pack('HHHH',24,56,0,0))
                while True:
                    if time.monotonic()>deadline:raise TimeoutError('rebind_keyboard_deadline')
                    if not select.select([fd],[],[],.2)[0]:continue
                    try:chunk=os.read(fd,65536)
                    except OSError as e:
                        if e.errno==errno.EIO:break
                        raise
                    if not chunk:break
                    data.extend(chunk)
                    if (index<len(answers) and answers[index][0]=='Light MODEL'
                            and b'LIST UNAVAILABLE' in data[cursor:]):
                        raise RuntimeError('unexpected_unavailable_before_model')
                    if index<len(answers):
                        heading,keys,*callback=answers[index];pos=data.find(heading.encode(),cursor)
                        if pos>=0:
                            cursor=pos+len(heading)
                            if callback:callback[0]()
                            os.write(fd,keys);index+=1
                _,status=os.waitpid(pid,0);waited=True
                assert os.waitstatus_to_exitcode(status)==0,(status,data[-1000:]);assert index==len(answers),(index,data[-1000:])
            finally:
                if not waited:
                    if failure_output is not None:
                        failure_output.write_text(json.dumps({'stage':index,'waiting_for':answers[index][0] if index<len(answers) else None,
                            'owned_root':str(root),'owned_pid':pid,'argv':list(map(str,args)),
                            'stdout':data.decode(errors='replace')},indent=2)+'\n')
                    try:
                        if os.getpgid(pid)==pid:os.killpg(pid,signal.SIGKILL)
                    except ProcessLookupError:pass
                    os.waitpid(pid,0)
                os.close(fd)
            commands.append({'argv':list(map(str,args)),'exit':0,'geometry':[24,56],'keys':[a[1].decode() for a in answers]})
            text=re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]','',data.decode())
            return '\n'.join(line.rstrip() for line in text.splitlines()).rstrip()+'\n'

        def binding():return json.loads((registry/'registry.json').read_text())['bindings'][0]
        def profile_bytes():return {p.name:p.read_bytes() for p in path.parent.iterdir() if p.is_file()}
        down=b'\x1b[B';enter=b'\r'
        args=[entry,'model','light','--root',registry,'--width','56','--plain']
        captures['initial-save']=terminal(args,[('FIRST USE',enter),('CONFIRM MRH PROFILE',enter),
            ('Light MODEL',down+enter),('REASONING EFFORT',enter),('SAVE POLICY?',enter)])
        initial_binding=binding();path=Path(initial_binding['settings_path']);initial_policy=json.loads(path.read_text())
        assert initial_policy['policy']['tiers']['Light']=={'model':'gemini-3.1-pro-preview-customtools'}
        assert initial_policy['revision']==1 and not initial_policy['enabled'] and not initial_policy['task_export_permitted']
        seed="import sys,json;sys.path.insert(0,sys.argv[1]);from mrh.store import Store;from mrh.types import Proposal,Decision;s=Store(sys.argv[2]);p=Proposal('codex','simulation','e16r','owned','stored-stop',{},True);d=Decision('operator_update_required','unsupported_model','Light',.9,{},True,target_model='owned-stopped-target');s.claim(p);s.complete(p.identity,d);print(json.dumps({'synthetic_stop_seeded':True}))"
        seed_result=json.loads(run([python,'-I','-B','-c',seed,bundle/'app/mrh.pyz',path.parent/'events.sqlite3']))
        before=profile_bytes();stub=(package/'bundle/gemini.js').read_bytes();payload=package/'bundle/chunk-AM7DMDAW.js'
        payload.write_bytes(payload.read_bytes()+b'\n// owned E16R compatible update one\n')
        captures['cancel-confirm']=terminal(args,[('LIST UNAVAILABLE',down*2+enter),('INSPECT UPDATED CLI',enter),
                                                ('CONFIRM CLI UPDATE',down+enter)])
        cancelled_binding=binding()
        assert cancelled_binding['executable_sha256']==initial_binding['executable_sha256']
        assert cancelled_binding['catalog']==initial_binding['catalog'] and profile_bytes()==before
        captures['confirm-cancel']=terminal(args,[('LIST UNAVAILABLE',down*2+enter),('INSPECT UPDATED CLI',enter),
            ('CONFIRM CLI UPDATE',enter),('Light MODEL',down*5+enter)])
        accepted_binding=binding();assert accepted_binding['executable_sha256']!=initial_binding['executable_sha256']
        assert accepted_binding['catalog']['scope']==accepted_binding['executable_sha256'] and profile_bytes()==before
        assert accepted_binding['refresh_error'] is None
        readbacks.append({'stage':'accepted metadata then cancelled model edits','binding':accepted_binding,
                          'settings':json.loads(path.read_text()),'profile_bytes_unchanged':True})

        def update_during_review():payload.write_bytes(payload.read_bytes()+b'\n// owned E16R update during unsaved review\n')
        def readback_draft():
            current=binding();assert current['executable_sha256']!=accepted_binding['executable_sha256']
            assert current['catalog']['scope']==current['executable_sha256'] and profile_bytes()==before
            readbacks.append({'stage':'accepted metadata with unsaved draft','binding':current,
                              'settings':json.loads(path.read_text()),'profile_bytes_unchanged':True})
        captures['draft-recovery-cancel']=terminal(args,[('Light MODEL',down+enter),('REASONING EFFORT',enter),
            ('SAVE POLICY?',enter,update_during_review),('LIST UNAVAILABLE',down*2+enter),('INSPECT UPDATED CLI',enter),
            ('CONFIRM CLI UPDATE',enter),('Light MODEL',enter,readback_draft),('REASONING EFFORT',enter),
            ('SAVE POLICY?',down*2+enter)])
        assert profile_bytes()==before
        assert 'Confirmed CLI update' in captures['draft-recovery-cancel']
        assert 'gemini-3-flash-preview)[current]' in re.sub(r'\s+','',captures['draft-recovery-cancel'])
        captures['separate-save']=terminal(args,[('Light MODEL',down+enter),('REASONING EFFORT',enter),('SAVE POLICY?',enter)])
        saved=json.loads(path.read_text());assert saved['revision']==2
        assert saved['policy']['tiers']['Light']=={'model':'gemini-3-flash-preview'}
        history={k:v for k,v in before.items() if k.startswith('events.')}
        assert history=={k:v for k,v in profile_bytes().items() if k.startswith('events.')}
        final_binding=binding();assert all(b['binding']['id']==initial_binding['id'] and b['binding']['settings_path']==str(path) for b in readbacks)
        assert final_binding['id']==initial_binding['id'] and len(json.loads((registry/'registry.json').read_text())['bindings'])==1
        before_unsupported=profile_bytes();meta_path=package/'package.json';meta=json.loads(meta_path.read_text());meta['version']='0.64.0';meta_path.write_text(json.dumps(meta))
        captures['unsupported-cancel']=terminal(args,[('LIST UNAVAILABLE',down*2+enter),('INSPECT UPDATED CLI',enter),
                                                    ('LIST UNAVAILABLE',down*3+enter)])
        unsupported_binding=binding();assert unsupported_binding['executable_sha256']==final_binding['executable_sha256']
        assert unsupported_binding['catalog']==final_binding['catalog'] and profile_bytes()==before_unsupported
        assert 'gemini_catalog_version_unsupported' in captures['unsupported-cancel']
        assert (package/'bundle/gemini.js').read_bytes()==stub
        with sqlite3.connect(path.parent/'events.sqlite3') as db:
            stops=db.execute('SELECT decision FROM operator_stops').fetchall()
            assert len(stops)==1 and json.loads(stops[0][0])['target_model']=='owned-stopped-target'
        assert vendor_identity==json.loads(run([python,'-I','-B','-c',vendor_script,bundle/'app/mrh.pyz',original/'bundle/gemini.js']))
        result={'bundle':str(bundle),'module_identity':identity,'commands':commands,'initial_binding':initial_binding,
                'cancelled_binding':cancelled_binding,'readbacks':readbacks,'final_binding':final_binding,
                'unsupported_binding':unsupported_binding,'saved':saved,'seed':seed_result,'stored_stop_retained':True,
                'same_binding_profile_and_history':True,'cancelled_metadata_confirmation_unchanged':True,
                'accepted_metadata_cancel_policy_unchanged':True,'draft_retained_after_update':True,
                'separate_save_revision':2,'unsupported_version_not_adopted':True,'stub_unchanged':True,
                'real_vendor_identity':vendor_identity,'real_vendor_unchanged':True,
                'real_credential_or_provider':False,'input_keys':'directions and Enter only','owned_pids':pids,
                'owned_root':str(root),'captures':captures}
    result.update(owned_root_absent=not root.exists(),seconds=round(time.monotonic()-started,3))
    assert result['owned_root_absent'];return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--bundle',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    result=inspect(args.bundle.resolve(),args.output.with_suffix('.failure.json'))
    for name,text in result.pop('captures').items():(args.output.parent/('e16r-'+name+'.txt')).write_text(text)
    args.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'bundled_rebind':True,'same_profile':True,'keyboard_only':True,'cancel_save_unsupported':True,
                      'stored_stop_retained':True,'cleanup':result['owned_root_absent'],'seconds':result['seconds']}))
