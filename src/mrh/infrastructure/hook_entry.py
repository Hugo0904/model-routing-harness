"""The hook entry: how the static marketplace plugin finds the installed engine.

`plugins/mrh/scripts/mrh-hook` reads one small file per host from a fixed place under the user's home.
That script ships in a folder whose bytes are covered by Codex hook trust, so the location and the
three-line format below are a contract: change them only together with a new format line.
"""
from __future__ import annotations

import json
from pathlib import Path

from mrh.infrastructure import locations, owned

FORMAT = 'mrh-hook-entry 1'
PLUGIN_ID = 'mrh@model-routing-harness'    # the static plugin's identity in a host: <plugin>@<marketplace>
LAUNCHER = 'plugins/model-routing-harness/launcher.py'


def directory():
    """Always the default configuration root: the adapter cannot be told about a custom one."""
    return locations.default_config_root() / 'hook-entry'


def path(host):
    return directory() / host


def content(artifact):
    """The entry for one prepared host artifact: its private interpreter and its hook launcher."""
    artifact = Path(artifact)
    python = json.loads(owned.read_regular(artifact / 'artifact.json'))['python']
    launcher = artifact / LAUNCHER
    for value in (python, str(launcher)):
        if not Path(value).is_absolute() or any(ord(c) < 32 for c in value):
            raise owned.OwnedError('hook_entry_path_invalid')
    if not launcher.is_file():
        raise owned.OwnedError('hook_entry_launcher_missing')
    return '\n'.join((FORMAT, python, str(launcher), '')).encode()
