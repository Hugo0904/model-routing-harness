"""Small stdlib PEP 517 wheel backend, enabling credential-free offline install."""
import base64
import csv
import hashlib
import io
from pathlib import Path
import tomllib
import zipfile

ROOT = Path(__file__).resolve().parent


def metadata():
    p = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    name = p["name"].replace("-", "_")
    dist = f'{name}-{p["version"]}.dist-info'
    content = {f"{dist}/METADATA": (f'Metadata-Version: 2.1\nName: {p["name"]}\nVersion: {p["version"]}\n'
                                      f'Requires-Python: {p["requires-python"]}\nSummary: {p["description"]}\n\n').encode(),
               f"{dist}/WHEEL": b"Wheel-Version: 1.0\nGenerator: mrh-stdlib\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
               f"{dist}/entry_points.txt": ("[console_scripts]\n" + "".join(f"{k} = {v}\n" for k, v in p["scripts"].items())).encode()}
    return name, p["version"], dist, content


def get_requires_for_build_wheel(config_settings=None):
    return []


def prepare_metadata_for_build_wheel(metadata_directory, config_settings=None):
    _, _, dist, files = metadata()
    root = Path(metadata_directory)
    for name, data in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    return dist


def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):
    name, version, dist, files = metadata()
    source = ROOT / "src"
    for p in sorted((source / "mrh").rglob("*.py")):
        files[p.relative_to(source).as_posix()] = p.read_bytes()
    record = io.StringIO(newline="")
    writer = csv.writer(record, lineterminator="\n")
    for filename, data in sorted(files.items()):
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
        writer.writerow([filename, "sha256=" + digest, len(data)])
    writer.writerow([f"{dist}/RECORD", "", ""])
    files[f"{dist}/RECORD"] = record.getvalue().encode()
    filename = f"{name}-{version}-py3-none-any.whl"
    destination = Path(wheel_directory)
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination / filename, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            archive.writestr(name, data)
    return filename
