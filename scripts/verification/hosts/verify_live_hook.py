#!/usr/bin/env python3
"""Trusted owned producer launch; actual native Hook subprocess, no live API."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
import argparse
import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import time
import uuid

PROJECT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT/"src"))
from mrh.infrastructure import settings
from mrh.infrastructure.store import Store


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--owned-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.owned_root.resolve(strict=True)
    assert json.loads((root/"OWNED.json").read_text())["owner"] == "MRH-001-E8"
    assert subprocess.check_output(["git","rev-parse","HEAD"],cwd=root/"source",text=True).strip() == "01fc69f4026735edfdf6789820549727a4867b11"
    lineage = json.loads((PROJECT/"integrations/codex-live-hook/source.json").read_text())
    for entry in lineage["patches"]:
        assert hashlib.sha256((PROJECT/entry["path"]).read_bytes()).hexdigest() == entry["sha256"]
    for name, digest in lineage["source_files"].items():
        assert hashlib.sha256((root/"source"/name).read_bytes()).hexdigest() == digest
    metadata = json.loads((root/"binaries.json").read_text())
    candidates = [s for s in metadata["rust-suites"].values() if s["kind"]=="lib" and s["package-name"]=="codex-core"]
    assert len(candidates)==1
    binary = Path(candidates[0]["binary-path"])
    run_metadata = json.loads((root/"run-binaries.json").read_text())
    assert str(binary) in [entry["binary-path"] for entry in run_metadata["rust-binaries"].values()]
    assert binary.is_absolute() and binary.resolve().is_relative_to(root/"target") and not binary.is_symlink()
    binary_hash = hashlib.sha256(binary.read_bytes()).hexdigest()
    bootstrap = root/"bootstrap.py"
    shutil.copyfile(PROJECT/"scripts/fixtures/e8_hook_bootstrap.py", bootstrap); bootstrap.chmod(0o600)
    registration = {"registration_id":str(uuid.uuid4()),"producer":{"path":str(binary),"sha256":binary_hash},
                    "bootstrap":{"path":str(bootstrap),"sha256":hashlib.sha256(bootstrap.read_bytes()).hexdigest()},
                    "python":sys.executable,"package_root":str(PROJECT/"src"),"source_lineage":lineage}
    context = root/"context.json"; context.write_text(json.dumps(registration)); context.chmod(0o600)
    path = root/"state/settings.json"
    settings.init(path); settings.update(path,enabled=True,task_export_permitted=True,allowed_workspaces=[str(root)],policy={"top_mode":"Main"})
    lockpath = root/"launch.lock";lockpath.touch(mode=0o600)
    environment = {"PATH":str(root/"tools")+os.pathsep+str(root/"cargo/bin")+os.pathsep+os.defpath,
                   "CARGO_HOME":str(root/"cargo"),"RUSTUP_HOME":str(root/"rustup"),"RUSTUP_TOOLCHAIN":"1.95.0",
                   "HOME":str(root/"home"),"CODEX_HOME":str(root/"home/.codex"),"TMPDIR":str(root/"tmp"),
                   "LANG":"en_US.UTF-8","MRH_E8_CONTEXT":str(context),"CODEX_MRH_PENDING_EXPORT_V1":"1","PYTHONDONTWRITEBYTECODE":"1"}
    started = time.monotonic()
    with lockpath.open("r+") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        argv = [str(root/"tools/just"),"test","--binaries-metadata",str(root/"run-binaries.json"),
                "--run-ignored","only","-E","test(=tools::registry::live_export_tests::e8_live_registry_hook_subprocess_control)","--no-capture","--retries","0"]
        result = subprocess.run(argv,cwd=root/"source/codex-rs",env=environment,text=True,capture_output=True,timeout=120)
    (root/"live-test.log").write_text(result.stdout+"\n"+result.stderr)
    (root/"live-run-result.json").write_text(json.dumps({"argv":argv,"exit_code":result.returncode,
          "elapsed_seconds":round(time.monotonic()-started,3),"log":"live-test.log"},indent=2)+"\n")
    assert hashlib.sha256(binary.read_bytes()).hexdigest()==binary_hash
    for name, digest in lineage["source_files"].items():
        assert hashlib.sha256((root/"source"/name).read_bytes()).hexdigest() == digest
    assert result.returncode==0, result.stdout[-2500:]+result.stderr[-2500:]
    native = json.loads((root/"native-results.json").read_text())
    # The Rust fixture always quotes each word, including shell-safe paths.
    expected_command = " ".join("'"+str(p).replace("'", "'\\''")+"'" for p in (sys.executable,bootstrap,context))
    assert native["registered_command"] == expected_command
    assert native["registration_key"] and native["registration_current_hash"]
    observations = [json.loads(row) for row in (root/"hook-observations.jsonl").read_text().splitlines()]
    stats = Store(path.parent/"events.sqlite3").stats(True)
    assert len(observations)==9 and native["controlled_handler_calls"]==6
    assert [o["transport_calls"] for o in observations]==[1,0,1,0,0,0,0,1,0]
    assert [o["deny_emitted"] for o in observations]==[True,True,True,False,False,False,False,False,False]
    assert stats["proposals"]==7 and stats["synthetic_attempts"]==3 and stats["confirmed_children"]==0 and stats["actual_models"]=={}
    assert Store(path.parent/"events.sqlite3").stats()["proposals"]==0
    assert stats["outcomes"]["top_main_requested"]==2 and stats["outcomes"]["typesafe_network_error"]==1
    evidence = {"kind":"actual source ToolRegistry -> native trusted Hook engine -> subprocess MRH -> same dispatch",
                "base_revision":"01fc69f4026735edfdf6789820549727a4867b11","registration":registration,
                "source_lineage":lineage,"test_argv":argv,
                "producer_sha256":binary_hash,"native":native,"hook_observations":observations,"synthetic_stats":stats,
                "real_provider_requests":0,"provider_partition":"synthetic in-process HTTP with dummy credential",
                "preserve_child_boundary":"controlled handler counter; no actual child graph/provider",
                "installed_host_changed":False,"production_resolver_changed":False,"elapsed_seconds":round(time.monotonic()-started,3)}
    args.output.write_text(json.dumps(evidence,indent=2)+"\n")
    print(json.dumps({"native_dispatches":9,"main_blocks":3,"handler_entries":6,"synthetic_attempts":3,
                      "elapsed_seconds":evidence["elapsed_seconds"],"real_provider_requests":0}))


if __name__ == "__main__":
    main()
