import base64
import csv
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROBE_SOURCE = "VALUE = 'wheel-build'\n"
IMPORT_PROBE = (
    "import site, sys; site.addsitedir(sys.argv[1]); "
    "from mrh import _editable_build_probe; print(_editable_build_probe.VALUE)"
)


class EditableBuildTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary.name)
        self.project = self.workspace / "fixture"
        self._copy_fixture(self.project)
        self.probe = self.project / "src" / "mrh" / "_editable_build_probe.py"
        self.probe.write_text(PROBE_SOURCE)

        spec = importlib.util.spec_from_file_location(
            "mrh_build_editable_fixture", self.project / "mrh_build.py"
        )
        self.backend = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.backend)
        self.backend.ROOT = self.project

    def tearDown(self):
        self.temporary.cleanup()

    def _copy_fixture(self, destination):
        destination.mkdir(parents=True)
        shutil.copy2(PROJECT_ROOT / "mrh_build.py", destination / "mrh_build.py")
        shutil.copy2(PROJECT_ROOT / "pyproject.toml", destination / "pyproject.toml")
        shutil.copy2(PROJECT_ROOT / "LICENSE", destination / "LICENSE")
        shutil.copytree(
            PROJECT_ROOT / "src",
            destination / "src",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )

    def _build_standard_wheel(self, wheel_directory=None, metadata_directory=None):
        wheel_directory = wheel_directory or self.workspace / "standard-dist"
        filename = self.backend.build_wheel(
            wheel_directory, metadata_directory=metadata_directory
        )
        return Path(wheel_directory) / filename

    def _archive_files(self, wheel_path):
        with zipfile.ZipFile(wheel_path) as archive:
            names = archive.namelist()
            self.assertEqual(len(names), len(set(names)), "wheel contains duplicate paths")
            return {name: archive.read(name) for name in names}

    def _assert_valid_record(self, wheel_path):
        files = self._archive_files(wheel_path)
        record_paths = [name for name in files if name.endswith(".dist-info/RECORD")]
        self.assertEqual(len(record_paths), 1)
        record_path = record_paths[0]
        rows = list(csv.reader(io.StringIO(files[record_path].decode(), newline="")))
        self.assertEqual({row[0] for row in rows}, set(files))
        self.assertEqual(len(rows), len(files))

        for path, digest, size in rows:
            self.assertEqual(len([row for row in rows if row[0] == path]), 1)
            if path == record_path:
                self.assertEqual((digest, size), ("", ""))
                continue
            expected_digest = base64.urlsafe_b64encode(
                hashlib.sha256(files[path]).digest()
            ).rstrip(b"=").decode()
            self.assertEqual(digest, "sha256=" + expected_digest)
            self.assertEqual(int(size), len(files[path]))
        return files, record_path

    def _run_import(self, site_directory):
        result = subprocess.run(
            [sys.executable, "-B", "-I", "-c", IMPORT_PROBE, str(site_directory)],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    def test_standard_wheel_keeps_resources_metadata_and_record(self):
        wheel_path = self._build_standard_wheel()
        files, record_path = self._assert_valid_record(wheel_path)

        _, _, dist, expected = self.backend.metadata()
        expected.update(self.backend.package_files())
        self.assertEqual({name: data for name, data in files.items() if name != record_path}, expected)
        self.assertFalse(any(name.endswith(".pth") for name in files))
        self.assertNotIn(self.backend.EDITABLE_DESCRIPTOR, files)
        fixture_path = str(self.project.resolve()).encode()
        self.assertTrue(all(fixture_path not in content for content in files.values()))
        self.assertIn(f"{dist}/entry_points.txt", files)

    def test_editable_wheel_uses_prepared_metadata_and_tracks_source_edits(self):
        self.assertEqual(self.backend.get_requires_for_build_editable(), [])
        metadata_root = self.workspace / "prepared-metadata"
        dist = self.backend.prepare_metadata_for_build_editable(metadata_root)
        metadata_directory = metadata_root / dist
        (metadata_directory / "backend-state.json").write_text('{"opaque":true}\n')
        prepared = {
            path.relative_to(metadata_root).as_posix(): path.read_bytes()
            for path in metadata_directory.rglob("*")
            if path.is_file()
        }
        standard_wheel = self._build_standard_wheel(
            self.workspace / "standard-from-prepared",
            metadata_directory=metadata_directory,
        )
        standard_files, standard_record_path = self._assert_valid_record(standard_wheel)

        wheel_directory = self.workspace / "editable-dist"
        filename = self.backend.build_editable(
            wheel_directory, metadata_directory=metadata_directory
        )
        wheel_path = wheel_directory / filename
        files, record_path = self._assert_valid_record(wheel_path)

        self.assertEqual(filename, "model_routing_harness-0.4.0-py3-none-any.whl")
        wheel_metadata = {
            name: data for name, data in files.items()
            if name.startswith(f"{dist}/") and name != record_path
        }
        self.assertEqual(wheel_metadata, prepared)
        standard_metadata = {
            name: data for name, data in standard_files.items()
            if name.startswith(f"{dist}/") and name != standard_record_path
        }
        self.assertEqual(wheel_metadata, standard_metadata)
        self.assertIn(f"{dist}/entry_points.txt", wheel_metadata)
        self.assertFalse(any(name.startswith("mrh/") for name in files))

        pth_paths = [name for name in files if name.endswith(".pth")]
        self.assertEqual(pth_paths, [self.backend.EDITABLE_PTH])
        source_path = str((self.project / "src").resolve())
        self.assertEqual(files[self.backend.EDITABLE_PTH], (source_path + "\n").encode("utf-8"))

        descriptor = json.loads(files[self.backend.EDITABLE_DESCRIPTOR])
        self.assertEqual(
            descriptor,
            {
                "schema_version": 1,
                "source_root": str(self.project.resolve()),
                "source_path": source_path,
            },
        )

        site_directory = self.workspace / "editable-site"
        site_directory.mkdir()
        with zipfile.ZipFile(wheel_path) as archive:
            archive.extractall(site_directory)
        self.assertEqual(self._run_import(site_directory), "wheel-build")

        self.probe.write_text("VALUE = 'source-edited'\n")
        self.assertEqual(self._run_import(site_directory), "source-edited")

    def test_standard_wheel_import_survives_removing_source_tree(self):
        wheel_path = self._build_standard_wheel()
        self.probe.write_text("VALUE = 'source-edited-after-build'\n")
        shutil.rmtree(self.project / "src")

        site_directory = self.workspace / "standard-site"
        site_directory.mkdir()
        with zipfile.ZipFile(wheel_path) as archive:
            archive.extractall(site_directory)
        self.assertEqual(self._run_import(site_directory), "wheel-build")

    def test_editable_build_rejects_control_newline_in_source_path(self):
        bad_project = self.workspace / "fixture\nwith-newline"
        self._copy_fixture(bad_project)
        self.backend.ROOT = bad_project
        wheel_directory = self.workspace / "rejected-dist"

        with self.assertRaisesRegex(ValueError, "control characters"):
            self.backend.build_editable(wheel_directory)
        self.assertFalse(wheel_directory.exists())


if __name__ == "__main__":
    unittest.main()
