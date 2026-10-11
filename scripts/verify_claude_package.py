#!/usr/bin/env python3
"""E13 isolated installed entry + real PTY Claude selection; SDK never needed.

This is developer wheel evidence, not R3 standalone-runtime release acceptance.
"""
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pty
import re
import select
import signal
import struct
import subprocess
import sys
import tempfile
import termios
import time
import zipfile

PROJECT=Path(__file__).resolve().parents[1]


def main():
    started=time.monotonic();commands=[];captures={}
    hashes={str(p.relative_to(PROJECT)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((PROJECT/'src/mrh').glob('*.py'))}
    with tempfile.TemporaryDirectory(prefix='mrh-e13-installed-',dir='/private/tmp') as tmp:
        root=Path(tmp).resolve();work=root/'work';work.mkdir()
        for name in ['home','tmp']:(root/name).mkdir()
        env={'PATH':'/opt/homebrew/bin:/usr/bin:/bin','HOME':str(root/'home'),
             'TMPDIR':str(root/'tmp'),'LANG':'en_US.UTF-8','TERM':'xterm-256color',
             'PYTHONDONTWRITEBYTECODE':'1','NO_COLOR':'1'}
        def run(argv,expected=0):
            before=time.monotonic()
            result=subprocess.run(list(map(str,argv)),text=True,capture_output=True,cwd=work,env=env,timeout=30)
            commands.append({'argv':list(map(str,argv)),'exit':result.returncode,
                             'seconds':round(time.monotonic()-before,4)})
            assert result.returncode==expected,(result.returncode,result.stderr[:500])
            return result.stdout
        run([sys.executable,'-m','venv',root/'venv'])
        python=root/'venv/bin/python';entry=root/'venv/bin/mrh'
        build="import sys;sys.path.insert(0,sys.argv[1]);import mrh_build;print(mrh_build.build_wheel(sys.argv[2]))"
        wheel=root/'wheel'/run([sys.executable,'-c',build,PROJECT,root/'wheel']).strip()
        with zipfile.ZipFile(wheel) as archive:
            for name,digest in hashes.items():
                assert hashlib.sha256(archive.read(name.removeprefix('src/'))).hexdigest()==digest
            metadata=archive.read('model_routing_harness-0.3.0.dist-info/METADATA').decode()
            assert 'Requires-Dist:' not in metadata
            assert not any(name.endswith(('.js','.mjs','.tgz')) for name in archive.namelist())
        run([python,'-m','pip','--isolated','--no-cache-dir','install','--no-index','--no-deps','--no-build-isolation',wheel])
        identity=json.loads(run([python,'-I','-c',
            "import json,mrh,mrh.claude_catalog,os;print(json.dumps({'module':mrh.__file__,'claude':mrh.claude_catalog.__file__,'cwd':os.getcwd()}))"]))
        assert Path(identity['claude']).is_relative_to(root/'venv') and identity['cwd']==str(work)
        for name,digest in hashes.items():
            installed=Path(identity['module']).parent/name.removeprefix('src/mrh/')
            assert hashlib.sha256(installed.read_bytes()).hexdigest()==digest
        candidates=json.loads(run([python,'-I','-c',
            "import json;from mrh.catalog import discover;print(json.dumps(discover()))"]))
        claude_index=next(i for i,c in enumerate(candidates) if c['tool']=='claude' and c['supported'])

        def terminal(argv,answers,width=56):
            pid,fd=pty.fork()
            if pid==0:
                os.chdir(work);os.execve(str(argv[0]),list(map(str,argv)),env)
            fcntl.ioctl(fd,termios.TIOCSWINSZ,struct.pack('HHHH',24,width,0,0))
            data=bytearray();consumed=0;index=0;deadline=time.monotonic()+30;waited=False
            try:
                while True:
                    if time.monotonic()>deadline:
                        os.kill(pid,signal.SIGKILL);raise TimeoutError('owned E13 PTY deadline')
                    if not select.select([fd],[],[],.2)[0]:continue
                    try:chunk=os.read(fd,65536)
                    except OSError as exc:
                        if exc.errno==errno.EIO:break
                        raise
                    if not chunk:break
                    data.extend(chunk)
                    if index<len(answers):
                        heading,keys=answers[index];position=data.find(heading.encode(),consumed)
                        if position>=0:
                            consumed=position+len(heading);os.write(fd,keys.encode());index+=1
                _,status=os.waitpid(pid,0);waited=True
                assert os.waitstatus_to_exitcode(status)==0,(status,data[-1000:])
                assert index==len(answers),(index,len(answers),data[-1000:])
            finally:
                os.close(fd)
                if not waited:
                    try:os.kill(pid,signal.SIGKILL)
                    except ProcessLookupError:pass
                    os.waitpid(pid,0)
            commands.append({'argv':list(map(str,argv)),'exit':0,'pty_rows':24,'pty_columns':width,
                             'keys':[keys for _,keys in answers]})
            return data.decode().replace('\r\n','\n')

        registry=root/'bindings';args=[entry,'model','light','--root',registry,'--width','56','--plain']
        down='\x1b[B';up='\x1b[A';back='\x1b[D'
        captures['save-back']=terminal(args,[('FIRST USE',down*claude_index+'\n'),
            ('CONFIRM MRH PROFILE','\n'),('Light MODEL',down+'\n'),('REASONING EFFORT',down+'\n'),
            ('SAVE POLICY?',back),('REASONING EFFORT',back),('Light MODEL',down+up+'\n'),
            ('REASONING EFFORT','\n'),('SAVE POLICY?','\n')])
        binding=json.loads((registry/'registry.json').read_text())['bindings'][0]
        path=Path(binding['settings_path']);first=json.loads(path.read_text());snapshot=binding['catalog']
        assert binding['tool']=='claude' and snapshot['assurance']=='tool-advertised'
        assert first['policy']['tiers']['Light']=={'model':'opus[1m]','effort':'low'}
        assert first['revision']==1 and not first['enabled'] and not first['task_export_permitted']
        assert first['allowed_workspaces']==[]
        # Exercise the real MRH event files, not a nonexistent history filename.
        initial_stats=json.loads(run([entry,'stats','--settings',path,'--json']))
        assert initial_stats['proposals']==0 and initial_stats['jev_attempts']==0
        event_files=('events.sqlite3','events.sqlite3.key','events.sqlite3.lock','events.sqlite3-wal','events.sqlite3-shm')
        def event_bytes():
            return {name:(path.parent/name).read_bytes() if (path.parent/name).exists() else None for name in event_files}
        before=path.read_bytes();history=event_bytes()
        assert history['events.sqlite3'] is not None
        captures['cancel']=terminal(args,[('Light MODEL',down+'\n'),('REASONING EFFORT',down+'\n'),
                                           ('SAVE POLICY?',down+down+'\n')])
        assert path.read_bytes()==before
        assert event_bytes()==history
        small=[entry,'model','small','--root',registry,'--width','56','--plain']
        captures['inherit']=terminal(small,[('Small MODEL',down*3+'\n'),('REASONING EFFORT','\n'),('SAVE POLICY?','\n')])
        final=json.loads(path.read_text());assert final['policy']['tiers']['Small']=={'model':'haiku'}
        assert not final['enabled'] and not final['task_export_permitted'] and final['allowed_workspaces']==[]
        before=path.read_bytes()
        fixture="""import sys,time
from mrh import cli
from mrh.bindings import Registry
from mrh.catalog import Catalog,CatalogError
class Provider:
 def __init__(self):self.calls=0
 def refresh(self,b):
  self.calls+=1
  if self.calls>1:raise CatalogError('claude_catalog_timeout')
  c=Catalog.from_dict(Registry(sys.argv[1]).read()['bindings'][0]['catalog'])
  return Catalog(**{**c.__dict__,'fetched_at':time.time(),'source':'synthetic:claude-save-refresh-failure','assurance':'synthetic'})
raise SystemExit(cli.main(['model','small','--root',sys.argv[1],'--width','56','--plain'],model_dependencies={'provider':Provider()}))
"""
        captures['save-failure-cancel']=terminal([python,'-I','-c',fixture,registry],[('Small MODEL','\n'),
            ('REASONING EFFORT','\n'),('SAVE POLICY?','\n'),('LIST UNAVAILABLE',down*2+'\n')])
        assert path.read_bytes()==before
        assert 'display only' in captures['save-failure-cancel']
        assert 'Nothing saved' in captures['save-failure-cancel']
        stats=json.loads(run([entry,'stats','--settings',path,'--json']))
        assert stats['proposals']==0 and stats['jev_attempts']==0
        evidence={'kind':'E13 SDK-free installed Python entry and actual Claude PTY',
                  'source_sha256':hashes,'wheel_sha256':hashlib.sha256(wheel.read_bytes()).hexdigest(),
                  'installed_identity':identity,'all_installed_bytes_match_source':True,
                  'wheel_runtime_dependencies':[],'contains_sdk_or_js_runtime_files':False,
                  'no_pythonpath':True,'outside_source_cwd':True,'discovered_tools':candidates,
                  'actual_claude_catalog':snapshot,'first_saved_profile':first,'final_profile':final,
                  'cancel_policy_and_history_unchanged':True,'save_failure_is_synthetic':True,
                  'cancel_existing_event_files':[name for name,data in history.items() if data is not None],
                  'failed_save_policy_unchanged':True,'commands':commands,'stats':stats,
                  'owned_root':str(root),'no_global_install':True,'account_confirmation':False,
                  'keyboard_inputs':'Only directional keys and Enter; no model/effort/path/confirmation text',
                  'r3_standalone_distribution_verified':False}
    evidence.update(cleanup_removed=not root.exists(),seconds=round(time.monotonic()-started,4))
    assert evidence['cleanup_removed']
    (PROJECT/'docs/evidence/e13-package.json').write_text(json.dumps(evidence,indent=2)+'\n')
    for name,capture in captures.items():
        text=re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]','',capture)
        text='\n'.join(line.rstrip() for line in text.splitlines()).rstrip()+'\n'
        (PROJECT/('docs/evidence/e13-'+name+'.txt')).write_text(text)
    print(json.dumps({'seconds':evidence['seconds'],'cleanup_removed':True,'wheel_sha256':evidence['wheel_sha256']}))


if __name__=='__main__':main()
