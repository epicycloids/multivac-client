"""Loopback dashboard tests using synthetic provider and project data."""

import json
import threading
import time

import httpx
import pytest
from test_plan_contribution import local_cycle as local_cycle

from research_market.plan_dashboard import make_dashboard
from research_market.remote_client import RemoteClient, assistant_result_directory


@pytest.fixture
def dashboard(local_cycle):
    remote, plan, inbox = local_cycle
    remote.origin = "https://fixture.invalid"
    remote.path = remote.directory / "fixture.json"
    remote.config = {"token": "SECRET_SENTINEL", "identity": {"role": "contributor"}}
    plan.status = lambda: {
        "connected": True,
        "plan_use_authorized": True,
        "account": "synthetic",
        "email": "fixture@example.invalid",
    }
    remote.connect = lambda label: {
        "state": "approved",
        "identity": {"role": "contributor", "projects": ["protocol-fixture"]},
    }
    remote.poll = lambda: remote.connect("")
    remote.grant = lambda *args, **kwargs: remote.record
    server, state = make_dashboard(remote, plan)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    with httpx.Client(base_url=state.origin, trust_env=False, timeout=5) as http:
        yield http, state, remote, plan, inbox
    state.close()
    server.shutdown()
    server.server_close()
    thread.join(timeout=3)


def post(dashboard, route, body=None):
    http, state, *_ = dashboard
    return http.post(
        route, json=body or {}, headers={"Origin": state.origin, "X-Multivac-CSRF": state.csrf}
    )


def test_local_ui_loads_without_authentication_or_inference(dashboard):
    http, state, remote, plan, _ = dashboard
    response = http.get("/")
    assert response.status_code == 200
    assert "Continue with ChatGPT" in response.text and "__CSRF__" not in response.text
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert http.get("/plan_ui.js").status_code == 200
    assert http.get("/plan_ui.css").status_code == 200
    assert not plan.requests
    assert remote.record["state"] == "ready"
    response = http.get("/api/state", headers={"X-Multivac-CSRF": state.csrf})
    assert response.json()["running"] is False
    assert "token" not in response.text


def test_assistant_setup_needs_no_chatgpt_account_and_hides_credentials(dashboard):
    http, state, remote, plan, _ = dashboard
    plan.status = lambda: {"connected": False}
    response = http.get("/api/assistant-setup", headers={"X-Multivac-CSRF": state.csrf})
    assert response.status_code == 200
    assert "SECRET_SENTINEL" not in response.text
    assert {p["id"] for p in response.json()["profiles"]} == {
        "custom",
        "claude-code",
        "qwen",
        "kimi",
        "codex",
    }
    assert not plan.requests
    assert http.get("/api/assistant-setup").status_code == 403


def test_dashboard_shows_project_receipt_from_an_existing_assistant(dashboard):
    http, state, remote, plan, _ = dashboard
    receipt = {
        "accepted": True,
        "review_required": True,
        "artifact": {"report": "Synthetic assistant report"},
    }
    remote.record.update(state="accepted", receipt=receipt)
    assert post(dashboard, "/api/work", {"id": "fixture-contribution"}).status_code == 200
    evidence = http.get("/api/evidence", headers={"X-Multivac-CSRF": state.csrf}).json()
    assert evidence["receipt"] == receipt
    assert not plan.requests


def test_dashboard_recovers_saved_assistant_result_without_plan_execution(dashboard):
    _, state, fixture, plan, inbox = dashboard
    remote = RemoteClient(origin=fixture.origin, directory=fixture.directory)
    remote.call, remote.contribution = fixture.call, fixture.contribution
    state.remote = remote
    identifier = "fixture-contribution"
    fixture.failed_delivery = True
    artifact = {
        "report": "Synthetic assistant result for dashboard recovery. No research was performed.",
        "test_only": True,
        "research_claim": False,
    }
    try:
        with pytest.raises(ValueError, match="delivery failure"):
            remote.submit_result(identifier, artifact, {"model_calls": 0})
        saved = assistant_result_directory(remote, identifier)
        original = (saved / "result.json").read_bytes()
        fixture.failed_delivery = False
        assert post(dashboard, "/api/work", {"id": identifier}).status_code == 200
        assert post(dashboard, "/api/collect", {"id": identifier}).status_code == 200
        state.job.join(timeout=3)
        assert state.snapshot()["outcome"]["state"] == "accepted"
        evidence = state.read("/api/evidence")
        assert evidence["result"]["artifact"] == artifact
        assert evidence["receipt"] == inbox.read()["findings"][0]
        assert json.loads((saved / "receipt.json").read_text()) == evidence["receipt"]
        assert (saved / "result.json").read_bytes() == original
        assert not plan.requests and inbox.read()["active"] == 0
    finally:
        remote.http.close()


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Origin": "https://unrelated.invalid"},
        {"Host": "attacker.invalid"},
        {"X-Multivac-CSRF": "wrong"},
    ],
)
def test_cross_origin_or_untrusted_requests_cannot_trigger_work(dashboard, headers):
    http, state, _, plan, _ = dashboard
    baseline = {"Origin": state.origin, "X-Multivac-CSRF": state.csrf}
    supplied = {} if not headers else {**baseline, **headers}
    response = http.post(
        "/api/run",
        json={"id": "fixture-contribution", "confirmed": True, "model": "fixture-astra"},
        headers=supplied,
    )
    assert response.status_code == 403 and not plan.requests
    assert http.get("/api/state").status_code == 403


def test_review_authorization_and_project_receipt_cycle(dashboard):
    _, state, remote, plan, inbox = dashboard
    assert post(dashboard, "/api/platform/connect").json()["state"] == "approved"
    assert (
        post(dashboard, "/api/reserve", {"project": "protocol-fixture", "seconds": 90}).status_code
        == 200
    )
    assert not plan.requests
    request = {"id": "fixture-contribution", "model": "fixture-astra"}
    assert post(dashboard, "/api/run", request).status_code == 400
    assert not plan.requests
    assert post(dashboard, "/api/task").json()["task"]["project_id"] == "protocol-fixture"
    assert post(dashboard, "/api/run", {**request, "confirmed": True}).status_code == 200
    state.job.join(timeout=3)
    snapshot = state.snapshot()
    assert snapshot["outcome"]["state"] == "accepted" and not snapshot["running"]
    assert snapshot["contribution"]["state"] == "accepted"
    evidence = state.read("/api/evidence")
    assert evidence["receipt"] == inbox.read()["findings"][0]
    assert "Synthetic integration fixture" in evidence["result"]["artifact"]["report"]
    assert post(dashboard, "/api/collect", {"id": "fixture-contribution"}).status_code == 200
    state.job.join(timeout=3)
    assert len(plan.requests) == 1 and len(inbox.read()["findings"]) == 1


def test_cancellation_is_available_while_model_stream_is_silent(dashboard):
    _, state, remote, plan, _ = dashboard
    plan.wait = True
    post(dashboard, "/api/reserve", {"project": "protocol-fixture", "seconds": 90})
    post(
        dashboard,
        "/api/run",
        {"id": "fixture-contribution", "model": "fixture-astra", "confirmed": True},
    )
    deadline = time.monotonic() + 3
    while not plan.requests and time.monotonic() < deadline:
        time.sleep(0.01)
    assert plan.requests
    assert post(dashboard, "/api/chatgpt/disconnect").status_code == 400
    assert post(dashboard, "/api/cancel").status_code == 200
    state.job.join(timeout=3)
    assert plan.stopped and remote.record["state"] == "cancelled"
    assert not remote.submissions


def test_recovery_rejects_path_escape_and_current_work_switch(dashboard):
    _, state, *_ = dashboard
    assert post(dashboard, "/api/work", {"id": "../outside"}).status_code == 400
    assert state.current is None
