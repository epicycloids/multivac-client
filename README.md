# Multivac client

Connect resources with questions worth answering. Multivac helps people discover
independent research projects, choose what they can contribute, and see the project's
response. Each project keeps its own research methods, orchestration, and acceptance.

This repository contains the contributor client, a local ChatGPT plan connector,
and an independent-project starter. The [hosted pilot](https://multivac.onrender.com/)
offers public browsing and invited participation. You can also use compatible
project endpoints with your existing MCP-capable assistant.

**Experimental release candidate:** the ChatGPT connector has been exercised with
synthetic protocol tests, including cancellation and receipt recovery. It has not
yet been verified with a real ChatGPT account. Publishing this client does not imply
OpenAI approval of Multivac's hosted service or a resource market. No rewards or market
are active. The existing invited pilot supports contributions through other harnesses.

## Run from source

Linux with Python 3.12–3.14 is the supported environment for this preview. Install
[uv](https://docs.astral.sh/uv/getting-started/installation/), then, inside this checkout:

```sh
uv sync --python 3.13
uv run multivac-plan --account academic dashboard
```

The command prints a local URL and opens your browser. Keep its terminal running.
No research starts automatically. The local page guides you through:

1. Requesting a Multivac connection and having its public pairing code approved.
2. Authorizing an eligible ChatGPT account through **Continue with ChatGPT**.
3. Selecting a project, an account-available model, and a time allowance.
4. Reading the project's task and explicitly starting the contribution.
5. Viewing the saved report, usage information, and the project's actual receipt.

This execution profile analyzes the issued task and shared context, with optional
web search. It does not run a shell or local experiments. Project questions can be
open-ended; the model chooses how to investigate within the available capabilities.
Your existing assistant can perform broader work through the separate MCP route.

Set app limits and purchased-credit choices in [ChatGPT Settings → Usage](https://chatgpt.com/settings/usage).
A local time allowance closes the request at its deadline; it does not guarantee
a fixed token count, plan percentage, or provider-side spending cap. Credentials
remain on your device. The client never switches account or billing method automatically.

OpenAI documents [plan access for open-source/local apps](https://developers.openai.com/siwc/token-sharing-open-source).
Account and app eligibility still apply; remotely hosted and paid integrations have
a separate interest route. Choose the integration you are eligible to use.

## Use an existing assistant

```sh
uv run multivac-client connect --label "My research assistant"
# Ask the pilot owner to approve the printed public code.
uv run multivac-client assistant-config
```

Add the printed MCP configuration to your assistant. Tell it which projects interest
you, what resources it may use, and what findings it may return. This route uses
your assistant's own harness and permissions; it does not require the ChatGPT
connector. Never share private connection files with the pilot owner.

## Use the connector from a terminal

```sh
uv run multivac-plan --account academic connect
uv run multivac-plan --account academic models
uv run multivac-client offer --project trefethen-autonomous --kind agent \
  --seconds 300 --allow-network --request-id my-investigation-1
uv run multivac-client inspect CONTRIBUTION_ID
# Once ready, choose an actual slug returned by models:
uv run multivac-plan --account academic run-report CONTRIBUTION_ID --model MODEL_SLUG
uv run multivac-plan --account academic collect CONTRIBUTION_ID
```

`collect` recovers delivery of the saved result without another model request.
Repeated execution of the same contribution is refused. A delivery acknowledgement
is not a project receipt; delayed acceptance remains pending. A receipt may mean
“received for interpretation,” rather than scientific verification.

The dashboard and commands use the same state directory and connection. Global
`--origin`, `--connection`, and `--data-dir` options select a different connection.
`--account` selects a distinct ChatGPT registration. State defaults to
`~/.local/state/research-market`; the legacy directory name preserves earlier clients.

## Add a project or inspect the protocol

See [the project guide](PROJECTS.md), [protocol](PROTOCOL.md), and [data flow](PRIVACY.md).
The project starter exposes standard MCP tools. Run a completely local synthetic
cycle with no account, model, or hosted connection:

```sh
uv run python examples/protocol_check.py
```

The numerical CPU runner and hosted platform internals are outside this client
package. This release does not claim to support arbitrary executable workloads,
an always-on hosted assistant, or provider-backed credit resale.

## Develop

```sh
uv sync --python 3.13 --extra dev
uv run pytest
uv run ruff check src tests examples
uv build
```

Tests isolate all state and use explicitly synthetic provider responses. See
[CONTRIBUTING.md](CONTRIBUTING.md) and [the roadmap](ROADMAP.md). Licensed under
[Apache-2.0](LICENSE). Multivac is an independent project.
