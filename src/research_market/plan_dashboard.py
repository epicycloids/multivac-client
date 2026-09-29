"""Participant-owned loopback UI. Provider credentials never reach JavaScript."""

from __future__ import annotations

import asyncio
import json
import secrets
import threading
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .chatgpt_plan import PlanError
from .models import Offer
from .plan_contribution import collect_plan_result, contribution_directory, run_plan_report

TERMINAL = {"accepted", "rejected", "cancelled", "expired", "failed"}


class Dashboard:
    def __init__(self, remote, plan):
        self.remote, self.plan = remote, plan
        self.lock = threading.RLock()
        self.csrf = secrets.token_urlsafe(32)
        self.origin = None
        self.pending = None
        self.platform = {"state": "unchecked"}
        self.current = None
        self.job = None
        self.job_kind = None
        self.outcome = None
        self.error = None
        self.authorization_error = None
        self.offer_request = None
        self.loop = self.task = None

    def snapshot(self):
        with self.lock:
            record = self.current or {}
            return {
                "account": self.plan.status(),
                "platform": self.platform,
                "origin": self.remote.origin,
                "running": bool(self.job and self.job.is_alive()),
                "job_kind": self.job_kind,
                "contribution": {k: record.get(k) for k in ("id", "state", "project_id")},
                "outcome": self.outcome,
                "error": self.error,
                "authorization_error": self.authorization_error,
            }

    def idle(self):
        if self.job and self.job.is_alive():
            raise ValueError("A contribution is still running. Stop it or wait for its result.")

    def action(self, route, value):
        with self.lock:
            if route == "/api/platform/connect":
                self.platform = self.remote.connect("Multivac local dashboard")
                return self.platform
            if route == "/api/platform/check":
                self.platform = self.remote.poll()
                return self.platform
            if route == "/api/chatgpt/connect":
                self.idle()
                self.pending = self.plan.begin(
                    self.origin + "/auth/callback", enable_plan=value.get("enable_plan") is True
                )
                self.authorization_error = None
                return {"url": "/authorize"}
            if route == "/api/chatgpt/disconnect":
                self.idle()
                return self.plan.disconnect()
            if route == "/api/reserve":
                self.idle()
                if self.current and self.current.get("state") not in TERMINAL:
                    raise ValueError("Finish or cancel the current contribution first.")
                offer = Offer(
                    project_id=value["project"],
                    allowed_projects=[value["project"]],
                    kind="agent",
                    budget_seconds=value["seconds"],
                    allow_network=True,
                )
                body = offer.model_dump()
                if self.offer_request and self.offer_request["offer"] != body:
                    raise ValueError(
                        "The earlier reservation has an uncertain response. Retry its original settings or inspect your contributions."
                    )
                if not self.offer_request:
                    self.offer_request = {"offer": body, "id": uuid.uuid4().hex}
                self.current = self.remote.grant(
                    offer, agent=True, request_id=self.offer_request["id"]
                )
                self.offer_request = None
                self.outcome = self.error = None
                return self.current
            if route == "/api/work":
                identifier = value.get("id") or (self.current or {}).get("id", "")
                contribution_directory(self.remote, identifier)
                if self.job and self.job.is_alive() and identifier != self.current["id"]:
                    raise ValueError("Wait for the current contribution before opening another.")
                if identifier != (self.current or {}).get("id"):
                    self.outcome = self.error = None
                self.current = self.remote.contribution(identifier, summary=True, timeout=5)
                return self.current
            if route == "/api/task":
                if not self.current:
                    raise ValueError("Choose a contribution first.")
                self.current = self.remote.contribution(self.current["id"], timeout=10)
                return self.current
            if route == "/api/cancel":
                if not self.current:
                    raise ValueError("There is no current contribution.")
                self.current = self.remote.call(
                    "POST", f"/contributions/{self.current['id']}/cancel", timeout=10
                )
                if self.loop and self.task:
                    self.loop.call_soon_threadsafe(self.task.cancel)
                return self.current
            if route in {"/api/run", "/api/collect"}:
                self.idle()
                if not self.current or value.get("id") != self.current["id"]:
                    raise ValueError("Review the current contribution before starting.")
                identifier = self.current["id"]
                if route == "/api/run":
                    if value.get("confirmed") is not True:
                        raise ValueError(
                            "Authorize this task and its ChatGPT plan use before starting."
                        )
                    if self.current.get("state") != "ready":
                        raise ValueError("Wait for a ready task before starting.")
                    if not isinstance(value.get("model"), str) or not value["model"]:
                        raise ValueError("Choose an available model.")

                    async def work():
                        return await run_plan_report(
                            self.remote,
                            self.plan,
                            identifier,
                            model=value["model"],
                            web_search=value.get("web_search") is True,
                        )
                else:

                    async def work():
                        return await collect_plan_result(self.remote, identifier)

                self.outcome = self.error = None
                self.job_kind = "report" if route == "/api/run" else "collect"

                async def execute():
                    with self.lock:
                        self.loop, self.task = asyncio.get_running_loop(), asyncio.current_task()
                    return await work()

                def background():
                    try:
                        result = asyncio.run(execute())
                        with self.lock:
                            self.outcome = {
                                k: result.get(k)
                                for k in ("state", "contribution_id", "billing_source")
                            }
                    except (ValueError, PlanError) as error:
                        with self.lock:
                            self.error = str(error)
                    except asyncio.CancelledError:
                        with self.lock:
                            self.error = "Contribution stopped. Preserve the saved attempt; provider usage may be incomplete."
                    except Exception:
                        with self.lock:
                            self.error = "The request was interrupted. Saved evidence is retained; collect the result without repeating inference."
                    finally:
                        try:
                            record = self.remote.contribution(identifier, summary=True, timeout=5)
                            with self.lock:
                                self.current = record
                        except Exception:
                            pass
                        with self.lock:
                            self.loop = self.task = None

                self.job = threading.Thread(target=background, daemon=True)
                self.job.start()
                return {"started": True, "contribution_id": identifier}
            raise ValueError("Unknown action.")

    def read(self, route):
        if route == "/api/state":
            return self.snapshot()
        if route == "/api/models":
            return {"models": self.plan.models()}
        if route == "/api/projects":
            return self.remote.call("GET", "/projects", timeout=10)
        if route == "/api/history":
            return self.remote.call("GET", "/contributions?view=summary", timeout=10)
        if route == "/api/evidence":
            with self.lock:
                if not self.current:
                    raise ValueError("Choose a contribution first.")
                path = contribution_directory(self.remote, self.current["id"])
                return {
                    name: json.loads((path / (name + ".json")).read_text())
                    for name in ("attempt", "result", "receipt")
                    if (path / (name + ".json")).is_file()
                }
        raise ValueError("Unknown page.")

    def close(self):
        with self.lock:
            if self.loop and self.task:
                self.loop.call_soon_threadsafe(self.task.cancel)
        if self.job:
            self.job.join(timeout=12)


def make_dashboard(remote, plan, *, port=0):
    state = Dashboard(remote, plan)
    root = Path(__file__).parent

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Callback query strings and provider errors are never access logs.

        def reply(self, status, body, content_type="application/json", **headers):
            if content_type == "application/json":
                body = json.dumps(body, allow_nan=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
            )
            for key, value in headers.items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

        def permitted(self, *, api=False):
            if self.headers.get("Host") != urlparse(state.origin).netloc:
                self.reply(403, {"error": "Use the local address printed by Multivac."})
                return False
            if api and (
                not secrets.compare_digest(self.headers.get("X-Multivac-CSRF", ""), state.csrf)
                or self.headers.get("Origin", state.origin) != state.origin
            ):
                self.reply(403, {"error": "Open this action from the local Multivac page."})
                return False
            return True

        def do_GET(self):
            parsed = urlparse(self.path)
            if not self.permitted(api=parsed.path.startswith("/api/")):
                return
            try:
                if parsed.path == "/" and not parsed.query:
                    body = (
                        (root / "plan_ui.html").read_text().replace("__CSRF__", state.csrf).encode()
                    )
                    self.reply(200, body, "text/html; charset=utf-8")
                elif parsed.path in {"/plan_ui.css", "/plan_ui.js"} and not parsed.query:
                    mime = "text/css" if parsed.path.endswith("css") else "text/javascript"
                    self.reply(200, (root / parsed.path[1:]).read_bytes(), mime + "; charset=utf-8")
                elif parsed.path == "/authorize" and not parsed.query:
                    with state.lock:
                        if not state.pending or state.pending.consumed:
                            raise ValueError("Start a new connection from Multivac.")
                        self.reply(302, b"", "text/plain", Location=state.pending.url)
                elif parsed.path == "/auth/callback":
                    fields = parse_qs(parsed.query, keep_blank_values=True)
                    if any(len(v) != 1 for v in fields.values()):
                        raise ValueError("Invalid authorization callback.")
                    with state.lock:
                        if not state.pending:
                            raise ValueError("No authorization is pending.")
                        try:
                            state.plan.finish(state.pending, {k: v[0] for k, v in fields.items()})
                            state.authorization_error = None
                        except PlanError as error:
                            state.authorization_error = str(error)
                    self.reply(303, b"", "text/plain", Location="/")
                elif parsed.path.startswith("/api/") and not parsed.query:
                    self.reply(200, state.read(parsed.path))
                else:
                    self.reply(404, {"error": "Page not found."})
            except (ValueError, KeyError) as error:
                self.reply(
                    400,
                    {
                        "error": str(error)
                        if isinstance(error, ValueError)
                        else "Incomplete request."
                    },
                )
            except Exception:
                self.reply(
                    503,
                    {
                        "error": "The request could not finish. Retry from this page; no account or billing fallback was used."
                    },
                )

        def do_POST(self):
            if not self.permitted(api=True):
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 16384:
                    raise ValueError("Invalid request size.")
                value = json.loads(self.rfile.read(length))
                if not isinstance(value, dict):
                    raise ValueError("Expected a structured request.")
                self.reply(200, state.action(self.path, value))
            except (ValueError, KeyError) as error:
                self.reply(
                    400,
                    {
                        "error": str(error)
                        if isinstance(error, ValueError)
                        else "Incomplete request."
                    },
                )
            except Exception:
                self.reply(
                    503,
                    {
                        "error": "The request could not finish. Check its saved state before repeating work."
                    },
                )

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    state.origin = f"http://127.0.0.1:{server.server_port}"
    return server, state


def serve_dashboard(remote, plan, *, port=0, open_browser=True):
    server, state = make_dashboard(remote, plan, port=port)
    print(f"Open Multivac on this device: {state.origin}", flush=True)
    print("Keep this terminal open. Ctrl+C stops the local connector.", flush=True)
    if open_browser:
        webbrowser.open(state.origin)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        state.close()
        server.server_close()
