"""Validate project tasks against the contributor's approved offer."""

from .models import AgentPolicy, Offer


def _validate_execution_access(profiles, assets, offer: Offer) -> None:
    """Local registration does not authorize use in every contribution."""
    if any(
        not isinstance(profile, str) or profile not in offer.execution_profiles
        for profile in profiles
    ):
        raise ValueError("Project task requests an execution profile outside the approved offer.")
    if not isinstance(assets, list) or any(not isinstance(asset, str) for asset in assets):
        raise ValueError("Project task must declare required assets as a list of labels.")
    if not set(assets).issubset(offer.asset_labels):
        raise ValueError("Project task requests local assets outside the approved offer.")


def validate_task_envelope(task: dict, offer: Offer, project_id: str) -> dict:
    """Check project, resource, and continuation limits in a task envelope."""
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
    if task.get("agent_profile") is not None:
        if offer.agent_profile is None or task["agent_profile"] != offer.agent_profile.model_dump():
            raise ValueError("The project changed the contributor's declared AI configuration.")
    if offer.kind == "agent" and task.get("agent_policy"):
        AgentPolicy.model_validate(task["agent_policy"]).require(offer.agent_profile)
    _validate_execution_access(
        [task["execution_profile"]] if "execution_profile" in task else [],
        task.get("required_assets", []),
        offer,
    )
    if task.get("operation") == "workbench_compute":
        compute = task.get("compute")
        if not isinstance(compute, dict):
            raise ValueError("Project compute task must declare its execution requirements.")
        # Existing compute envelopes predate the optional top-level declarations.
        # Keep their wire default, while binding it to this contribution's consent.
        _validate_execution_access(
            [compute.get("profile", "python-sandbox-v1")], compute.get("assets", []), offer
        )
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
        from .cpu_profile import CPU_PROJECTS, TREFETHEN_REV

        if (
            project_id not in CPU_PROJECTS
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
