"""Commands for local ChatGPT sign-in and research contributions."""

from __future__ import annotations

import asyncio
import html
import json
import os
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import typer

from .chatgpt_plan import PlanClient, PlanError
from .plan_contribution import collect_plan_result, run_plan_report
from .remote_client import DEFAULT_ORIGIN, RemoteClient

app = typer.Typer(
    no_args_is_help=True,
    pretty_exceptions_show_locals=False,
    help="Preview: connect a ChatGPT plan and contribute through this local client.",
)


@app.callback()
def account(
    ctx: typer.Context,
    account: str = "default",
    origin: str = DEFAULT_ORIGIN,
    connection: str = "device",
    data_dir: Path | None = None,
):
    base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
    directory = (
        data_dir or Path(os.environ.get("MARKET_DATA_DIR", base / "research-market")) / "remote"
    )
    remote = RemoteClient(origin, connection, directory=directory)
    ctx.obj = {"remote": remote, "plan": PlanClient(remote.directory / "chatgpt-plan", account)}
    ctx.call_on_close(ctx.obj["plan"].http.close)
    ctx.call_on_close(remote.http.close)


@app.command()
def status(ctx: typer.Context):
    """Read saved connection metadata. Credentials are omitted; no model is called."""
    typer.echo(json.dumps(ctx.obj["plan"].status(), indent=2))


@app.command()
def models(ctx: typer.Context):
    """List models available to the selected ChatGPT registration."""
    typer.echo(json.dumps(ctx.obj["plan"].models(), indent=2))


def page(message, *, start=False):
    action = '<a href="/authorize">Continue with ChatGPT</a>' if start else ""
    return (
        "<!doctype html><html lang='en'><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>Multivac · ChatGPT connection</title>"
        "<style>body{background:#f5f3ed;color:#202a35;font:18px/1.65 system-ui;"
        "max-width:650px;margin:12vh auto;padding:24px}h1{font-size:36px;line-height:1.2}"
        "a{display:inline-block;padding:12px 20px;border-radius:8px;background:#202a35;"
        "color:white;text-decoration:none;margin-top:20px}small{display:block;margin-top:28px}</style>"
        "<main><p>Multivac / Local connector preview</p><h1>Connect your ChatGPT plan</h1>"
        f"<p>{html.escape(message)}</p>{action}"
        "<small>Review a task and choose when to start. Credentials stay in this local client. "
        "Review app access and limits in ChatGPT Settings → Usage.</small></main></html>"
    ).encode()


def login_local(plan: PlanClient, *, enable_plan=False, open_browser=True, ready=None):
    """Serve the loopback sign-in page with authorization and callback logging disabled."""
    outcome = {}
    pending = None
    expected_host = None

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, code, message, *, start=False):
            body = page(message, start=start)
            self.send_response(code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.headers.get("Host") != expected_host:
                self.reply(400, "Use the local address printed by the client.")
                return
            parsed = urlparse(self.path)
            if parsed.path == "/" and not parsed.query:
                self.reply(
                    200,
                    "Connect an eligible ChatGPT account to this installation. "
                    "Choose app permissions at OpenAI. Local sign-in and model requests "
                    "have not been verified with a real account.",
                    start=True,
                )
            elif parsed.path == "/authorize" and not parsed.query:
                self.send_response(302)
                self.send_header("Location", pending.url)
                self.send_header("Cache-Control", "no-store")
                self.send_header("Referrer-Policy", "no-referrer")
                self.end_headers()
            elif parsed.path == "/auth/callback":
                fields = parse_qs(parsed.query, keep_blank_values=True)
                if any(len(v) != 1 for v in fields.values()):
                    self.reply(400, "The sign-in callback is invalid.")
                    return
                try:
                    outcome["result"] = plan.finish(pending, {k: v[0] for k, v in fields.items()})
                except PlanError as error:
                    self.reply(400, str(error))
                    # A mismatched callback cannot close a legitimate sign-in attempt.
                    if pending.consumed:
                        outcome["error"] = error
                    return
                self.reply(
                    200,
                    "Connected. Return to Multivac to choose a project, model, and time allowance, "
                    "then review a task before starting research."
                    if outcome["result"]["plan_use_authorized"]
                    else "Signed in. ChatGPT plan use is disabled; no model requests will run.",
                )
            else:
                self.reply(404, "Page not found.")

    with HTTPServer(("127.0.0.1", 0), Handler) as server:
        expected_host = f"127.0.0.1:{server.server_port}"
        origin = "http://" + expected_host
        pending = plan.begin(origin + "/auth/callback", enable_plan=enable_plan)
        server.timeout = 0.5
        if ready:
            ready(origin)
        if open_browser:
            webbrowser.open(origin)
        while not outcome and time.time() < pending.expires_at:
            server.handle_request()
    if outcome.get("error"):
        raise outcome["error"]
    if not outcome:
        raise PlanError("authorization_expired")
    return outcome["result"]


@app.command("connect")
def connect(ctx: typer.Context, enable_plan: bool = False, open_browser: bool = True):
    """Open OpenAI's consent page for an eligible local or approved client."""
    result = login_local(
        ctx.obj["plan"],
        enable_plan=enable_plan,
        open_browser=open_browser,
        ready=lambda origin: typer.echo("Open this local connection page: " + origin),
    )
    typer.echo(json.dumps(result, indent=2))


@app.command()
def disconnect(ctx: typer.Context):
    """Revoke this client's renewable session and clear only its local tokens."""
    typer.echo(json.dumps(ctx.obj["plan"].disconnect(), indent=2))


@app.command("run-report")
def run_report(
    ctx: typer.Context, identifier: str, model: str = typer.Option(...), web_search: bool = False
):
    """Use the selected plan for one reserved agent contribution and return its report.

    Sends the task and project-published context to OpenAI. This report profile
    has no shell or local data access. The selected account and billing path stay
    fixed. Repeating this command leaves any prior execution attempt unchanged.
    """
    result = asyncio.run(
        run_plan_report(
            ctx.obj["remote"], ctx.obj["plan"], identifier, model=model, web_search=web_search
        )
    )
    typer.echo(json.dumps(result, indent=2))


@app.command("collect")
def collect(ctx: typer.Context, identifier: str, wait_seconds: int = 20):
    """Retry saved result delivery and collect its receipt without using the model again."""
    result = asyncio.run(
        collect_plan_result(ctx.obj["remote"], identifier, wait_seconds=wait_seconds)
    )
    typer.echo(json.dumps(result, indent=2))


@app.command("dashboard")
def dashboard(ctx: typer.Context, port: int = 0, open_browser: bool = True):
    """Open the local browser interface to connect, review tasks, and contribute."""
    from .plan_dashboard import serve_dashboard

    serve_dashboard(ctx.obj["remote"], ctx.obj["plan"], port=port, open_browser=open_browser)


def main():
    try:
        app()
    except (ValueError, httpx.HTTPError) as error:
        typer.echo(str(error), err=True)
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
