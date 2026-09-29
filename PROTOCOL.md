# Multivac contribution profile

This is an application profile over standard MCP, not a replacement transport or
an orchestration framework. The Python client uses the official MCP 2.2.0 SDK.
Research internals remain project-owned. Multiple endpoints may pursue the same
objective with different orchestration systems.

## Required project tools

| Tool | Arguments | Result |
| --- | --- | --- |
| `describe_project` | None | Project identity, purpose, supported resource kinds, source/version, and acceptance scope. |
| `list_opportunities` | None | Resource kind, availability, minimum time/memory, network requirement, and objective. |
| `claim_work` | `offer`, `contribution_id` | Immutable task, private lease token, and expiry. |
| `submit_result` | `contribution_id`, `lease_token`, `artifact`, `usage` | Durable project-owned receipt. |
| `release_work` | `contribution_id`, `lease_token` | Release an active claim, preserving completed evidence. |

The bridge reads metadata/opportunities and forwards only claim, result, and release
operations. These tools do not expose project administration. A project may have
additional read/coordination tools for its own lead or other integrations.

## Offers and tasks

An [Offer](src/research_market/models.py) specifies permitted projects, a resource
kind, time allowance, memory and CPU limits, network permission, and allocation
preference. Supported vocabulary includes compute, agent work, local-data analysis,
and human judgment; vocabulary alone does not provide an executor for every kind.

The task must match the project and resource kind and stay within the offer's
limits. [`validate_task_envelope`](src/research_market/contracts.py) enforces that
boundary without prescribing a research method. Project briefs can be open-ended.
Context bundles contain only explicitly selected text resources, with hashes;
downloading context never executes it.

The same contribution ID and offer must return the same claim. A changed offer
under that ID is a conflict. Repeating an identical result returns the existing
receipt; it must not create another finding or award. A changed result is a conflict.

## Hosted lifecycle and observation

An approved client reserves work. The platform asks the project to claim it and
records `ready` only after the project responds. Starting records the execution
deadline. Returning a result initially records `delivering`; the eventual project
receipt determines the disposition. Project capacity can still refuse a claim.

Task IDs correlate allocation, execution, delivery, and acceptance. Model token
counts reported by a client are not independently attested. Missing costs and
unknown usage stay unknown. A received report, a reproduced numerical certificate,
and a new research finding have different meanings.

The local ChatGPT connector persists an exclusive attempt before inference and
saves completed output before delivery. Retry delivery from that output. An
interrupted stream is not a completed report. Closing a provider connection is
not a guarantee that provider-side computation or charging stopped instantly.

See the [project starter](src/research_market/project_starter.py) and
[synthetic local example](examples/protocol_check.py) for executable behavior.
