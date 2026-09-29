"""Project-owned lifecycle checks. Fixtures never populate hosted research activity."""

from concurrent.futures import ThreadPoolExecutor

import pytest

from research_market.models import Offer
from research_market.project_starter import ProjectInbox, scaffold


def test_project_owns_capacity_idempotency_and_evidence(tmp_path):
    directory = tmp_path / "project"
    scaffold(
        directory,
        "external-test",
        "Isolated test",
        "Inspect a test protocol only. No scientific finding is requested.",
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
    artifact = {
        "report": "This is an isolated lifecycle test artifact, not a research contribution."
    }
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
