from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Kind = Literal["cpu", "gpu", "agent", "data", "human"]
Policy = Literal["manual", "weighted", "performance", "managed"]


class Offer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: str = "trefethen-arena"
    kind: Kind = "cpu"
    budget_seconds: int = Field(default=30, ge=1, le=900)
    cpu_cores: int = Field(default=1, ge=1, le=4)
    memory_mb: int = Field(default=1024, ge=128, le=8192)
    policy: Policy = "manual"
    contributor: str = Field(default="Local contributor", min_length=1, max_length=80)
    seed: int = Field(default=42, ge=0, le=2**31 - 1)
    interests: list[str] = Field(default_factory=list, max_length=12)
    allowed_projects: list[str] = Field(
        default_factory=lambda: ["trefethen-arena", "trefethen-autonomous"], max_length=30
    )
    weights: dict[str, float] = Field(
        default_factory=lambda: {"trefethen-arena": 1, "trefethen-autonomous": 1}
    )
    allow_network: bool = False
    max_harness_invocations: Literal[1] = 1
    resume_from: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_-]{1,100}$")

    @field_validator("weights")
    @classmethod
    def valid_weights(cls, values: dict[str, float]) -> dict[str, float]:
        import math

        if len(values) > 30 or any(
            not math.isfinite(v) or v <= 0 or v > 100 for v in values.values()
        ):
            raise ValueError("Project weights must be finite and between 0 and 100.")
        return values


class HumanReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    verdict: Literal["supported", "needs_work", "inconclusive"]
    rationale: str = Field(min_length=30, max_length=4000)
    limitations: str = Field(min_length=15, max_length=2000)


class Aggregate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1.0"] = "1.0"
    count: int = Field(ge=3, le=1000000)
    mean_improvement: float
    mean_seconds: float = Field(ge=0, le=1000000)
    data_origin: Literal["local_records", "demo_records"]

    @field_validator("mean_improvement", "mean_seconds")
    @classmethod
    def finite(cls, value: float) -> float:
        import math

        if not math.isfinite(value):
            raise ValueError("Aggregate fields must be finite.")
        return value


class ProjectMetadata(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,39}$")
    title: str = Field(min_length=1, max_length=100)
    subtitle: str = Field(default="Independent research project", max_length=200)
    description: str = Field(max_length=3000)
    tags: list[str] = Field(max_length=12)
    kinds: list[Kind] = Field(min_length=1, max_length=5)
    color: str = Field(default="#3858e9", pattern=r"^#[0-9a-fA-F]{6}$")
    objective: str = Field(max_length=200)
    orchestration: str = Field(max_length=500)
    integration_label: str = Field(max_length=200)
    acceptance_scope: str = Field(max_length=1000)
    expected_outcome: str = Field(default="Project-validated contribution", max_length=500)
    source_revision: str = Field(default="unversioned", max_length=100)
    source_url: str | None = None
    protocols: list[Literal["MCP", "A2A"]] = Field(default_factory=lambda: ["MCP"])
    status: Literal["active", "placeholder"] = "active"
    availability_note: str = Field(default="", max_length=1000)
    orchestration_family: str = Field(default="Independent project", max_length=100)
    objective_label: str = Field(default="", max_length=200)
    pilot: bool = False
    visibility: Literal["public", "unlisted"] = "public"
    acceptance_metric: str | None = Field(default=None, max_length=200)

    @field_validator("source_url")
    @classmethod
    def web_source(cls, value):
        from urllib.parse import urlparse

        if value is not None and urlparse(value).scheme not in {"http", "https"}:
            raise ValueError("Source links must use HTTP or HTTPS.")
        return value
