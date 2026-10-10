"""Experimental source-test consumer, never selected by the production Hook.

Only a code-level launcher with an independently pinned, actually executed
producer can mint an exchange. Wire strings, operator policy and tool_input
cannot mint one. Source-test/replay evidence always remains synthetic.
"""
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess

from .facts import CallScope, Fact, HostSnapshot, TargetFacts
from .types import Proposal, safe_id

BASE_REVISION = "01fc69f4026735edfdf6789820549727a4867b11"
_SEAL = object()


class ExportError(ValueError):
    pass


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ExportError("invalid_host_export")
        result[key] = value
    return result


def _decode(data):
    if type(data) is not bytes or len(data) > 16384:
        raise ExportError("invalid_host_export")
    try:
        return json.loads(data, object_pairs_hook=_pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(ExportError("invalid_host_export")))
    except (ValueError, UnicodeError):
        raise ExportError("invalid_host_export") from None


@dataclass(frozen=True)
class _Emission:
    payload: bytes
    scope: CallScope
    binary_sha256: str
    seal: object


class SourceTestProducer:
    """Trusted test-driver dependency; no CLI/settings factory exposes it.

    The expected digest comes from the independently reviewed local build, not
    from an export. The owned producer's stdout is the capture transport. This
    does not attest an installed Codex, a provider or a native Hook invocation.
    """
    def __init__(self, owned_root, executable, expected_sha256):
        self.root = Path(owned_root).resolve(strict=True)
        self.executable = Path(executable)
        self.expected_sha256 = expected_sha256
        if not self.executable.is_absolute():
            raise ExportError("unverified_producer")
        if (type(expected_sha256) is not str or len(expected_sha256) != 64
                or any(c not in "0123456789abcdef" for c in expected_sha256)):
            raise ExportError("unverified_producer")
        marker = json.loads((self.root / "OWNED.json").read_text())
        if marker.get("owner") != "MRH-001-E7":
            raise ExportError("unverified_producer")
        self._verify()

    def _verify(self):
        path = self.executable
        info = path.lstat()
        if (path.is_symlink() or not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid() or info.st_mode & 0o022
                or not path.resolve(strict=True).is_relative_to(self.root / "target")
                or hashlib.sha256(path.read_bytes()).hexdigest() != self.expected_sha256):
            raise ExportError("unverified_producer")

    def capture(self, expected_scope, arguments, *, environment, timeout=60):
        if type(expected_scope) is not CallScope or not expected_scope.valid():
            raise ExportError("host_fact_scope_mismatch")
        allowed = {"PATH", "HOME", "CODEX_HOME", "TMPDIR", "LANG", "RUSTUP_HOME", "CARGO_HOME",
                   "RUSTUP_TOOLCHAIN", "CARGO_TARGET_DIR"}
        if set(environment) - allowed:
            raise ExportError("unsafe_producer_environment")
        for key in ("HOME", "CODEX_HOME", "TMPDIR", "RUSTUP_HOME", "CARGO_HOME", "CARGO_TARGET_DIR"):
            if key in environment:
                path = Path(environment[key])
                if not path.is_absolute() or not path.resolve().is_relative_to(self.root):
                    raise ExportError("unsafe_producer_environment")
        self._verify()
        result = subprocess.run([str(self.executable), *arguments], cwd=self.root,
                                env=dict(environment), text=False, capture_output=True, timeout=timeout)
        self._verify()
        if result.returncode:
            raise ExportError("producer_failed")
        prefix = b"MRH_PENDING_EXPORT_JSON="
        packets = [line[len(prefix):] for line in result.stdout.splitlines() if line.startswith(prefix)]
        matching = []
        for packet in packets:
            value = _decode(packet)
            if type(value) is dict and value.get("scope") == expected_scope.__dict__:
                matching.append(packet)
        if len(matching) != 1:
            raise ExportError("host_fact_scope_mismatch")
        # Origin is independently verified execution and captured stdout. IDs,
        # nonce and revision are consistency/validity checks, not authenticators.
        return ExportExchange(_Emission(matching[0], expected_scope, self.expected_sha256, _SEAL))


class ExportExchange:
    synthetic = True

    def __init__(self, emission):
        if type(emission) is not _Emission or emission.seal is not _SEAL:
            raise ExportError("unverified_producer")
        self._emission = emission
        self._active = True

    def close(self):
        self._active = False

    def resolve(self, event):
        if not self._active:
            raise ExportError("expired_host_export")
        scope = CallScope.for_hook(event)
        if scope != self._emission.scope:
            raise ExportError("host_fact_scope_mismatch")
        # Ignore ALL event/tool_input pending_delegation assertions. Only the
        # immutable bytes captured from the pinned owned producer are parsed.
        return _snapshot(self._emission.payload, scope)


def _snapshot(payload, scope):
    value = _decode(payload)
    keys = {"schema_version", "producer_revision", "surface", "scope", "validity", "facts", "targets",
            "target_availability", "effort_semantics"}
    if type(value) is not dict or set(value) != keys:
        raise ExportError("invalid_host_export")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ExportError("unsupported_host_export_version")
    if value["producer_revision"] != BASE_REVISION or value["surface"] != "native-v1":
        raise ExportError("unsupported_producer")
    if value["scope"] != scope.__dict__:
        raise ExportError("host_fact_scope_mismatch")
    validity = value["validity"]
    if (type(validity) is not dict or set(validity) != {"kind", "nonce", "expires"}
            or validity["kind"] != "frozen-invocation" or validity["expires"] != "hook-completion"
            or not safe_id(validity["nonce"])):
        raise ExportError("invalid_host_export")
    if (value["target_availability"] != "unknown-account; no catalog promotion"
            or value["effort_semantics"] != "configured-request-not-provider-execution"):
        raise ExportError("unsupported_host_export_semantics")
    raw = value["facts"]
    fields = {"role_protection", "deny_supported", "rewrite_supported", "original_model", "original_effort"}
    if type(raw) is not dict or set(raw) != fields:
        raise ExportError("invalid_host_export")

    def fact(item, tuple_value=False):
        if (type(item) is not dict or set(item) - {"known", "value", "source"}
                or not {"known", "source"} <= set(item) or type(item["known"]) is not bool
                or not safe_id(item["source"])):
            raise ExportError("invalid_host_export")
        data = item.get("value")
        if not item["known"]:
            if data is not None:
                raise ExportError("invalid_host_export")
            return Fact(source=item["source"])
        if "value" not in item:
            raise ExportError("invalid_host_export")
        if tuple_value:
            if type(data) is not list:
                raise ExportError("invalid_host_export")
            data = tuple(data)
        return Fact.observed(scope, data, item["source"])

    raw_targets = value["targets"]
    if type(raw_targets) is not list or len(raw_targets) > 5:
        raise ExportError("invalid_host_export")
    targets = []
    for target in raw_targets:
        if type(target) is not dict or set(target) != {"model", "host_accepted", "available", "efforts", "inherited_effort"}:
            raise ExportError("invalid_host_export")
        # This contract deliberately cannot establish remote account availability.
        accepted = fact(target["host_accepted"])
        if (not accepted.known or type(accepted.value) is not bool
                or type(target["available"]) is not dict or target["available"].get("known") is not False):
            raise ExportError("invalid_host_export")
        targets.append(TargetFacts(target["model"], fact(target["available"]),
                                   fact(target["efforts"], True), fact(target["inherited_effort"])))
    snapshot = HostSnapshot(scope, True, targets=tuple(targets), **{name: fact(raw[name]) for name in fields})
    proposal = Proposal(scope.platform, "simulation", scope.session_id, scope.turn_id, scope.tool_call_id, {}, True)
    if snapshot.validation_reason(proposal):
        raise ExportError("invalid_host_export")
    return snapshot
