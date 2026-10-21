"""Available native hook hosts and their local installation capabilities.

Catalog-only platforms do not acquire hook support by appearing in settings.
The adapters retain their own native fields and response semantics.
"""
from dataclasses import dataclass
import os
from mrh.adapters.hosts.advisory_hosts import CodexHost, ClaudeHost


@dataclass(frozen=True)
class Registration:
    name: str
    adapter: object
    installation: str
    surfaces: tuple
    packet: bool = False

    def public(self):
        windows = os.name == 'nt'
        return {'host':self.name, 'tools':list(self.adapter.tools),
                'installation':'official-plugin' if windows and self.name == 'claude' else self.installation,
                'surfaces':list(self.surfaces), 'codex_packet':self.packet and not windows, 'hook_supported':True}


REGISTRATIONS = {
    'codex':Registration('codex',CodexHost(),'official-plugin',('Codex App','Codex CLI'),True),
    'claude':Registration('claude',ClaudeHost(),'settings-merge',('Claude Desktop Code','Claude Code CLI')),
}
HOSTS = {name:r.adapter for name,r in REGISTRATIONS.items()}


def public_hosts():
    return [r.public() for r in REGISTRATIONS.values()]
