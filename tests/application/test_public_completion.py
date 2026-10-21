"""New completion behavior only; fake homes, profiles, and explicitly supplied backup root."""
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from mrh.application import skills
from mrh.presentation import cli


class SkillCompletionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.home = self.root/'home';self.home.mkdir()
        self.env = patch.dict(os.environ, HOME=str(self.home), CLAUDE_CONFIG_DIR=str(self.root/'claude'), MRH_PROJECT_ROOT=str(self.root))
        self.env.start();self.addCleanup(self.env.stop)

    def test_config_directory_and_cli_aliases_do_not_touch_the_other_skill_tree(self):
        installed=skills.run('install','claude')
        self.assertEqual(Path(installed['path']),self.root/'claude/skills/mrh-delegation-claude')
        self.assertFalse((self.home/'.claude').exists())
        base=self.root/'custom';out=io.StringIO()
        self.assertEqual(cli.main(['skill','install','--host','codex','--skills-dir',str(base),'--root',str(base)],stdout=out),0)
        self.assertTrue(json.loads(out.getvalue())['changed'])
        error=io.StringIO()
        self.assertEqual(cli.main(['skill','remove','--host','codex','--skills-dir',str(base),'--root',str(self.root/'other')],stderr=error),2)
        self.assertIn('不同位置',error.getvalue());self.assertEqual(skills.status('codex',base)['status'],'latest')

    def test_force_never_accepts_foreign_extra_or_linked_content(self):
        base=self.root/'skills';target=base/'mrh-delegation-codex'
        target.mkdir(parents=True);(target/'SKILL.md').write_text('foreign')
        with self.assertRaises(ValueError):skills.run('install','codex',base,force=True,backup_dir=self.root/'irrelevant')
        self.assertEqual((target/'SKILL.md').read_text(),'foreign')
        (target/'SKILL.md').unlink();target.rmdir();skills.run('install','codex',base)
        (target/'extra.txt').write_text('preserve')
        with self.assertRaises(ValueError):skills.run('remove','codex',base,force=True)
        self.assertTrue((target/'extra.txt').exists())
        (target/'extra.txt').unlink();original=(target/'SKILL.md').read_bytes();(target/'SKILL.md').unlink()
        external=self.root/'external';external.write_bytes(original)
        try:(target/'SKILL.md').symlink_to(external)
        except OSError:self.skipTest('symlinks unavailable')
        with self.assertRaises(ValueError):skills.run('remove','codex',base,force=True)
        self.assertEqual(external.read_bytes(),original)

    @unittest.skipUnless(os.environ.get('MRH_TEST_BACKUP_ROOT'), 'explicit external test backup root required')
    def test_modified_owned_skill_requires_force_and_recoverable_external_backup(self):
        with tempfile.TemporaryDirectory(dir=os.environ['MRH_TEST_BACKUP_ROOT']) as destination:
            for host in ('codex','claude'):
                base=self.root/host;first=skills.run('install',host,base);target=Path(first['path'])
                (target/'SKILL.md').write_bytes(b'local custom brief');marker=(target/skills.MARKER).read_bytes()
                original_mode=(target/'SKILL.md').stat().st_mode&0o777
                for kwargs in ({},{'force':True},{'force':True,'backup_dir':self.root/'wrong-backup'}):
                    with self.assertRaises(ValueError):skills.run('install',host,base,**kwargs)
                result=skills.run('install',host,base,force=True,backup_dir=Path(destination))
                saved=Path(result['backup']);self.assertEqual((saved/'SKILL.md').read_bytes(),b'local custom brief')
                self.assertEqual((saved/skills.MARKER).read_bytes(),marker)
                self.assertEqual(json.loads((saved/'backup-manifest.json').read_text())['files']['SKILL.md']['mode'],original_mode)
                self.assertEqual(result['status'],'latest')
                (target/'SKILL.md').write_bytes(b'second local change')
                result=skills.run('remove',host,base,force=True,backup_dir=Path(destination))
                self.assertEqual((Path(result['backup'])/'SKILL.md').read_bytes(),b'second local change')
                self.assertFalse(target.exists())


@unittest.skipIf(os.name=='nt','Mac user-shell adapter')
class MacPathCompletionTests(unittest.TestCase):
    def setUp(self):
        from mrh.adapters.platforms.macos_path import UserPath,PathError
        self.manager_type,self.error=UserPath,PathError
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.home=self.root/'home';self.home.mkdir()
        self.bin=self.root/'bin space';self.bin.mkdir()
        (self.bin/'mrh').write_text('#!/bin/sh\nprintf "fixture\\n"\n');(self.bin/'mrh').chmod(0o700)
        self.environment={'HOME':str(self.home),'PATH':'/usr/bin:/bin','TERM':'dumb'}

    def manager(self,shell='zsh',environment=None):
        return self.manager_type(self.bin,user_home=self.home,environ=environment or self.environment,login_shell='/bin/'+shell)

    def test_real_new_login_and_interactive_shells_use_fake_profiles_and_repeat_is_noop(self):
        for shell in ('zsh','bash'):
            with self.subTest(shell=shell):
                env=dict(self.environment)
                if shell=='zsh':
                    directory=self.home/'zdot';directory.mkdir();env['ZDOTDIR']=str(directory)
                    files=[directory/'.zprofile',directory/'.zshrc']
                else:files=[self.home/'.bash_login',self.home/'.bashrc']
                for file in files:file.write_text('export PATH="/usr/bin:/bin"\n# keep operator content\n');file.chmod(0o640)
                manager=self.manager(shell,env);manager.apply(manager.plan())
                before=[(f.read_bytes(),f.stat().st_mtime_ns) for f in files]
                self.assertEqual(manager.apply(manager.plan())['action'],'unchanged')
                self.assertEqual(before,[(f.read_bytes(),f.stat().st_mtime_ns) for f in files])
                self.assertTrue(all(f.stat().st_mode&0o777==0o640 for f in files))
                outside=self.root/'outside';outside.mkdir(exist_ok=True)
                for login in (False,True):
                    options=['-d'] if shell=='zsh' else []
                    options+=['-l'] if login else ['-i']
                    command='command -v mrh; mrh; printf "%s\\n" "$PATH"'
                    result=subprocess.run(['/bin/'+shell,*options,'-c',command],env=env,cwd=outside,text=True,capture_output=True,timeout=5)
                    self.assertEqual(result.returncode,0,result.stderr)
                    lines=result.stdout.splitlines();self.assertEqual(lines[:2],[str(self.bin/'mrh'),'fixture'])
                    self.assertEqual(lines[2].split(':').count(str(self.bin)),1)
                self.assertFalse(manager.report()['existing_processes_refreshed'])

    def test_conflicts_modified_blocks_unknown_shell_and_links_preserve_originals(self):
        other=self.root/'other';other.mkdir();(other/'mrh').write_text('#!/bin/sh\n');(other/'mrh').chmod(0o700)
        with self.assertRaises(self.error):self.manager(environment={**self.environment,'PATH':str(other)}).plan()
        with self.assertRaises(self.error):self.manager('unknown-shell').plan()
        manager=self.manager();manager.apply(manager.plan());profile=self.home/'.zshrc'
        profile.write_bytes(profile.read_bytes().replace(b'export PATH',b'export CHANGED'))
        before=profile.read_bytes()
        with self.assertRaises(self.error):manager.plan()
        self.assertEqual(profile.read_bytes(),before)
        profile.unlink();external=self.root/'keep';external.write_bytes(b'original')
        profile.symlink_to(external)
        with self.assertRaises(self.error):manager.plan()
        self.assertEqual(external.read_bytes(),b'original')

    def test_inherited_path_without_profiles_is_not_persistent_readiness(self):
        for shell in ('zsh','bash'):
            with self.subTest(shell=shell):
                manager=self.manager(shell,{**self.environment,'PATH':str(self.bin)+':/usr/bin:/bin'})
                fresh=dict(self.environment)
                outside=self.root/'independent';outside.mkdir(exist_ok=True)
                def resolve(login):
                    options=['-d'] if shell=='zsh' else []
                    options+=['-l'] if login else ['-i']
                    return subprocess.run(['/bin/'+shell,*options,'-c','command -v mrh'],
                            env=fresh,cwd=outside,text=True,capture_output=True,timeout=5)
                before=[resolve(login) for login in (False,True)]
                self.assertTrue(all(result.returncode!=0 for result in before),[r.stdout for r in before])
                report=manager.report()
                self.assertTrue(report['current_process_ready'])
                self.assertFalse(report['future_terminal_ready'],
                        'Independent login/interactive shells cannot resolve mrh, despite inherited parent PATH')
                manager.apply(manager.plan())
                self.assertTrue(manager.report()['future_terminal_ready'])
                for login in (False,True):
                    result=resolve(login)
                    self.assertEqual(result.returncode,0,result.stderr)
                    self.assertEqual(result.stdout.strip(),str(self.bin/'mrh'))
                profiles=[p for p in self.home.iterdir() if p.is_file()]
                snapshot={p:(p.read_bytes(),p.stat().st_mode,p.stat().st_mtime_ns) for p in profiles}
                self.assertEqual(manager.apply(manager.plan())['action'],'unchanged')
                self.assertEqual(snapshot,{p:(p.read_bytes(),p.stat().st_mode,p.stat().st_mtime_ns) for p in profiles})

    def test_concurrent_edit_is_preserved(self):
        manager=self.manager();plan=manager.plan();(self.home/'.zshrc').write_text('operator change\n')
        with self.assertRaises(self.error):manager.apply(plan)
        self.assertFalse((self.home/'.zprofile').exists());self.assertEqual((self.home/'.zshrc').read_text(),'operator change\n')
