"""Internal same-call facts; source labels are metadata, never verifiers.

Only trusted in-process adapters or explicit synthetic dependencies construct
snapshots. This is not a public host wire schema or an operator settings format.
"""
from dataclasses import dataclass, field
from pathlib import Path
from mrh.routing.types import safe_id, safe_model_id


@dataclass(frozen=True)
class CallScope:
    platform: str
    session_id: str
    turn_id: str
    tool_call_id: str

    @classmethod
    def for_proposal(cls, proposal):
        return cls(proposal.platform, proposal.session_id, proposal.turn_id, proposal.tool_call_id)

    @classmethod
    def for_hook(cls, event):
        return cls("codex", event.get("session_id"), event.get("turn_id"), event.get("tool_use_id"))

    def valid(self):
        return all(safe_id(v) for v in (self.platform, self.session_id, self.turn_id, self.tool_call_id))


@dataclass(frozen=True)
class Fact:
    known: bool = False
    value: object = None
    source: str = "unavailable"
    scope: CallScope | None = None
    basis: str = 'observed'

    @classmethod
    def observed(cls, scope, value, source):
        return cls(True, value, source, scope)

    @classmethod
    def configured(cls, scope, value, source):
        return cls(True, value, source, scope, 'configuration')

    def valid(self, scope, predicate):
        if type(self.known) is not bool or not safe_id(self.source) or self.basis not in ('observed','configuration'):
            return False
        if not self.known:
            return self.value is None and (self.scope is None or self.scope == scope)
        return type(self.scope) is CallScope and self.scope == scope and predicate(self.value)


@dataclass(frozen=True)
class TargetFacts:
    model: str
    available: Fact = field(default_factory=Fact)
    efforts: Fact = field(default_factory=Fact)
    inherited_effort: Fact = field(default_factory=Fact)


@dataclass(frozen=True)
class HostSnapshot:
    scope: CallScope
    synthetic: bool
    parent_model: Fact = field(default_factory=Fact)
    workspace: Fact = field(default_factory=Fact)
    role_protection: Fact = field(default_factory=Fact)
    deny_supported: Fact = field(default_factory=Fact)
    rewrite_supported: Fact = field(default_factory=Fact)
    original_model: Fact = field(default_factory=Fact)
    original_effort: Fact = field(default_factory=Fact)
    targets: tuple = ()

    def validation_reason(self, proposal, *, configuration=False):
        if type(self.scope) is not CallScope or not self.scope.valid() or self.scope != CallScope.for_proposal(proposal):
            return "host_fact_scope_mismatch"
        if type(self.synthetic) is not bool or type(proposal.synthetic) is not bool or self.synthetic != proposal.synthetic:
            return "evidence_partition_mismatch"
        optional_effort = lambda x: x is None or safe_id(x)
        canonical_workspace = lambda x: isinstance(x, str) and Path(x).is_absolute() and str(Path(x)) == x and ".." not in Path(x).parts and not any(ord(c) < 32 for c in x)
        predicates = {"parent_model": safe_model_id, "workspace": canonical_workspace,
                      "role_protection": lambda x: x in ("unprotected", "model", "effort", "model_effort") and type(x) is str,
                      "deny_supported": lambda x: type(x) is bool, "rewrite_supported": lambda x: type(x) is bool,
                      "original_model": safe_model_id, "original_effort": optional_effort}
        for name, predicate in predicates.items():
            value = getattr(self, name)
            if type(value) is Fact and value.basis == 'configuration' and not configuration:
                return 'invalid_host_facts'
            if type(value) is Fact and value.known and type(value.scope) is CallScope and value.scope != self.scope:
                return "host_fact_scope_mismatch"
            if type(value) is not Fact or not value.valid(self.scope, predicate):
                return "invalid_host_facts"
        if type(self.targets) is not tuple or len(self.targets) > 128:
            return "invalid_host_facts"
        names = []
        for target in self.targets:
            if type(target) is not TargetFacts or not safe_model_id(target.model):
                return "invalid_host_facts"
            names.append(target.model)
            tests = [(target.available, lambda x: type(x) is bool),
                     (target.efforts, lambda x: type(x) is tuple and len(x) <= 32 and all(optional_effort(v) for v in x) and len(set(x)) == len(x)),
                     (target.inherited_effort, optional_effort)]
            if not configuration and any(type(value) is Fact and value.basis == 'configuration' for value,_ in tests):
                return 'invalid_host_facts'
            if any(type(value) is Fact and value.known and type(value.scope) is CallScope and value.scope != self.scope for value, _ in tests):
                return "host_fact_scope_mismatch"
            if any(type(value) is not Fact or not value.valid(self.scope, test) for value, test in tests):
                return "invalid_host_facts"
        if len(names) != len(set(names)):
            return "invalid_host_facts"
        return None

    def target(self, model):
        return next((t for t in self.targets if t.model == model), None)


def synthetic_legacy_snapshot(proposal, value):
    """Isolated compatibility for existing explicitly SYNTHETIC fixture input.

    This never interprets a dictionary as production host evidence. Every
    asserted fixture field is freshly bound to the fixture's exact call.
    """
    if proposal.synthetic is not True or not isinstance(value, dict):
        raise ValueError("invalid_host_facts")
    scope = CallScope.for_proposal(proposal)
    known = lambda val: Fact.observed(scope, val, "synthetic-legacy-fixture")
    roles = value.get("roles", {})
    role = roles.get(proposal.tool_input.get("agent_type", "default")) if isinstance(roles, dict) else None
    protected, rewrite = Fact(), Fact()
    if isinstance(role, dict) and role.get("known") is True:
        has_model, has_effort = bool(role.get("fixed_model")), bool(role.get("fixed_effort"))
        protected = known("model_effort" if has_model and has_effort else "model" if has_model else "effort" if has_effort else "unprotected")
        if type(role.get("rewrite_allowed")) is bool:
            rewrite = known(role["rewrite_allowed"])
    targets = []
    models = value.get("models", {})
    for name, item in models.items() if isinstance(models, dict) else ():
        if not isinstance(item, dict):
            continue
        availability = known(item["available"]) if type(item.get("available")) is bool else Fact()
        efforts = known(tuple(item["efforts"])) if isinstance(item.get("efforts"), (tuple, list)) else Fact()
        inherited = known(item.get("inherited_effort")) if item.get("inherited_effort_known") is True else Fact()
        targets.append(TargetFacts(name, availability, efforts, inherited))
    baseline = value.get("original_resolution_known") is True
    return HostSnapshot(scope, True,
        parent_model=known(value["main_model"]) if safe_model_id(value.get("main_model")) else Fact(),
        role_protection=protected,
        deny_supported=known(value["deny_supported"]) if type(value.get("deny_supported")) is bool else Fact(),
        rewrite_supported=rewrite,
        original_model=known(value["original_model"]) if baseline and safe_model_id(value.get("original_model")) else Fact(),
        original_effort=known(value["original_effort"]) if baseline and "original_effort" in value else Fact(),
        targets=tuple(targets))


def snapshot_for(proposal, value):
    from mrh.adapters.hosts.codex_scope import ConfigurationScope
    if type(value) is ConfigurationScope:
        return value
    if type(value) is HostSnapshot:
        return value
    if proposal.synthetic is True and isinstance(value, dict):
        return synthetic_legacy_snapshot(proposal, value)
    if value is None:
        return HostSnapshot(CallScope.for_proposal(proposal), proposal.synthetic)
    raise ValueError("invalid_host_facts")
