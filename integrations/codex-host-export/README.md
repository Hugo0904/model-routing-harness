# Isolated Codex pending-delegation export

MRH-001 E7 source experiment for the exact official base in [base.json](base.json). Apply [pending-delegation.patch](pending-delegation.patch) only to a disposable checkout under a new MRH-owned ignored root. Apache-2.0 [LICENSE](LICENSE) and upstream [NOTICE](NOTICE) accompany the patch. Installed Codex and formal Hooks are unchanged.

[tested-pending-delegation.patch](tested-pending-delegation.patch) preserves the exact source patch used for the captured lib-test executable. Final `just fix` removed an unused existing import and a redundant last-use JSON clone; this neutral delta is reviewed separately. Both patch identities are recorded; no tests were rerun after fix, following upstream instructions. The captured executable is not promoted to a final patched native CLI.

## Reproduce the source boundary

Use an owned root such as `model-routing-harness/runtime/e7-host`; its `OWNED.json` must contain `{"owner":"MRH-001-E7"}`. Fetch `https://github.com/openai/codex.git` at `rust-v0.159.3`, verify HEAD is `01fc69f4026735edfdf6789820549727a4867b11`, then run `git apply --check` and `git apply` with the saved patch. Do not copy a real HOME, credentials or installed settings into the root.

Use Rust 1.95.0, just 1.58.0 and cargo-nextest 0.9.148. All toolchain, dependency and build files in this delivery were placed under the owned root. Set **only the child process environment**: HOME=`ROOT/home`, CODEX_HOME=`ROOT/home/.codex`, TMPDIR=`ROOT/tmp`, CARGO_HOME=`ROOT/cargo`, RUSTUP_HOME=`ROOT/rustup`, CARGO_TARGET_DIR=`ROOT/target`, RUSTUP_TOOLCHAIN=`1.95.0`, CARGO_BUILD_JOBS=`4`. PATH includes the owned tools/cargo bin plus system compiler tools. Never change shell startup or global environment. Create those directories before execution.

From `ROOT/source/codex-rs`, run the affected source tests using the owned just:

```sh
just test -p codex-core --lib -E 'test(pending_delegation)' --retries 0 --success-output immediate
cargo run -p codex-hooks --bin write_hooks_schema_fixtures -- hooks/schema
just test -p codex-hooks --lib -E 'test(generated_hook_schemas_match_fixtures)' --retries 0
```

The repository release manifests use 0.159.3 while its saved Cargo.lock uses 0.0.0 for workspace packages. Cargo updates only those 159 package-version fields; this generated lock is excluded from the patch. No dependency declarations were added. Initial dependency retrieval requires network; subsequent checks used offline caches. The delivery did not run the full workspace suite or replace installed binaries.

Identify the built `codex-core` lib-test executable from `cargo nextest list -p codex-core --lib --message-format json`. Record its SHA256 **outside the wire** with the verified build/base/patch. From the MRH root, pass that absolute path and reviewed digest to the driver:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 scripts/verify_source_export.py \
  --owned-root /absolute/owned/root \
  --binary /absolute/owned/root/target/debug/deps/codex_core-TEST_HASH \
  --sha256 REVIEWED_BINARY_SHA256 \
  --output /absolute/path/to/e7-producer-consumer.json
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests -p test_isolated_host_export.py -v
```

The driver executes three exact Rust source tests, captures their actual resolver-generated stdout, then injects the sealed source-test exchange into the existing MRH settings/factory/E6 decision path with scripted transport and a dummy credential. It uses no provider socket or actual child. Parser fixtures remain separately labeled.

## Activation boundary

The source patch adds an optional native-v1 PreToolUse `pending_delegation` field. Only the **owned host process** may enable `CODEX_MRH_PENDING_EXPORT_V1=1`; `CODEX_MRH_EXPORT_TARGETS` may contain up to five bounded `{model, reasoning_effort}` queries (at most 1024 bytes). Task input cannot enable the export or assert these facts. Unsupported/unpatched hosts emit no field. The delivery tested the production source helper and Hook schema, not a patched native CLI invocation.

MRH's consumer is intentionally source-test-only, always synthetic, and has no CLI/settings activation. It trusts reviewed owned executable execution and captured stdout; revision strings, IDs, nonce and known flags are consistency checks, not authenticators. Live native adoption needs a separately reviewed host-origin transport and Hook lifecycle boundary. This experiment supplies no account availability, prices, actual model telemetry or autonomous Main handback. Remove the owned root after saving the patch and sanitized evidence; it is never part of the Git artifact.
