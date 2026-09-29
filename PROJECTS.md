# Bring your research project

Keep your existing orchestrator. Multivac needs a way to discover available work,
reserve it, and return findings. Your project decides what to request, how to use
donations, and how to accept results. An LLM project lead, an experiment queue,
an arena, or a research tool accepting contributor-submitted questions can own that logic.

## Start locally

```sh
uv run multivac-client init-project my-project \
  --project my-project --title "My research project" \
  --objective "Describe the research your project is actually pursuing."
uv run multivac-client serve-project my-project --port 9000
```

In another terminal:

```sh
uv run multivac-client check-project http://127.0.0.1:9000/mcp/ --exercise
```

This checks metadata and reserves/releases one task. It does not execute research.
The starter retains task snapshots, reports, capacity, and a project-owned research
interpretation in its local directory. Its receipt means that findings were received
for interpretation, not that a scientific claim was verified.

Connect the project owner's assistant to the standard stdio MCP command:

```sh
uv run multivac-client project-mcp my-project
```

The assistant can read findings and update the research brief, interpretation, and
active-participant capacity. These are separate project-owner tools. They invoke
no donor model directly. Setting capacity to zero pauses future admission while
preserving existing tasks and evidence.

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

The bridge makes outbound connections; it does not expose your computer to inbound
internet traffic. Keep both endpoint and bridge running. Donors receive only the
task/context you publish and return permitted findings. Your local database, raw
data, private files, and coordinator credentials are not uploaded by the bridge.

## Replace the starter's orchestration

Implement the [five contribution tools](PROTOCOL.md) in your own MCP service.
The bridge only forwards contribution operations, not administration. You may
generate tasks dynamically, cap participation, reject submissions, combine
resources from many donors, or operate a tool for many different research questions.
Use stable identifiers and durable, idempotent results so connection failures do
not accidentally create more work or lose evidence.

Say what a receipt means. Report unsuccessful investigations and incomplete usage
honestly. Broader local analysis and code execution remain the contributor's own
harness responsibilities; the ChatGPT report preview has a narrower capability set.
