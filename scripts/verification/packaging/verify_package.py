#!/usr/bin/env python3
"""Offline installed-entry smoke in an owned temporary venv; no provider calls."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
import datetime
import argparse
import json
import os
import subprocess
import tempfile
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-prefix", choices=("e2", "e3"), default="e3")
    args = parser.parse_args()
    start = time.monotonic()
    root = Path(__file__).resolve().parents[3]
    with tempfile.TemporaryDirectory(prefix="mrh-package-") as scratch:
        scratch = Path(scratch)
        venv = scratch / "venv"
        subprocess.run([sys.executable, "-B", "-m", "venv", str(venv)], check=True, capture_output=True, timeout=30)
        python, executable = venv / "bin/python", venv / "bin/mrh"
        env = {k: os.environ[k] for k in ("PATH", "HOME", "TMPDIR", "LANG") if k in os.environ}
        env['PYTHONDONTWRITEBYTECODE'] = '1'
        install = subprocess.run([str(python), "-B", "-m", "pip", "--no-cache-dir", "install", "--no-index", "--no-deps",
                                  "--no-build-isolation", str(root)], env=env, cwd=scratch,
                                 text=True, capture_output=True, timeout=30)
        if install.returncode:
            print(install.stderr, file=sys.stderr)
            return install.returncode
        db = scratch / "facts.sqlite3"
        commands = [[str(executable), "demo", "--db", str(db), "--json"],
                    [str(python), "-B", "-m", "mrh", "stats", "--db", str(db), "--synthetic", "--json"],
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
        provider_fixture = '''
import json, sys
from mrh.adapters.providers.typesafe import TypesafeClassifier, HttpResponse
from mrh.adapters.providers.typesafe_protocol import PINNED_MODEL
from mrh.routing.types import Proposal
from mrh.application.service import process
from mrh.infrastructure.store import Store
from mrh.application.simulation import demo_policy, demo_capabilities
class Fake:
    synthetic = True
    def request(self, body, headers, deadline, enter):
        enter()
        assert body["model"] == PINNED_MODEL
        return HttpResponse(200, json.dumps({"model": PINNED_MODEL,
          "usage": {"input_tokens":100,"output_tokens":2},
          "answers":{"tier":{"type":"choice","choice":"top","confidence":0.6,
          "probabilities":{"light":0.1,"small":0.1,"mid":0.1,"top":0.7}}}}).encode())
store = Store(sys.argv[1])
p = Proposal("codex","simulation","package","fixture","provider",{"message":"offline example"},True)
client = TypesafeClassifier(enabled=True, task_export_permitted=True,
                           credential_resolver=lambda:"fake-offline-key",transport=Fake())
assert process(p,demo_policy(),demo_capabilities(),store,client).action == "return_to_main"
assert store.stats()["jev_attempts"] == 0
print(json.dumps(store.stats(True)))
'''
        provider = subprocess.run([str(python), "-B", "-c", provider_fixture, str(db)], text=True, capture_output=True,
                                  env=env, cwd=scratch, timeout=10, check=True)
        provider_stats = json.loads(provider.stdout)
        assert provider_stats["jev"]["source"] == "explicit_synthetic_offline_transport"
        assert provider_stats["jev"]["input_tokens"] == 100
        installed_stats = subprocess.run([str(executable), "stats", "--db", str(db), "--synthetic", "--json"],
                                        text=True, capture_output=True, env=env, cwd=scratch, timeout=10, check=True)
        assert json.loads(installed_stats.stdout) == provider_stats
        if args.evidence_prefix == "e3":
            for i, width in [(3, 80), (4, 28)]:
                rendered = subprocess.run([str(executable), "stats", "--db", str(db), "--synthetic", "--plain", "--width", str(width)],
                                         text=True, capture_output=True, env=env, cwd=scratch, timeout=10, check=True)
                results[i] = rendered.stdout
            assert max(map(len, results[4].splitlines())) <= 28
        (root / "examples").mkdir(exist_ok=True)
        (root / "examples/synthetic-stats.json").write_text(json.dumps(synthetic, indent=2) + "\n")
        (root / "examples/synthetic-provider-stats.json").write_text(json.dumps(provider_stats, indent=2) + "\n")
        for width, output in [(80, results[3]), (28, results[4])]:
            (root / f"docs/evidence/{args.evidence_prefix}-terminal-{width}.txt").write_text(output)
        result = {"schema_version": 1, "evidence_kind": "isolated_offline_installed_package",
                  "recorded_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  "python": sys.version.split()[0], "pip_install_exit": install.returncode,
                  "entrypoints": ["installed mrh", "installed python -m mrh"],
                  "synthetic_stats_consistent": True, "live_proposals": 0, "ansi_in_json": False,
                  "narrow_width": 28, "global_installation": False, "provider_requests": 0,
                  "installed_typesafe_fake_transport": True, "provider_telemetry_json_consistent": True,
                  "elapsed_seconds": round(time.monotonic() - start, 3)}
    (root / f"docs/evidence/{args.evidence_prefix}-package.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
