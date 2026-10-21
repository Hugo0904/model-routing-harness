#!/usr/bin/env python3
"""Only the owned E8 driver registers this bootstrap; no public activation."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import json

_context = json.loads(Path(sys.argv[1]).read_text())
sys.path.insert(0, _context["package_root"])
from mrh.adapters.hosts.isolated_live_hook import OwnedRegistration
from mrh.adapters.hosts.isolated_host_export import ExportError
from mrh.application.runtime import configured_event
from mrh.adapters.providers.typesafe import HttpResponse
from mrh.adapters.providers.typesafe_protocol import PINNED_MODEL


def main(context_path):
    output, exchange, transport_calls, keys = {}, None, [], []
    registration = OwnedRegistration(context_path)
    event = json.loads(sys.stdin.buffer.read(65537))
    scope = {key:event.get(key) for key in ("session_id", "turn_id", "tool_use_id")}
    class Transport:
        synthetic = True
        def request(self, body, headers, deadline, enter):
            exchange.check(event); enter(); transport_calls.append(1)
            if event["tool_use_id"] == "e8-midclose":
                exchange._lease["phase"] = "closed"; exchange._write()
            exchange.check(event)
            return HttpResponse(200, json.dumps({"model":PINNED_MODEL,"answers":{"tier":{
                "type":"choice","choice":"top","probabilities":{"light":.1,"small":.1,"mid":.1,"top":.7},"confidence":.9}}}).encode())
    class Unavailable:
        synthetic = True
        def resolve(self, value):
            raise ExportError("unavailable_live_export")
    def dummy():
        keys.append(1); return "explicit-e8-synthetic-dummy"
    try:
        try:
            exchange = registration.exchange(event)
        except ExportError:
            exchange = None
        output = configured_event(event, registration.root/"state/settings.json", host_resolver=exchange or Unavailable(),
                                  transport=Transport(), credential_resolver=dummy)
        if exchange:
            try:
                exchange.check(event)
            except ExportError:
                output = {}
    finally:
        if exchange:
            exchange.close()
    with (registration.root/"hook-observations.jsonl").open("a") as record:
        record.write(json.dumps({"scope":scope,"host_export_present":type(event.get("pending_delegation")) is dict,
                    "role_protection":event.get("pending_delegation",{}).get("facts",{}).get("role_protection"),
                    "transport_calls":len(transport_calls),"dummy_keys":len(keys),"deny_emitted":bool(output),
                    "source":"actual registered Hook stdin; provider synthetic"})+"\n")
    print(json.dumps(output))


if __name__ == "__main__":
    main(sys.argv[1])
