"""Synthetic local round trip. No model, account, hosted service, or research claim."""

import json
import tempfile
from pathlib import Path

from research_market.models import Offer
from research_market.project_starter import ProjectInbox, scaffold

with tempfile.TemporaryDirectory(prefix="multivac-protocol-") as temporary:
    directory = Path(temporary) / "project"
    scaffold(
        directory,
        "protocol-example",
        "Synthetic protocol example",
        "Exercise a contribution cycle only; no scientific investigation is requested.",
    )
    project = ProjectInbox(directory)
    offer = Offer(
        project_id="protocol-example",
        allowed_projects=["protocol-example"],
        kind="agent",
        allow_network=True,
    ).model_dump()
    claim = project.claim(offer, "synthetic-example")
    receipt = project.finish(
        "synthetic-example",
        claim["lease_token"],
        {
            "report": "Synthetic test payload. This example performed no research and used no AI model.",
            "test_only": True,
            "research_claim": False,
        },
        {"wall_seconds": 0, "model_calls": 0},
    )
    assert receipt["accepted"] and not receipt["new_research_claim"]
    assert project.read()["active"] == 0
    print(json.dumps({"synthetic": True, "model_calls": 0, "project_receipt": receipt}, indent=2))
