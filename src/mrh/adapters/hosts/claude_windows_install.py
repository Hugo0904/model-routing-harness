"""Version-pinned native Claude plugin lifecycle; never edits host settings.

The caller supplies a protected, signed CLI snapshot. Public native commands own
their registration files. MRH only removes its exact user-scoped plugin and uses
--keep-data; unknown schemas and conflicting/disabled entries fail closed.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess

from mrh.infrastructure import owned, plugin

TESTED_VERSION = "2.1.303 (Claude Code)"
PLUGIN_FOLDER = Path("plugins") / plugin.NAME
MARKET_FIELDS = {"name", "source", "path", "installLocation"}
PLUGIN_FIELDS = {"id", "version", "scope", "enabled", "installPath", "readFromFolder", "folderVersion",
                 "installedAt", "lastUpdated", "projectEnabled"}


class ClaudeInstallError(ValueError):
    pass


def _json(text):
    try:
        return json.loads(text, object_pairs_hook=owned._unique)
    except (ValueError, TypeError):
        raise ClaudeInstallError("claude_native_response_invalid") from None


def _path(value):
    if not isinstance(value, str) or not value or any(ord(c) < 32 for c in value):
        raise ClaudeInstallError("claude_native_path_invalid")
    path = Path(value)
    if not path.is_absolute():
        raise ClaudeInstallError("claude_native_path_invalid")
    # Native JSON may spell directory separators twice. Path normalizes them;
    # owned artifact inspection below rejects links and verifies every byte.
    return path.absolute()


class ClaudeWindowsInstaller:
    def __init__(self, executable, *, run=None, artifact_reader=None):
        if os.name != "nt":
            raise ClaudeInstallError("claude_native_windows_required")
        from mrh.adapters.platforms.windows import assert_safe
        from mrh.adapters.platforms.windows_process import run as native_run
        self.executable = owned.canonical_path(Path(executable).absolute())
        assert_safe(self.executable, private=True)
        self.run = run or native_run
        self.artifact_reader = artifact_reader or plugin.show
        result = self._run(["--version"])
        if result.stdout.strip() != TESTED_VERSION:
            raise ClaudeInstallError("claude_cli_unsupported_version")
        self.cli = {"executable": str(self.executable), "version": TESTED_VERSION,
                    "sha256": hashlib.sha256(owned.read_regular(self.executable, 600_000_000)).hexdigest(),
                    "source": "protected_native_cli", "catalog": "isolated_initialize",
                    "registration": "native_plugin", "account_availability": "not_probed"}

    def _run(self, args):
        try:
            result = self.run([str(self.executable), *args], timeout=40, encoding="utf-8", errors="strict")
        except (OSError, subprocess.SubprocessError, UnicodeError):
            raise ClaudeInstallError("claude_native_command_unavailable") from None
        if result.returncode:
            # Native errors can include local configuration values. Keep them
            # out of receipts; operation and exit code are sufficient evidence.
            raise ClaudeInstallError("claude_native_command_failed:" + ":".join(args[:3])
                                     + ":exit_" + str(result.returncode))
        if not isinstance(result.stdout, str) or len(result.stdout) > 2_000_000:
            raise ClaudeInstallError("claude_native_response_invalid")
        return result

    def _list(self, *args):
        value = _json(self._run(["plugin", *args, "--json"]).stdout)
        if not isinstance(value, list) or len(value) > 4096 or any(not isinstance(row, dict) for row in value):
            raise ClaudeInstallError("claude_native_schema_unknown")
        return value

    def _artifact(self, root, settings=None):
        root = owned.canonical_path(_path(str(root)))
        info = self.artifact_reader(root)["artifact"]
        market_name = ".claude-plugin/marketplace.json"
        native_name = (PLUGIN_FOLDER / ".claude-plugin/plugin.json").as_posix()
        if (not isinstance(info.get("version"), str) or not info["version"]
                or not {market_name, native_name}.issubset(info.get("files", {}))):
            raise ClaudeInstallError("claude_artifact_incomplete")
        market = _json(owned.read_regular(root / market_name).decode("utf-8"))
        definition = _json(owned.read_regular(root / native_name).decode("utf-8"))
        entries = market.get("plugins") if isinstance(market, dict) else None
        if (not isinstance(entries, list) or len(entries) != 1 or not isinstance(entries[0], dict)
                or market.get("name") != plugin.MARKETPLACE or entries[0].get("name") != plugin.NAME
                or entries[0].get("source") != "./" + PLUGIN_FOLDER.as_posix()
                or not isinstance(definition, dict) or definition.get("name") != plugin.NAME
                or definition.get("version") != info.get("version")):
            raise ClaudeInstallError("claude_artifact_identity_invalid")
        if settings is not None and info.get("settings_path") != str(settings):
            raise ClaudeInstallError("claude_settings_conflict")
        if info.get("codex_packets"):
            raise ClaudeInstallError("claude_packet_mode_unsupported")
        return info

    def observe(self):
        markets = self._list("marketplace", "list")
        rows = self._list("list")
        if any(not isinstance(m.get("name"), str) for m in markets) or any(not isinstance(r.get("id"), str) for r in rows):
            raise ClaudeInstallError("claude_native_schema_unknown")
        ours = [m for m in markets if m["name"] == plugin.MARKETPLACE]
        entries = [r for r in rows if r["id"] == plugin.PLUGIN_ID]
        if len(ours) > 1 or len(entries) > 1:
            raise ClaudeInstallError("claude_registration_conflict")
        if any((r["id"].split("@", 1)[0] == plugin.NAME and r["id"] != plugin.PLUGIN_ID)
               or (r["id"].endswith("@" + plugin.MARKETPLACE) and r["id"] != plugin.PLUGIN_ID) for r in rows):
            raise ClaudeInstallError("claude_name_conflict")
        market = ours[0] if ours else None
        row = entries[0] if entries else None
        root = None
        if market:
            if set(market) != MARKET_FIELDS or market.get("source") != "directory":
                raise ClaudeInstallError("claude_marketplace_unowned")
            root = _path(market["path"])
            if _path(market["installLocation"]) != root:
                raise ClaudeInstallError("claude_marketplace_unowned")
            self._artifact(root)
        if row:
            if (set(row) != PLUGIN_FIELDS or not root or row.get("scope") != "user"
                    or type(row.get("enabled")) is not bool or type(row.get("projectEnabled")) is not bool
                    or not all(isinstance(row.get(k), str) and row[k] for k in
                               ("version", "folderVersion", "installPath", "readFromFolder", "installedAt", "lastUpdated"))):
                raise ClaudeInstallError("claude_native_schema_unknown")
            info = self._artifact(root)
            if (_path(row["readFromFolder"]) != root / PLUGIN_FOLDER or row["version"] != info["version"]
                    or row["folderVersion"] != info["version"]):
                raise ClaudeInstallError("claude_registration_conflict")
            _path(row["installPath"])
            if not row["enabled"]:
                raise ClaudeInstallError("claude_disabled_plugin_preserved:review_in_native_ui")
        return {"root": str(root) if root else None, "installed": row is not None,
                "enabled": row["enabled"] if row else None, "marketplace": market, "plugin": row}

    def preflight(self, settings, packets=False):
        if packets:
            raise ClaudeInstallError("claude_packet_mode_unsupported")
        before = self.observe()
        if before["root"]:
            self._artifact(Path(before["root"]), settings)
        return before

    def configured(self, artifact):
        observed = self.observe()
        self._artifact(Path(artifact))
        return observed["root"] == str(artifact) and observed["installed"] and observed["enabled"] is True

    def _mutate(self, args, expected, command, identity, progress, step):
        # A native command has no conditional-write argument. Compare the
        # exact MRH observation immediately before it and require readback.
        if self.observe() != expected:
            raise ClaudeInstallError("claude_native_concurrent_change")
        progress(step + "_intent")
        if self.observe() != expected:
            raise ClaudeInstallError("claude_native_concurrent_change")
        text = self._run(["plugin", *args, "--json"]).stdout
        # Marketplace commands document the result as the last stdout line.
        lines = [line for line in text.splitlines() if line.strip()]
        reply = _json(lines[-1]) if lines else None
        if (not isinstance(reply, dict) or reply.get("command") != command or reply.get("outcome") != "ok"
                or reply.get("marketplace" if command.startswith("marketplace-") else "pluginId") != identity
                or (not command.startswith("marketplace-") and reply.get("scope") != "user")
                or (command == "uninstall" and reply.get("keptData") is not True)):
            raise ClaudeInstallError("claude_native_mutation_response_invalid")
        progress(step + "_done")
        return self.observe()

    def install(self, artifact, before, progress):
        artifact = owned.canonical_path(Path(artifact))
        target = str(artifact)
        target_info = self._artifact(artifact)
        if before["root"]:
            previous_info = self._artifact(Path(before["root"]))
            if previous_info.get("settings_path") != target_info.get("settings_path"):
                raise ClaudeInstallError("claude_settings_conflict")
        current = self.observe()
        if current["root"] not in (None, before["root"], target):
            raise ClaudeInstallError("claude_native_concurrent_change")
        if current["root"] == before["root"] and current["installed"] and current != before:
            # A successfully installed target after a lost acknowledgement is
            # already verified through its immutable readFromFolder binding.
            if current["root"] != target:
                raise ClaudeInstallError("claude_native_concurrent_change")
        if current["root"] == target and current["installed"]:
            return current
        if current["root"] and current["root"] != target:
            if current["installed"]:
                current = self._mutate(["uninstall", plugin.PLUGIN_ID, "--scope", "user", "--keep-data"],
                    current, "uninstall", plugin.PLUGIN_ID, progress, "remove_plugin")
                if current["installed"] or current["root"] != before["root"]:
                    raise ClaudeInstallError("claude_native_readback_failed")
            current = self._mutate(["marketplace", "remove", plugin.MARKETPLACE, "--scope", "user"],
                current, "marketplace-remove", plugin.MARKETPLACE, progress, "remove_marketplace")
            if current["root"] is not None or current["installed"]:
                raise ClaudeInstallError("claude_native_readback_failed")
        if current["root"] is None:
            current = self._mutate(["marketplace", "add", target, "--scope", "user"],
                current, "marketplace-add", plugin.MARKETPLACE, progress, "add_marketplace")
            if current["root"] != target or current["installed"]:
                raise ClaudeInstallError("claude_native_readback_failed")
        current = self._mutate(["install", plugin.PLUGIN_ID, "--scope", "user"],
            current, "install", plugin.PLUGIN_ID, progress, "add_plugin")
        if current["root"] != target or not current["installed"] or current["enabled"] is not True:
            raise ClaudeInstallError("claude_native_readback_failed")
        return current
