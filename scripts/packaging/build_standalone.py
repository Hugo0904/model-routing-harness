#!/usr/bin/env python3
"""Developer build entry; normal bundled MRH never runs this downloader."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import argparse
import json
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from mrh_bundle import build

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--cache', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--archive', type=Path, required=True)
parser.add_argument('--download', action='store_true', help='fetch only fixed official hash-pinned build inputs')
args = parser.parse_args()
print(json.dumps(build(args.cache, args.output, args.archive, download=args.download), indent=2))
