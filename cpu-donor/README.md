# Optional Linux CPU donor · 0.1.0a1

This prerelease candidate contributes CPU to an invitation-based Multivac pilot.
It is separate from the portable `multivac-client 0.4.0a3`: install it in its own
environment. Both packages use the same Python namespace and must not be
installed together. The CPU donor has one reviewed numerical profile and no
arbitrary-code, GPU, model or general compute-pool executor.

The supported project IDs are `trefethen-arena` and `trefethen-autonomous`, subject
to your invitation and ready work. Projects issue tasks and acceptance receipts;
Multivac connects and allocates your contribution within your chosen limits.
The current task reproduces an existing Trefethen certificate Gram batch. A valid
870-place reproduction can receive `rejected_min_improvement`; it adds no digits.

## Install and connect

Obtain the matching CPU wheel, source archive, `requirements.lock` and
`SHA256SUMS` from your inviter or an approved CPU donor prerelease. CPU release
tags use `cpu-donor-v...`; portable client tags use `v...`. This source candidate
does not establish that a CPU release has been published.

Use Linux x86_64, Git and `uv`, with a writable directory owned by the same user
who will contribute. The tested client environment is Python 3.13.8 on
glibc 2.39. Package metadata accepts Python 3.12–3.14; the CPU runtime's fresh
installation was qualified on 3.13.8. The numerical project separately uses
Python 3.14, `python-flint 0.9.0` and `numpy 2.5.1`; qualification used 3.14.0.
Internet access is needed for setup and the platform connection.

After downloading all matching assets, verify them and choose a new donor
directory. Replace the example path with a directory you can write:

```sh
sha256sum --check SHA256SUMS
donor_dir=/path/to/new-donor-directory
mkdir -p "$donor_dir"
export UV_CACHE_DIR="$donor_dir/uv-cache"
export UV_PYTHON_INSTALL_DIR="$donor_dir/python"
export MARKET_DATA_DIR="$donor_dir/data"
uv venv --python 3.13.8 "$donor_dir/client"
uv pip sync --python "$donor_dir/client/bin/python" --require-hashes \
  --only-binary :all: requirements.lock
uv pip install --python "$donor_dir/client/bin/python" --no-deps \
  multivac_cpu_donor-0.1.0a1-py3-none-any.whl
cpu="$donor_dir/client/bin/multivac-cpu"
"$cpu" connect --label "My CPU contribution" --no-wait
```

Share only the printed pairing code with your inviter, who approves your identity
and permitted projects. Run `"$cpu" status` to finish admission. Keep your client
environment and data directory separate from existing installations and research.
Preserve these environment settings across terminals. The default state directory
is `~/.local/state/multivac-cpu-donor`; the explicit `MARKET_DATA_DIR` above keeps
connection, numerical and contribution state together in your chosen directory.
Supply a different `--origin` or `--connection` consistently if your inviter asks.

## Prepare, offer, inspect and run

```sh
"$cpu" prepare-cpu
"$cpu" capabilities
"$cpu" projects
"$cpu" offer --project trefethen-arena --policy manual \
  --seconds 90 --memory-mb 2048 --cores 1 --request-id my-cpu-01
"$cpu" inspect CONTRIBUTION_ID
"$cpu" run-cpu CONTRIBUTION_ID
"$cpu" inspect CONTRIBUTION_ID
```

Preparation independently clones the public numerical source at
`d30e732f63a3d308fb6ab2fcb5a3948011bbe42e` and runs its own `uv sync --frozen`.
It starts no computation or project-host services. Git, the interpreter and
certificate inputs must be accessible as the donor user. A wrong existing source
revision is rejected rather than reset. The client's `UV_PYTHON` and `VIRTUAL_ENV`
are excluded from numerical setup so that project's interpreter remains separate.

Use the ID returned by `offer`. Local preparation is checked before reserving
work, and again before running it. Offering alone starts no computation. Inspect
the task, allocation reason, limits and deadline before executing. The command
accepts only the reviewed operation and exact source revision within your offer.
Repeat `--project` to permit both reviewed projects; existing `weighted`,
`performance` or `managed` policies remain within your permitted list and limits.
The schema allows at most 900 seconds, four cores and 8192 MB. Choose smaller
limits that fit your host; the numerical profile runs with one library thread.

## Receipt, recovery and stop

If delivery is pending, inspect again for the project receipt. A disconnected
donor can retry saved output without repeating calculation:

```sh
"$cpu" collect CONTRIBUTION_ID
"$cpu" inspect CONTRIBUTION_ID
```

Artifact and usage are retained before sending. `collect` does not execute, and
repeating `run-cpu` with saved output collects it. An uncertain earlier attempt
without output is never rerun automatically. Inspect its private work directory
and cancel rather than deleting the attempt marker. Retrying an offer request ID
retains its original parameters; use a new ID when changing limits or projects.
Reconnection and retries never extend the original execution deadline.

When a working systemd user scope is available, the runner requests aggregate
cgroup memory/CPU caps and no swap. The qualified host used the fallback:
per-process virtual address-space and CPU-time limits, one-core affinity and an
original wall-deadline watchdog. Fallback is not an aggregate resident-memory or
swap cap. Check `usage.memory_enforcement` for the actual mode. Numerical threads
are one; usage is donor-reported OS accounting, not a provider attestation.

To choose to stop, use a second terminal with the same state and connection:

```sh
"$cpu" cancel CONTRIBUTION_ID
```

Cancellation is polled roughly every five seconds and process cleanup can add two
seconds for kill escalation. A cancellation response does not itself prove local
exit; wait for the runner to exit. During a platform outage, the local deadline
still applies. Ctrl+C in the runner triggers local process-group cleanup; cancel
the grant when connectivity returns. Local exit does not itself claim reservation
release, and identity revocation prevents future access rather than instantly
stopping local work. Retain your result and receipt before removing trial data.

The reviewed code runs with your user permissions. There is no OS network or
filesystem sandbox: `allow_network=false` does not block networking at OS level.
The successful reference cycle needed no operator source/lease repair. Its real
receipt and saved-result recovery were tested; deterministic running-stop fixtures
were separate from numerical work. These tests do not establish outside adoption,
other architectures, an exercised cgroup branch or arbitrary project-code support.
