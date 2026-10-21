"""User PATH ownership and actual cmd lookup, without touching real registry."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

if os.name == 'nt':
    import winreg
    from mrh.adapters.platforms.windows_path import UserPath, PathValue, PathError


class Store:
    def __init__(self, user=None, machine=None):
        self.values = {'user': user or PathValue(), 'machine': machine or PathValue()}
        self.writes = 0

    def read(self, scope):return self.values[scope]

    def write(self, expected, replacement):
        if self.read('user') != expected: raise PathError('user_path_concurrent_change')
        self.values['user'] = replacement
        self.writes += 1


@unittest.skipUnless(os.name == 'nt', 'native Windows PATH and cmd')
class UserPathTests(unittest.TestCase):
    def setUp(self):
        runtime = Path(__file__).resolve().parents[2]/'runtime'
        runtime.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='path with spaces ', dir=runtime)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root/'private bin'
        self.bin.mkdir()
        (self.bin/'mrh.cmd').write_text('@echo off\r\necho {"status":"fixture"}\r\n', encoding='ascii')
        self.store = Store()
        self.notices = []
        self.env = {'PATH':'', 'PATHEXT':'.COM;.EXE;.BAT;.CMD', 'SystemRoot':os.environ['SystemRoot'],
                    'PROFILE_ROOT':str(self.root)}

    def manager(self):
        return UserPath(self.bin, store=self.store, environ=self.env, cwd=self.root,
                        notify=lambda:self.notices.append(True) or True)

    def test_add_preserves_other_entries_kind_and_order_and_repeat_is_noop(self):
        original = r'%PROFILE_ROOT%\one;;"C:\Folder With Spaces";C:\last;'
        self.store.values['user'] = PathValue(original, winreg.REG_EXPAND_SZ, True)
        machine = PathValue(r'C:\Windows\System32', winreg.REG_SZ, True)
        self.store.values['machine'] = machine
        manager = self.manager()
        self.assertFalse(manager.report()['user_path_registered'])
        self.assertEqual(self.store.writes, 0)
        manager.apply(manager.plan())
        value = self.store.read('user')
        self.assertEqual(value.value, original+';'+str(self.bin))
        self.assertEqual(value.kind, winreg.REG_EXPAND_SZ)
        self.assertEqual(self.store.read('machine'), machine)
        self.assertEqual(manager.apply(manager.plan())['action'], 'unchanged')
        self.assertEqual((self.store.writes, len(self.notices)), (1,1))
        self.assertTrue(manager.report()['future_terminal_ready'])
        self.assertFalse(manager.report()['current_process_ready'])
        self.assertEqual(manager.report()['terminal_refresh'], 'new_terminal_required')

    def test_only_mrh_duplicates_are_removed_with_variables_case_and_quotes(self):
        original = r'C:\before;"%PROFILE_ROOT%\private bin";C:\same;'+str(self.bin).upper()+r'\;C:\same'
        self.store.values['user'] = PathValue(original, winreg.REG_EXPAND_SZ, True)
        manager = self.manager()
        manager.apply(manager.plan())
        self.assertEqual(self.store.read('user').value, r'C:\before;"%PROFILE_ROOT%\private bin";C:\same;C:\same')
        self.assertEqual(manager.apply(manager.plan())['action'], 'unchanged')

    def test_conflicting_command_is_not_executed_and_no_path_is_written(self):
        other = self.root/'other';other.mkdir()
        (other/'mrh.cmd').write_text('@echo SHOULD_NOT_RUN', encoding='ascii')
        for scope in ('user','machine','process','cwd'):
            with self.subTest(scope=scope):
                self.store = Store()
                self.env['PATH'] = str(other) if scope=='process' else ''
                if scope in ('user','machine'):self.store.values[scope] = PathValue(str(other),winreg.REG_SZ,True)
                manager = self.manager()
                if scope=='cwd':manager.cwd = other
                with self.assertRaisesRegex(PathError,'mrh_command_conflict'):
                    manager.apply(manager.plan())
                self.assertEqual(self.store.writes,0)

    def test_registry_changes_after_planning_are_preserved(self):
        manager = self.manager();plan = manager.plan()
        changed = PathValue(r'C:\new-from-another-installer', winreg.REG_EXPAND_SZ, True)
        self.store.values['user'] = changed
        with self.assertRaisesRegex(PathError,'concurrent_change'):manager.apply(plan)
        self.assertEqual(self.store.read('user'),changed)
        self.assertEqual(self.store.writes,0)

    def test_powershell_script_collision_is_detected_without_pathext_ps1(self):
        other=self.root/'PowerShell scripts';other.mkdir()
        (other/'mrh.ps1').write_text('throw "never execute"',encoding='ascii')
        self.env['PATH']=str(other)
        with self.assertRaisesRegex(PathError,'mrh_command_conflict'):
            self.manager().apply(self.manager().plan())
        self.assertEqual(self.store.writes,0)

    def test_long_user_path_is_preserved_without_setx_truncation(self):
        original = ';'.join(r'C:\unused%03d'%n for n in range(300))
        self.assertGreater(len(original),2048)
        self.store.values['user'] = PathValue(original,winreg.REG_EXPAND_SZ,True)
        manager=self.manager();manager.apply(manager.plan())
        self.assertEqual(self.store.read('user').value,original+';'+str(self.bin))
        self.store.values['user'] = PathValue('C:\\unused;'*4000)
        with self.assertRaisesRegex(PathError,'too_long'):self.manager().plan()

    def test_path_entry_separators_and_expansions_are_not_registered(self):
        for name in ('semi;colon','%PROFILE_ROOT%','quote"'):
            with self.subTest(name=name):
                with self.assertRaisesRegex(PathError,'entry_unsupported'):
                    UserPath(self.root/name,store=self.store,environ=self.env,cwd=self.root)
        self.assertEqual(self.store.writes,0)

    def test_reg_sz_literal_variables_are_not_reinterpreted_and_bad_values_stop(self):
        self.store.values['user'] = PathValue(r'%PROFILE_ROOT%\private bin',winreg.REG_SZ,True)
        manager = self.manager();manager.apply(manager.plan())
        self.assertEqual(self.store.read('user').value,r'%PROFILE_ROOT%\private bin;'+str(self.bin))
        self.assertEqual(self.store.read('user').kind,winreg.REG_SZ)
        for value in ('%PATH%;C:\\one','C:\\one\nC:\\two'):
            self.store.values['user'] = PathValue(value)
            with self.assertRaisesRegex(PathError,'value_unsupported'):self.manager().plan()

    def test_missing_cmd_extension_refuses_without_silent_pathext_change(self):
        self.env['PATHEXT'] = '.EXE'
        with self.assertRaisesRegex(PathError,'pathext_missing_cmd'):
            self.manager().apply(self.manager().plan())
        self.assertEqual(self.store.writes,0)

    def test_new_cmd_resolves_space_path_outside_bin_and_old_environment_stays_old(self):
        manager = self.manager();manager.apply(manager.plan())
        cmd = str(Path(os.environ['SystemRoot'])/'System32/cmd.exe')
        result = subprocess.run([cmd,'/d','/c','mrh status --json'],cwd=self.root,
                                env=manager.future_environment(),capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout),{'status':'fixture'})
        old = subprocess.run([cmd,'/d','/c','mrh status --json'],cwd=self.root,
                             env=self.env,capture_output=True,text=True,timeout=5)
        self.assertNotEqual(old.returncode,0)
        self.assertFalse(manager.report()['existing_terminals_refreshed'])

    def test_failed_environment_broadcast_does_not_claim_shell_refresh(self):
        manager=self.manager();manager.notify=lambda:False
        result=manager.apply(manager.plan())
        self.assertTrue(manager.report()['user_path_registered'])
        self.assertFalse(result['environment_notification'])
        self.assertFalse(result['existing_terminals_refreshed'])


if __name__ == '__main__':unittest.main()
