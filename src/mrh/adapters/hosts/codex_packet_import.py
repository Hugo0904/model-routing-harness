"""Explicit local upgrade of owned v1 packet history. No provider or native calls.

Original evidence stays in place. A central transaction stores the original
rows and a fingerprint marker together; reset retains the marker to suppress
resurrection. Unknown histories are reported, never guessed or silently dropped.
"""
from contextlib import closing
import json
import math
import os
from pathlib import Path
import sqlite3
import stat

from mrh.adapters.hosts import codex_packets as p
from mrh.advisory.store import AdviceStore, request_id, candidates
from mrh.infrastructure import owned, settings_v2 as v2


def _snapshot(directory, row):
    dbpath = directory / 'query.sqlite3'
    p._private(dbpath)
    for suffix in ('-wal','-shm'):
        sidecar = Path(str(dbpath)+suffix)
        if sidecar.exists() or sidecar.is_symlink():
            # Old SQLite created WAL/SHM before chmod of the DB. A 0644
            # sidecar inside the already verified 0700 packet directory is not
            # accessible outside its owner; preserve rather than rewrite it.
            if os.name == 'nt':
                p._private(sidecar)
            else:
                info = sidecar.lstat()
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                        or info.st_nlink != 1 or info.st_mode & 0o022):
                    raise p.PacketError('legacy_unsafe_sidecar')
    with closing(sqlite3.connect(dbpath.as_uri()+'?mode=ro',uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute('BEGIN')
        queries = [dict(r) for r in db.execute('SELECT * FROM advice')]
        attempts = [dict(r) for r in db.execute('SELECT * FROM attempts ORDER BY rowid')]
        if db.execute('SELECT COUNT(*) FROM children').fetchone()[0] or db.execute('SELECT COUNT(*) FROM notices').fetchone()[0]:
            # Failure notices are legitimate history too; preserve them below.
            if db.execute('SELECT COUNT(*) FROM children').fetchone()[0]:
                raise p.PacketError('legacy_query_has_execution_rows')
        notices = [dict(r) for r in db.execute('SELECT * FROM notices ORDER BY rowid')]
    if row['version'] != 1 or len(queries) != 1 or row.get('state') not in ('classified','failed','released','completed','expired','cancelled'):
        raise p.PacketError('legacy_history_incomplete')
    q, scope, classification = queries[0], row['scope'], row.get('classification',{})
    if (q['platform'] != 'codex' or q['session_id'] != scope.get('session') or q['turn_id'] != scope.get('turn')
            or q['call_id'] != row.get('query_call') or q['request_id'] != request_id(q['platform'],q['session_id'],q['turn_id'],q['call_id'])
            or classification.get('query_request_id') != q['request_id']
            or any(classification.get(k) != q[k] for k in ('action','reason','tier','confidence'))
            or classification.get('candidates') != list(candidates(q))
            or any(a['request_id'] != q['request_id'] for a in attempts)
            or not all(isinstance(x.get('ts'),(int,float)) and math.isfinite(x['ts']) for x in [q,*attempts,*notices])):
        raise p.PacketError('legacy_history_conflict')
    body = directory/'packet.json'
    if body.exists():
        packet = p._read(body)
        task = packet.get('task')
        from mrh.advisory.store import task_hash
        if (not isinstance(task,str) or p._hash(task.encode()) != row['sha256'] or len(task.encode()) != row['length']
                or packet.get('scope') != scope or task_hash(q['platform'],q['session_id'],task) != q['task_hash']):
            raise p.PacketError('legacy_hash_conflict')
    else:
        sent = row.get('transport_observation',{}).get('outbound',{})
        if sent.get('task_sha256') != row['sha256'] or sent.get('task_length') != row['length']:
            raise p.PacketError('legacy_body_hash_unknown')
    snapshot = {'query':q,'attempts':attempts,'notices':notices,
                'receipt':{k:row.get(k) for k in ('id','scope','sha256','length','query_call','release_call','released','requested_model','requested_effort','child_id','completed')}}
    return snapshot, p._hash(json.dumps(snapshot,sort_keys=True,allow_nan=False).encode())


def _import(store, row, snapshot, fingerprint):
    q, scope = snapshot['query'], row['scope']
    with closing(store.connect()) as db:
        try:
            db.execute('BEGIN IMMEDIATE')
            marker = db.execute('SELECT fingerprint FROM packet_imports WHERE packet_id=?',(row['id'],)).fetchone()
            if marker:
                if marker[0] != fingerprint:
                    raise p.PacketError('legacy_import_source_changed')
                return 'already_imported'  # includes deliberately reset history
            existing = db.execute('SELECT * FROM advice WHERE request_id=?',(q['request_id'],)).fetchone()
            if existing:
                raise p.PacketError('legacy_import_request_conflict')
            if db.execute('SELECT 1 FROM packet_links WHERE packet_id=?',(row['id'],)).fetchone():
                raise p.PacketError('legacy_import_binding_conflict')
            release = None
            if row.get('release_call'):
                rid = request_id(q['platform'],q['session_id'],q['turn_id'],row['release_call'])
                release = db.execute('SELECT * FROM advice WHERE request_id=?',(rid,)).fetchone()
                if (not release or any(release[k] != q[k] for k in ('platform','session_id','turn_id','task_hash'))
                        or release['action'] != 'preserve' or release['reason'] != 'explicit_model'
                        or not 0 <= release['ts']-q['ts'] <= p.TTL_SECONDS
                        or not row.get('requested_model') or not isinstance(row.get('released'),(int,float))):
                    raise p.PacketError('legacy_release_unknown')
                child = db.execute('SELECT * FROM children WHERE platform=? AND session_id=? AND call_id=?', (q['platform'],q['session_id'],row['release_call'])).fetchone()
                if row.get('child_id') and (not child or child['agent_id'] != row['child_id']
                        or child['requested_model'] != row['requested_model'] or child['requested_effort'] != row.get('requested_effort')):
                    raise p.PacketError('legacy_child_conflict')
            db.execute('INSERT INTO advice VALUES('+','.join('?' for _ in q)+')',tuple(q.values()))
            for a in snapshot['attempts']:
                db.execute('INSERT INTO attempts VALUES('+','.join('?' for _ in a)+')',tuple(a.values()))
            for n in snapshot['notices']:
                db.execute('INSERT OR IGNORE INTO notices VALUES(?,?,?)',(n['session_id'],n['reason'],n['ts']))
            db.execute('INSERT INTO packet_links VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                       (row['id'],q['request_id'],q['platform'],q['session_id'],q['turn_id'],q['task_hash'],row['sha256'],row['length'],scope['workspace'],scope['revision'],q['call_id'],q['ts'],
                        release['request_id'] if release else None,row.get('release_call'),release['ts'] if release else None,row.get('requested_model'),row.get('requested_effort'),'legacy_import'))
            db.execute('INSERT INTO packet_imports VALUES(?,?,?)',(row['id'],fingerprint,q['ts']))
            db.commit()
            return 'imported'
        except Exception:
            db.rollback()
            raise


def import_history(settings_path):
    settings = v2.read(settings_path)  # explicit upgrade, not a status side effect
    root = p.root_for(settings_path)
    if not root.exists():
        return {'imported':0,'already_imported':0,'unknown':[]}
    owned.verify(root,'codex_packets');p._private(root,True)
    results = {'imported':0,'already_imported':0,'unknown':[]}
    store = None
    for entry in sorted(root.iterdir()):
        if not p.IDENTIFIER.fullmatch(entry.name):
            continue
        try:
            directory = p._directory(settings_path,entry.name)
            with p._lock(directory):
                row = p._receipt(directory,entry.name)
                if row['version'] != 1:
                    continue
                snapshot, fingerprint = _snapshot(directory,row)
                if store is None:
                    target = Path(settings_path).parent/'advice.sqlite3'
                    if target.exists() or target.is_symlink():p._private(target)
                    store = AdviceStore(target)
                outcome = _import(store,row,snapshot,fingerprint)
                results[outcome] += 1
        except (p.PacketError,owned.OwnedError) as exc:
            results['unknown'].append({'packet_id':entry.name,'reason':exc.reason})
        except (OSError,ValueError,sqlite3.Error,KeyError,TypeError):
            results['unknown'].append({'packet_id':entry.name,'reason':'legacy_history_invalid_or_unavailable'})
    return results
