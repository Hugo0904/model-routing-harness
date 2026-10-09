#!/usr/bin/env python3
"""Offline installed-entry smoke in an owned temporary venv; no provider calls."""
import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time


def main():
    start = time.monotonic()
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="mrh-package-") as scratch:
        scratch = Path(scratch)
        venv = scratch / "venv"
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True, capture_output=True, timeout=30)
        python, executable = venv / "bin/python", venv / "bin/mrh"
        env = {k: os.environ[k] for k in ("PATH", "HOME", "TMPDIR", "LANG") if k in os.environ}
        install = subprocess.run([str(python), "-m", "pip", "--no-cache-dir", "install", "--no-index", "--no-deps",
                                  "--no-build-isolation", str(root)], env=env, cwd=scratch,
                                 text=True, capture_output=True, timeout=30)
        if install.returncode:
            print(install.stderr, file=sys.stderr)
            return install.returncode
        db = scratch / "facts.sqlite3"
        commands = [[str(executable), "demo", "--db", str(db), "--json"],
                    [str(python), "-m", "mrh", "stats", "--db", str(db), "--synthetic", "--json"],
                    [str(executable), "stats", "--db", str(db), "--json"],
                    [str(executable), "stats", "--db", str(db), "--synthetic", "--plain", "--width", "80"],
                    [str(executable), "stats", "--db", str(db), "--synthetic", "--plain", "--width", "28"],
                    [str(executable), "doctor", "--plain", "--width", "80"]]
        results = []
        for command in commands:
            r = subprocess.run(command, text=True, capture_output=True, env=env, cwd=scratch, timeout=10, check=True)
            results.append(r.stdout)
        assert json.loads(results[0]) == json.loads(results[1])
        assert json.loads(results[2])["proposals"] == 0
        assert all("\x1b" not in x for x in results)
        assert max(map(len, results[4].splitlines())) <= 28
        synthetic = json.loads(results[0])
        (root / "examples").mkdir(exist_ok=True)
        (root / "examples/synthetic-stats.json").write_text(json.dumps(synthetic, indent=2) + "\n")
        for width, output in [(80, results[3]), (28, results[4])]:
            (root / f"docs/evidence/e2-terminal-{width}.txt").write_text(output)
        result = {"schema_version": 1, "evidence_kind": "isolated_offline_installed_package",
                  "recorded_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  "python": sys.version.split()[0], "pip_install_exit": install.returncode,
                  "entrypoints": ["installed mrh", "installed python -m mrh"],
                  "synthetic_stats_consistent": True, "live_proposals": 0, "ansi_in_json": False,
                  "narrow_width": 28, "global_installation": False, "provider_requests": 0,
                  "elapsed_seconds": round(time.monotonic() - start, 3)}
    (root / "docs/evidence/e2-package.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
