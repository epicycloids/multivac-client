# Multivac client

Multivac connects contributors with independent research projects. Contributors
choose projects and resource limits; projects issue tasks and return receipts
describing how they handled the results. Each project controls its research methods,
orchestration, and acceptance criteria.

This repository contains the contributor client, a local ChatGPT plan connector,
and a project starter. The [hosted pilot](https://multivac.onrender.com/)
offers public browsing and invited participation. An MCP bridge lets contributors
use their existing assistants with compatible project endpoints.

**Experimental alpha:** the ChatGPT connector's cancellation and receipt recovery
have been exercised with synthetic provider responses. OAuth and inference with a
real ChatGPT account remain unverified. The invited pilot supports contributions
through the MCP bridge.

## Run from source

Linux with Python 3.12–3.14 is the supported environment for this preview. Install
[uv](https://docs.astral.sh/uv/getting-started/installation/), then, inside this checkout:

```sh
uv sync --python 3.13
uv run multivac-plan dashboard
```

The command prints a local URL and opens your browser. Keep its terminal running.
Research starts only after your confirmation. The local page guides you through:

1. Requesting a Multivac connection and having its public pairing code approved.
2. Authorizing an eligible ChatGPT account through **Continue with ChatGPT**.
3. Selecting a project, a model available to your account, and a time allowance.
4. Reading the project's task and explicitly starting the contribution.
5. Viewing the saved report, usage information, and the project's receipt.

The ChatGPT connector produces a report from one Responses request containing the
issued task and project context, with web search available when enabled. This
profile has no shell, local file access, or experiment runner. Contributors can use
their own assistant's tools through the MCP route described below.

Set app limits and purchased-credit choices in [ChatGPT Settings → Usage](https://chatgpt.com/settings/usage).
A local time allowance sets the deadline for the client request. Provider computation
or charging may continue after the client closes the connection, so this allowance
does not set a token limit, plan percentage, or spending cap. Credentials are stored
on your device. The client never switches account or billing method automatically.

For account and app eligibility, see OpenAI's
[plan access for open-source/local apps](https://developers.openai.com/siwc/token-sharing-open-source).

## Use an existing assistant

```sh
uv run multivac-client connect --label "My research assistant"
# Ask the pilot owner to approve the printed public code.
uv run multivac-client assistant-config
```

Add the printed MCP configuration to your assistant. Tell it which projects interest
you, what resources it may use, and what findings it may return. This route uses
your assistant's own harness and permissions, independently of the ChatGPT
connector. Share only the public pairing code with the pilot owner; keep connection
files private.

## Use the connector from a terminal

After your Multivac pairing code has been approved:

```sh
uv run multivac-plan connect
uv run multivac-plan models
uv run multivac-client offer --project trefethen-autonomous --kind agent \
  --seconds 300 --allow-network --request-id my-investigation-1
uv run multivac-client inspect CONTRIBUTION_ID
# Once the contribution is ready, use a slug returned by models:
uv run multivac-plan run-report CONTRIBUTION_ID --model MODEL_SLUG
uv run multivac-plan collect CONTRIBUTION_ID
```

`collect` delivers the saved result and retrieves its receipt without another model
request. The connector allows one execution attempt per contribution. Delivery
remains pending until the project returns a receipt. The project's acceptance
criteria determine what that receipt means; for example, it may acknowledge receipt
for interpretation without verifying a scientific claim.

The dashboard and commands use the same state directory and connection. Global
`--origin`, `--connection`, and `--data-dir` options select a different connection.
Use `--account LABEL` to keep multiple ChatGPT registrations under separate local
labels; omitting it uses the default registration. State defaults to
`~/.local/state/research-market`; the legacy directory name preserves earlier clients.

## Add a project or inspect the protocol

See [the project guide](PROJECTS.md), [protocol](PROTOCOL.md), and [data flow](PRIVACY.md).
The project starter exposes standard MCP tools. Run a local synthetic
cycle with no account, model, or hosted connection:

```sh
uv run python examples/protocol_check.py
```

## Develop

```sh
uv sync --python 3.13 --extra dev
uv run pytest
uv run ruff check src tests examples
uv build
```

Tests isolate all state and use synthetic provider responses. See
[CONTRIBUTING.md](CONTRIBUTING.md) and [the roadmap](ROADMAP.md). Licensed under
[Apache-2.0](LICENSE).
