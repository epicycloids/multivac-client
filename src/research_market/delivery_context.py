"""Original gateway receipt evidence, carried by the project owner's scoped bridge."""

from pydantic import BaseModel, ConfigDict, Field

from .models import Offer
from .wire import fingerprint

CONTRACT = "multivac-retained-result-v1"


class RetainedResultContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contract: str
    command_id: str = Field(min_length=1, max_length=130)
    project_id: str = Field(min_length=1, max_length=40)
    contribution_id: str = Field(min_length=1, max_length=100)
    contributor_id: str = Field(min_length=1, max_length=100)
    offer: dict
    received_at: float = Field(ge=0, allow_inf_nan=False, strict=True)
    started_at: float = Field(ge=0, allow_inf_nan=False, strict=True)
    deadline: float = Field(ge=0, allow_inf_nan=False, strict=True)
    expires_at: float = Field(ge=0, allow_inf_nan=False, strict=True)
    task_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    lease_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    payload_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")


def gateway_context(record, command):
    """Use the original committed outbox time, never retry or donor timestamps."""
    arguments = command["arguments"]
    if (command["id"] != record["id"] + ":submit_result"
            or command["project_id"] != record["project_id"]
            or command["tool"] != "submit_result"
            or command["contribution_id"] != record["id"]
            or arguments["contribution_id"] != record["id"]
            or arguments["lease_token"] != record["lease_token"]
            or arguments["artifact"] != record["artifact"]
            or arguments["usage"] != record["usage"]
            or record["offer"]["contributor"] != record["contributor_id"]):
        raise ValueError("The retained gateway command does not match its original contribution.")
    return RetainedResultContext(
        contract=CONTRACT, command_id=command["id"], project_id=record["project_id"],
        contribution_id=record["id"], contributor_id=record["contributor_id"], offer=record["offer"],
        received_at=command["created_at"], started_at=record["started_at"],
        deadline=record["deadline"], expires_at=record["expires_at"],
        task_fingerprint=fingerprint(record["task"]),
        lease_fingerprint=fingerprint({"lease_token": record["lease_token"]}),
        payload_fingerprint=fingerprint({"artifact": arguments["artifact"], "usage": arguments["usage"]}),
    ).model_dump()


def validate_context(value, contribution_id, work, artifact, usage):
    """The local project bridge is trusted; donor-supplied timestamps are not evidence."""
    context = RetainedResultContext.model_validate(value)
    # Match the representation hashed by ProjectInbox.claim, including typed weights.
    approved_offer = Offer.model_validate(context.offer).model_dump()
    expected = {
        "contract": CONTRACT,
        "command_id": contribution_id + ":submit_result",
        "project_id": work["task"]["project_id"],
        "contribution_id": contribution_id,
        "task_fingerprint": fingerprint(work["task"]),
        "lease_fingerprint": fingerprint({"lease_token": work["lease_token"]}),
        "payload_fingerprint": fingerprint({"artifact": artifact, "usage": usage}),
        "expires_at": work["expires_at"],
    }
    if (any(getattr(context, key) != expected_value for key, expected_value in expected.items())
            or context.offer.get("contributor") != context.contributor_id
            or fingerprint(approved_offer) != work["offer_hash"]
            or work.get("contribution_id", work["task"].get("id")) != contribution_id):
        raise ValueError("Gateway receipt context conflicts with the original task, identity, lease or payload.")
    if not (context.started_at <= context.received_at <= context.deadline <= context.expires_at):
        raise ValueError("The original gateway result was not received within its execution deadline.")
    if context.deadline - context.started_at > work["task"]["budget_seconds"] + 1e-6:
        raise ValueError("Gateway receipt context exceeds the original execution allowance.")
    return context.model_dump()
