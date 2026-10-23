"""Native Windows packet privacy/readonly guards; no real Host or provider calls."""
import os
from pathlib import Path
import subprocess
import unittest

from tests.application import test_codex_packets as fixtures


@unittest.skipUnless(os.name=='nt','native Windows ACL and junction evidence required')
class WindowsPacketGuards(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.PacketTests();self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_native_private_acl_hardlink_and_writable_body_are_refused(self):
        from mrh.adapters.platforms import windows as native
        for kind in ('acl','hardlink','writable'):
            with self.subTest(kind=kind):
                packet=self.fixture.prep();body=Path(packet['body_path']);extra=None
                if kind=='acl':
                    descriptor=native.P()
                    sddl=f'D:P(A;;FA;;;{native.current_sid()})(A;;FR;;;WD)(A;;FA;;;SY)(A;;FA;;;BA)'
                    native.checked(native.convert_sd(sddl,1,native.c.byref(descriptor),None))
                    try:native.checked(native.set_security(str(body),0x80000004,descriptor))
                    finally:native.local_free(descriptor)
                elif kind=='hardlink':
                    extra=self.fixture.root/('linked-'+packet['packet_id'])
                    os.link(body,extra)
                else:os.chmod(body,0o600)
                try:self.fixture.reason(self.fixture.run_hook(self.fixture.event(packet)))
                finally:
                    os.chmod(body,0o600)
                    if extra is not None:extra.unlink()
                    native.protect(body)
        self.assertEqual(self.fixture.fake.calls,0)

    def test_native_packet_body_directory_junction_is_refused(self):
        packet=self.fixture.prep();body=Path(packet['body_path'])
        directory=body.parent;moved=directory.with_name(directory.name+'-moved')
        directory.rename(moved)
        command=[str(Path(os.environ['SystemRoot'])/'System32/cmd.exe'),'/d','/c','mklink','/J',str(directory),str(moved)]
        result=subprocess.run(command,capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        try:self.fixture.reason(self.fixture.run_hook(self.fixture.event(packet)))
        finally:os.rmdir(directory)
        self.assertEqual(self.fixture.fake.calls,0)


if __name__=='__main__':unittest.main()
