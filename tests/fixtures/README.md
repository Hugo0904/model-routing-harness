# Offline fixtures

These files are inputs for parsers and isolated replay, not fresh evidence of a
real account, installed host or provider execution.

| File | Purpose |
| --- | --- |
| `claude_agent_events.json` | Synthetic Claude Agent event shapes used by runtime tests. |
| `e16-acp-probe.json` | Deidentified Gemini metadata response shapes used by catalog tests. |
| `e17r-parser-forms.json` | Historical parser-form sample with generic paths. |
| `e5-shell-plugin.json`, `e5-bundled-plugin.json` | Deidentified recorded event shapes retained for offline replay and compatibility inspection. |

Personal home and temporary-directory paths use placeholders. UUID identities
are consistently remapped, and opaque encrypted message strings are replaced
with synthetic opaque values that retain the parser's ciphertext form. Model
IDs, field types, array order, numeric results and event relationships remain
available to the consumer. Existing hashes describe historical sample fields;
they do not authenticate these edited fixture files.

Do not execute embedded command/output records or use their settings paths on a
real machine. A fixture passing a test proves the parser/replay boundary only.
New raw captures belong in ignored `runtime/`, not in this directory. Add only
the smallest deidentified or synthetic input needed by a consumer.
