#!/usr/bin/env python3
"""E9R offline installed CLI and actual PTY; no source import in child processes."""
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
import zipfile

PROJECT=Path(__file__).resolve().parents[3]


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output-prefix',type=Path,required=True)
    prefix=parser.parse_args().output_prefix.resolve();prefix.parent.mkdir(parents=True,exist_ok=True)
    started=time.monotonic();commands=[]
    hashes={str(p.relative_to(PROJECT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((PROJECT/'src/mrh').rglob('*.py'))}
    base=subprocess.check_output(['git','rev-parse','HEAD'],cwd=PROJECT,text=True).strip()
    with tempfile.TemporaryDirectory(prefix='mrh-e9r-installed-',dir='/private/tmp') as temporary:
        root=Path(temporary).resolve();work=root/'work';work.mkdir();(root/'home').mkdir();(root/'tmp').mkdir()
        env={'PATH':os.defpath,'HOME':str(root/'home'),'TMPDIR':str(root/'tmp'),'LANG':'en_US.UTF-8',
             'TERM':'xterm-256color','PYTHONDONTWRITEBYTECODE':'1'}
        assert 'PYTHONPATH' not in env and not work.is_relative_to(PROJECT)
        def run(argv,text=''):
            before=time.monotonic()
            r=subprocess.run([str(v) for v in argv],input=text,text=True,capture_output=True,cwd=work,env=env,timeout=30)
            commands.append({'argv':[str(v) for v in argv],'exit_code':r.returncode,'elapsed_seconds':round(time.monotonic()-before,3)})
            assert r.returncode==0,(r.returncode,r.stderr[:1000])
            return r.stdout
        run([sys.executable,'-m','venv',root/'venv'])
        python=root/'venv/bin/python';exe=root/'venv/bin/mrh'
        # Reuse the actual stdlib PEP517 backend, preserving a wheel identity.
        build="import sys;sys.path.insert(0,sys.argv[1]);import mrh_build;print(mrh_build.build_wheel(sys.argv[2]))"
        wheel=root/'wheel'/run([sys.executable,'-c',build,PROJECT,root/'wheel']).strip()
        wheel_hash=hashlib.sha256(wheel.read_bytes()).hexdigest()
        with zipfile.ZipFile(wheel) as archive:
            for name,digest in hashes.items():assert hashlib.sha256(archive.read(name.removeprefix('src/'))).hexdigest()==digest
            assert 'mrh/presentation/settings_editor.py' in archive.namelist()
        run([python,'-m','pip','--no-cache-dir','install','--no-index','--no-deps','--no-build-isolation',wheel])
        identity=json.loads(run([python,'-I','-c',
            "import json,os,mrh,mrh.presentation.settings_editor,importlib.metadata;print(json.dumps({'module':mrh.__file__,'editor':mrh.presentation.settings_editor.__file__,'version':importlib.metadata.version('model-routing-harness'),'cwd':os.getcwd()}))"]))
        assert Path(identity['editor']).is_relative_to(root/'venv') and identity['cwd']==str(work)
        for name,digest in hashes.items():
            installed=Path(identity['module']).parent/name.removeprefix('src/mrh/')
            assert hashlib.sha256(installed.read_bytes()).hexdigest()==digest
        def terminal(argv,answers=(),width=120):
            pid,fd=pty.fork()
            if pid==0:
                os.chdir(work);os.execve(str(exe),[str(exe),*map(str,argv)],env)
            fcntl.ioctl(fd,termios.TIOCSWINSZ,struct.pack('HHHH',60,width,0,0))
            data=bytearray();consumed=0;next_answer=0;deadline=time.monotonic()+15;waited=False
            try:
                while True:
                    if time.monotonic()>deadline:os.write(fd,b'\x03');raise TimeoutError('owned installed CLI PTY deadline')
                    ready,_,_=select.select([fd],[],[],.2)
                    if not ready:continue
                    try:chunk=os.read(fd,65536)
                    except OSError as exc:
                        if exc.errno==errno.EIO:break
                        raise
                    if not chunk:break
                    data.extend(chunk);prompt=data.find(b'  > ',consumed)
                    if prompt>=0:
                        consumed=prompt+4
                        if next_answer<len(answers):
                            os.write(fd,(answers[next_answer]+'\n').encode());next_answer+=1
                _,status=os.waitpid(pid,0);waited=True
                assert os.waitstatus_to_exitcode(status)==0,status
            finally:
                os.close(fd)
                if not waited:os.waitpid(pid,0)
            text=data.decode().replace('\r\n','\n')
            commands.append({'argv':[str(exe),*map(str,argv)],'exit_code':0,'pty_width':width})
            return text
        path=root/'state/settings.json'
        run([exe,'settings','init','--path',path])
        captures={}
        captures['editor-120']=terminal(['settings','edit','--path',path],
            ['light-choice','inherit','small-choice','low','mid-choice','high','Fixed','fixed-choice','inherit','save'])
        saved=json.loads(run([exe,'settings','show','--path',path]))['settings']
        assert saved['revision']==1 and not saved['enabled'] and not saved['task_export_permitted']
        assert saved['policy']['fixed']=={'model':'fixed-choice'}
        assert saved['policy']['tiers']=={'Light':{'model':'light-choice'},'Small':{'model':'small-choice','effort':'low'},'Mid':{'model':'mid-choice','effort':'high'}}
        stable=path.read_bytes()
        captures['view-120']=terminal(['settings','view','--path',path])
        captures['status-120']=terminal(['status','--settings',path])
        captures['status-56']=terminal(['status','--settings',path],width=56)
        for name in ('view-120','status-120'):
            assert 'REQUESTED MODEL' in captures[name] and '\x1b[38;2;173;178;250m\x1b[1m' in captures[name]
        assert 'Top / Fixed' in captures['status-56'] and 'Effort: inherit' in captures['status-56']
        stats=json.loads(run([exe,'stats','--settings',path,'--json']))
        assert stats['proposals']==0 and stats['jev_attempts']==0 and stats['actual_models']=={}
        assert json.loads(run([exe,'stats','--settings',path,'--json']))==stats and path.read_bytes()==stable
        assert 'configuration' not in stats
        # The inactive Fixed target remains stored, but Main never displays it.
        main_editor=terminal(['settings','edit','--path',path],['','','','','','','Main','save'])
        main_value=json.loads(run([exe,'settings','show','--path',path]))['settings']
        assert main_value['policy']['top_mode']=='Main' and main_value['policy']['fixed']==saved['policy']['fixed']
        assert not main_value['enabled'] and not main_value['task_export_permitted']
        captures['main-view-120']=terminal(['settings','view','--path',path])
        assert 'fixed-choice' not in captures['main-view-120'] and 'Current main agent' in captures['main-view-120']
        for name,text in captures.items():
            Path(str(prefix)+'-'+name+'.ansi').write_text(text)
            plain=re.sub(r'\x1b\[[0-9;]*m','',text)
            Path(str(prefix)+'-'+name+'.txt').write_text('\n'.join(line.rstrip() for line in plain.splitlines()).rstrip()+'\n')
        result={'kind':'offline installed mrh executable, outside checkout/PYTHONPATH, real POSIX PTY','git_base_before_source_fix_commit':base,
                'source_sha256':hashes,'wheel_name':wheel.name,'wheel_sha256':wheel_hash,'installed_identity':identity,
                'all_installed_source_bytes_equal_wheel_and_candidate':True,'settings_editor_packaged':True,'commands':commands,
                'saved_fixed_settings':saved,'saved_main_settings':main_value,'stats_json':stats,'save_readback':True,'enable_export_gates_preserved':True,
                'no_pythonpath':True,'no_source_cwd':True,'global_install':False,'real_provider_calls':0,'native_mac_terminal_window_observed':False,
                'owned_root':str(root),'pty_widths':[120,56]}
    assert not root.exists()
    for name,digest in hashes.items():assert hashlib.sha256((PROJECT/name).read_bytes()).hexdigest()==digest
    result.update(cleanup_removed=True,elapsed_seconds=round(time.monotonic()-started,3))
    Path(str(prefix)+'-package.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'installed_entry':'pass','package_module_present':True,'pty_widths':[120,56],'root_removed':True,'elapsed_seconds':result['elapsed_seconds']}))


if __name__=='__main__':main()
