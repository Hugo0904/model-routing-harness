"""Explicit standalone skill changes; modified owned content requires a recovery copy."""
import hashlib
from importlib import resources
import json
import os
from pathlib import Path
import stat
import uuid

from mrh.adapters.hosts.skill_registry import registration, default_directory
from mrh.infrastructure import owned

OWNER = 'org.model-routing-harness.delegation-skill.v1'
MARKER = '.mrh-skill.json'


def payload(host):
    name, _ = registration(host)
    return resources.files('mrh').joinpath('resources/skills', name, 'SKILL.md').read_bytes()


def released_hashes(host):
    manifest = json.loads(resources.files('mrh').joinpath('resources/skills/delegation-sources.json').read_bytes())
    return set(manifest['skills'][host]['released_sha256'])


def _directory(host, root, skills_dir):
    if root is not None and skills_dir is not None and Path(root) != Path(skills_dir):
        raise ValueError('--root 與 --skills-dir 指向不同位置；未變更')
    explicit = skills_dir if skills_dir is not None else root
    return owned.canonical_path(Path(explicit) if explicit is not None else default_directory(host))


def status(host, root=None, *, skills_dir=None):
    name, _ = registration(host)
    base = _directory(host, root, skills_dir)
    target = base / name
    result = {'host': host, 'path': str(target), 'status': 'not_installed'}
    if not target.exists() and not target.is_symlink():
        return result
    try:
        owned.canonical_path(target)
        if not target.is_dir() or {p.name for p in target.iterdir()} != {'SKILL.md', MARKER}:
            raise ValueError()
        meta = json.loads(owned.read_regular(target / MARKER))
        if set(meta) != {'owner', 'host', 'sha256'} or meta['owner'] != OWNER or meta['host'] != host:
            raise ValueError()
        data = owned.read_regular(target / 'SKILL.md')
        digest = hashlib.sha256(data).hexdigest()
        if meta['sha256'] not in released_hashes(host) | {hashlib.sha256(payload(host)).hexdigest()}:
            raise ValueError()
        result['status'] = ('modified' if digest != meta['sha256'] else
                            'latest' if data == payload(host) else
                            'outdated' if digest in released_hashes(host) else 'unmanaged')
    except (OSError, ValueError, TypeError):
        result['status'] = 'unmanaged'
    return result


def _backup(target, host, destination):
    if destination is None:
        raise ValueError('--force 變更自改 MRH skill 前，必須明確提供專案外的 --backup-dir')
    from mrh.infrastructure import temporary
    directory = owned.canonical_path(destination)
    project = temporary.project_root()
    if directory == project or directory.is_relative_to(project) or directory == target or directory.is_relative_to(target):
        raise ValueError('備份位置不可位於 MRH 專案或要變更的 skill 內')
    if status(host, target.parent)['status'] not in ('modified', 'outdated'):
        raise ValueError('無法再確認 MRH skill 所有權；未覆寫或移除')
    original = {name: (owned.read_regular(target / name), stat.S_IMODE((target / name).stat().st_mode))
                for name in ('SKILL.md', MARKER)}
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    saved = directory / ('mrh-skill-' + host + '-' + uuid.uuid4().hex)
    saved.mkdir(mode=0o700)
    if os.name == 'nt':
        from mrh.adapters.platforms.windows import protect
        protect(saved)
    for name, (data, _) in original.items():
        fd = os.open(saved / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as stream:stream.write(data)
    manifest = {'owner': OWNER, 'host': host, 'original_path': str(target),
                'files': {name: {'sha256': hashlib.sha256(data).hexdigest(), 'mode': mode}
                          for name, (data, mode) in original.items()}}
    fd = os.open(saved / 'backup-manifest.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:json.dump(manifest, stream, indent=2)
    if any(owned.read_regular(target / name) != data for name, (data, _) in original.items()):
        raise ValueError('skill 在備份期間被改動；備份保留，未覆寫或移除')
    return str(saved)


def run(action, host, root=None, *, skills_dir=None, force=False, backup_dir=None):
    result = status(host, root, skills_dir=skills_dir)
    state, target = result['status'], Path(result['path'])
    if action == 'status':
        return result
    if action == 'install':
        if state == 'latest':
            return {**result, 'changed': False}
        if state != 'not_installed' and not (force and state in ('modified', 'outdated')):
            raise ValueError('目標已有不同內容；未覆寫。請保留自己的修改，或明確移除原 MRH skill 後再安裝')
        backup = _backup(target, host, backup_dir) if state != 'not_installed' else None
        if state == 'not_installed':
            target.parent.mkdir(parents=True, exist_ok=True)
            owned.canonical_path(target.parent)
            target.mkdir(mode=0o700)
        if os.name == 'nt' and state == 'not_installed':
            from mrh.adapters.platforms.windows import protect
            protect(target)
        data = payload(host)
        for name, body in [('SKILL.md', data), (MARKER, (json.dumps({
                'owner': OWNER, 'host': host, 'sha256': hashlib.sha256(data).hexdigest()}) + '\n').encode())]:
            if state == 'not_installed':
                fd = os.open(target / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, 'wb') as output:output.write(body)
            else:owned.replace_owned(target / name, body)
        return {**status(host, root, skills_dir=skills_dir), 'changed': True, **({'backup': backup} if backup else {})}
    if action == 'remove':
        if state == 'not_installed':
            return {**result, 'changed': False}
        if state not in ('latest', 'outdated') and not (force and state == 'modified'):
            raise ValueError('內容已改過或不是 MRH 自己的 skill；未移除')
        backup = _backup(target, host, backup_dir) if state == 'modified' else None
        # No recursive deletion or changes to sibling skills.
        for name in ('SKILL.md', MARKER):
            (target / name).unlink()
        target.rmdir()
        return {**status(host, root, skills_dir=skills_dir), 'changed': True, **({'backup': backup} if backup else {})}
    raise ValueError('不支援的 skill 操作')
