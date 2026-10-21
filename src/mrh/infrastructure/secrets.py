"""macOS Keychain access through /usr/bin/security. Values never enter argv or output."""
from __future__ import annotations

import os
import subprocess

SECURITY = "/usr/bin/security"
SERVICE = "model-routing-harness"
ACCOUNTS = {"jev": "typesafe"}
ENV_VARS = {"jev": "TYPESAFE_API_KEY"}
_TIMEOUT = 5


class SecretError(ValueError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


def _account(name):
    if name not in ACCOUNTS:
        raise SecretError("secret_name_unknown")
    return ACCOUNTS[name]


def _query(name, extra, run):
    return run([SECURITY, "find-generic-password", "-s", SERVICE, "-a", _account(name), *extra],
               capture_output=True, text=True, timeout=_TIMEOUT)


def is_set(name, run=subprocess.run):
    """Attribute lookup only: reading metadata never exposes or prompts for the value."""
    _account(name)
    if os.name == 'nt' and run is subprocess.run:
        from mrh.adapters.platforms import windows_secrets
        return windows_secrets.is_set()
    try:
        return _query(name, [], run).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def read(name, run=subprocess.run):
    """Return the stored value, or None when absent, denied or the lookup times out."""
    _account(name)
    if os.name == 'nt' and run is subprocess.run:
        from mrh.adapters.platforms import windows_secrets
        return windows_secrets.read()
    try:
        result = _query(name, ["-w"], run)
    except (OSError, subprocess.SubprocessError):
        return None
    value = result.stdout.rstrip("\n") if result.returncode == 0 else ""
    return value or None


def credential_resolver(name, environ=None, run=subprocess.run):
    """Environment variable first, then Keychain. Nothing is cached."""
    def resolve():
        value = (os.environ if environ is None else environ).get(ENV_VARS.get(name, ""), "")
        return value or read(name, run)
    return resolve


def store_interactively(name, run=subprocess.run):
    """Let `security` prompt on the terminal: the value never passes through MRH."""
    _account(name)
    if os.name == 'nt' and run is subprocess.run:
        from mrh.adapters.platforms import windows_secrets
        try: return windows_secrets.store_interactively()
        except OSError: raise SecretError('secret_store_failed') from None
    result = run([SECURITY, "add-generic-password", "-U", "-s", SERVICE, "-a", _account(name), "-w"])
    if result.returncode != 0:
        raise SecretError("secret_store_failed")


def delete(name, run=subprocess.run):
    _account(name)
    if os.name == 'nt' and run is subprocess.run:
        from mrh.adapters.platforms import windows_secrets
        return windows_secrets.delete()
    result = run([SECURITY, "delete-generic-password", "-s", SERVICE, "-a", _account(name)],
                 capture_output=True, text=True, timeout=_TIMEOUT)
    return result.returncode == 0
