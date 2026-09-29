# Contributing

Install development dependencies with `uv sync --python 3.13 --extra dev`, run
`uv run pytest` and `uv run ruff check src tests examples`, and build with `uv build`.
Tests use isolated state and synthetic model responses. Keep tests free of real
account access, model usage, and publication to the hosted pilot.

Changes should preserve contributor limits, project control over research and
acceptance, and delivery retries that reuse saved results. Record missing or
incomplete usage measurements as unknown.

For an integration issue, include the client version, operating system, command or
UI step, and a redacted error. Keep provider tokens, callback URLs, private connection
files, and unapproved project data out of issues, examples, and test fixtures.

This source package covers the client, integration contract, project starter,
and their tests and documentation. The hosted platform, project research
implementations, and private operating data are maintained separately.
