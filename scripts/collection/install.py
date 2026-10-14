"""Install only the standalone local collector and its exact marked handlers.

No trust-store edits, vendor calls, dependency downloads, or data deletion.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import shlex
import stat
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
import daily

OWNER = 'org.model-routing-harness.daily-collector.v1'
MARKER = '--managed-by-mrh-daily-collector'
EVENTS = ('UserPromptSubmit', 'PreToolUse', 'PostToolUse')
FILES = ('daily.py', 'install.py', 'COLLECTION.md')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(path):
    path = Path(path).absolute()
    if path != path.resolve():
        raise ValueError('symlink_ancestor')
    return path


def directory(path):
    path = canonical(path)
    if not path.exists():
        path.mkdir(mode=0o700)  # Existing parent required; never follow a link.
    daily.private(path, True)
    return path


def exclusive(path, data, mode=0o600):
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, mode)
    os.fchmod(fd, mode)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def hooks_read(path):
    path = canonical(path)
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or info.st_nlink != 1 or info.st_mode & 0o022 or info.st_size > 1_000_000):
        raise ValueError('unsafe_hooks_file')
    data = path.read_bytes()
    value = json.loads(data)
    if not isinstance(value.get('hooks'), dict):
        raise ValueError('invalid_hooks_schema')
    for rows in value['hooks'].values():
        if not isinstance(rows, list) or any(not isinstance(row.get('hooks'), list) for row in rows):
            raise ValueError('invalid_hooks_schema')
    return data, value, stat.S_IMODE(info.st_mode)


def without_ours(value, commands):
    result = copy.deepcopy(value)
    for event, rows in result['hooks'].items():
        kept = []
        for row in rows:
            hooks = [h for h in row['hooks'] if h.get('command') not in commands]
            if hooks or not row['hooks']:
                row['hooks'] = hooks
                kept.append(row)
        result['hooks'][event] = kept
    return result


def hook_groups(command):
    groups = {}
    for event in EVENTS:
        row = {'hooks': [{'type': 'command', 'command': command, 'timeout': 4}]}
        if event != 'UserPromptSubmit':
            row['matcher'] = r'^(spawn_agent|collaborationspawn_agent|collaboration\.spawn_agent)$'
        groups[event] = row
    return groups


def hooks_commit(path, before, value, mode, root):
    current, _, current_mode = hooks_read(path)
    if current != before or current_mode != mode:
        raise ValueError('hooks_concurrent_change')
    data = (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()
    if data == before:
        return None
    backups = directory(root / 'backups')
    backup = backups / (str(time.time_ns()) + '-hooks.before.json')
    exclusive(backup, before)
    temp = path.with_name('.hooks.mrh-collector-next')
    exclusive(temp, data, mode)
    try:
        # Recheck after staging; never restore a whole old file over other owners.
        if hooks_read(path)[0] != before:
            raise ValueError('hooks_concurrent_change')
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()
    return str(backup)


def migrate(dataset, document, root, authorization, workspace_roots):
    daily.private(dataset, True)
    with daily.locked(dataset):
        path = dataset / 'collection.json'
        index = daily.read(path)
        if index.get('daily_collector_scope') == OWNER:
            # Recover a crash between the index commit and document publication.
            current_doc = (dataset / 'COLLECTION.md').read_bytes()
            saved = Path(index['scope_migrations'][-1]['backup_directory'])
            if current_doc != document:
                if not saved.is_relative_to(root / 'migrations') or current_doc != (saved / 'COLLECTION.before.md').read_bytes():
                    raise ValueError('collection_document_changed')
                temp = dataset / '.COLLECTION.mrh-collector-next'
                exclusive(temp, document)
                os.replace(temp, dataset / 'COLLECTION.md')
            return str(saved)
        if len(index['samples']) != index['count']:
            raise ValueError('index_count_mismatch')
        migrations = directory(root / 'migrations')
        saved = directory(migrations / uuid.uuid4().hex)
        original_index = path.read_bytes()
        original_doc = (dataset / 'COLLECTION.md').read_bytes()
        daily.private(dataset / 'COLLECTION.md')
        exclusive(saved / 'collection.before.json', original_index)
        exclusive(saved / 'COLLECTION.before.md', original_doc)
        history = {'authorization': authorization, 'activated_at': time.time(),
                   'previous_scope': index.get('scope'), 'previous_participants': index.get('participants'),
                   'previous_central_index_owner': index.get('central_index_owner'),
                   'backup_directory': str(saved)}
        index.setdefault('scope_migrations', []).append(history)
        index.update(daily_collector_scope=OWNER,
                     scope='Future natural root-chat Codex spawn dispatches on this local account after activation; no historical backfill.',
                     participants=['local_codex_root_chats'], central_index_owner='local_event_collector; B maintains its installation',
                     workspace_roots=workspace_roots)
        # Neither sample records nor any original sample file is modified.
        if path.read_bytes() != original_index or (dataset / 'COLLECTION.md').read_bytes() != original_doc:
            raise ValueError('dataset_concurrent_change')
        daily.write(path, index)
        temp = dataset / '.COLLECTION.mrh-collector-next'
        exclusive(temp, document)
        os.replace(temp, dataset / 'COLLECTION.md')
        return str(saved)


def install(root, hooks, dataset, python, workspace_roots, excluded_threads, authorization, spool=None):
    root = directory(root)
    owner = root / 'owner.json'
    if owner.exists():
        if daily.read(owner) != {'owner': OWNER}:
            raise ValueError('unowned_installation')
    else:
        if list(root.iterdir()):
            raise ValueError('unowned_installation')
        daily.write(owner, {'owner': OWNER})
    with daily.locked(root):
        state_path = root / 'installation.json'
        old = daily.read(state_path) if state_path.exists() else {}
        before, value, mode = hooks_read(hooks)
        known = set(old.get('owned_commands', [old['command']] if old.get('command') else []))
        if any(MARKER in h.get('command', '') and h.get('command') not in known
               for rows in value['hooks'].values() for row in rows for h in row['hooks']):
            raise ValueError('unowned_collector_handler')
        source = Path(__file__).resolve().parent
        contents = {name: (source / name).read_bytes() for name in FILES}
        version = sha(b''.join(name.encode() + b'\0' + contents[name] for name in FILES))[:20]
        versions = directory(root / 'versions')
        fixed = directory(versions / version)
        for name, data in contents.items():
            target = fixed / name
            if target.exists() or target.is_symlink():
                daily.private(target)
                if target.read_bytes() != data:
                    raise ValueError('installed_source_changed')
            else:
                exclusive(target, data, 0o400)
        python = canonical(python)
        if not python.is_file() or not os.access(python, os.X_OK):
            raise ValueError('python_unavailable')
        config_path = root / 'config.json'
        spool = directory(spool or Path('/private/tmp') / ('mrh-daily-collector-' + str(os.getuid())))
        spool_owner = spool / 'owner.json'
        expected_spool = {'owner': daily.SPOOL_OWNER, 'config': str(config_path)}
        if spool_owner.exists():
            if daily.read(spool_owner) != expected_spool:
                raise ValueError('unowned_spool')
        else:
            if list(spool.iterdir()):
                raise ValueError('unowned_spool')
            daily.write(spool_owner, expected_spool)
        config = {'enabled': False, 'dataset': str(canonical(dataset)), 'workspace_roots': workspace_roots,
                  'spool_root': str(spool),
                  'excluded_threads': excluded_threads, 'authorization': authorization,
                  'root_dispatch_only': True, 'native_hook_trust': 'unverified'}
        command = shlex.join([str(python), '-I', '-B', str(fixed / 'daily.py'), '--config',
                              str(config_path), MARKER, 'hook'])
        groups = hook_groups(command)
        merged = without_ours(value, known)
        for event, group in groups.items():
            merged['hooks'].setdefault(event, []).append(group)
        manifest = {'owner': OWNER, 'version': version, 'command': command, 'phase': 'prepared',
                    'owned_commands': sorted(known | {command}),
                    'files': {name: sha(data) for name, data in contents.items()},
                    'python': str(python), 'python_sha256': sha(python.read_bytes()),
                    'hooks_file': str(hooks), 'source_directory': str(fixed), 'definition_groups': groups}
        daily.write(state_path, manifest)  # Recovery knows precisely our pending command.
        daily.write(config_path, config)
        migration = migrate(canonical(dataset), contents['COLLECTION.md'], root, authorization, workspace_roots)
        backup = hooks_commit(hooks, before, merged, mode, root)
        config['enabled'] = True  # This does not grant native hook trust.
        daily.write(config_path, config)
        manifest.update(phase='installed_pending_native_review', hooks_backup=backup, migration_backup=migration)
        daily.write(state_path, manifest)
        return status(root)


def status(root):
    daily.private(root, True)
    state = daily.read(root / 'installation.json')
    config = daily.read(root / 'config.json')
    fixed = Path(state['source_directory'])
    daily.private(fixed, True)
    for name in state['files']:
        daily.private(fixed / name)
    hashes = {name: sha((fixed / name).read_bytes()) for name in state['files']}
    _, hooks, _ = hooks_read(Path(state['hooks_file']))
    count = sum(h.get('command') == state['command'] for rows in hooks['hooks'].values()
                for row in rows for h in row['hooks'])
    index = daily.read(Path(config['dataset']) / 'collection.json')
    return {'installed_files_verified': hashes == state['files'], 'installed_version': state['version'],
            'configured_enabled': config['enabled'], 'own_handlers': count,
            'native_activation': 'unverified: official /hooks review/trust required; natural event proof separate',
            'count': index['count'], 'target': index['target'], 'workspace_roots': config['workspace_roots'],
            'excluded_threads': config['excluded_threads'], 'source_directory': str(fixed),
            'config_path': str(root / 'config.json'), 'hooks_backup': state.get('hooks_backup'),
            'spool_root': config['spool_root'],
            'migration_backup': state.get('migration_backup')}


def disable(root, uninstall=False):
    daily.private(root, True)
    with daily.locked(root):
        state = daily.read(root / 'installation.json')
        config = daily.read(root / 'config.json')
        config['enabled'] = False
        daily.write(root / 'config.json', config)
        path = Path(state['hooks_file'])
        before, value, mode = hooks_read(path)
        backup = hooks_commit(path, before, without_ours(value, set(state.get('owned_commands', [state['command']]))), mode, root)
        state.update(phase='uninstalled_data_retained' if uninstall else 'disabled', last_disable_backup=backup)
        daily.write(root / 'installation.json', state)
    return status(root)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.home() / '.local/share/mrh-daily-collector')
    commands = parser.add_subparsers(dest='operation', required=True)
    add = commands.add_parser('install')
    add.add_argument('--hooks', type=Path, default=Path.home() / '.codex/hooks.json')
    add.add_argument('--dataset', type=Path, required=True)
    add.add_argument('--python', type=Path, required=True)
    add.add_argument('--workspace-root', action='append', required=True)
    add.add_argument('--exclude-thread', action='append', default=[])
    add.add_argument('--authorization', required=True)
    add.add_argument('--spool-root', type=Path)
    for name in ('status', 'disable', 'uninstall'):
        commands.add_parser(name)
    args = parser.parse_args(argv)
    try:
        root = canonical(args.root)
        if args.operation == 'install':
            result = install(root, canonical(args.hooks), canonical(args.dataset), args.python,
                             [str(canonical(p)) for p in args.workspace_root], args.exclude_thread, args.authorization, args.spool_root)
        elif args.operation == 'status':
            result = status(root)
        else:
            result = disable(root, args.operation == 'uninstall')
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as error:
        print(json.dumps({'status': 'error', 'error_type': type(error).__name__}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
