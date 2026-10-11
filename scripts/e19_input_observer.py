#!/usr/bin/env python3
"""Temporary D45 literal-work observer. Always neutral; never product tracing."""
import json
import os
from pathlib import Path
import re
import sys


def observe(event, control, output):
    captured=None; reason='out_of_scope'
    if (type(event) is dict and event.get('hook_event_name')=='PreToolUse'
            and event.get('tool_name') in ('spawn_agent','collaborationspawn_agent')
            and event.get('cwd')==control['workspace'] and event.get('session_id')==control['session_id']):
        args=event.get('tool_input');ids={key:event.get(key) for key in ('session_id','turn_id','tool_use_id')}
        message=args.get('message') if type(args) is dict else None
        identity_ok=all(type(v) is str and len(v)<=256 and re.fullmatch(r'[A-Za-z0-9_.:/-]+',v) for v in ids.values())
        benign=(type(message) is str and 0<len(message.encode('utf-8'))<=8192
                and all(re.search(r'\b'+digit+r'\b',message) for digit in ('1','2','3'))
                and ('sort' in message.lower() or 'ascending' in message.lower())
                and not any(word in message.lower() for word in ('bearer ', 'sk-proj-', 'begin private key', '\x00')))
        model=args.get('model') if type(args) is dict else None
        effort=args.get('reasoning_effort') if type(args) is dict else None
        values_ok=all(v is None or type(v) is str and len(v)<=128 and re.fullmatch(r'[A-Za-z0-9_.:/\[\]-]+',v)
                      for v in (model,effort))
        if identity_ok and benign and values_ok:
            captured={'tool_name':event['tool_name'],**ids,'message':message,
                      'model_present':'model' in args,'model':model,
                      'reasoning_effort_present':'reasoning_effort' in args,'reasoning_effort':effort}
            line=(json.dumps(captured,ensure_ascii=False)+'\n').encode()
            if output.exists() and (output.is_symlink() or output.stat().st_uid!=os.getuid()):raise ValueError('unsafe_output')
            size=output.stat().st_size if output.exists() else 0
            if size+len(line)>32768:raise ValueError('bounded_capture_exceeded')
            fd=os.open(output,os.O_WRONLY|os.O_CREAT|os.O_APPEND|os.O_NOFOLLOW,0o600)
            try:os.write(fd,line)
            finally:os.close(fd)
            reason='captured'
    return reason


def main():
    control=Path(sys.argv[1]);output=Path(sys.argv[2]);status=Path(sys.argv[3])
    reason='observer_error'
    try:
        if control.is_symlink() or control.stat().st_uid!=os.getuid():raise ValueError()
        data=sys.stdin.buffer.read(1048577)
        if len(data)>1048576:raise ValueError()
        reason=observe(json.loads(data),json.loads(control.read_text()),output)
    except Exception:pass
    # No raw event/error text enters a status record. This is not a deny gate.
    try:
        if status.exists() and (status.is_symlink() or status.stat().st_uid!=os.getuid()):raise ValueError()
        fd=os.open(status,os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW,0o600)
        try:os.write(fd,(json.dumps({'observation':reason})+'\n').encode())
        finally:os.close(fd)
    except Exception:pass
    print('{}')


if __name__=='__main__':main()
