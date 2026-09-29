"""The contributor rechecks project work against its own authority and limits."""

from .models import Offer


def validate_task_envelope(task: dict, offer: Offer, project_id: str) -> dict:
    """Check donor authority without prescribing a project's execution profile."""
    if not isinstance(task, dict):
        raise ValueError("Project task must be a structured object.")
    if project_id not in offer.allowed_projects:
        raise ValueError("Project is outside the contributor's permitted list.")
    if task.get("project_id") != project_id or task.get("kind") != offer.kind:
        raise ValueError("Project task does not match the approved project and resource type.")
    for field in ("budget_seconds", "memory_mb", "cpu_cores"):
        value = task.get(field)
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or value < 1
            or value > getattr(offer, field)
        ):
            raise ValueError(f"Project task exceeds the approved {field} limit.")
    if offer.kind == "agent" and not offer.allow_network:
        raise ValueError("Model-provider access is not authorized by this offer.")
    if task.get("seed") != offer.seed:
        raise ValueError("Project changed the contributor's experiment seed.")
    if task.get("resume_from") != offer.resume_from:
        raise ValueError("The project changed the requested research continuation.")
    return task


def validate_task(task: dict, offer: Offer, project_id: str) -> dict:
    validate_task_envelope(task, offer, project_id)
    permitted = {
        "cpu": {"trefethen_recompute"},
        "gpu": set(),
        "agent": {"research_session"},
        "data": {"local_analysis"},
        "human": {"human_review"},
    }
    if task.get("operation") not in permitted[offer.kind]:
        raise ValueError("No reviewed local execution profile supports this task.")
    if task["operation"] in {"trefethen_recompute", "research_session"}:
        from .catalog import TREFETHEN_REV

        if (
            project_id not in {"trefethen-arena", "trefethen-autonomous"}
            or task.get("source_revision") != TREFETHEN_REV
        ):
            raise ValueError("This research profile needs the pinned Trefethen project source.")
        if task["operation"] == "trefethen_recompute":
            spec = task.get("input", {})
            if (
                spec.get("mode") != "gram-batch"
                or type(spec.get("start")) is not int
                or spec["start"] not in range(0, 641, 32)
            ):
                raise ValueError("The CPU profile must name a valid installed certificate batch.")
    return task
