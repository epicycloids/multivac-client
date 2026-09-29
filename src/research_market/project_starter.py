"""A starter inbox for a research project's tasks and contributed findings."""

from __future__ import annotations

import json
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from .contracts import validate_task_envelope
from .models import Offer, ProjectMetadata
from .wire import fingerprint


class ProjectInbox:
    def __init__(self, directory: Path):
        self.directory = directory.resolve()
        self.config_path = self.directory / "project.json"
        self.config()
        with self.db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS work(id TEXT PRIMARY KEY, body TEXT NOT NULL)")
            db.execute(
                "CREATE TABLE IF NOT EXISTS settings(id TEXT PRIMARY KEY, body TEXT NOT NULL)"
            )

    def config(self):
        if not self.config_path.is_file():
            raise ValueError("No project.json in this directory. Create a project with init-project first.")
        value = json.loads(self.config_path.read_text())
        ProjectMetadata.model_validate(value["metadata"])
        if not isinstance(value.get("brief"), str) or len(value["brief"]) < 20:
            raise ValueError(
                "Describe your research objective and the contributions you welcome in brief."
            )
        return value

    @contextmanager
    def db(self):
        connection = sqlite3.connect(self.directory / "project.sqlite3", timeout=20)
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def settings(self, db):
        row = db.execute("SELECT body FROM settings WHERE id='research'").fetchone()
        config = self.config()
        return (
            json.loads(row[0])
            if row
            else {"brief": config["brief"], "capacity": 3, "interpretation": ""}
        )

    def describe(self):
        return ProjectMetadata.model_validate(self.config()["metadata"]).model_dump()

    def active(self, db):
        return sum(
            1
            for (body,) in db.execute("SELECT body FROM work")
            if (w := json.loads(body))["state"] == "claimed" and w["expires_at"] > time.time()
        )

    def opportunities(self):
        with self.db() as db:
            ready = self.active(db) < self.settings(db)["capacity"]
        return [
            {
                "kind": kind,
                "ready": ready,
                "min_seconds": 30,
                "memory_mb": 128,
                "requires_network": kind == "agent",
                "objective": self.describe()["objective"],
            }
            for kind in self.describe()["kinds"]
        ]

    def read(self):
        with self.db() as db:
            records = [json.loads(row[0]) for row in db.execute("SELECT body FROM work")]
            return {
                "metadata": self.describe(),
                "research": self.settings(db),
                "active": self.active(db),
                "findings": [w["receipt"] for w in records if w.get("receipt")],
            }

    def coordinate(self, brief: str, capacity: int, interpretation: str):
        if not 20 <= len(brief) <= 16000 or not 0 <= capacity <= 100 or len(interpretation) > 16000:
            raise ValueError(
                "Provide a research brief (20–16000 characters), capacity 0–100, and bounded interpretation."
            )
        with self.db() as db:
            settings = {
                "brief": brief,
                "capacity": capacity,
                "interpretation": interpretation,
                "updated_at": time.time(),
            }
            db.execute(
                "INSERT OR REPLACE INTO settings VALUES ('research', ?)", (json.dumps(settings),)
            )
        return settings

    def claim(self, offer: dict, contribution_id: str):
        approved = Offer.model_validate(offer)
        metadata = self.describe()
        if approved.kind not in metadata["kinds"]:
            raise ValueError("This project does not request that resource type.")
        signature = fingerprint(approved.model_dump())
        with self.db() as db:
            previous = db.execute("SELECT body FROM work WHERE id=?", (contribution_id,)).fetchone()
            if previous:
                work = json.loads(previous[0])
                if work["offer_hash"] != signature:
                    raise ValueError("A changed offer needs a new contribution ID.")
                return {k: work[k] for k in ("task", "lease_token", "expires_at")}
            settings = self.settings(db)
            if self.active(db) >= settings["capacity"]:
                raise ValueError("The project has paused or reached its participant limit.")
            task = {
                "id": contribution_id,
                "project_id": metadata["id"],
                **{
                    k: getattr(approved, k)
                    for k in (
                        "kind",
                        "budget_seconds",
                        "cpu_cores",
                        "memory_mb",
                        "seed",
                        "resume_from",
                    )
                },
                "objective": metadata["objective"],
                "instruction": settings["brief"],
                "research_context": {"interpretation": settings["interpretation"]},
                "disclosure": "Return only findings you are permitted to share. Your harness enforces your resource and access limits.",
                "operation": "project_investigation",
            }
            validate_task_envelope(task, approved, metadata["id"])
            work = {
                "task": task,
                "lease_token": secrets.token_urlsafe(32),
                "expires_at": time.time() + approved.budget_seconds + 1800,
                "state": "claimed",
                "offer_hash": signature,
            }
            db.execute("INSERT INTO work VALUES (?,?)", (contribution_id, json.dumps(work)))
            return {k: work[k] for k in ("task", "lease_token", "expires_at")}

    def finish(self, contribution_id, lease_token, artifact=None, usage=None):
        with self.db() as db:
            row = db.execute("SELECT body FROM work WHERE id=?", (contribution_id,)).fetchone()
            if not row or not secrets.compare_digest(
                json.loads(row[0])["lease_token"], lease_token
            ):
                raise ValueError("Unknown project lease.")
            work = json.loads(row[0])
            if artifact is None:
                if work["state"] == "claimed":
                    work["state"] = "released"
                result = {"released": work["state"] == "released"}
            else:
                signature = fingerprint({"artifact": artifact, "usage": usage})
                if work.get("receipt"):
                    if signature != work["result_hash"]:
                        raise ValueError("A different result is already retained.")
                    return work["receipt"]
                if work["state"] != "claimed" or work["expires_at"] <= time.time():
                    raise ValueError("This lease is no longer active.")
                report = artifact.get("report", artifact.get("rationale", ""))
                if not isinstance(report, str) or len(report.strip()) < 30:
                    raise ValueError("Return a substantive report with evidence and limitations.")
                result = {
                    "project_id": self.describe()["id"],
                    "accepted": True,
                    "review_required": True,
                    "new_research_claim": False,
                    "accomplishment": "Findings received for review by the project.",
                    "artifact": artifact,
                    "usage": usage,
                    "artifact_hash": fingerprint(artifact),
                    "contribution_id": contribution_id,
                }
                work.update(state="received", receipt=result, result_hash=signature)
            db.execute(
                "UPDATE work SET body=? WHERE id=?",
                (json.dumps(work, allow_nan=False), contribution_id),
            )
            return result


def scaffold(directory: Path, project: str, title: str, objective: str):
    metadata = ProjectMetadata(
        id=project,
        title=title,
        description=objective,
        tags=["research"],
        kinds=["agent", "human"],
        objective=project,
        orchestration="Research inbox with a replaceable project coordinator.",
        integration_label="Project starter over MCP",
        visibility="unlisted",
        acceptance_scope="Reports are received for review. Scientific claims require separate verification.",
    )
    if len(objective) < 20:
        raise ValueError("Provide the actual research question in at least 20 characters.")
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "project.json").write_text(
        json.dumps({"metadata": metadata.model_dump(), "brief": objective}, indent=2)
    )
    (directory / ".gitignore").write_text("*.sqlite3*\n.local-token\n")
    (directory / "README.md").write_text("""# Research project starter

Edit project.json with your research question, approach, and acceptance rules.
The starter is unlisted until you choose visibility=public and the pilot owner approves it.
Starting this endpoint makes tasks available; it does not run research or call a model.

Run `multivac-client serve-project .` and check `multivac-client check-project http://127.0.0.1:9000/mcp/`.
Connect a project identity, get approval for this project ID, then run
`multivac-client --connection my-project host PROJECT_ID --endpoint http://127.0.0.1:9000/mcp/`.

Connect your assistant through `multivac-client project-mcp /absolute/path/to/this/directory`
to read and interpret findings, update the brief, and set capacity. A capacity of zero pauses
new claims. These administration tools are available to the project owner; the platform
cannot call them. Brief changes affect future tasks only.

The starter accepts reports for review. You are responsible for interpreting their evidence
and verifying scientific claims. Customize ProjectInbox or replace it with your MCP service
to change orchestration, task generation, data access, execution, or acceptance rules.
Back up the local SQLite database and keep it private.
""")
    return {"directory": str(directory.resolve()), "project_id": project, "visibility": "unlisted"}


def server(directory: Path, *, coordinator=False):
    from mcp.server import MCPServer

    project = ProjectInbox(directory)
    mcp = MCPServer(project.describe()["title"])
    if coordinator:

        @mcp.tool()
        def read_research() -> dict:
            """Read the project's objective, active capacity, accumulated findings and interpretation."""
            return project.read()

        @mcp.tool()
        def coordinate_research(brief: str, capacity: int, interpretation: str) -> dict:
            """Update the research brief, interpretation, and capacity for future claims.

            Use this tool within the project owner's research scope. It leaves platform allocation,
            existing tasks, and returned findings unchanged. It does not start model or contributor work.
            """
            return project.coordinate(brief, capacity, interpretation)
    else:

        @mcp.tool()
        def describe_project() -> dict:
            return project.describe()

        @mcp.tool()
        def list_opportunities() -> list[dict]:
            return project.opportunities()

        @mcp.tool()
        def claim_work(offer: Offer, contribution_id: str) -> dict:
            return project.claim(offer.model_dump(), contribution_id)

        @mcp.tool()
        def submit_result(
            contribution_id: str, lease_token: str, artifact: dict, usage: dict
        ) -> dict:
            return project.finish(contribution_id, lease_token, artifact, usage)

        @mcp.tool()
        def release_work(contribution_id: str, lease_token: str) -> dict:
            return project.finish(contribution_id, lease_token)

    return mcp


async def check_endpoint(endpoint: str, token: str | None = None, exercise=False):
    import uuid
    from urllib.parse import urlparse

    from .mcp_client import call_endpoint

    parsed = urlparse(endpoint)
    if (
        parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.scheme not in {"http", "https"}
        or parsed.username
        or parsed.password
    ):
        raise ValueError(
            "Check an explicit local MCP endpoint; no credentials are forwarded remotely."
        )
    headers = {"Authorization": "Bearer " + token} if token else {}

    async def call(name, arguments=None):
        return await call_endpoint(endpoint, name, arguments, headers)

    metadata = ProjectMetadata.model_validate(await call("describe_project"))
    opportunities = await call("list_opportunities")
    if not isinstance(opportunities, list):
        raise ValueError("list_opportunities must return a list.")
    for opportunity in opportunities:
        if (
            opportunity["kind"] not in metadata.kinds
            or type(opportunity["ready"]) is not bool
            or not 1 <= opportunity["min_seconds"] <= 900
            or not 1 <= opportunity["memory_mb"] <= 8192
            or type(opportunity["requires_network"]) is not bool
            or not isinstance(opportunity["objective"], str)
        ):
            raise ValueError("An opportunity does not satisfy the contribution contract.")
    checks = ["project metadata", "opportunity metadata"]
    if exercise:
        opportunity = next(
            (o for o in opportunities if o["ready"] and o["kind"] in {"agent", "human"}), None
        )
        if not opportunity:
            raise ValueError(
                "No ready human/agent reservation for a non-executing lifecycle check."
            )
        offer = Offer(
            project_id=metadata.id,
            allowed_projects=[metadata.id],
            kind=opportunity["kind"],
            budget_seconds=opportunity["min_seconds"],
            memory_mb=max(128, opportunity["memory_mb"]),
            allow_network=opportunity["requires_network"],
            contributor="Explicit contract check; no research execution",
        )
        arguments = {
            "offer": offer.model_dump(),
            "contribution_id": "contract-check-" + uuid.uuid4().hex,
        }
        lease = await call("claim_work", arguments)
        try:
            validate_task_envelope(lease["task"], offer, metadata.id)
            if lease["expires_at"] <= time.time() or not lease["lease_token"]:
                raise ValueError("A claim needs a live lease and token.")
            if await call("claim_work", arguments) != lease:
                raise ValueError("Repeated claim changed the task or lease.")
            checks.append("idempotent bounded claim")
        finally:
            release = {
                "contribution_id": arguments["contribution_id"],
                "lease_token": lease["lease_token"],
            }
            first = await call("release_work", release)
            if await call("release_work", release) != first:
                raise ValueError("Repeated release changed its response.")
        checks.append("idempotent release; no execution or submitted finding")
    return {"project": metadata.model_dump(), "checks": checks, "research_executed": False}
