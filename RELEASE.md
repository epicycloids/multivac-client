# Version and upgrade compatibility

`0.4.0a3` is an unpublished public-client candidate. Preparing or installing this
candidate does not publish it or change the hosted `0.4.0a2` download. Preserve
the earlier public wheel and private candidates until a qualified replacement is
explicitly selected. This preview supports Linux with Python 3.12–3.14.

## Scope of this distribution

The source export contains the portable contributor CLI and MCP bridge, local
ChatGPT report connector and dashboard, optional independent-project starter,
task/consent and retained-delivery validators, context reader, and their shared
models/configuration/wire helpers. Dashboard HTML, CSS, JavaScript and logo assets
are included. Standalone tests cover the connector, dashboard, project starter,
assistant setup and consent; documentation, Apache-2.0 license/notice, a protocol
example, CI configuration and the dependency lock complete the source package.

`release-manifest.json` enumerates every exported source file and its SHA-256 hash.
The canonical exporter uses an explicit inventory rather than repository history.
The wheel contains the client package and its assets, not the standalone source
tests or documentation.

The hosted gateway, database/store, project research implementations, Trefethen
adapters/numerical runner, private GitHub Workbench integration, GPU executor,
repository history, local state, credentials and research data are excluded.
The portable client does not supply a general CPU or GPU executor. Run
`multivac-client capabilities` to inspect local support before offering compute.
An execution-profile or asset label records specific consent; it neither installs
a runtime nor confines an assistant's tools or spending.

## Changes from the installed public 0.4.0a2

- Offer requests are immutable and scoped to the approved contributor identity.
  An equivalent retry sends the original saved body. Changed parameters fail
  locally and require a new request ID. Legacy request files stay intact; the
  selected connection may recover only caller-supplied equivalent parameters,
  without inferring another file's owner.
- Explicit profile, asset and AI-configuration consent can travel with an offer;
  task validation rejects requests outside that consent. Read-only capability
  inspection reports unavailable portable executors.
- MCP offer errors retain the platform status/reason and recovery guidance.
  Connection/result delivery retries preserve their request or result identity;
  they do not authorize another execution. Saved completed ChatGPT output is
  delivered without another model call. An unknown provider request outcome
  remains uncertain and is not automatically rerun.
- An upgraded, opted-in starter can finalize a first report after reservation
  expiry when the gateway originally retained that exact report within the
  original execution deadline. Project receipt and review semantics are unchanged.

## Client and project-host requirements

| Outcome | Requirement |
| --- | --- |
| Immutable local offer retry, clearer MCP errors, typed consent and capability inspection | Candidate contributor client. The current hosted pilot understands the consent fields; inspect another gateway's compatibility before using optional fields. |
| Ordinary claim/report/receipt recovery through the five MCP tools | Compatible gateway and project endpoint. The basic interface is unchanged. An old starter still applies its own first-delivery expiry. |
| First report delivered after reservation expiry | Gateway with `multivac-retained-result-v1`, upgraded owner bridge and endpoint, and project metadata explicitly opting in. New candidate starters opt in. |
| Existing `0.4.0a2` donor with an upgraded opted-in host | Ordinary reports remain compatible; gateway/bridge/host handle retained-delivery evidence. This does not fix the old donor's local offer cache. |
| Existing third-party endpoint without the delivery contract | Ordinary delivery follows that endpoint's rules. No automatic deadline extension or late-first-delivery promise. |
| Full private research adapter or CPU/GPU execution | Separately installed, compatible project/runner release; not distributed here. Preserve its original running pin. |

Updating the website does not upgrade a contributor environment, its generated
assistant setup, the project bridge or a separately hosted endpoint. The local
endpoint should accept retained gateway context only through the project owner's
scoped bridge; donor-supplied timestamps are not authority. Released, reassigned,
cancelled, late or conflicting work cannot be revived by this contract.

## Install or upgrade a reviewed candidate

Use a reviewed local wheel or source artifact. No public `0.4.0a3` download is
assumed here. For an isolated wheel installation:

```sh
python3.13 -m venv /path/to/new-client-environment
/path/to/new-client-environment/bin/python -m pip install /path/to/reviewed-wheel.whl
/path/to/new-client-environment/bin/python -c 'from importlib.metadata import version; print(version("multivac-client"))'
/path/to/new-client-environment/bin/multivac-client --connection YOUR_CONNECTION check-assistant
```

Source users run `uv sync --locked --python 3.13` inside the reviewed export.
Keep the previous environment and artifact. At a natural pause, select the new
environment with the same origin, connection name and state directory; no new
pairing is needed for an existing approved connection. Defaults retain
`~/.local/state/research-market`. Preserve connection files, saved requests,
artifacts, usage and receipts. Regenerate `assistant-config` for the new installed
path, then start a new harness session. Do not switch an active execution's pin.
The bridge check starts no model request and contacts no project.

For an existing starter host, retain `project.json` and `project.sqlite3`, stop at
a natural pause, select the upgraded endpoint and bridge, and explicitly set
`metadata.result_delivery_contract` to `"multivac-retained-result-v1"` in
`project.json` if that behavior is desired. Restart the owner-controlled endpoint
and bridge and check metadata before accepting new claims. Do not reinitialize
the project over existing evidence. Project methods, tasks and acceptance remain
under the owner's control.

Recover a saved assistant result with `multivac-client collect CONTRIBUTION_ID`,
or saved ChatGPT output with `multivac-plan collect CONTRIBUTION_ID`. Recovery
sends the saved evidence and retrieves the project receipt; it does not repeat
research. Cancellation releases the platform reservation; separately stop any
execution your own harness is running. Keep original evidence after either action.
