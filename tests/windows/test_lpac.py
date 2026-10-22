"""Real OS denial/lifecycle checks. Run with the protected MRH Python runtime.

No host credentials, provider requests, or persistent AppContainer profiles.
Compile lpac_payload.c and set MRH_LPAC_TEST_HELPER_EXE to that private image.
The payload imports only kernel32 and observes synthetic canaries.
"""
from contextlib import contextmanager
import ctypes as c
from ctypes import wintypes as w
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

if os.name == 'nt':
    from mrh.adapters.platforms import windows as win, windows_lpac as lpac


@unittest.skipUnless(os.name == 'nt', 'native Windows LPAC only')
class LpacTests(unittest.TestCase):
    @contextmanager
    def payload(self, mode):
        source = os.environ.get('MRH_LPAC_TEST_HELPER_EXE')
        if not source: self.skipTest('compile lpac_payload.c and set MRH_LPAC_TEST_HELPER_EXE')
        with tempfile.TemporaryDirectory(prefix='MRH native helper space ') as directory:
            target = Path(directory)/'helper.exe'
            shutil.copyfile(source,target)
            win.protect(target)
            with lpac.isolated(target) as sandbox:
                sandbox.env['MRH_LPAC_TEST_CASE'] = mode
                yield sandbox

    def dead(self, pid):
        open_process = win.api(win.k, 'OpenProcess', [w.DWORD, w.BOOL, w.DWORD], w.HANDLE)
        handle = open_process(0x100000, False, pid)
        if not handle:
            self.assertEqual(c.get_last_error(), 87)
        else:
            try: self.assertEqual(lpac.wait(handle, 0), 0, 'owned descendant survived cleanup')
            finally: win.close(handle)

    def test_zero_capability_lpac_denies_outside_files_and_image_write(self):
        with tempfile.TemporaryDirectory(prefix='MRH outside space ') as temp, self.payload('files') as sandbox:
            outside = Path(temp)/'private-canary'
            outside.write_text('synthetic, never credentials')
            # Even an ALL APPLICATION PACKAGES read grant must not reach LPAC.
            descriptor = lpac.P()
            sddl = f'D:P(A;;FA;;;{win.current_sid()})(A;;FA;;;SY)(A;;GR;;;S-1-15-2-1)S:(ML;;NW;;;LW)'
            win.checked(win.convert_sd(sddl, 1, c.byref(descriptor), None))
            try: win.checked(win.set_security(str(outside), 0x80000014, descriptor))
            finally: win.local_free(descriptor)
            sandbox.env['MRH_LPAC_CANARY'] = str(outside)
            with patch.dict(os.environ, {'MRH_LPAC_SECRET_CANARY':'synthetic'}):
                out = dict(line.split('=') for line in sandbox.capture([],timeout=5).decode().splitlines())
            self.assertEqual(out,{'outside_read':'5','outside_write':'5','image_write':'5','inside_write':'0','secret_inherited':'0'})
            self.assertTrue((sandbox.work/'allowed.txt').exists())
            self.assertEqual(outside.read_text(), 'synthetic, never credentials')

    def test_matching_metadata_and_timeout_reap_root(self):
        for timeout in (False, True):
            with self.subTest(timeout=timeout), self.payload('hold') as sandbox:
                if timeout:
                    with self.assertRaises(subprocess.TimeoutExpired):sandbox.capture([],timeout=2)
                else:
                    sandbox.capture([],timeout=5,until=lambda data:b'pid=' in data)
                self.dead(int((sandbox.work/'pid').read_text()))

    def test_direct_child_is_denied_or_contained_and_reaped(self):
        with self.payload('children') as sandbox:
            out=sandbox.capture([],timeout=5,until=lambda data:b'\n' in data).decode().strip()
            if out.startswith('child='):
                self.dead(int(out.split('=')[1]))
            else:
                self.assertEqual(out,'create_error=5')

    def test_failed_job_assignment_and_token_verification_never_resume(self):
        for owner, name in ((lpac.Job, 'assign'), (lpac, '_verify')):
            with self.subTest(failure=name), lpac.isolated(sys.executable) as sandbox:
                children = []
                original = lpac.create
                def created(*args):
                    result = original(*args)
                    if result: children.append(c.cast(args[-1], c.POINTER(lpac.PI)).contents.pid)
                    return result
                with patch.object(owner, name, side_effect=OSError('synthetic_refusal')), \
                     patch.object(lpac, 'create', side_effect=created), patch.object(lpac,'resume') as resume:
                    with self.assertRaisesRegex(OSError,'synthetic_refusal'):
                        sandbox.capture([],timeout=1)
                    resume.assert_not_called()
                self.assertEqual(len(children),1)
                self.dead(children[0])

    def test_image_change_refused_before_process_creation_and_profile_removed(self):
        with lpac.isolated(sys.executable) as sandbox:
            root = sandbox.root
            folder = w.LPWSTR()
            get_folder = win.api(lpac.u, 'GetAppContainerFolderPath', [w.LPCWSTR,c.POINTER(w.LPWSTR)], c.c_long)
            self.assertEqual(get_folder(sandbox.sid,c.byref(folder)),0)
            try: profile = Path(folder.value)
            finally:
                win.api(c.WinDLL('ole32'),'CoTaskMemFree',[c.c_void_p],None)(c.cast(folder,c.c_void_p))
            self.assertTrue(profile.exists())
            sandbox.executable.write_bytes(b'changed fixture')
            with patch.object(lpac,'create') as create:
                with self.assertRaisesRegex(OSError,'image_changed'): sandbox.capture([],timeout=1)
                create.assert_not_called()
        self.assertFalse(root.exists())
        self.assertFalse(profile.exists(), 'AppContainer profile survived cleanup')

    def test_output_limit_reaps_the_process(self):
        with self.payload('output') as sandbox:
            with self.assertRaisesRegex(OSError,'output_limit'):
                sandbox.capture([],timeout=5,limit=100)

    def test_zero_capabilities_deny_the_winsock_network_path(self):
        with self.payload('network') as sandbox:
            out = dict(line.split('=') for line in sandbox.capture([],timeout=5).decode().splitlines())
            # On LTSC 19044 Winsock cannot initialize. On systems which can
            # initialize it, the first socket/connect must be denied by WFP.
            self.assertTrue(out == {'startup':'10107'} or out == {'startup':'0','socket':'10013'}
                            or out == {'startup':'0','socket':'0','connect':'10013'},out)


if __name__ == '__main__': unittest.main()
