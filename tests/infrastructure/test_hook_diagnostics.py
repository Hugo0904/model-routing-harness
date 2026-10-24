"""Only new transport/control/lifecycle seams; accepted DIAG22 is not replayed."""
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from mrh.infrastructure import hook_diagnostics as d, owned, plugin


class FakeService:
    def __init__(self, root, runtime):
        self.root, self.runtime = root, runtime
        self.registered = False
        self.command = None
        self.process = None
        self.starts = 0
        self.fail_install = False
        self.fail_start = False

    def inspect(self):
        return {'registered': self.registered, 'running': bool(self.process and self.process.poll() is None),
                'name': 'owned-test-service'}

    def install(self, command):
        if self.fail_install:
            self.fail_install = False
            raise owned.OwnedError('synthetic_login_failure')
        if self.process and self.process.poll() is None:
            self.process.terminate(); self.process.wait(timeout=2)
        self.registered, self.command = True, command

    def start(self):
        if self.fail_start:
            self.fail_start = False
            raise owned.OwnedError('synthetic_start_failure')
        if self.process and self.process.poll() is None:
            return
        self.starts += 1
        code = ('import sys;from pathlib import Path;sys.path.insert(0,' + repr(str(Path(d.__file__).resolve().parents[2])) + ');'
                'from mrh.infrastructure.hook_diagnostics import receive;'
                'raise SystemExit(receive(Path(' + repr(str(self.root)) + '),Path(' + repr(str(self.runtime)) + ')))')
        self.process = subprocess.Popen([sys.executable, '-I', '-B', '-c', code],
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def remove(self):
        if self.process:
            if self.process.poll() is None:
                self.process.terminate()
            self.process.wait(timeout=2)
        self.registered = False


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.root = self.base / 'config/hook-diagnostics'
        self.runtime = self.base / 'runtime'
        self.service = FakeService(self.root, self.runtime)
        self.addCleanup(self.stop)

    def stop(self):
        if d._state(self.root):
            d.control('off', root=self.root, runtime=self.runtime, service=self.service)

    def on(self, command=None):
        return d.control('on', root=self.root, runtime=self.runtime, service=self.service,
                         command=command or ['synthetic-owned-command'])

    def rows(self):
        area = d.log_root(self.runtime)
        return [json.loads(line) for name in d.LOG_NAMES if (area / name).exists()
                for line in owned.read_regular(area / name, d.MAX_LOG_BYTES).splitlines()]

    def wait_rows(self, count):
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            rows = self.rows()
            if len(rows) >= count:
                return rows
            time.sleep(.02)
        self.fail('expected safe diagnostic record not received')

    def send(self, **changes):
        endpoint = d._endpoint(self.root)
        frame = {'stage': 'result', 'exception': 'ValueError', 'winerror': None, 'child_rc': 1, 'elapsed_ms': 1}
        value = {'version': 1, 'platform': 'codex', 'capability': endpoint['capability'], 'frame': frame, **changes}
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as channel:
            channel.sendto(d._json(value), ('127.0.0.1', endpoint['port']))

    def test_control_default_idempotence_broken_route_settings_and_clear(self):
        state = d.control('status', root=self.root, runtime=self.runtime, service=self.service)
        self.assertFalse(state['enabled']); self.assertFalse(self.root.exists())
        route = self.base / 'settings.json'; route.write_text('broken routing settings')
        self.assertTrue(self.on()['ready']); self.assertTrue(self.on()['ready'])
        self.assertEqual(self.service.starts, 1)
        with self.assertRaisesRegex(owned.OwnedError, 'clear_requires_off'):
            d.control('clear', root=self.root, runtime=self.runtime, service=self.service)
        from mrh.presentation import cli
        output = io.StringIO()
        with patch.object(d, 'config_root', return_value=self.root), patch.object(d.locations, 'runtime_root', return_value=self.runtime), patch.object(d, '_service', return_value=self.service):
            self.assertEqual(cli.main(['ctrl', '--settings', str(route), 'diagnostics', 'status', '--json'], stdout=output, stderr=io.StringIO()), 0)
        self.assertTrue(json.loads(output.getvalue())['ready'])
        self.assertEqual(route.read_text(), 'broken routing settings')
        self.send(); self.wait_rows(1)
        off = d.control('off', root=self.root, runtime=self.runtime, service=self.service)
        self.assertFalse(off['enabled']); self.assertFalse(off['login']['registered'])
        area = d.log_root(self.runtime); foreign = area / 'keep.txt'; foreign.write_text('preserve')
        d.control('clear', root=self.root, runtime=self.runtime, service=self.service)
        self.assertEqual(foreign.read_text(), 'preserve'); self.assertEqual(self.rows(), [])

    def test_udp_rejects_bad_packets_and_reports_sink_degradation(self):
        self.on()
        self.send(capability='0' * 64); self.send(extra='discard')
        self.send(frame={'stage': 'result', 'exception': 'ValueError', 'private': 'discard'})
        endpoint = d._endpoint(self.root)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as channel:
            channel.sendto(b'x' * 513, ('127.0.0.1', endpoint['port']))
        self.send(); rows = self.wait_rows(1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(set(rows[0]), {'received_at', 'version', 'platform', 'stage', 'exception', 'winerror', 'child_rc', 'elapsed_ms'})
        current = d.log_root(self.runtime) / d.LOG_NAMES[0]
        original = current.read_bytes(); current.unlink()
        protected = self.base / 'preserved-original'; protected.write_text('preserve')
        current.symlink_to(protected)
        try:
            self.send()
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                state = d.status(root=self.root, runtime=self.runtime, service=self.service)
                if state['collector'] == 'degraded':
                    break
                time.sleep(.02)
            self.assertFalse(state['ready']); self.assertEqual(state['reason'], 'diagnostics_log_unavailable')
        finally:
            self.assertEqual(protected.read_text(), 'preserve')
            current.unlink(); current.write_bytes(original); current.chmod(0o600)
        self.send(); self.wait_rows(2)
        self.assertTrue(d.status(root=self.root, runtime=self.runtime, service=self.service)['ready'])

    def test_rotation_retention_and_unsafe_log_ownership(self):
        area = d._initialize(d.log_root(self.runtime), d.LOG_KIND)
        frame = {'stage': 'result', 'exception': 'ValueError', 'winerror': None, 'child_rc': 1, 'elapsed_ms': 1}
        foreign = area / 'unrelated.jsonl'; foreign.write_text('keep')
        with owned.locked(area, d.LOG_KIND), patch.object(d, 'MAX_LOG_BYTES', 256):
            for _ in range(5):
                d._append(area, frame, 'codex')
            self.assertEqual(len([p for p in area.iterdir() if p.name in d.LOG_NAMES]), 3)
            self.assertTrue(all((area / name).stat().st_size <= 256 for name in d.LOG_NAMES))
            old = area / d.LOG_NAMES[-1]; os.utime(old, (0, 0)); d._prune(area, time.time())
            self.assertFalse(old.exists()); self.assertEqual(foreign.read_text(), 'keep')
        target = self.base / 'original'; target.write_text('preserve')
        (area / d.LOG_NAMES[-1]).symlink_to(target)
        with self.assertRaises((OSError, ValueError)):
            d._prune(area, time.time())
        self.assertEqual(target.read_text(), 'preserve')

    def test_on_failure_rolls_back_and_restart_preserves_enabled_state(self):
        self.service.fail_start = True
        with self.assertRaisesRegex(owned.OwnedError, 'synthetic_start_failure'):
            self.on()
        self.assertFalse(d._state(self.root)['enabled']); self.assertFalse(self.service.registered)
        self.on()
        previous = d._state(self.root)
        self.service.fail_install = True
        with self.assertRaisesRegex(owned.OwnedError, 'synthetic_login_failure'):
            self.on(['new-synthetic-command'])
        self.assertEqual(d._state(self.root), previous)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and not d.status(root=self.root, runtime=self.runtime, service=self.service)['ready']:
            time.sleep(.02)
        self.assertTrue(d.status(root=self.root, runtime=self.runtime, service=self.service)['ready'])
        self.on(['new-synthetic-command'])
        self.assertEqual(d._state(self.root)['command'], ['new-synthetic-command'])
        self.assertTrue(d._state(self.root)['enabled'])

    def test_producer_drops_missing_invalid_unreachable_and_send_failure(self):
        d._initialize(self.root, d.CONFIG_KIND)
        endpoint = self.root / 'endpoint.json'
        code = d.producer(endpoint) + '\n_diag_emit("result",ValueError("PRIVATE-SENTINEL"));print("{}")\n'
        variants = ('missing', 'invalid', 'unreachable', 'send_failure')
        for variant in variants:
            with self.subTest(variant=variant):
                endpoint.unlink(missing_ok=True)
                if variant == 'invalid':
                    endpoint.write_text('{"host":"remote.invalid"}'); endpoint.chmod(0o600)
                elif variant != 'missing':
                    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as channel:
                        channel.bind(('127.0.0.1', 0)); port = channel.getsockname()[1]
                    owned.replace_owned(endpoint, d._json({'version': 1, 'host': '127.0.0.1', 'port': port, 'capability': 'a' * 64}))
                script = code
                if variant == 'send_failure':
                    script = 'import socket\ndef broken(*a,**k):raise OSError("PRIVATE-SENTINEL")\nsocket.socket=broken\n' + code
                run = subprocess.run([sys.executable, '-I', '-B', '-c', script, 'codex'], capture_output=True, timeout=3)
                self.assertEqual((run.returncode, run.stdout, run.stderr), (0, b'{}\n', b''))

    def test_prepared_launcher_udp_seam_and_safe_adoption_marker(self):
        self.on()
        artifact = self.base / 'artifact'; settings = self.base / 'profile/settings.json'
        plugin.prepare(artifact, settings, sys.executable, advisory=True, diagnostics_root=self.root, runtime_root=self.runtime)
        folder = artifact / 'plugins/model-routing-harness'
        original = folder / 'original.py'; original.write_bytes(plugin.LAUNCHER)
        event = b'{}'
        def run(file):
            return subprocess.run([sys.executable, '-I', '-B', str(file), 'codex'], input=event, capture_output=True, timeout=3)
        before = run(original); normal = run(folder / 'launcher.py')
        self.assertEqual((normal.returncode, normal.stdout, normal.stderr), (before.returncode, before.stdout, b''))
        self.assertEqual(self.rows(), [])
        (folder / 'runtime.pyz').write_bytes(b'synthetic integrity failure')
        before = run(original); failed = run(folder / 'launcher.py')
        self.assertEqual((failed.returncode, failed.stdout, failed.stderr), (before.returncode, before.stdout, b''))
        self.assertEqual(self.wait_rows(1)[0]['stage'], 'integrity')
        proof = d.self_check(root=self.root, runtime=self.runtime)
        self.assertTrue(proof['received'] and proof['marker_removed'])
        self.assertEqual(len(self.rows()), 1)

    def test_exclusive_writer_and_descriptor_ownership(self):
        self.on()
        self.assertEqual(d.receive(self.root, self.runtime), 2)
        self.assertTrue(d.status(root=self.root, runtime=self.runtime, service=self.service)['ready'])
        endpoint = self.root / 'endpoint.json'; original = endpoint.read_bytes()
        # Prepare binds a canonical path first; mutate only at Hook runtime.
        code = d.producer(endpoint) + '\n_diag_emit("result",ValueError("PRIVATE"));print("{}")\n'
        target = self.base / 'foreign-endpoint'; target.write_bytes(original)
        endpoint.unlink(); endpoint.symlink_to(target)
        try:
            result = subprocess.run([sys.executable, '-I', '-B', '-c', code, 'codex'], capture_output=True, timeout=3)
            self.assertEqual((result.returncode, result.stdout, result.stderr), (0, b'{}\n', b''))
            self.assertEqual(self.rows(), [])
        finally:
            endpoint.unlink(); endpoint.write_bytes(original); endpoint.chmod(0o600)


if __name__ == '__main__':
    unittest.main()
