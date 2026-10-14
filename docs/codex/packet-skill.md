# Optional packet skill ownership

MRH owns the original `mrh-codex-packet` skill source at
`src/mrh/resources/skills/mrh-codex-packet/SKILL.md`. It is packaged in the wheel
and standalone runtime, then exposed under the plugin's `skills/` directory only
when `setup --host codex --codex-packets` or the equivalent explicit prepare
option is selected. Ordinary artifacts expose no skill. This is a custom,
provider-owned component; generic Router and worker policies are not copied.

The portable plugin root follows the official
[plugin package format](https://developers.openai.com/plugins/build/plugins):
root `plugin.json` declares the Agent Plugins schema and discovers root
`skills/`; a Codex compatibility manifest must explicitly declare its skills
path. The original MRH manifest/host contract remains independently validated.

Activation is bounded to independently authorized real delegation with this
artifact's explicit packet binding. The skill reads the binding's interpreter
and profile and is self-contained; no Monitor or shared-workbench installation
is required. Explicit human profiles and fixed named roles retain protection,
Top/Main keeps the work in the parent, and unknown releases are not retried.

An existing Router bridge may supply task/profile selection. Only one owner
operates prepare/query/release for that task, reusing an already-created packet;
there is no second classification. Packaged discovery does not prove the model
loaded these instructions, made a query, adopted a profile or saved cost. Packet
adoption remains a separate comparison/acceptance decision.
