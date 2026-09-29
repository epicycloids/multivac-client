# Privacy and data flow

The connector runs on your machine. Its browser interface listens only on
`127.0.0.1` and accepts requests only from the local page. Do not expose it through
a public tunnel or reverse proxy. Linux is the tested environment.

| Destination | Data sent |
| --- | --- |
| OpenAI sign-in | Registration, identity and plan-use scopes, and standard OAuth parameters. |
| OpenAI Responses | Your selected model, the issued project task, project-published context, and optional web-search choice. |
| Multivac | Resource offers, selected project, returned report, reported usage, and contribution status. |
| Research project | Claim, result, and release messages; returned findings and usage. |

OAuth tokens and ChatGPT account metadata are not sent to Multivac or the research
project. The connector does not retrieve your ChatGPT conversation history. The
model in the Responses report route has no shell or general local filesystem tool.
An assistant used through the separate MCP route may have other local permissions;
review its configuration before use.

Local state includes connection credentials, account registrations, token refresh
state, attempts, reports, and receipts. Credentials use owner-only file permissions.
Keep the state directory private and retain research evidence after failures. Share
only the public pairing code with the pilot owner; keep connection files and
provider credentials private.

Use `multivac-plan --account ACCOUNT disconnect` or the dashboard to disconnect.
The client reports whether provider revocation was confirmed. If it was not,
finish disconnecting in [ChatGPT Usage](https://chatgpt.com/settings/usage).
Do not assume removing local files revokes a remote session.

The connector never automatically buys credits, switches accounts, or falls back
to API-key billing. Set provider-side permissions and app allowances in ChatGPT.
A time allowance does not cap token use or the percentage of your plan used.
Web search availability depends on your selected model and account.

For provider eligibility and requirements, see
[Sign in with ChatGPT](https://developers.openai.com/siwc/token-sharing-open-source).
