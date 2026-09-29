# Multivac contribution profile

This profile defines how contributors discover, claim, and return research work
over standard MCP. The Python client uses the official MCP 2.2.0 SDK. Each project
owns its research methods, orchestration, and acceptance criteria. Projects with
different orchestration systems may pursue the same objective.

## Required project tools

| Tool | Arguments | Result |
| --- | --- | --- |
| `describe_project` | None | Project identity, purpose, supported resource kinds, source and version, and acceptance scope. |
| `list_opportunities` | None | Resource kind, availability, minimum time and memory, network requirement, and objective. |
| `claim_work` | `offer`, `contribution_id` | Immutable task, private lease token, and expiry. |
| `submit_result` | `contribution_id`, `lease_token`, `artifact`, `usage` | Durable project-owned receipt. |
| `release_work` | `contribution_id`, `lease_token` | Release an active claim, preserving completed evidence. |

The bridge reads metadata and opportunities and forwards claim, result, and release
operations. It does not forward project administration or coordination calls.
Projects may expose those tools to their owners or other integrations.

## Offers and tasks

An [Offer](src/research_market/models.py) specifies permitted projects, a resource
kind, time allowance, memory and CPU limits, network permission, and allocation
preference. Resource kinds describe compute, agent work, local-data analysis, and
human judgment. Each kind requires a compatible executor or contributor harness.

The task must match the project and resource kind and stay within the offer's
limits. [`validate_task_envelope`](src/research_market/contracts.py) checks these
fields against the offer. Projects can issue open-ended research briefs. Context
bundles contain explicitly selected text resources and their hashes. The client
downloads this context as data and does not execute it.

The same contribution ID and offer must return the same claim. A changed offer
under that ID is a conflict. Repeating an identical result returns the existing
receipt without recording another finding. A changed result is a conflict.

## Hosted lifecycle and observation

An approved client reserves work. The platform asks the project to claim it and
records `ready` only after the project responds. Starting records the execution
deadline. Returning a result initially records `delivering`; the eventual project
receipt determines the disposition. A project may refuse a claim when it reaches
capacity.

Task IDs correlate allocation, execution, delivery, and acceptance. Model token
counts reported by a client are not independently attested. Missing costs and usage
remain unknown. Interpret receipts according to the project's acceptance scope:
receiving a report, reproducing a numerical certificate, and accepting a new research
finding are distinct outcomes.

The local ChatGPT connector records one exclusive execution attempt before sending
a Responses request and saves completed output before delivery. Delivery retries
use that saved output. An interrupted stream remains incomplete. Provider
computation or charging may continue after the client closes the connection,
including when the local time allowance expires.

See the [project starter](src/research_market/project_starter.py) and
[synthetic local example](examples/protocol_check.py) for executable behavior.
