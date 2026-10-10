#!/usr/bin/env python3
"""E5 owned native-plugin proof. All provider/context injection is synthetic."""
import argparse,copy,hashlib,json,os,subprocess,sys,threading,time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from verify_host import CATALOG_HASHES,OwnedScratch,Fixture,Rpc,trust_fixture,curate_events

BOOTSTRAP = r'''import io,json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])  # installed runtime archive, never repository source
from mrh.cli import main
from mrh.typesafe import HttpResponse
from mrh.typesafe_protocol import PINNED_MODEL
scenario=Path(sys.argv[3]).read_text().strip()
event=json.load(sys.stdin)
class Host:
    synthetic=True
    def resolve(self,event):
        return {"configuration_known":True,"main_model":"mrh-synthetic-parent","main_effort":"low",
                "original_model":"mrh-synthetic-parent","original_effort":"low","original_resolution_known":True,
                "roles":{"default":{"known":True,"rewrite_allowed":True}},
                "models":{"mrh-synthetic-fixed":{"available":True,"efforts":["high"]}}}
class HTTP:
    synthetic=True
    calls=0
    def request(self,body,headers,deadline,enter):
        enter();self.calls+=1
        assert body["model"]==PINNED_MODEL and set(body)=={"model","state","questions"}
        assert headers["Authorization"]=="Bearer mrh-fixture-dummy"
        if scenario=="failure":raise OSError("synthetic failure")
        return HttpResponse(200,json.dumps({"model":PINNED_MODEL,"usage":{"input_tokens":1,"output_tokens":1},
           "answers":{"tier":{"type":"choice","choice":"top","confidence":.9,
           "probabilities":{"light":.1,"small":.1,"mid":.1,"top":.7}}}}).encode())
http=HTTP();keys=[]
def key():keys.append(1);return "mrh-fixture-dummy"
out,err=io.StringIO(),io.StringIO()
main(["hook","--settings",sys.argv[2]],stdin=io.StringIO(json.dumps(event)),stdout=out,stderr=err,
     runtime_dependencies={"host_resolver":Host(),"transport":http,"credential_resolver":key})
result=json.loads(out.getvalue())
safe={k:event.get(k) for k in ("hook_event_name","session_id","turn_id","tool_use_id","tool_name","tool_input","tool_response","cwd","model")}
with Path(sys.argv[4]).open("a") as log:log.write(json.dumps({"event":safe,"output":result,"http_calls":http.calls,"key_resolutions":len(keys),"classifier_factory":"TypesafeClassifier; installed runtime", "diagnostic":err.getvalue().strip()})+"\n")
print(out.getvalue(),end="")
'''


def inspect(binary,catalog_path):
    started=time.monotonic();fixture=Fixture("failure");native=[];cases=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*_):pass
        def do_POST(self):
            assert self.path.endswith("/responses") and self.headers.get("Authorization") is None
            size=int(self.headers["Content-Length"]);assert size<=2_000_000
            output=fixture.response(json.loads(self.rfile.read(size)),self.headers)
            rid="response-"+str(len(fixture.requests))
            events=[{"type":"response.created","response":{"id":rid,"status":"in_progress","output":[]}}]
            for index,item in enumerate(output):
                events.extend([{"type":"response.output_item.added","output_index":index,"item":item},
                               {"type":"response.output_item.done","output_index":index,"item":item}])
            events.append({"type":"response.completed","response":{"id":rid,"status":"completed","output":output,
                          "usage":{"input_tokens":1,"output_tokens":1,"total_tokens":2,"input_tokens_details":{"cached_tokens":0}}}})
            payload="".join("data: "+json.dumps(x)+"\n\n" for x in events).encode()
            self.send_response(200);self.send_header("Content-Type","text/event-stream")
            self.send_header("Content-Length",str(len(payload)));self.end_headers();self.wfile.write(payload)
    server=ThreadingHTTPServer(("127.0.0.1",0),Handler);server.daemon_threads=True
    serving=threading.Thread(target=server.serve_forever,daemon=True);serving.start()
    scope=OwnedScratch();result={"status":"not_complete","native_commands":native,"cases":cases,
         "evidence_kind":"installed_native_plugin_scripted_loopback_provider",
         "real_provider_requests":0,"formal_global_changes":False,"desktop_ui_validation":False,
         "synthetic_dependencies":"process bootstrap into installed runtime archive; production host resolver remains unknown"}
    try:
      with scope as alias:
        scratch=alias.resolve();home=scratch/"home";work=scratch/"workspace";home.mkdir();work.mkdir()
        env={"PATH":str(Path(binary).parent)+":/usr/bin:/bin:/usr/sbin:/sbin","HOME":str(scratch),"CODEX_HOME":str(home),"LANG":"en_US.UTF-8","TERM":"xterm-256color"}
        def command(args,check=True):
            run=subprocess.run(args,cwd=work,env=env,capture_output=True,text=True,timeout=30)
            row={"command":args,"exit_code":run.returncode,"stdout":run.stdout,"stderr":run.stderr}
            native.append(row)
            if check and run.returncode:raise RuntimeError("native_or_package_operation_refused")
            return json.loads(run.stdout) if run.stdout.strip().startswith(("{","[")) else run.stdout
        version=command([binary,"--version"]).strip().split()[-1];result["version"]=version;result["binary"]=binary
        original=catalog_path.read_bytes();assert hashlib.sha256(original).hexdigest()==CATALOG_HASHES[version]
        entry=next(x for x in json.loads(original)["models"] if x["slug"]=="gpt-6.1-sol")
        aliases=[]
        for suffix,effort in (("parent","low"),("fixed","high"),("explicit","high")):
            value=copy.deepcopy(entry);value.update(slug="mrh-synthetic-"+suffix,display_name="MRH synthetic "+suffix,description="Synthetic provider only",upgrade=None,availability_nux=None,default_reasoning_level=effort,tool_mode=None,multi_agent_version="v1",use_responses_lite=False,supports_search_tool=False);aliases.append(value)
        catalog=scratch/"models.json";catalog.write_text(json.dumps({"models":aliases}))
        result["catalog"]={"source_tag":"rust-v"+version,"sha256":hashlib.sha256(original).hexdigest(),"overrides":{"tool_mode":None,"multi_agent_version":"v1","use_responses_lite":False,"supports_search_tool":False},"actual_model_execution":False}
        (home/"config.toml").write_text('model="mrh-synthetic-parent"\nmodel_reasoning_effort="low"\nmodel_provider="mrh_fixture"\nmodel_catalog_json='+json.dumps(str(catalog))+'\nsandbox_mode="workspace-write"\napproval_policy="never"\n[model_providers.mrh_fixture]\nname="MRH loopback"\nbase_url="http://127.0.0.1:'+str(server.server_address[1])+'/v1"\nrequires_openai_auth=false\nwire_api="responses"\nrequest_max_retries=0\nstream_max_retries=0\n[analytics]\nenabled=false\n')
        third=scratch/"third.py";third_log=scratch/"third.jsonl";third_mode=scratch/"third-mode";third_mode.write_text("benign")
        third.write_text('import json,os,sys\nfrom pathlib import Path\ne=json.load(sys.stdin);mode=Path(sys.argv[2]).read_text()\nwith Path(sys.argv[1]).open("a") as f:f.write(json.dumps({"tool_use_id":e.get("tool_use_id"),"mode":mode,"revision":os.environ.get("THIRD_PARTY_REV","1")})+"\\n")\nout={"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"Independent fixture denial"}} if mode=="deny" else {"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"allow","updatedInput":{**e["tool_input"],"model":"mrh-synthetic-explicit","reasoning_effort":"high"}}} if mode=="rewrite" else {}\nprint(json.dumps(out))\n')
        import shlex
        third_command=shlex.join([sys.executable,str(third),str(third_log),str(third_mode)])
        shared=home/"hooks.json";shared.write_text(json.dumps({"hooks":{"PreToolUse":[{"matcher":"^spawn_agent$","hooks":[{"type":"command","command":third_command,"timeout":5}]}]}}))
        original_shared=shared.read_bytes();config_bytes=(home/"config.toml").read_bytes()
        venv=scratch/"venv";command([sys.executable,"-m","venv",str(venv)])
        python=venv/"bin/python";mrh=venv/"bin/mrh"
        source=Path(__file__).resolve().parents[1]
        command([str(python),"-m","pip","--no-cache-dir","install","--no-index","--no-deps","--no-build-isolation",str(source)])
        bundle=scratch/"bundle";state=scratch/"state/settings.json"
        prepared=command([str(mrh),"plugin","prepare","--root",str(bundle),"--settings",str(state)])
        result["prepared_artifact"]=prepared["artifact"]
        native_add=lambda *args:command([binary,"--no-daemon","plugin",*args,"--json"])
        result["marketplace_add"]=native_add("marketplace","add",str(bundle))
        plugin_id="model-routing-harness@model-routing-harness-local"
        installed=native_add("add",plugin_id);result["plugin_add"]=installed
        result["plugin_repeat_add"]=native_add("add",plugin_id)
        result["plugin_list"]=native_add("list")
        installed_path=Path(installed["installedPath"]);result["installed_path"]=str(installed_path)
        result["installed_manifest"]=json.loads((installed_path/"plugin.json").read_text())
        assert result["installed_manifest"]["version"]==prepared["artifact"]["version"]
        actual_runtime=installed_path/"runtime.pyz"
        assert hashlib.sha256(actual_runtime.read_bytes()).hexdigest()==prepared["artifact"]["files"]["plugins/model-routing-harness/runtime.pyz"]
        result["installed_runtime_sha256"]=hashlib.sha256(actual_runtime.read_bytes()).hexdigest()
        assert shared.read_bytes()==original_shared and (home/"config.toml").read_bytes()!=b""
        # Native registration may update its own plugin config; product code never
        # restores that host-owned file. Shared hooks stay byte-exact.
        def start_rpc():
            rpc=Rpc(binary,env,work,scope);rpc.request("initialize",{"clientInfo":{"name":"mrh-e5","version":"1"},"capabilities":{"experimentalApi":True}});rpc.write({"method":"initialized"});return rpc
        def hook_list(rpc):
            reply=rpc.request("hooks/list",{"cwd":str(work)})
            entries=[h for row in reply["result"]["data"] for h in row["hooks"]]
            assert len([h for h in entries if h.get("pluginId")==plugin_id])==2,"repeated_install_duplicate_hooks"
            return reply
        def one(rpc,name,expected=None):
            fixture.scenario="explicit" if name=="explicit" else "failure";fixture.step=0
            if control.exists():control.write_text(name)
            a,b=len(rpc.events),len(fixture.requests)
            log_count=len(log.read_text().splitlines()) if log.exists() else 0
            third_count=len(third_log.read_text().splitlines()) if third_log.exists() else 0
            parent=rpc.request("thread/start",{"cwd":str(work),"model":"mrh-synthetic-parent","modelProvider":"mrh_fixture","sandbox":"workspace-write","approvalPolicy":"never"})["result"]["thread"]["id"]
            done=rpc.turn(parent,"MRH_PARENT_"+name+" native plugin fixture")
            events=rpc.events[a:];ids={i for e in events if e.get("method")=="item/completed" for i in e.get("params",{}).get("item",{}).get("receiverThreadIds",[])}
            rpc.await_children(ids);events=rpc.events[a:];requests=fixture.requests[b:]
            parent_read=rpc.request("thread/read",{"threadId":parent,"includeTurns":False})["result"]["thread"]
            assert parent_read["model"]=="mrh-synthetic-parent" and parent_read["reasoningEffort"]=="low"
            assert all(r["model"]=="mrh-synthetic-parent" and r["reasoning"]["effort"]=="low" for r in requests if r["is_parent"])
            rows=[json.loads(x) for x in log.read_text().splitlines()[log_count:]] if log.exists() else []
            thirds=[json.loads(x) for x in third_log.read_text().splitlines()[third_count:]] if third_log.exists() else []
            children=[r for r in requests if not r["is_parent"]]
            if expected=="deny":assert not ids and not children
            if expected=="fixed":assert len(ids)==1 and len(children)==1 and children[0]["model"]=="mrh-synthetic-fixed" and children[0]["reasoning"]["effort"]=="high"
            if expected=="passthrough":assert len(ids)==1 and len(children)==1
            result_case={"scenario":name,"parent_id":parent,"completed_turn":done,"native_events":curate_events(events),"requests":requests,
                         "child_ids":sorted(ids),"injected_runtime_events":rows,"third_party_events":thirds,"parent_unchanged":True}
            cases.append(result_case);return result_case
        control=scratch/"scenario";log=scratch/"mrh.jsonl";control.write_text("disabled")
        rpc=start_rpc()
        try:
            result["before_trust_hooks"]=hook_list(rpc)
            assert all(h["trustStatus"]=="untrusted" for row in result["before_trust_hooks"]["result"]["data"] for h in row["hooks"])
            before=one(rpc,"before-trust","passthrough");assert before["third_party_events"]==[] and before["injected_runtime_events"]==[]
        finally:rpc.close()
        result["original_trust_review"]=trust_fixture(binary,env,work,scope)
        rpc=start_rpc()
        try:
            result["trusted_original_hooks"]=hook_list(rpc)
            assert all(h["trustStatus"]=="trusted" for row in result["trusted_original_hooks"]["result"]["data"] for h in row["hooks"])
            after=one(rpc,"disabled-original","passthrough");assert len(after["third_party_events"])==1
            assert not (state.parent/"events.sqlite3").exists()
            runs=[e for e in after["native_events"] if e["method"]=="hook/completed" and str(installed_path/"hooks/hooks.json") in e["run"]["id"]]
            assert len(runs)==2 and all(e["run"]["status"]=="completed" for e in runs),"unmodified_launcher_native_execution_missing"
            result["unmodified_installed_launcher"]={"native_hook_runs":runs,"runtime_hash_matches_artifact":True,"disabled_output_neutral":True}
        finally:rpc.close()
        # Test-only process bootstrap changes this owned fixture definition.
        # It imports installed runtime bytes and injects HTTP/context into the
        # exact public CLI/reader/factory. It is not a production adapter.
        bootstrap=scratch/"bootstrap.py";bootstrap.write_text(BOOTSTRAP)
        hook_file=installed_path/"hooks/hooks.json"
        definition=json.loads(hook_file.read_text())
        injected_command=shlex.join([prepared["artifact"]["python"],"-I",str(bootstrap),str(actual_runtime),str(state),str(control),str(log)])
        for rows in definition["hooks"].values():rows[0]["hooks"][0]["command"]=injected_command
        hook_file.write_text(json.dumps(definition))
        result["bootstrap_trust_review"]=trust_fixture(binary,env,work,scope)
        policy=scratch/"policy.json"
        def configure(mode):
            policy.write_text(json.dumps({"top_mode":mode,"timeout_seconds":1,"fixed":{"model":"mrh-synthetic-fixed","effort":"high"},"tiers":{},"rates":{}}))
            return command([str(mrh),"settings","configure","--path",str(state),"--provider","typesafe","--policy",str(policy),"--allow-workspace",str(work),"--permit-task-export"])
        result["configured_disabled"]=configure("Main")
        rpc=start_rpc()
        try:
            result["trusted_injected_hooks"]=hook_list(rpc)
            c=one(rpc,"configured-disabled","passthrough");assert all(r["http_calls"]==r["key_resolutions"]==0 for r in c["injected_runtime_events"])
            result["enable"]=command([str(mrh),"settings","enable","--path",str(state)])
            c=one(rpc,"main","deny");assert sum(r["http_calls"] for r in c["injected_runtime_events"])==1
            configure("Fixed");c=one(rpc,"fixed","fixed");assert sum(r["http_calls"] for r in c["injected_runtime_events"])==1
            c=one(rpc,"explicit","passthrough");assert all(r["http_calls"]==r["key_resolutions"]==0 for r in c["injected_runtime_events"])
            one(rpc,"failure","passthrough")
            third_mode.write_text("deny");c=one(rpc,"co-deny","deny")
            result["co_denial_rewrite_observed"]=any(r["output"].get("hookSpecificOutput",{}).get("updatedInput") for r in c["injected_runtime_events"])
            third_mode.write_text("rewrite");one(rpc,"competing-rewrite")
            third_mode.write_text("benign")
            result["disable"]=command([str(mrh),"settings","disable","--path",str(state)])
            c=one(rpc,"disabled-again","passthrough");assert all(r["http_calls"]==r["key_resolutions"]==0 for r in c["injected_runtime_events"])
            assert shared.read_bytes()==original_shared
        finally:rpc.close()
        # Independent fixture writer edits its own Hook after MRH disable.
        revised=json.loads(shared.read_text());revised["hooks"]["PreToolUse"][0]["hooks"][0]["command"]="THIRD_PARTY_REV=2 "+third_command
        shared.write_text(json.dumps(revised));changed_shared=shared.read_bytes()
        result["third_update_trust_review"]=trust_fixture(binary,env,work,scope)
        rpc=start_rpc()
        try:
            c=one(rpc,"third-party-update","passthrough");assert c["third_party_events"][0]["revision"]=="2"
        finally:rpc.close()
        result["native_remove"]=native_add("remove",plugin_id)
        result["after_remove_list"]=native_add("list")
        assert not any(x["pluginId"]==plugin_id for x in result["after_remove_list"]["installed"]),"native_remove_readback_failed"
        assert shared.read_bytes()==changed_shared and state.exists()
        result["shared_hook_preservation"]={"unchanged_through_install_and_disable":True,"independent_later_update_preserved":True,"original_sha256":hashlib.sha256(original_shared).hexdigest(),"final_sha256":hashlib.sha256(changed_shared).hexdigest()}
        result["separate_state_preserved_after_native_remove"]=True
        stats=command([str(mrh),"stats","--db",str(state.parent/"events.sqlite3"),"--synthetic","--json"])
        result["synthetic_stats"]=stats
        result["live_stats"]=command([str(mrh),"stats","--db",str(state.parent/"events.sqlite3"),"--json"])
        assert result["live_stats"]["jev_attempts"]==0 and result["live_stats"]["confirmed_children"]==0
        result["status"]="passed"
      result["temporary_files_removed"]=not alias.exists()
    except Exception as exc:
      result["status"]="failed_or_unsupported";result["error_type"]=type(exc).__name__;result["error_code"]=str(exc)
      result["temporary_files_removed"]=not scope.path.exists()
    finally:
      server.shutdown();server.server_close();serving.join(2)
    result["server_stopped"]=not serving.is_alive();result["elapsed_seconds"]=round(time.monotonic()-started,3)
    result["elapsed_scope"]="package preparation, native CLI lifecycle, fixture operation and final cleanup"
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--binary",required=True);parser.add_argument("--catalog",type=Path,required=True);parser.add_argument("--output",type=Path,required=True);args=parser.parse_args()
    result=inspect(args.binary,args.catalog);args.output.write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps({"version":result.get("version"),"status":result["status"],"error":result.get("error_code"),"cases":[c["scenario"] for c in result["cases"]],"elapsed_seconds":result["elapsed_seconds"],"temporary_files_removed":result["temporary_files_removed"]}))
    return 0 if result["status"]=="passed" else 2

if __name__=="__main__":raise SystemExit(main())
