"""Project-owned task, contribution, and receipt lifecycle tests."""

import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from research_market.models import Offer
from research_market.project_starter import ProjectInbox, scaffold


def retained_fixture(tmp_path, monkeypatch):
    from research_market import project_starter
    from research_market.delivery_context import gateway_context

    clock = [1000.0]
    monkeypatch.setattr(project_starter, "time", SimpleNamespace(time=lambda: clock[0]))
    directory = tmp_path / "retained-project"
    scaffold(directory, "retained-project", "Synthetic delayed delivery", "Exercise retained report delivery without executing research.")
    project = ProjectInbox(directory)
    offer = Offer(project_id="retained-project", allowed_projects=["retained-project"],
                  kind="agent", allow_network=True, budget_seconds=90, contributor="fixture-donor").model_dump()
    lease = project.claim(offer, "saved-report")
    payload = {"artifact": {"report": "Synthetic retained report for protocol testing only."},
               "usage": {"wall_seconds": 2, "model_calls": 0}}
    record = {"id": "saved-report", "project_id": "retained-project", "contributor_id": "fixture-donor",
              "offer": offer, "task": lease["task"], "lease_token": lease["lease_token"],
              "started_at": 1001.0, "deadline": 1091.0, "expires_at": lease["expires_at"], **payload}
    command = {"id": "saved-report:submit_result", "tool": "submit_result",
               "project_id": "retained-project", "contribution_id": "saved-report",
               "created_at": 1003.0, "updated_at": 9000.0,
               "arguments": {"contribution_id": "saved-report", "lease_token": lease["lease_token"], **payload}}
    context = gateway_context(record, command)
    clock[0] = lease["expires_at"] + 1
    return project, lease, payload, context, clock


def test_first_expired_delivery_uses_original_gateway_context_without_reviving_execution(tmp_path, monkeypatch):
    project, lease, payload, context, clock = retained_fixture(tmp_path, monkeypatch)
    assert context["received_at"] == 1003 and context["received_at"] < context["deadline"]
    # Default integer weights revalidate as floats in the project-owned offer hash.
    assert all(isinstance(weight, int) for weight in context["offer"]["weights"].values())
    restarted = ProjectInbox(project.directory)
    receipt = restarted.finish("saved-report", lease["lease_token"], **payload, delivery_context=context)
    assert receipt["accepted"] and receipt["review_required"] and not receipt["new_research_claim"]
    assert receipt["artifact"] == payload["artifact"] and receipt["usage"] == payload["usage"]
    assert receipt["delivery"]["reservation_expired"] is True
    assert receipt["delivery"]["execution_deadline"] == context["deadline"]
    with restarted.db() as db:
        work = json.loads(db.execute("SELECT body FROM work WHERE id='saved-report'").fetchone()[0])
    assert work["task"] == lease["task"] and work["expires_at"] == lease["expires_at"]
    assert work["lease_token"] == lease["lease_token"] and work["state"] == "received"
    clock[0] += 10000
    assert restarted.finish("saved-report", lease["lease_token"], **payload) == receipt
    assert restarted.read()["findings"] == [receipt]
    with pytest.raises(ValueError, match="different result"):
        restarted.finish("saved-report", lease["lease_token"], payload["artifact"], {"wall_seconds": 0})


@pytest.mark.parametrize("change", ["missing", "late", "identity", "offer", "task", "reassigned", "released", "cancelled", "payload", "lease", "disabled"])
def test_expired_first_delivery_requires_exact_timely_unreleased_project_authority(tmp_path, monkeypatch, change):
    project, lease, payload, context, _ = retained_fixture(tmp_path, monkeypatch)
    token = lease["lease_token"]
    if change == "missing":
        context = None
    elif change == "late":
        context["received_at"] = context["deadline"] + 1
    elif change == "identity":
        context["contributor_id"] = "different-donor"
    elif change == "offer":
        context["offer"] = {**context["offer"], "budget_seconds": 900}
    elif change in {"task", "reassigned", "cancelled"}:
        with project.db() as db:
            work = json.loads(db.execute("SELECT body FROM work WHERE id='saved-report'").fetchone()[0])
            if change == "cancelled":
                work["state"] = "cancelled"
            elif change == "reassigned":
                work["task"]["id"] = "replacement"
            else:
                work["task"]["instruction"] = "Changed assignment"
            db.execute("UPDATE work SET body=? WHERE id='saved-report'", (json.dumps(work),))
    elif change == "released":
        project.finish("saved-report", token)
    elif change == "payload":
        payload = {**payload, "usage": {"wall_seconds": 0}}
    elif change == "lease":
        token = "wrong-lease"
    elif change == "disabled":
        config = project.config()
        config["metadata"].pop("result_delivery_contract")
        project.config_path.write_text(json.dumps(config))
    with pytest.raises(ValueError):
        project.finish("saved-report", token, **payload, delivery_context=context)
    assert project.read()["findings"] == []


def test_project_owns_capacity_idempotency_and_evidence(tmp_path):
    directory = tmp_path / "project"
    scaffold(
        directory,
        "external-test",
        "Isolated test",
        "Exercise the contribution protocol with synthetic test data.",
    )
    project = ProjectInbox(directory)
    offer = Offer(
        project_id="external-test",
        allowed_projects=["external-test"],
        kind="agent",
        allow_network=True,
    ).model_dump()
    with ThreadPoolExecutor(max_workers=4) as pool:
        claims = list(pool.map(lambda _: project.claim(offer, "same-id"), range(4)))
    assert all(c == claims[0] for c in claims)
    project.coordinate(
        "Changed future research brief, preserving already-issued context.",
        0,
        "An interpretation of the test evidence.",
    )
    assert project.claim(offer, "same-id") == claims[0]
    with pytest.raises(ValueError, match="participant limit"):
        project.claim(offer, "second-id")
    with pytest.raises(ValueError, match="changed offer"):
        project.claim({**offer, "budget_seconds": 42}, "same-id")
    with pytest.raises(ValueError, match="Unknown project lease"):
        project.finish("same-id", "wrong", {"report": "Invalid lease fixture"}, {})
    artifact = {"report": "Synthetic lifecycle test artifact."}
    receipt = project.finish("same-id", claims[0]["lease_token"], artifact, {"wall_seconds": 0})
    assert receipt["accepted"] and receipt["review_required"] and not receipt["new_research_claim"]
    assert (
        ProjectInbox(directory).finish(
            "same-id", claims[0]["lease_token"], artifact, {"wall_seconds": 0}
        )
        == receipt
    )
    assert project.read()["findings"] == [receipt]
    with pytest.raises(ValueError, match="different result"):
        project.finish("same-id", claims[0]["lease_token"], {"report": "Changed content"}, {})
    project.coordinate(
        "A future investigation can use the interpreted results.",
        1,
        "Retain the first observation.",
    )
    lease = project.claim(offer, "second-id")
    assert lease["task"]["research_context"]["interpretation"] == "Retain the first observation."
    assert project.finish("second-id", lease["lease_token"]) == {"released": True}
    assert project.finish("second-id", lease["lease_token"]) == {"released": True}
    assert project.read()["active"] == 0
