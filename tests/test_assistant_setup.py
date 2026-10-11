"""Local assistant configuration and synthetic MCP contribution cycles."""

import json
import shlex
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from typer.testing import CliRunner

from research_market.assistant_setup import (
    assistant_config,
    assistant_setup,
    check_assistant_bridge,
)
from research_market.models import Offer
from research_market.project_starter import ProjectInbox, scaffold
from research_market.remote_cli import app
from research_market.remote_client import RemoteClient, assistant_result_directory


def test_setup_preserves_connection_and_quotes_commands_without_credentials(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = RemoteClient(connection="research", directory=tmp_path / "state with ' quotes")
    client.save({"token": "SECRET_SENTINEL", "identity": {"role": "contributor"}})
    setup = assistant_setup(client)
    server = setup["mcpServers"]["multivac"]
    assert "SECRET_SENTINEL" not in json.dumps(setup)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    arguments = server["args"]
    resumed = RemoteClient(connection="research", directory=client.directory.parent)
    assert resumed.path == client.path
    for profile in setup["profiles"]:
        if profile["format"] == "json":
            assert json.loads(profile["setup"])["mcpServers"]["multivac"] == server
        else:
            words = shlex.split(profile["setup"])
            assert words[words.index("--") + 1 :] == [server["command"], *arguments]
        result = CliRunner().invoke(
            app,
            [
                "--connection",
                "research",
                "--data-dir",
                str(client.directory.parent),
                "assistant-config",
                "--harness",
                profile["id"],
            ],
        )
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["setup"] == profile["setup"]
    assert client.config["token"] == "SECRET_SENTINEL"
    client.http.close()
    resumed.http.close()


@pytest.mark.parametrize("role", ["contributor", "overseer"])
async def test_bridge_check_starts_role_scoped_tools_without_platform_access(tmp_path, role):
    client = RemoteClient(origin="http://127.0.0.1:1", directory=tmp_path)
    client.save({"identity": {"role": role}, "token": "synthetic-check-token"})
    result = await check_assistant_bridge(client)
    assert result["state"] == "ready" and result["model_calls"] == 0
    if role == "overseer":
        assert "inspect_allocation" in result["tools"]
        assert "offer_resources" not in result["tools"]
    else:
        assert {"offer_resources", "recover_result", "inspect_local_capabilities"} <= set(result["tools"])
        assert "inspect_allocation" not in result["tools"]
    assert not (client.directory / "requests").exists()
    client.http.close()


def test_saved_result_survives_failure_and_delayed_project_receipt(tmp_path):
    client = RemoteClient(directory=tmp_path)
    client.save({"token": "synthetic-recovery-token"})
    receipt = {"accepted": True, "review_required": True, "new_research_claim": False}
    calls = []

    def receive(request):
        calls.append(request)
        if len(calls) == 1:
            raise httpx.ConnectError("Synthetic delivery failure")
        return httpx.Response(
            200,
            json={"state": "delivering"}
            if request.method == "POST"
            else {"state": "accepted", "receipt": receipt},
        )

    client.http.close()
    client.http = httpx.Client(transport=httpx.MockTransport(receive))
    artifact = {"report": "Synthetic protocol result", "test_only": True, "research_claim": False}
    with pytest.raises(httpx.ConnectError):
        client.submit_result("fixture", artifact, {"model_calls": 0})
    path = assistant_result_directory(client, "fixture")
    original = (path / "result.json").read_bytes()
    assert (path / "result.json").stat().st_mode & 0o777 == 0o600
    assert client.collect_result("fixture")["state"] == "delivering"
    assert not (path / "receipt.json").exists()
    assert client.contribution("fixture")["receipt"] == receipt
    assert json.loads((path / "receipt.json").read_text()) == receipt
    assert (path / "result.json").read_bytes() == original
    assert calls[0].content == calls[1].content
    with pytest.raises(ValueError, match="different saved result"):
        client.submit_result("fixture", {"report": "Changed synthetic report"}, {})
    for identifier in ("../escape", "/tmp/elsewhere", "bad?value"):
        with pytest.raises(ValueError, match="identifier"):
            client.collect_result(identifier)
    assert len(calls) == 3
    client.http.close()


def test_concurrent_different_results_cannot_replace_saved_evidence(tmp_path):
    client = RemoteClient(directory=tmp_path)
    submitted = []

    def receive(*args):
        submitted.append(args[-1])
        return {"state": "delivering"}

    client.call = receive

    def send(label):
        try:
            return client.submit_result("fixture", {"report": label}, {})
        except ValueError as error:
            return str(error)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(send, ["Synthetic A", "Synthetic B"]))
    assert len(submitted) == 1
    assert sum(isinstance(result, dict) for result in results) == 1
    saved = assistant_result_directory(client, "fixture") / "result.json"
    assert json.loads(saved.read_text()) == submitted[0]
    client.http.close()


async def test_real_stdio_bridge_completes_synthetic_independent_project_cycle(tmp_path):
    directory = tmp_path / "project"
    scaffold(
        directory,
        "protocol-fixture",
        "Synthetic project",
        "Exercise the contribution protocol with synthetic test data.",
    )
    inbox = ProjectInbox(directory)
    records, leases, result_posts = {}, {}, []
    readiness, offer_posts, start_posts = [False], [], []
    identity = {"id": "fixture-device", "role": "contributor", "projects": ["protocol-fixture"]}

    class Platform(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, value, status=200):
            body = json.dumps(value).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            assert self.headers["Authorization"] == "Bearer synthetic-mcp-token"
            if self.path.endswith("/session"):
                self.reply({"identity": identity})
            elif self.path.endswith("/projects"):
                self.reply({"projects": [{"id": "protocol-fixture", "title": "Synthetic project",
                                          "ready": readiness[0]}]})
            else:
                self.reply(records[self.path.split("/")[-1]])

        def do_POST(self):
            assert self.headers["Authorization"] == "Bearer synthetic-mcp-token"
            value = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            if self.path.endswith("/contributions"):
                offer_posts.append(value)
                if not readiness[0]:
                    self.reply({"detail": "Synthetic project not ready; inspect availability."}, 409)
                    return
                identifier = value["request_id"]
                work = inbox.claim(value["offer"], identifier)
                leases[identifier] = work["lease_token"]
                records[identifier] = {
                    "id": identifier,
                    "project_id": "protocol-fixture",
                    "kind": "agent",
                    "state": "ready",
                    "task": work["task"],
                    "offer": value["offer"],
                }
            else:
                identifier = self.path.split("/")[-2]
                if self.path.endswith("/start"):
                    start_posts.append(identifier)
                    records[identifier].update(state="running", deadline=time.time() + 90)
                elif self.path.endswith("/result"):
                    result_posts.append(value)
                    if len(result_posts) == 1:
                        self.reply({"detail": "Synthetic delivery interruption"}, 503)
                        return
                    receipt = inbox.finish(
                        identifier, leases[identifier], value["artifact"], value["usage"]
                    )
                    records[identifier].update(state="accepted", receipt=receipt)
                else:
                    raise AssertionError(self.path)
            self.reply(records[identifier])

    platform = ThreadingHTTPServer(("127.0.0.1", 0), Platform)
    thread = threading.Thread(target=platform.serve_forever, daemon=True)
    thread.start()
    client = RemoteClient(
        origin=f"http://127.0.0.1:{platform.server_port}", directory=tmp_path / "client"
    )
    client.save({"token": "synthetic-mcp-token", "identity": identity})
    server = assistant_config(client)["mcpServers"]["multivac"]
    try:
        async with stdio_client(StdioServerParameters(**server, cwd=str(tmp_path))) as streams:
            async with ClientSession(*streams, read_timeout_seconds=10) as session:
                await session.initialize()
                tools = await session.list_tools()
                offered_schema = next(tool for tool in tools.tools if tool.name == "offer_resources").model_dump(by_alias=True)
                schema_text = json.dumps(offered_schema)
                assert all(name in schema_text for name in ("execution_profiles", "asset_labels", "agent_profile"))
                capabilities = await session.call_tool("inspect_local_capabilities", {})
                assert not capabilities.is_error

                async def call(name, args=None):
                    result = await session.call_tool(name, args or {})
                    assert not result.is_error, result
                    value = result.structured_content
                    if value is None:
                        value = json.loads(
                            next(item.text for item in result.content if hasattr(item, "text"))
                        )
                    return value.get("result", value)

                assert (await call("connection_status"))["identity"] == identity
                assert (await call("list_projects"))["projects"][0]["id"] == "protocol-fixture"
                offer = Offer(
                    project_id="protocol-fixture",
                    allowed_projects=["protocol-fixture"],
                    kind="agent",
                    allow_network=True,
                    budget_seconds=90,
                ).model_dump()
                offered = {"offer": offer, "request_id": "synthetic-cycle"}
                denied = await session.call_tool("offer_resources", offered)
                assert denied.is_error
                reason = " ".join(item.text for item in denied.content if hasattr(item, "text"))
                assert "Platform response 409" in reason and "Synthetic project not ready" in reason
                assert "list_projects" in reason and "same request ID" in reason
                assert "synthetic-mcp-token" not in reason
                assert not records and not start_posts and inbox.read()["active"] == 0
                readiness[0] = True
                assert (await call("list_projects"))["projects"][0]["ready"]
                record = await call("offer_resources", offered)
                assert await call("offer_resources", offered) == record
                assert record["state"] == "ready"
                assert len(records) == 1 and inbox.read()["active"] == 1 and not start_posts
                assert offer_posts[0] == offer_posts[1] == offer_posts[2]
                assert json.loads(client.offer_request_path("synthetic-cycle").read_text()) == offer_posts[0]
                preserved = client.offer_request_path("synthetic-cycle").read_bytes()
                changed = {**offered, "offer": {**offer, "budget_seconds": 91}}
                conflict = await session.call_tool("offer_resources", changed)
                assert conflict.is_error
                conflict_reason = " ".join(item.text for item in conflict.content if hasattr(item, "text"))
                assert "new request ID" in conflict_reason and "original saved request" in conflict_reason
                assert len(offer_posts) == 3 and client.offer_request_path("synthetic-cycle").read_bytes() == preserved
                await call("inspect_contribution", {"contribution_id": "synthetic-cycle"})
                await call("start_contribution", {"contribution_id": "synthetic-cycle"})
                artifact = {
                    "report": "Synthetic MCP protocol test: exercise saved result recovery and receipt delivery. No research was performed.",
                    "test_only": True,
                    "research_claim": False,
                }
                failure = await session.call_tool(
                    "return_result",
                    {
                        "contribution_id": "synthetic-cycle",
                        "artifact": artifact,
                        "usage": {"model_calls": 0},
                    },
                )
                assert failure.is_error
                completed = await call("recover_result", {"contribution_id": "synthetic-cycle"})
                repeated = await call("recover_result", {"contribution_id": "synthetic-cycle"})
                assert repeated["receipt"] == completed["receipt"]
        assert completed["receipt"] == inbox.read()["findings"][0]
        assert (
            completed["receipt"]["review_required"]
            and not completed["receipt"]["new_research_claim"]
        )
        assert len(inbox.read()["findings"]) == 1 and inbox.read()["active"] == 0
        assert len(records) == 1 and result_posts[0] == result_posts[1] == result_posts[2]
        assert start_posts == ["synthetic-cycle"]
        saved = assistant_result_directory(client, "synthetic-cycle")
        assert json.loads((saved / "result.json").read_text())["artifact"] == artifact
        assert json.loads((saved / "receipt.json").read_text()) == completed["receipt"]
    finally:
        client.http.close()
        platform.shutdown()
        platform.server_close()
        thread.join(timeout=3)
