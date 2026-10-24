"""One current-user LaunchAgent; never controls a process by an arbitrary PID."""
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
        return __import__('json').loads(owned.read_regular(path)) if path.exists() else None

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

    def install(self, command):
        state = self.inspect()
        previous = self._record()
        before = owned.read_regular(self.path) if state['registered'] else None
        if previous and previous['command'] == command and state['registered']:
            return
        if state['running']:
            self._run('bootout', self.identity)
        parent = owned.canonical_path(self.path.parent)
        parent.mkdir(parents=True, exist_ok=True)
        info = parent.stat()
        if info.st_uid != os.getuid() or info.st_mode & 0o022:
            raise owned.OwnedError('diagnostics_login_directory_unsafe')
        raw = plistlib.dumps({'Label': LABEL, 'ProgramArguments': command, 'RunAtLoad': True,
                             'KeepAlive': {'SuccessfulExit': False}, 'ProcessType': 'Background',
                             'StandardOutPath': os.devnull, 'StandardErrorPath': os.devnull}, sort_keys=True)
        record = {'platform': 'darwin', 'name': LABEL, 'command': command,
                  'sha256': hashlib.sha256(raw).hexdigest()}
        try:
            owned.replace_owned(self.root / 'service.json', __import__('json').dumps(record).encode())
            owned.replace_owned(self.path, raw)
        except (OSError, ValueError):
            if previous:
                owned.replace_owned(self.root / 'service.json', __import__('json').dumps(previous).encode())
                owned.replace_owned(self.path, before)
            elif not self.path.exists():
                (self.root / 'service.json').unlink(missing_ok=True)
            raise

    def start(self):
        if not self.inspect()['running']:
            self._run('bootstrap', 'gui/' + str(os.getuid()), str(self.path))

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
