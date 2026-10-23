"""Small stdlib PEP 517/660 backend for offline wheel builds."""
import base64
import csv
import hashlib
import io
import json
from pathlib import Path
import tomllib
import zipfile

ROOT = Path(__file__).resolve().parent
EDITABLE_DESCRIPTOR = "model_routing_harness-editable.json"
EDITABLE_PTH = "model_routing_harness-editable.pth"


def package_files():
    source = ROOT / 'src'
    paths = list((source/'mrh').rglob('*.py'))
    paths += [p for p in (source/'mrh/resources').rglob('*') if p.is_file()]
    return {p.relative_to(source).as_posix():p.read_bytes() for p in paths}


def metadata():
    p = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    name = p["name"].replace("-", "_")
    dist = f'{name}-{p["version"]}.dist-info'
    content = {f"{dist}/METADATA": (f'Metadata-Version: 2.1\nName: {p["name"]}\nVersion: {p["version"]}\n'
                                      f'Requires-Python: {p["requires-python"]}\nSummary: {p["description"]}\nLicense: {p["license"]["text"]}\n\n').encode(),
               f"{dist}/LICENSE": (ROOT / "LICENSE").read_bytes(),
               f"{dist}/WHEEL": b"Wheel-Version: 1.0\nGenerator: mrh-stdlib\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
               f"{dist}/entry_points.txt": ("[console_scripts]\n" + "".join(f"{k} = {v}\n" for k, v in p["scripts"].items())).encode()}
    return name, p["version"], dist, content


def _prepared_metadata(metadata_directory, dist, default_files):
    if metadata_directory is None:
        return dict(default_files)

    root = Path(metadata_directory)
    nested_dist_info = root / dist
    if nested_dist_info.is_dir():
        dist_info = nested_dist_info
    elif root.name == dist and root.is_dir():
        dist_info = root
    else:
        dist_info = nested_dist_info
    if not dist_info.is_dir():
        raise ValueError(f"prepared metadata directory is missing {dist}")

    files = {}
    for path in sorted(dist_info.rglob("*")):
        if path.is_file():
            name = f"{dist}/{path.relative_to(dist_info).as_posix()}"
            if name != f"{dist}/RECORD":
                files[name] = path.read_bytes()
    return files


def _write_wheel(wheel_directory, filename, dist, files):
    files = dict(files)
    record_path = f"{dist}/RECORD"
    files.pop(record_path, None)

    record = io.StringIO(newline="")
    writer = csv.writer(record, lineterminator="\n")
    for path, data in sorted(files.items()):
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
        writer.writerow([path, "sha256=" + digest, len(data)])
    writer.writerow([record_path, "", ""])
    files[record_path] = record.getvalue().encode()

    destination = Path(wheel_directory)
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination / filename, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, data in sorted(files.items()):
            archive.writestr(path, data)
    return filename


def _editable_paths():
    root = Path(ROOT).resolve()
    source = (root / "src").resolve()
    if not source.is_dir():
        raise ValueError(f"editable source path is not a directory: {source}")

    root_text = str(root)
    source_text = str(source)
    if any(ord(character) < 0x20 or ord(character) == 0x7f
           for character in root_text + source_text):
        raise ValueError("editable source paths cannot contain control characters")
    return root_text, source_text


def get_requires_for_build_wheel(config_settings=None):
    return []


def get_requires_for_build_editable(config_settings=None):
    return []


def prepare_metadata_for_build_wheel(metadata_directory, config_settings=None):
    _, _, dist, files = metadata()
    root = Path(metadata_directory)
    for name, data in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    return dist


def prepare_metadata_for_build_editable(metadata_directory, config_settings=None):
    return prepare_metadata_for_build_wheel(metadata_directory, config_settings)


def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):
    name, version, dist, default_files = metadata()
    files = _prepared_metadata(metadata_directory, dist, default_files)
    files.update(package_files())
    filename = f"{name}-{version}-py3-none-any.whl"
    return _write_wheel(wheel_directory, filename, dist, files)


def build_editable(wheel_directory, config_settings=None, metadata_directory=None):
    name, version, dist, default_files = metadata()
    root_text, source_text = _editable_paths()
    files = _prepared_metadata(metadata_directory, dist, default_files)
    files[EDITABLE_PTH] = (source_text + "\n").encode("utf-8")
    descriptor = {
        "schema_version": 1,
        "source_root": root_text,
        "source_path": source_text,
    }
    files[EDITABLE_DESCRIPTOR] = (json.dumps(descriptor, ensure_ascii=False,
                                             sort_keys=True, indent=2) + "\n").encode("utf-8")
    filename = f"{name}-{version}-py3-none-any.whl"
    return _write_wheel(wheel_directory, filename, dist, files)
