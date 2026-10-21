# Native host extension points

Only Codex and Claude have hook/install adapters. Gemini's catalog does not
register hook support. A new host is a source change with evidence, not a
runtime plugin drop-in or a reason to modify the classifier engine.

The current minimum ownership points are:

- `src/mrh/adapters/hosts/registry.py`: host name, native adapter, installation
  mechanism and documented surfaces. Registry metadata means supported code,
  not installed/trusted/accepted status.
- `adapters/hosts/advisory_hosts.py`: normalize native request/child events and
  emit that platform's output. Preserve native model/effort/role semantics;
  don't generalize one vendor's parameter names onto another.
- `mrh_setup.py`: an installer adapter with read-only preflight/observation and
  explicit install/readback. New adapters must preserve unrelated configuration,
  expose conflicts and interrupted state, and use supported native interfaces.
- `adapters/catalogs/`: optional public model declarations with source, time,
  assurance, supported efforts and retirement state. Catalog presence is not
  account availability or hook support.

For a proposed third host, document its tool names, stable native scope,
explicit-profile protection, deny/output semantics, child acknowledgement,
installation/removal/trust contract, public catalog source and test seam before
adding a registry entry. Reuse normalized request/child/output contracts and the
unchanged engine/provider; write bounded native and lifecycle fixtures plus the
smallest actual consumer proof. Unknown capabilities stay unsupported. No third
host adapter, SDK, daemon or automatic plugin downloader is implemented here.
