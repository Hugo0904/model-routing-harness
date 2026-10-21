"""Standalone opt-in skill locations, independent of Hook installation."""
from pathlib import Path
import os

REGISTRY = {
    'codex': ('mrh-delegation-codex', Path('.agents/skills')),
    'claude': ('mrh-delegation-claude', Path('.claude/skills')),
}


def registration(host):
    if host not in REGISTRY:
        raise ValueError('此平台尚未支援派工 skill；請指定 --host codex 或 claude')
    return REGISTRY[host]


def default_directory(host, *, environ=None, user_home=None):
    _, relative = registration(host)
    environ = os.environ if environ is None else environ
    if host == 'claude' and 'CLAUDE_CONFIG_DIR' in environ:
        if not environ['CLAUDE_CONFIG_DIR']:
            raise ValueError('CLAUDE_CONFIG_DIR 不可為空白')
        return Path(environ['CLAUDE_CONFIG_DIR']).expanduser() / 'skills'
    return Path(user_home or Path.home()) / relative


def install_suggestions(hosts):
    return {'automatically_installed': False,
            'commands': ['mrh skill install --host ' + host for host in hosts if host in REGISTRY],
            'host_restart': '安裝後若宿主尚未載入 skill，請重新啟動宿主；這與 PATH 刷新是不同步驟。'}
