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
            source_files = {p.relative_to(bundle.ROOT / 'src').as_posix(): p.read_bytes()
                            for p in (bundle.ROOT / 'src/mrh').rglob('*.py')}
            packaged_files = {name: z.read(name) for name in z.namelist()
                              if name.startswith('mrh/') and name.endswith('.py')}
            self.assertEqual(packaged_files, source_files)
            self.assertTrue(any(n.endswith('/METADATA') for n in z.namelist()))
            self.assertFalse(any(n.endswith(('.js', '.mjs')) or n.startswith('mrh_bundle') for n in z.namelist()))
            self.assertEqual(set(hashes), set(z.namelist()))


class LicensingSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='mrh-notice-check-');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.source=self.root/'packaging/macos-arm64/license-snapshot';self.source.mkdir(parents=True)
        self.runtime=self.root/'runtime';(self.runtime/'bin').mkdir(parents=True)
        binary=self.runtime/'bin/python3.11';binary.write_bytes(b'synthetic pinned binary')
        self.lock=bundle.read_lock()
        metadata=self.source/'PYTHON.json';metadata.write_text(json.dumps({'python_version':self.lock['python_version'],'target_triple':self.lock['target']}))
        notice=self.source/'licenses/LICENSE.fixture.txt';notice.parent.mkdir();notice.write_text('Synthetic license fixture\n')
        files={p.relative_to(self.source).as_posix():{'sha256':bundle.sha256(p),'size':p.stat().st_size} for p in (metadata,notice)}
        self.value={'schema_version':1,'source':{'provider':self.lock['provider'],'release':self.lock['release'],'runtime_sha256':self.lock['runtime']['sha256'],'licensing_sha256':self.lock['licensing_source']['sha256']},'files':files,'runtime_binary':{'path':'bin/python3.11','sha256':bundle.sha256(binary),'verified_system_libraries':[]},'summary':{'metadata_sha256':files['PYTHON.json']['sha256'],'metadata_source':self.lock['licensing_source'],'required_license_paths':['licenses/LICENSE.fixture.txt'],'copied_notices':{'licenses/LICENSE.fixture.txt':files['licenses/LICENSE.fixture.txt']['sha256']},'missing_nonredistributed_alternative':{}}}
        self.save_snapshot()

    def save_snapshot(self):
        (self.source/'snapshot.json').write_text(json.dumps(self.value))
        self.lock['licensing_snapshot_sha256']=bundle.sha256(self.source/'snapshot.json')

    def test_locked_snapshot_copies_notices_without_external_decompressor_or_otool(self):
        destination=self.root/'out'
        with patch('mrh_bundle.ROOT',self.root),patch('mrh_bundle.subprocess.run',side_effect=AssertionError('external licensing command forbidden')):
            result=bundle.licensing(self.root/'unused.tar.zst',destination,self.lock,self.runtime)
        self.assertEqual((destination/'licenses/LICENSE.fixture.txt').read_bytes(),(self.source/'licenses/LICENSE.fixture.txt').read_bytes())
        self.assertEqual(result['snapshot_verification']['runtime_binary_sha256'],bundle.sha256(self.runtime/'bin/python3.11'))

    def test_modified_notice_or_binary_fails_before_output(self):
        for target in (self.source/'licenses/LICENSE.fixture.txt',self.runtime/'bin/python3.11'):
            original=target.read_bytes();target.write_bytes(b'changed')
            with patch('mrh_bundle.ROOT',self.root):
                with self.assertRaisesRegex(bundle.BundleError,'licensing_snapshot_invalid'):
                    bundle.licensing(self.root/'unused',self.root/'out',self.lock,self.runtime)
            self.assertFalse((self.root/'out').exists());target.write_bytes(original)

    def test_unknown_notice_or_wrong_provenance_fails_closed(self):
        (self.source/'unknown').write_bytes(b'not declared')
        with patch('mrh_bundle.ROOT',self.root):
            with self.assertRaisesRegex(bundle.BundleError,'licensing_snapshot_invalid'):
                bundle.licensing(self.root/'unused',self.root/'out',self.lock,self.runtime)
        (self.source/'unknown').unlink();self.value['source']['release']='not-pinned';self.save_snapshot()
        with patch('mrh_bundle.ROOT',self.root):
            with self.assertRaisesRegex(bundle.BundleError,'licensing_snapshot_invalid'):
                bundle.licensing(self.root/'unused',self.root/'out',self.lock,self.runtime)
        self.assertFalse((self.root/'out').exists())


if __name__ == '__main__': unittest.main()
