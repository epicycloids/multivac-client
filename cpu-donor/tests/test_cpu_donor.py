"""Standalone donor consent/setup/recovery checks; no numerical execution."""

import json
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from research_market import cpu_cli, cpu_entry, cpu_profile
from research_market.contracts import validate_task
from research_market.models import Offer
from research_market.remote_client import RemoteClient, private_json
from research_market.trefethen import TrefethenExecutionUnavailable


def test_cpu_offer_uses_existing_consent_and_checks_preparation_first(tmp_path, monkeypatch):
    events = []
    client = SimpleNamespace(
        grant=lambda offer, **kwargs: events.append((offer.model_dump(), kwargs)) or {"id": "fixture"}
    )
    monkeypatch.setattr(cpu_cli, "RemoteClient", lambda *a, **k: client)
    monkeypatch.setattr(cpu_cli, "require_environment", lambda: events.append("prepared"))
    result = CliRunner().invoke(cpu_cli.app, [
        "offer", "--project", "trefethen-arena", "--project", "trefethen-autonomous",
        "--policy", "weighted", "--seconds", "60", "--memory-mb", "1024", "--cores", "1",
        "--request-id", "cpu-fixture-01",
    ])
    assert result.exit_code == 0, result.output
    assert events[0] == "prepared"
    offer, arguments = events[1]
    assert offer["kind"] == "cpu" and not offer["allow_network"]
    assert offer["allowed_projects"] == list(cpu_profile.CPU_PROJECTS)
    assert offer["budget_seconds"] == 60 and offer["memory_mb"] == 1024
    assert offer["policy"] == "weighted" and arguments == {"request_id": "cpu-fixture-01"}
    assert not {"execution_profiles", "asset_labels", "agent_profile"}.intersection(offer)


@pytest.mark.parametrize("arguments", [
    ["offer", "--project", "unreviewed-project"],
    ["offer", "--kind", "agent"],
    ["owner-key"],
    ["mcp"],
])
def test_cpu_command_surface_cannot_admit_other_execution_or_owner_tools(monkeypatch, arguments):
    client = SimpleNamespace(grant=lambda *a, **k: pytest.fail("Unexpected grant"))
    monkeypatch.setattr(cpu_cli, "RemoteClient", lambda *a, **k: client)
    monkeypatch.setattr(cpu_cli, "require_environment", lambda: pytest.fail("Unexpected preparation"))
    assert CliRunner().invoke(cpu_cli.app, arguments).exit_code != 0


def test_unprepared_cpu_offer_never_reserves_work(monkeypatch):
    client = SimpleNamespace(grant=lambda *a, **k: pytest.fail("Unprepared offer contacted gateway"))
    monkeypatch.setattr(cpu_cli, "RemoteClient", lambda *a, **k: client)

    def missing():
        raise TrefethenExecutionUnavailable("Fixture missing environment")

    monkeypatch.setattr(cpu_cli, "require_environment", missing)
    result = CliRunner().invoke(cpu_cli.app, ["offer"])
    assert result.exit_code != 0 and "Fixture missing environment" in str(result.exception)


def test_preparation_uses_only_pinned_source_and_independent_frozen_environment(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setenv("UV_PYTHON", "donor-client-python")
    monkeypatch.setenv("VIRTUAL_ENV", "donor-client-venv")
    monkeypatch.setattr(cpu_profile, "prepare_data", lambda: None)
    monkeypatch.setattr(cpu_profile, "trefethen_path", lambda: tmp_path / "numerical")
    monkeypatch.setattr(cpu_profile, "ensure_source", lambda *args: calls.append(args))
    monkeypatch.setattr(cpu_profile.subprocess, "run", lambda command, **kw: calls.append((command, kw)))
    cpu_profile.prepare_cpu()
    assert calls[0] == (
        "https://github.com/epicycloids/trefethen-constant.git",
        tmp_path / "numerical",
        cpu_profile.TREFETHEN_REV,
    )
    command, options = calls[1]
    assert command == ["uv", "sync", "--frozen"]
    assert options["cwd"] == tmp_path / "numerical" and options["check"]
    assert not {"UV_PYTHON", "VIRTUAL_ENV"}.intersection(options["env"])
    assert len(calls) == 2


def test_existing_wrong_pin_is_not_reset_or_prepared(tmp_path, monkeypatch):
    monkeypatch.setattr(cpu_profile.subprocess, "check_output", lambda *a, **k: "other-revision\n")
    monkeypatch.setattr(cpu_profile.subprocess, "run", lambda *a, **k: pytest.fail("Existing source reset"))
    with pytest.raises(ValueError, match="another revision"):
        cpu_profile.ensure_source("unused", tmp_path, cpu_profile.TREFETHEN_REV)


def test_entry_uses_state_separate_from_portable_client(tmp_path, monkeypatch):
    import os

    monkeypatch.delenv("MARKET_DATA_DIR", raising=False)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setattr(cpu_entry.sys, "platform", "linux")
    observed = []
    monkeypatch.setattr(cpu_cli, "app", lambda: observed.append(os.environ["MARKET_DATA_DIR"]))
    cpu_entry.main()
    assert observed == [str(tmp_path / "multivac-cpu-donor")]


def test_cpu_validation_and_saved_result_reuse_do_not_require_private_catalog(tmp_path, monkeypatch):
    offer = Offer(project_id="trefethen-arena", allowed_projects=["trefethen-arena"])
    task = {
        **offer.model_dump(), "operation": "trefethen_recompute",
        "source_revision": cpu_profile.TREFETHEN_REV, "input": {"mode": "gram-batch", "start": 0},
    }
    assert validate_task(task, offer, offer.project_id) == task
    with pytest.raises(ValueError, match="pinned"):
        validate_task({**task, "source_revision": "different-pin"}, offer, offer.project_id)
    client = RemoteClient(directory=tmp_path)
    record = {"project_id": offer.project_id, "offer": offer.model_dump(), "task": task}
    monkeypatch.setattr(client, "contribution", lambda _: record)
    sent = []
    monkeypatch.setattr(client, "call", lambda method, path, body: sent.append(body) or {"state": "delivering"})
    work = client.directory / "work" / "saved-cpu"
    result = {"artifact": {"fixture": "saved result"}, "usage": {"wall_seconds": 1}}
    private_json(work / "output.json", result)
    private_json(work / "attempt.json", {"started": True})
    client.run_cpu("saved-cpu")
    client.collect_result("saved-cpu")
    assert sent == [result, result]
    assert json.loads((work / "attempt.json").read_text()) == {"started": True}
    client.http.close()
