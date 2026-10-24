"""One interactive, non-elevated current-user login Scheduled Task."""
import json
import os
from pathlib import Path
import subprocess

from mrh.infrastructure import owned
from mrh.adapters.platforms import windows


class Service:
    def __init__(self, root):
        self.root = root
        self.sid = windows.current_sid()
        self.name = 'ModelRoutingHarness-HookDiagnostics-' + self.sid

    def _run(self, script, **values):
        ps = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
        env = {**os.environ, 'MRH_DIAGNOSTICS_SPEC': json.dumps({'name': self.name, 'sid': self.sid, **values})}
        try:
            result = subprocess.run([str(ps), '-NoProfile', '-NonInteractive', '-Command',
                                     '$ErrorActionPreference="Stop";$s=$env:MRH_DIAGNOSTICS_SPEC|ConvertFrom-Json;' + script],
                                    env=env, capture_output=True, text=True, timeout=20)
        except subprocess.SubprocessError:
            raise owned.OwnedError('diagnostics_scheduled_task_timeout') from None
        if result.returncode:
            raise owned.OwnedError('diagnostics_scheduled_task_failed')
        return json.loads(result.stdout) if result.stdout.strip() else {}

    def inspect(self):
        data = self._run('''$t=Get-ScheduledTask -TaskName $s.name -TaskPath '\\' -ErrorAction SilentlyContinue;
if(!$t){@{registered=$false;running=$false}|ConvertTo-Json -Compress;exit};
$u=$t.Principal.UserId;if(!$u.StartsWith('S-1-')){$u=([System.Security.Principal.NTAccount]$u).Translate([System.Security.Principal.SecurityIdentifier]).Value};
@{registered=$true;running=($t.State -eq 'Running');execute=$t.Actions[0].Execute;arguments=$t.Actions[0].Arguments;sid=$u;level=[int]$t.Principal.RunLevel;logon=[int]$t.Principal.LogonType;trigger=$t.Triggers[0].CimClass.CimClassName;actions=@($t.Actions).Count;triggers=@($t.Triggers).Count}|ConvertTo-Json -Compress''')
        if data['registered']:
            path = self.root / 'service.json'
            if not path.exists():
                raise owned.OwnedError('diagnostics_service_unowned')
            record = json.loads(owned.read_regular(path))
            if (record.get('name') != self.name or record.get('platform') != 'win32'
                    or data.get('execute') != record['command'][0]
                    or data.get('arguments') != subprocess.list2cmdline(record['command'][1:])
                    or data.get('sid') != self.sid or data.get('level') != 0 or data.get('logon') != 3
                    or data.get('trigger') != 'MSFT_TaskLogonTrigger'
                    or data.get('actions') != 1 or data.get('triggers') != 1):
                raise owned.OwnedError('diagnostics_native_identity_changed')
        return {**{k: data[k] for k in ('registered', 'running')}, 'name': self.name, 'platform': 'win32'}

    def install(self, command):
        state = self.inspect()
        record = self.root / 'service.json'
        previous = json.loads(owned.read_regular(record)) if record.exists() else None
        if previous and previous.get('command') == command and state['registered']:
            return
        if state['running']:
            self._run('Stop-ScheduledTask -TaskName $s.name -TaskPath "\\"')
        self._run('''$a=New-ScheduledTaskAction -Execute $s.execute -Argument $s.arguments;
$t=New-ScheduledTaskTrigger -AtLogOn -User $s.sid;
$p=New-ScheduledTaskPrincipal -UserId $s.sid -LogonType Interactive -RunLevel Limited;
$o=New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries;
Register-ScheduledTask -TaskName $s.name -TaskPath '\\' -Action $a -Trigger $t -Principal $p -Settings $o -Force|Out-Null''',
                  execute=command[0], arguments=subprocess.list2cmdline(command[1:]))
        owned.replace_owned(record, json.dumps({'platform': 'win32', 'name': self.name, 'command': command}).encode())

    def start(self):
        if not self.inspect()['running']:
            self._run('Start-ScheduledTask -TaskName $s.name -TaskPath "\\"')

    def remove(self):
        state = self.inspect()
        if state['registered']:
            self._run('Stop-ScheduledTask -TaskName $s.name -TaskPath "\\" -ErrorAction SilentlyContinue;Unregister-ScheduledTask -TaskName $s.name -TaskPath "\\" -Confirm:$false')
        path = self.root / 'service.json'
        if path.exists():
            owned.read_regular(path)
            path.unlink()
