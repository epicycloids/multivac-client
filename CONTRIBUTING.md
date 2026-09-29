# Contributing

Run `uv sync --extra dev`, `uv run pytest`, and `uv run ruff check src tests examples`.
Build with `uv build`. Tests use isolated state and synthetic model responses; they
must not contact real accounts, spend usage, or publish findings to the hosted pilot.

Changes should preserve donor limits, project ownership of research and acceptance,
and retries that do not repeat model execution. Keep incomplete usage explicit.
Do not put credentials or private research files in issues, examples, or test fixtures.

For an integration issue, include the client version, operating system, command or
UI step, and a redacted error. Do not include provider tokens, callback URLs, private
connection files, or unapproved project data.

The hosted platform, project research implementations, and private operating data
are outside this source package. Focus contributions on the client, integration
contract, independent-project starter, and their tests and documentation.
