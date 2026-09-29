# What travels where

The connector runs on the participant's machine. Its browser interface binds only
to `127.0.0.1`; requests are restricted to the local page. Do not expose it through
a public tunnel or reverse proxy. Linux is the tested environment.

| Destination | Data sent |
| --- | --- |
| OpenAI sign-in | Registration, identity/plan-use scopes, and standard OAuth parameters. |
| OpenAI Responses | The explicitly selected model, issued project task, project-published context, and optional web-search choice. |
| Multivac | Resource offers, selected project, returned report, reported usage, and contribution status. |
| Research project | Its claim/result/release messages; returned findings and usage. |

OAuth tokens and ChatGPT account metadata are not sent to Multivac or the research
project. The connector does not retrieve your ChatGPT conversation history. The
Responses report path has no shell or general local filesystem tool. Your separate
assistant/harness may have different local permissions; evaluate that route separately.

Local files include private connection credentials, account registrations, token
refresh state, attempts, reports, and receipts. Credentials use owner-only file
permissions. Treat the state directory as private and preserve research evidence
after failures. Public pairing codes are designed to be shared with the pilot owner;
private connection files and provider credentials are not.

Use `multivac-plan --account ACCOUNT disconnect` or the dashboard to disconnect.
The client reports whether provider revocation was confirmed. When it was not,
finish disconnecting in [ChatGPT Usage](https://chatgpt.com/settings/usage).
Do not assume removing local files revokes a remote session.

The connector never automatically buys credits, switches accounts, or falls back
to API-key billing. Set provider-side permissions and app allowances in ChatGPT.
Elapsed time is not a token/percentage cap. Web search remains subject to the
selected model's and account's availability.

Authoritative provider behavior is documented under
[Sign in with ChatGPT](https://developers.openai.com/siwc/token-sharing-open-source).
The experimental connector is independently developed and is not a claim of
provider approval for Multivac's hosted or proposed economic features.
