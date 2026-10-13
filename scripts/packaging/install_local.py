#!/usr/bin/env python3
"""Install (or upgrade) a built bundle at a fixed path so hook commands never change between versions.

  python3 scripts/packaging/install_local.py --bundle dist/model-routing-harness-X-macos-arm64 [--settings /abs/settings.json]

Puts the bundle at ~/.local/share/model-routing-harness/app, links ~/.local/bin/mrh to it, and (with
--settings) writes ~/.config/model-routing-harness/active-settings so `mrh ctrl` needs no --settings.
"""
import argparse
import os
import shutil
from pathlib import Path

HOME = Path.home()
parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("--bundle", type=Path, required=True)
parser.add_argument("--prefix", type=Path, default=HOME / ".local/share/model-routing-harness")
parser.add_argument("--bin", type=Path, default=HOME / ".local/bin")
parser.add_argument("--settings", type=Path)
args = parser.parse_args()

bundle = args.bundle.resolve()
if not (bundle / "mrh").is_file() or not (bundle / "runtime/bin/python3.11").is_file():
    raise SystemExit("not a built MRH bundle: " + str(bundle))
args.prefix.mkdir(parents=True, exist_ok=True)
app, staged, old = args.prefix / "app", args.prefix / "app.new", args.prefix / "app.old"
for leftover in (staged, old):
    shutil.rmtree(leftover, ignore_errors=True)
shutil.copytree(bundle, staged, symlinks=True)
if app.exists():
    app.rename(old)
staged.rename(app)
shutil.rmtree(old, ignore_errors=True)

link = args.bin / "mrh"
args.bin.mkdir(parents=True, exist_ok=True)
if link.is_symlink() or not link.exists():
    if link.is_symlink() and "model-routing-harness" not in os.readlink(link):
        raise SystemExit(f"{link} points elsewhere; not replacing it")
    link.unlink(missing_ok=True)
    link.symlink_to(app / "mrh")
else:
    raise SystemExit(f"{link} exists and is not a symlink; not replacing it")

if args.settings:
    pointer = HOME / ".config/model-routing-harness/active-settings"
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text(str(args.settings.resolve()) + "\n")
print("installed:", app)
print("python for hooks:", app / "runtime/bin/python3.11")
print("command:", link, "->", app / "mrh")
