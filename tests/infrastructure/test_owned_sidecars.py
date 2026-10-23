"""A transient SQLite sidecar must not make a valid POSIX profile unreadable."""
import errno
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from mrh.infrastructure import owned, settings_v2 as settings
from mrh.infrastructure.settings_schema import SettingsError


@unittest.skipUnless(os.name == "posix", "POSIX filesystem seam; native Windows has separate coverage")
class OwnedSidecarTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.path = self.root / "profile/settings.json"
        self.value = settings.init(self.path)
        self.before = self.path.read_bytes()

    def failing_lstat(self, target, error):
        original = Path.lstat

        def check(path, *args, **kwargs):
            if path == target:
                raise error
            return original(path, *args, **kwargs)

        return patch.object(Path, "lstat", check)

    def test_settings_remain_readable_when_each_known_sqlite_sidecar_vanishes(self):
        for name in ("advice.sqlite3-wal", "advice.sqlite3-shm", "events.sqlite3-wal", "events.sqlite3-shm"):
            with self.subTest(sidecar=name):
                sidecar = self.path.parent / name
                sidecar.write_bytes(b"synthetic sidecar")
                with self.failing_lstat(sidecar, FileNotFoundError(errno.ENOENT, "deleted after listing", str(sidecar))):
                    self.assertEqual(settings.read(self.path), self.value)
                self.assertEqual(self.path.read_bytes(), self.before)
                sidecar.unlink()

    def metadata_lstat(self, target, *, nlink=0, mode=None, uid=None):
        original = Path.lstat

        def check(path, *args, **kwargs):
            result = original(path, *args, **kwargs)
            if path == target:
                values = list(result)
                values[3] = nlink
                if mode is not None:
                    values[0] = mode
                if uid is not None:
                    values[4] = uid
                return os.stat_result(values)
            return result

        return patch.object(Path, "lstat", check)

    def test_settings_remain_readable_when_each_known_sqlite_sidecar_has_zero_links(self):
        for name in ("advice.sqlite3-wal", "advice.sqlite3-shm", "events.sqlite3-wal", "events.sqlite3-shm"):
            with self.subTest(sidecar=name):
                target = self.path.parent / name
                target.write_bytes(b"synthetic unlinked sidecar")
                with self.metadata_lstat(target):
                    self.assertEqual(settings.read(self.path), self.value)
                self.assertEqual(self.path.read_bytes(), self.before)
                target.unlink()

    def test_zero_links_do_not_bypass_filename_type_or_owner_protections(self):
        for name in ("settings.json", owned.MARKER, "advice.sqlite3", "events.sqlite3", "model-profile.json", "unknown.sqlite3-wal"):
            with self.subTest(file=name):
                target = self.path.parent / name
                created = not target.exists()
                if created:
                    target.write_bytes(b"synthetic file")
                with self.metadata_lstat(target):
                    with self.assertRaises(SettingsError):
                        settings.read(self.path)
                self.assertEqual(self.path.read_bytes(), self.before)
                if created:
                    target.unlink()
        target = self.path.parent / "custom-wal"
        target.write_bytes(b"synthetic file")
        with self.metadata_lstat(target):
            with self.assertRaisesRegex(owned.OwnedError, "unsafe_owned_file"):
                owned.verify(self.path.parent, "settings", settings.FILES | {target.name})
        target.unlink()
        target = self.path.parent / "advice.sqlite3-wal"
        target.write_bytes(b"synthetic sidecar")
        for changed in ({"uid": os.getuid() + 1}, {"mode": stat.S_IFLNK | 0o600}, {"mode": stat.S_IFDIR | 0o700}, {"nlink": 2}):
            with self.subTest(metadata=changed), self.metadata_lstat(target, **changed):
                with self.assertRaises(SettingsError):
                    settings.read(self.path)
            self.assertEqual(self.path.read_bytes(), self.before)

    def test_other_allowed_files_disappearing_still_fail(self):
        for name in ("settings.json", "advice.sqlite3", "events.sqlite3", "model-profile.json", owned.MARKER):
            with self.subTest(file=name):
                target = self.path.parent / name
                created = not target.exists()
                if created:
                    target.write_bytes(b"synthetic file")
                with self.failing_lstat(target, FileNotFoundError(errno.ENOENT, "deleted after listing", str(target))):
                    with self.assertRaises(SettingsError) as raised:
                        settings.read(self.path)
                self.assertEqual(raised.exception.reason, "settings_unowned")
                self.assertEqual(self.path.read_bytes(), self.before)
                if created:
                    target.unlink()
        # An explicitly allowed arbitrary suffix is still not a SQLite exception.
        target = self.path.parent / "custom-wal"
        target.write_bytes(b"synthetic file")
        with self.failing_lstat(target, FileNotFoundError(errno.ENOENT, "deleted after listing", str(target))):
            with self.assertRaises(FileNotFoundError):
                owned.verify(self.path.parent, "settings", settings.FILES | {target.name})

    def test_unknown_sidecars_are_rejected_before_any_disappearance_exception(self):
        target = self.path.parent / "unknown.sqlite3-shm"
        target.write_bytes(b"synthetic file")
        with self.failing_lstat(target, FileNotFoundError(errno.ENOENT, "deleted after listing", str(target))):
            with self.assertRaises(SettingsError) as raised:
                settings.read(self.path)
        self.assertEqual(raised.exception.reason, "settings_unowned")
        self.assertEqual(self.path.read_bytes(), self.before)

    def test_existing_unsafe_sidecars_and_other_os_errors_still_fail(self):
        target = self.path.parent / "advice.sqlite3-wal"
        outside = self.root / "outside"
        outside.write_bytes(b"preserve")
        for kind in ("symlink", "hardlink", "foreign_owner", "permission", "io_error"):
            with self.subTest(kind=kind):
                if kind == "symlink":
                    target.symlink_to(outside)
                elif kind == "hardlink":
                    os.link(outside, target)
                else:
                    target.write_bytes(b"synthetic sidecar")
                original = Path.lstat

                def check(path, *args, **kwargs):
                    result = original(path, *args, **kwargs)
                    if path == target:
                        if kind == "foreign_owner":
                            values = list(result)
                            values[4] = os.getuid() + 1
                            return os.stat_result(values)
                        if kind in ("permission", "io_error"):
                            code = errno.EACCES if kind == "permission" else errno.EIO
                            raise OSError(code, "synthetic filesystem failure", str(target))
                    return result

                with patch.object(Path, "lstat", check):
                    with self.assertRaises(SettingsError) as raised:
                        settings.read(self.path)
                self.assertEqual(raised.exception.reason, "settings_unowned")
                self.assertEqual(self.path.read_bytes(), self.before)
                self.assertEqual(outside.read_bytes(), b"preserve")
                target.unlink()


if __name__ == "__main__":
    unittest.main()
