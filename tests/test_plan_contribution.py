"""Contribution lifecycle tests using synthetic provider and project fixtures."""

import asyncio
import json
import time

import pytest

from research_market import plan_contribution
from research_market.chatgpt_plan import PlanError
from research_market.models import Offer
from research_market.plan_contribution import collect_plan_result, run_plan_report
from research_market.project_starter import ProjectInbox, scaffold


class SyntheticPlan:
    def __init__(self):
        self.requests = []
        self.error = None
        self.wait = False
        self.stopped = False

    def models(self):
        return [{"slug": "fixture-astra", "display_name": "Fixture model"}]

    async def respond(self, **kwargs):
        self.requests.append(kwargs)
        try:
            if self.wait:
                await asyncio.sleep(30)
            if self.error:
                raise self.error
            return {
                "report": "Synthetic integration fixture.",
                "model": "fixture-astra",
                "response_id": "fixture-response",
                "provider_usage": {"input_tokens": 12, "output_tokens": 10},
                "wall_seconds": 0.01,
                "harness": "Synthetic fixture",
            }
        finally:
            self.stopped = True


@pytest.fixture
def local_cycle(tmp_path):
    directory = tmp_path / "fixture-project"
    scaffold(
        directory,
        "protocol-fixture",
        "Synthetic test",
        "Exercise the contribution protocol with synthetic test data.",
    )
    inbox = ProjectInbox(directory)
    offer = Offer(
        project_id="protocol-fixture",
        allowed_projects=["protocol-fixture"],
        kind="agent",
        allow_network=True,
        budget_seconds=90,
    ).model_dump()
    work = inbox.claim(offer, "fixture-contribution")

    class Remote:
        directory = tmp_path / "client"
        record = {
            "id": "fixture-contribution",
            "project_id": "protocol-fixture",
            "kind": "agent",
            "state": "ready",
            "offer": offer,
            "task": work["task"],
        }
        failed_delivery = False
        queued = False
        submissions = []

        def contribution(self, identifier, **kwargs):
            return self.record

        def call(self, method, path, body=None, **kwargs):
            if path.endswith("/start"):
                self.record = {**self.record, "state": "running", "deadline": time.time() + 90}
            elif path.endswith("/cancel"):
                self.record = {**self.record, "state": "cancelled"}
            elif path.endswith("/result"):
                if self.failed_delivery:
                    raise ValueError("Synthetic delivery failure")
                self.submissions.append(body)
                if self.queued:
                    self.record = {**self.record, "state": "delivering"}
                else:
                    receipt = inbox.finish(
                        "fixture-contribution", work["lease_token"], body["artifact"], body["usage"]
                    )
                    self.record = {**self.record, "state": "accepted", "receipt": receipt}
            else:
                raise AssertionError(path)
            return self.record

    return Remote(), SyntheticPlan(), inbox


async def test_single_attempt_preserves_report_usage_and_exact_project_receipt(local_cycle):
    remote, plan, inbox = local_cycle
    result = await run_plan_report(remote, plan, "fixture-contribution", model="fixture-astra")
    assert result["state"] == "accepted"
    receipt = result["receipt"]
    assert receipt["accepted"] and receipt["review_required"] and not receipt["new_research_claim"]
    assert len(inbox.read()["findings"]) == 1 and inbox.read()["active"] == 0
    saved = remote.directory / "plan-contributions/fixture-contribution"
    assert json.loads((saved / "receipt.json").read_text()) == receipt
    output = json.loads((saved / "result.json").read_text())
    assert output["usage"]["provider_usage"]["input_tokens"] == 12
    assert output["usage"]["credit_cost"] is None and output["usage"]["plan_percentage"] is None
    assert "lease_token" not in json.dumps(plan.requests[0]["messages"])
    assert output["artifact"]["limitations"].endswith("no local experiments executed.")
    with pytest.raises(ValueError, match="already has a plan-execution attempt"):
        await run_plan_report(remote, plan, "fixture-contribution", model="fixture-astra")
    assert len(plan.requests) == 1
    assert (saved / "result.json").stat().st_mode & 0o777 == 0o600


async def test_delivery_retry_does_not_repeat_inference(local_cycle):
    remote, plan, inbox = local_cycle
    remote.failed_delivery = True
    with pytest.raises(ValueError, match="delivery failure"):
        await run_plan_report(remote, plan, "fixture-contribution", model="fixture-astra")
    attempt = remote.directory / "plan-contributions/fixture-contribution/attempt.json"
    assert json.loads(attempt.read_text())["state"] == "completed"
    remote.failed_delivery = False
    recovered = await collect_plan_result(remote, "fixture-contribution", wait_seconds=0)
    assert recovered["receipt"]["accepted"] and len(plan.requests) == 1
    await collect_plan_result(remote, "fixture-contribution", wait_seconds=0)
    assert len(inbox.read()["findings"]) == 1


async def test_delivery_acknowledgement_is_not_a_project_receipt(local_cycle):
    remote, plan, _ = local_cycle
    remote.failed_delivery = True
    with pytest.raises(ValueError, match="delivery failure"):
        await run_plan_report(remote, plan, "fixture-contribution", model="fixture-astra")
    remote.failed_delivery = False
    remote.queued = True
    result = await collect_plan_result(remote, "fixture-contribution", wait_seconds=0)
    assert result["state"] == "delivering" and result["receipt"] is None
    assert not (remote.directory / "plan-contributions/fixture-contribution/receipt.json").exists()


@pytest.mark.parametrize("change", ["project", "budget", "network", "resume", "model"])
async def test_task_constraints_precede_any_model_request(local_cycle, change):
    remote, plan, _ = local_cycle
    model = "fixture-astra"
    if change == "project":
        remote.record["task"]["project_id"] = "other-project"
    elif change == "budget":
        remote.record["task"]["budget_seconds"] = 900
    elif change == "network":
        remote.record["offer"]["allow_network"] = False
    elif change == "resume":
        remote.record["offer"]["resume_from"] = "some-native-session"
        remote.record["task"]["resume_from"] = "some-native-session"
    else:
        model = "not-available"
    with pytest.raises(ValueError):
        await run_plan_report(remote, plan, "fixture-contribution", model=model)
    assert not plan.requests and remote.record["state"] == "ready"


async def test_model_limit_failure_is_retained_without_submission_or_retry(local_cycle):
    remote, plan, inbox = local_cycle
    plan.error = PlanError("subscription_sharing_usage_limit_exceeded")
    with pytest.raises(PlanError):
        await run_plan_report(remote, plan, "fixture-contribution", model="fixture-astra")
    attempt = remote.directory / "plan-contributions/fixture-contribution/attempt.json"
    saved = json.loads(attempt.read_text())
    assert saved["state"] == "interrupted" and saved["usage_incomplete"]
    assert not remote.submissions and inbox.read()["findings"] == []
    assert remote.record["state"] == "cancelled"
    with pytest.raises(ValueError, match="already has"):
        await run_plan_report(remote, plan, "fixture-contribution", model="fixture-astra")
    assert len(plan.requests) == 1


async def test_platform_cancellation_stops_a_silent_model_request(local_cycle, monkeypatch):
    remote, plan, _ = local_cycle
    plan.wait = True
    watch = plan_contribution.watch_contribution

    async def accelerated(remote, identifier):
        while not plan.requests:
            await asyncio.sleep(0.01)
        remote.record = {**remote.record, "state": "cancelled"}
        await watch(remote, identifier, interval=0.01)

    monkeypatch.setattr(plan_contribution, "watch_contribution", accelerated)
    with pytest.raises(PlanError, match="contribution_closed"):
        await run_plan_report(remote, plan, "fixture-contribution", model="fixture-astra")
    assert plan.stopped and not remote.submissions


@pytest.mark.parametrize("identifier", ["../elsewhere", "/tmp/elsewhere", "bad?value"])
async def test_result_paths_cannot_escape_connection(local_cycle, identifier):
    remote, plan, _ = local_cycle
    with pytest.raises(ValueError, match="identifier"):
        await run_plan_report(remote, plan, identifier, model="fixture-astra")
    with pytest.raises(ValueError, match="identifier"):
        await collect_plan_result(remote, identifier)
