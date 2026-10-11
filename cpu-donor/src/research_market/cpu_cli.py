"""Contribute CPU resources through the existing reviewed donor execution path."""

from __future__ import annotations

import json
import time
from pathlib import Path

import typer

from .cpu_profile import CPU_PROJECTS, TREFETHEN_REV, prepare_cpu
from .models import Offer
from .remote_client import DEFAULT_ORIGIN, RemoteClient
from .trefethen import TrefethenExecutionUnavailable, require_environment

app = typer.Typer(
    no_args_is_help=True,
    pretty_exceptions_show_locals=False,
    help="Private Linux CPU donor candidate. Contribute only the installed reviewed profile.",
)


def show(value):
    typer.echo(json.dumps(value, indent=2))


@app.callback()
def connection(ctx: typer.Context, origin: str = DEFAULT_ORIGIN, connection: str = "cpu-donor"):
    ctx.obj = RemoteClient(origin, connection)


@app.command()
def connect(
    ctx: typer.Context, label: str = "My CPU contribution", wait: bool = True, renew: bool = False
):
    """Request normal inviter admission; share only the printed pairing code."""
    result = ctx.obj.connect(label, renew=renew)
    show(result)
    if result.get("state") == "approved":
        return
    typer.echo("Ask your inviter to approve this code for the projects you choose.")
    if wait:
        for _ in range(360):
            result = ctx.obj.poll()
            if result["state"] == "approved":
                show(result)
                return
            time.sleep(5)
        raise typer.Exit(1)


@app.command()
def status(ctx: typer.Context):
    """Finish pending admission or inspect your identity; credentials are omitted."""
    show(ctx.obj.poll())


@app.command()
def projects(ctx: typer.Context):
    """Discover projects; only compatible, permitted projects can receive this CPU work."""
    show(ctx.obj.call("GET", "/projects"))


@app.command("prepare-cpu")
def prepare():
    """Prepare the pinned numerical environment as this donor user; start no work."""
    prepare_cpu()
    require_environment()
    show({"environment_ready": True, "source_revision": TREFETHEN_REV, "work_started": False})


@app.command()
def capabilities(ctx: typer.Context):
    """Check pinned-source readiness without offering or starting work."""
    report = ctx.obj.local_capabilities()
    show({
        "cpu": report["cpu"],
        "reviewed_projects": list(CPU_PROJECTS),
        "source_revision": TREFETHEN_REV,
        "memory_enforcement": "Checked at launch: user cgroup scope when available; "
        "otherwise per-process virtual address-space limits. Inspect result usage for the mode used.",
        "work_started": False,
    })


@app.command()
def offer(
    ctx: typer.Context,
    project: list[str] = typer.Option(["trefethen-arena"]),
    policy: str = "manual",
    seconds: int = 90,
    memory_mb: int = 2048,
    cores: int = 1,
    request_id: str | None = None,
):
    """Reserve a reviewed CPU task within your limits; inspect it before run-cpu."""
    if not project or not set(project).issubset(CPU_PROJECTS):
        raise ValueError("This installed CPU profile supports only: " + ", ".join(CPU_PROJECTS))
    grant = Offer(
        project_id=project[0],
        allowed_projects=project,
        policy=policy,
        kind="cpu",
        budget_seconds=seconds,
        memory_mb=memory_mb,
        cpu_cores=cores,
        allow_network=False,
    )
    # Missing preparation must not consume a project reservation.
    try:
        require_environment()
    except TrefethenExecutionUnavailable as error:
        raise ValueError(str(error)) from None
    show(ctx.obj.grant(grant, request_id=request_id))


@app.command()
def contributions(ctx: typer.Context):
    """List your contribution status and receipts."""
    show(ctx.obj.call("GET", "/contributions"))


@app.command()
def inspect(ctx: typer.Context, identifier: str):
    """Read the assignment, original deadline, allocation reason and project receipt."""
    show(ctx.obj.contribution(identifier))


@app.command("context")
def context(ctx: typer.Context, identifier: str, output: Path | None = None):
    """Verify and save project-selected context without executing it."""
    show(ctx.obj.save_context(identifier, output))


@app.command("run-cpu")
def run_cpu(ctx: typer.Context, identifier: str):
    """Start and run the reviewed task once; retain its result before delivery."""
    show(ctx.obj.run_cpu(identifier))


@app.command("collect")
def collect(ctx: typer.Context, identifier: str):
    """Retry saved output and inspect delivery; do not repeat computation."""
    show(ctx.obj.collect_result(identifier))


@app.command()
def cancel(ctx: typer.Context, identifier: str):
    """Cancel the grant; a running donor observes cancellation on its next state check."""
    show(ctx.obj.call("POST", f"/contributions/{identifier}/cancel"))
