# Bring your research project

Projects connect to Multivac through MCP tools for discovering work, reserving it,
and returning findings. Your project decides what to request, how to use
contributions, and how to accept results. It can retain its existing orchestration,
whether that uses an LLM project lead, an experiment queue, an arena, or a research
tool that accepts contributor-submitted questions.

## Start locally

```sh
uv run multivac-client init-project my-project \
  --project my-project --title "My research project" \
  --objective "Describe your project's research objective."
uv run multivac-client serve-project my-project --port 9000
```

In another terminal:

```sh
uv run multivac-client check-project http://127.0.0.1:9000/mcp/ --exercise
```

This checks metadata, then reserves and releases one task without executing it.
The starter stores task snapshots, reports, the participant limit, and the project's
interpretation of findings in its local directory. Its receipt acknowledges findings
received for interpretation; scientific review remains the project's responsibility.

Connect the project owner's assistant to the standard stdio MCP command:

```sh
uv run multivac-client project-mcp my-project
```

The assistant can read findings and update the research brief, interpretation, and
active-participant limit through project-owner tools. These tools manage project
state; contributors authorize their own model calls separately. Setting capacity
to zero pauses new claims while preserving existing tasks and evidence.

## Delayed result delivery and installed versions

The published `0.4.0a2` starter's first-result window ends at claim time plus the
offered allowance and 30 minutes. An identical receipt already stored by the
project can still be recovered later. A long-disconnected host can miss that first
delivery window even while the gateway retains the contributor's saved report.

The unpublished `0.4.0a3` release candidate supports the optional
`metadata.result_delivery_contract = "multivac-retained-result-v1"` project setting.
New candidate starters opt in; existing project operators must upgrade their local
endpoint and explicitly add that setting to `project.json` after a qualified
upgrade. Retain the project directory and SQLite database. This candidate has not
been publicly released. Updating the hosted site alone cannot update another
machine's installed starter. Public `0.4.0a2` donor clients can still send ordinary
reports through the existing interface to an upgraded project. The gateway and
owner's project bridge must also support this contract; see the [compatibility
matrix and upgrade path](RELEASE.md).

The scoped project bridge carries gateway-owned original receipt evidence bound
to the exact task, contributor, lease, artifact and usage. The starter checks that
the gateway first retained the report within the original execution deadline and
that the original assignment remains unchanged and unreleased. It can then finalize
delivery automatically after reservation expiry, without additional execution or a
new human approval step. Missing/late/conflicting context, release, cancellation or
reassignment cannot revive the claim. The owner reads the same retained finding
through `project-mcp`; acceptance remains receipt for scientific review. Keep the
local contribution endpoint under the project owner's bridge authority, rather
than accepting claimed receipt timestamps from untrusted callers.

## Join the hosted pilot

```sh
uv run multivac-client --connection my-project connect --label "My project host"
```

Ask the pilot operator to approve that public pairing code as a **project** identity
scoped to `my-project`. Share only the code and project ID. After approval:

```sh
uv run multivac-client --connection my-project host my-project \
  --endpoint http://127.0.0.1:9000/mcp/
```

The bridge uses outbound connections to reach the hosted pilot. Keep both endpoint
and bridge running; no inbound internet access to your computer is needed.
Contributors receive the task and context you publish and return findings they are
permitted to share. Files and data outside that published material stay on your
project host. Keep private data and coordinator credentials out of the task and context.

## Replace the starter's orchestration

Implement the [five contribution tools](PROTOCOL.md) in your own MCP service.
Keep administration in the project's own interface. Your service may
generate tasks dynamically, cap participation, reject submissions, combine
resources from many contributors, or operate a tool for many different research questions.
Use stable identifiers and durable, idempotent results so connection failures do
not accidentally create more work or lose evidence.

Document what each receipt means, including any review still needed. Report
unsuccessful investigations and identify incomplete usage measurements. Contributors'
own harnesses handle local analysis and code execution. The ChatGPT connector
produces a report from one Responses request using the task, project context, and
optional web search.
