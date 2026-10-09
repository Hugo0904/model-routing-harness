import importlib.util
from pathlib import Path
import shutil
import signal
import subprocess
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("mrh_host_fixture", Path(__file__).resolve().parents[1]/"scripts/verify_host.py")
host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host)


class HungProcess:
    pid = 34567
    def __init__(self): self.code = None; self.reaped = False
    def poll(self): return self.code
    def wait(self, **_):
        if self.code is None: raise subprocess.TimeoutExpired("fake_fixture", 0)
        self.reaped = True; return self.code


class CleanupTests(unittest.TestCase):
    def test_ignored_term_is_followed_by_group_kill_and_reap(self):
        proc = HungProcess(); signals = []
        def send(pid, sig):
            self.assertEqual(pid, proc.pid); signals.append(sig)
            if sig == signal.SIGKILL: proc.code = -9
        with patch.object(host.os, "getpgid", return_value=proc.pid), patch.object(host.os, "killpg", side_effect=send):
            self.assertEqual(host.stop_owned(proc, seconds=.001), -9)
        self.assertEqual(signals, [signal.SIGTERM, signal.SIGKILL]); self.assertTrue(proc.reaped)

    def test_signal_permission_failure_retains_owned_home_and_reports_failure(self):
        scope = host.OwnedScratch(); proc = HungProcess(); scope.processes.append(proc)
        marker = scope.path/"fixture-marker"; marker.write_text("owned fixture only")
        try:
            with patch.object(host.os, "getpgid", return_value=proc.pid), patch.object(host.os, "killpg", side_effect=PermissionError()):
                with self.assertRaises(PermissionError): host.stop_owned(proc, seconds=.001)
            with self.assertRaisesRegex(RuntimeError, "cleanup_failed_temporary_home_preserved"):
                scope.__exit__(None, None, None)
            self.assertTrue(marker.exists())
        finally: shutil.rmtree(scope.path)

    def test_changed_group_is_never_signalled(self):
        proc = HungProcess()
        with patch.object(host.os, "getpgid", return_value=1), patch.object(host.os, "killpg") as send:
            with self.assertRaisesRegex(RuntimeError, "owned_process_group_changed"):
                host.stop_owned(proc, seconds=.001)
            send.assert_not_called()


if __name__ == "__main__": unittest.main()
