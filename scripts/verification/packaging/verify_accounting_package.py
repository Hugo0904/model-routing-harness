#!/usr/bin/env python3
"""Rebuild own archive and replay saved consumer shapes, no native/provider."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
import argparse,hashlib,json,os,subprocess,sys,tempfile,time

BOOTSTRAP = r'''import copy,io,json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])  # actual newly prepared archive, not repo source
from mrh.presentation import cli; from mrh.infrastructure import settings; from mrh.adapters.providers import typesafe
from mrh.infrastructure.store import Store
class Host:
    synthetic=True
    def __init__(self):self.calls=0
    def resolve(self,event):self.calls+=1;raise RuntimeError("synthetic unavailable")
class HTTP:
    synthetic=True
    def __init__(self):self.calls=0
    def request(self,*args):self.calls+=1;raise AssertionError("HTTP must not run")
keys=[]
def key():keys.append(1);return "dummy-unused"
host,http=Host(),HTTP()
path=Path(sys.argv[2]);pre,post=json.loads(Path(sys.argv[3]).read_text())
def invoke(event,production=False):
    out,err=io.StringIO(),io.StringIO()
    dependencies={"credential_resolver":key}
    if not production:dependencies.update(host_resolver=host,transport=http)
    assert cli.main(["hook","--settings",str(path)],stdin=io.StringIO(json.dumps(event)),stdout=out,stderr=err,runtime_dependencies=dependencies)==0
    assert json.loads(out.getvalue())=={}
for event in (pre,pre,post,post):invoke(event)
assert host.calls==0
unknown=[]
for event in (pre,post):
    value=copy.deepcopy(event);value["tool_use_id"]+="-unknown"
    value["tool_input"].pop("model");value["tool_input"].pop("reasoning_effort")
    unknown.append(value)
for event in (unknown[0],unknown[0],unknown[1],unknown[1]):invoke(event)
store=Store(path.parent/"events.sqlite3");stats=store.stats(True)
assert stats["proposals"]==2 and stats["outcomes"]=={"explicit_model":1,"missing_role_protection":1}
assert stats["synthetic_attempts"]==0 and stats["simulated_children"]==2
assert stats["confirmed_children"]==0 and stats["actual_models"]=={}
assert keys==[] and http.calls==0
outputs=[]
for option in ("--json","--plain"):
    output=io.StringIO()
    assert cli.main(["stats","--db",str(store.path),"--synthetic",option],stdout=output,stderr=io.StringIO())==0
    outputs.append(output.getvalue())
assert json.loads(outputs[0])==stats and store.stats(True)==stats
assert "explicit_model: 1" in outputs[1] and "missing_role_protection: 1" in outputs[1]
assert store.stats()["proposals"]==0
# Distinct production-unknown facts use the same archive and actual default
# factory. Block any accidental transport call before it could open a socket.
production_path=path.parent.parent/"production-state/settings.json"
settings.init(production_path);settings.update(production_path,enabled=True,task_export_permitted=True,allowed_workspaces=[pre["cwd"]])
path=production_path;live_http=[]
def no_network(*args):live_http.append(1);raise AssertionError("production HTTP prohibited")
typesafe.HttpTransport.request=no_network
for event in unknown:
    value=copy.deepcopy(event);value["tool_use_id"]+="-reported";invoke(value,True)
live=Store(path.parent/"events.sqlite3").stats()
assert live["proposals"]==1 and live["outcomes"]=={"missing_role_protection":1} and live["reported_children"]==1
assert live["jev_attempts"]==0 and live["confirmed_children"]==0 and live["actual_models"]=={}
assert keys==[] and live_http==[]
print(json.dumps({"synthetic_stats":stats,"production_unknown_stats":live,"provider_key_resolutions":len(keys),"synthetic_transport_calls":http.calls,"production_transport_calls":len(live_http),"explicit_host_resolution_calls":0,"unknown_host_resolution_calls":host.calls,"stats_reads_do_not_increment":True,"public_cli_used":True,"factory":"existing TypesafeClassifier, not replacement classifier","synthetic_dependency_boundary":"code-level host/HTTP injection; production unknown HTTP explicitly blocked"}))
'''


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--evidence-prefix", choices=("e5r","e6"), default="e6")
    prefix=parser.parse_args().evidence_prefix
    start=time.monotonic();source=Path(__file__).resolve().parents[3];rows=[]
    with tempfile.TemporaryDirectory(prefix="mrh-"+prefix+"-package-") as alias:
        scratch=Path(alias).resolve();work=scratch/"work";work.mkdir();home=scratch/"home";home.mkdir()
        env={"PATH":"/usr/bin:/bin:/usr/sbin:/sbin","HOME":str(home),"LANG":"en_US.UTF-8"}
        env['PYTHONDONTWRITEBYTECODE'] = '1'
        def run(args,input=None):
            began=time.monotonic();result=subprocess.run(args,input=input,env=env,cwd=work,text=True,capture_output=True,timeout=30)
            rows.append({"command":args,"exit_code":result.returncode,"wall_seconds":round(time.monotonic()-began,3)})
            if result.returncode:raise RuntimeError("accounting_package_smoke_failed:"+result.stderr[:200])
            return result.stdout
        venv=scratch/"venv";run([sys.executable, "-B","-m","venv",str(venv)])
        python=venv/"bin/python";executable=venv/"bin/mrh"
        run([str(python), "-B","-m","pip","--no-cache-dir","install","--no-index","--no-deps","--no-build-isolation",str(source)])
        bundle=scratch/"bundle";state=scratch/"state/settings.json"
        prepared=json.loads(run([str(executable),"plugin","prepare","--root",str(bundle),"--settings",str(state)]))
        assert prepared["live_routing_ready"] is False and prepared["readiness_reason"]=="missing_role_protection"
        archive=bundle/"plugins/model-routing-harness/runtime.pyz"
        archive_hash=hashlib.sha256(archive.read_bytes()).hexdigest()
        installed=json.loads(run([str(python), "-B","-I","-c","import importlib.metadata,json,mrh;print(json.dumps({'version':importlib.metadata.version('model-routing-harness'),'module':mrh.__file__}))"]))
        old=json.loads((source/"tests/fixtures/e5-shell-plugin.json").read_text())
        events=[r["event"] for c in old["cases"] if c["scenario"]=="explicit" for r in c["injected_runtime_events"]]
        assert len(events)==2
        saved=scratch/"saved-events.json";saved.write_text(json.dumps(events))
        neutral=json.loads(run([prepared["artifact"]["python"], "-B","-I",str(archive.parent/"launcher.py")],json.dumps(events[0])))
        assert neutral=={} and not (state.parent/"events.sqlite3").exists()
        run([str(executable),"settings","configure","--path",str(state),"--allow-workspace",events[0]["cwd"],"--permit-task-export"])
        run([str(executable),"settings","enable","--path",str(state)])
        bootstrap=scratch/"bootstrap.py";bootstrap.write_text(BOOTSTRAP)
        accounting=json.loads(run([prepared["artifact"]["python"], "-B","-I",str(bootstrap),str(archive),str(state),str(saved)]))
        result={"evidence_kind":"offline_installed_package_new_archive_saved_native_shape_replay","installed_package":installed,
          "archive_sha256":archive_hash,"artifact":prepared["artifact"],"accounting":accounting,"commands":rows,
          "raw_input_source":"tests/fixtures/e5-shell-plugin.json deidentified explicit Pre/Post fixture; offline replay, not original native evidence",
          "old_E5_native_archive_sha256":old["installed_runtime_sha256"],"new_native_install_execution":False,
          "real_provider_requests":0,"formal_hook_changes":False,"credential_environment_forwarded":False,
          "elapsed_scope":"venv/package/archive preparation, public entry replay and owned cleanup"}
    result["temporary_files_removed"]=not Path(alias).exists();result["elapsed_seconds"]=round(time.monotonic()-start,3)
    (source/"runtime/verification").mkdir(parents=True,exist_ok=True)
    (source/("runtime/verification/"+prefix+"-package.json")).write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps({"version":installed["version"],"archive_sha256":archive_hash,"proposals":accounting["synthetic_stats"]["proposals"],"receipts":accounting["synthetic_stats"]["simulated_children"],"key_resolutions":accounting["provider_key_resolutions"],"elapsed_seconds":result["elapsed_seconds"],"cleanup":result["temporary_files_removed"]}))

if __name__=="__main__":main()
