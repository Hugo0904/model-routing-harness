"""Only the new build-time validation/extraction seam; no remote execution."""
import copy
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import mrh_bundle as bundle


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='mrh-bundle-check-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def archive(self, rows):
        path = self.root / 'fixture.tar.gz'
        with tarfile.open(path, 'w:gz') as tf:
            for name, kind, data in rows:
                m = tarfile.TarInfo(name); m.mode = 0o755 if kind == 'file' else 0o644
                if kind == 'file':
                    m.size = len(data); tf.addfile(m, io.BytesIO(data))
                else:
                    m.type = {'sym': tarfile.SYMTYPE, 'hard': tarfile.LNKTYPE, 'device': tarfile.CHRTYPE}[kind]
                    m.linkname = data; tf.addfile(m)
        return path

    def test_safe_relative_links_and_regular_bytes_extract_without_permissions_escalation(self):
        archive = self.archive([('python/bin/python3.11', 'file', b'fixture bytes'), ('python/bin/python3', 'sym', 'python3.11')])
        root = self.root / 'runtime'; bundle.extract_runtime(archive, root)
        self.assertEqual((root / 'bin/python3').read_bytes(), b'fixture bytes')
        self.assertEqual((root / 'bin/python3').resolve(), root / 'bin/python3.11')
        self.assertEqual((root / 'bin/python3.11').stat().st_mode & 0o777, 0o755)

    def test_bad_paths_links_devices_and_case_collision_refuse_before_writes(self):
        rows = [
            [('python/../../outside', 'file', b'bad')],
            [('/absolute', 'file', b'bad')],
            [('other/bin/python', 'file', b'bad')],
            [('python/link', 'sym', '../../outside')],
            [('python/link', 'sym', '/absolute')],
            [('python/link', 'hard', 'python/../../outside')],
            [('python/device', 'device', '')],
            [('python/Name', 'file', b'one'), ('python/name', 'file', b'two')],
        ]
        for index, row in enumerate(rows):
            with self.subTest(index=index):
                root = self.root / ('runtime-' + str(index))
                with self.assertRaises(bundle.BundleError): bundle.extract_runtime(self.archive(row), root)
                self.assertFalse(root.exists())
        self.assertFalse((self.root / 'outside').exists())

    def test_extraction_refuses_existing_destination_and_size_limit(self):
        archive = self.archive([('python/bin/p', 'file', b'bytes')]); root = self.root / 'runtime'
        root.mkdir(); original = root / 'preserve'; original.write_bytes(b'original')
        with self.assertRaises(bundle.BundleError): bundle.extract_runtime(archive, root)
        self.assertEqual(original.read_bytes(), b'original')
        with patch('mrh_bundle.MAX_UNPACKED', 1):
            with self.assertRaises(bundle.BundleError): bundle.extract_runtime(archive, self.root / 'large')
        self.assertFalse((self.root / 'large').exists())

    def test_lock_cannot_select_unverified_origin_or_platform(self):
        lock = bundle.read_lock()
        for mutation in ('platform', 'origin', 'hash', 'url_name'):
            value = copy.deepcopy(lock)
            if mutation == 'platform': value['target'] = 'unverified-platform'
            elif mutation == 'origin': value['runtime']['url'] = 'https://untrusted.invalid/runtime'
            elif mutation == 'hash': value['runtime']['sha256'] = 'z' * 64
            else: value['runtime']['url'] = value['runtime']['url'].replace('install_only.tar.gz', 'debug-full.tar.zst')
            path = self.root / 'lock.json'; path.write_text(json.dumps(value))
            with self.assertRaises(bundle.BundleError): bundle.read_lock(path)

    def test_cached_wrong_bytes_and_foreign_content_are_not_replaced_or_downloaded(self):
        lock = bundle.read_lock(); root = self.root / 'cache'; root.mkdir()
        (root / bundle.CACHE_MARKER).write_text(bundle.CACHE_CONTENT)
        archive = root / lock['runtime']['name']; archive.write_bytes(b'wrong bytes')
        with patch('mrh_bundle.subprocess.run', side_effect=AssertionError('unexpected download')):
            with self.assertRaises(bundle.BundleError): bundle.fixed_assets(root, lock, download=True)
        self.assertEqual(archive.read_bytes(), b'wrong bytes')
        (root / 'foreign').write_bytes(b'preserve')
        with self.assertRaises(bundle.BundleError): bundle.fixed_assets(root, lock)
        self.assertEqual((root / 'foreign').read_bytes(), b'preserve')

    def test_foreign_or_symlink_cache_marker_refuses_without_reading_target(self):
        for name in ('foreign', 'symlink'):
            root = self.root / name; root.mkdir()
            if name == 'symlink':
                target = self.root / 'private-marker'; target.write_text('PRIVATE_CANARY')
                (root / bundle.CACHE_MARKER).symlink_to(target)
            with self.assertRaises(bundle.BundleError): bundle.fixed_assets(root, bundle.read_lock())

    def test_application_archive_has_metadata_and_all_mrh_modules_without_sdk_or_build_runtime(self):
        import zipfile
        path = self.root / 'app/mrh.pyz'; hashes = bundle.application_archive(path)
        with zipfile.ZipFile(path) as z:
            self.assertIn('mrh/cli.py', z.namelist()); self.assertIn('__main__.py', z.namelist())
            self.assertEqual(z.read('mrh/cli.py'), (bundle.ROOT / 'src/mrh/cli.py').read_bytes())
            self.assertTrue(any(n.endswith('/METADATA') for n in z.namelist()))
            self.assertFalse(any(n.endswith(('.js', '.mjs')) or n.startswith('mrh_bundle') for n in z.namelist()))
            self.assertEqual(set(hashes), set(z.namelist()))


if __name__ == '__main__': unittest.main()
