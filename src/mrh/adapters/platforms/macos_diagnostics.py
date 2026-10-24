"""Removal-only migration for the old owned LaunchAgent; never creates one."""
import hashlib
import os
from pathlib import Path
import plistlib
import subprocess

from mrh.infrastructure import owned

LABEL = 'org.model-routing-harness.hook-diagnostics'


class Service:
    def __init__(self, root):
        self.root = root
        self.path = Path.home() / 'Library/LaunchAgents' / (LABEL + '.plist')
        self.identity = 'gui/' + str(os.getuid()) + '/' + LABEL

    def _run(self, *args, optional=False):
        try:
            result = subprocess.run(['/bin/launchctl', *args], capture_output=True, text=True, timeout=12)
        except subprocess.SubprocessError:
            raise owned.OwnedError('diagnostics_launchagent_timeout') from None
        if result.returncode and not optional:
            raise owned.OwnedError('diagnostics_launchagent_failed')
        return result

    def _record(self):
        path = self.root / 'service.json'
        value = __import__('json').loads(owned.read_regular(path)) if path.exists() else None
        if value is not None and (not isinstance(value, dict) or value.get('platform') != 'darwin'
                or value.get('name') != LABEL or not isinstance(value.get('command'), list)
                or not value['command'] or not isinstance(value.get('sha256'), str)):
            raise owned.OwnedError('diagnostics_service_unowned')
        return value

    def inspect(self):
        record = self._record()
        result = self._run('print', self.identity, optional=True)
        if result.returncode not in (0, 113):
            raise owned.OwnedError('diagnostics_native_query_failed')
        registered = self.path.exists() or self.path.is_symlink() or result.returncode == 0
        if registered:
            if not record or record.get('platform') != 'darwin' or record.get('name') != LABEL:
                raise owned.OwnedError('diagnostics_service_unowned')
            raw = owned.read_regular(owned.canonical_path(self.path))
            if hashlib.sha256(raw).hexdigest() != record['sha256']:
                raise owned.OwnedError('diagnostics_service_changed')
            definition = plistlib.loads(raw)
            if definition.get('Label') != LABEL or definition.get('ProgramArguments') != record['command']:
                raise owned.OwnedError('diagnostics_service_changed')
            if result.returncode == 0:
                text = result.stdout
                if '\tprogram = ' + record['command'][0] not in text:
                    raise owned.OwnedError('diagnostics_native_identity_changed')
                # launchctl prints every argument on its own line.
                begin = text.find('arguments = {')
                arguments = text[begin:].split('}', 1)[0].splitlines()[1:] if begin >= 0 else []
                if [v.strip() for v in arguments if v.strip()] != record['command']:
                    raise owned.OwnedError('diagnostics_native_identity_changed')
        return {'registered': registered, 'running': result.returncode == 0,
                'name': LABEL, 'platform': 'darwin'}



    def remove(self):
        state = self.inspect()
        if state['running']:
            self._run('bootout', self.identity)
        if self.path.exists():
            self.inspect()
            self.path.unlink()
        record = self.root / 'service.json'
        if record.exists():
            owned.read_regular(record)
            record.unlink()
