"""Portable offer consent and read-only support checks; no model or execution calls."""

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from research_market import remote_cli
from research_market.contracts import validate_task_envelope
from research_market.models import Offer
from research_market.remote_client import (
    OfferRequestConflict,
    PlatformResponseError,
    RemoteClient,
    private_json,
)


def test_cli_offer_round_trips_only_the_named_consent_and_agent_profile(tmp_path, monkeypatch):
    offered = []
    client = SimpleNamespace(grant=lambda offer, **kwargs: offered.append(offer.model_dump()) or {"state": "claiming"})
    monkeypatch.setattr(remote_cli, "RemoteClient", lambda *args, **kwargs: client)
    profile = tmp_path / "agent.json"
    profile.write_text(json.dumps({"model": "fixture-model", "harness": "fixture-harness"}))
    result = CliRunner().invoke(remote_cli.app, [
        "offer", "--project", "consent-fixture", "--kind", "agent", "--allow-network",
        "--agent-profile", str(profile),
        "--execution-profile", "analysis-v1", "--execution-profile", "review-v1",
        "--asset-label", "approved-map", "--asset-label", "approved-summary",
    ])
    assert result.exit_code == 0, result.output
    assert offered[0]["execution_profiles"] == ["analysis-v1", "review-v1"]
    assert offered[0]["asset_labels"] == ["approved-map", "approved-summary"]
    assert offered[0]["agent_profile"]["model"] == "fixture-model"
    assert str(tmp_path) not in json.dumps(offered)
    default = CliRunner().invoke(remote_cli.app, ["offer", "--project", "consent-fixture"])
    assert default.exit_code == 0, default.output
    assert not {"execution_profiles", "asset_labels", "agent_profile"}.intersection(offered[1])


def test_portable_capability_check_and_cli_never_connect_or_reserve(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "research_market.trefethen", None)
    client = RemoteClient(directory=tmp_path)
    monkeypatch.setattr(client, "call", lambda *args, **kwargs: pytest.fail("Capability inspection contacted the platform"))
    monkeypatch.setattr(remote_cli, "RemoteClient", lambda *args, **kwargs: client)
    result = CliRunner().invoke(remote_cli.app, ["capabilities"])
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["cpu"]["runner_installed"] is False
    assert report["cpu"]["environment_ready"] is False
    assert report["assistant"]["readiness"] == "not_probed"
    assert report["gpu"]["executor_ready"] is False
    assert report["consent"]["installed_access_is_authorized"] is False
    assert not report["work_started"] and not client.directory.exists()
    client.http.close()


def test_named_consent_reaches_wire_but_does_not_advertise_a_gpu_executor(tmp_path, monkeypatch):
    client = RemoteClient(directory=tmp_path)
    requests = []
    monkeypatch.setattr(client, "call", lambda method, path, body: requests.append(body) or {"state": "claiming"})
    offer = Offer(kind="agent", allow_network=True, execution_profiles=["analysis-v1"], asset_labels=["approved-map"])
    client.grant(offer, agent=True, request_id="consent-wire")
    assert requests[0]["offer"] == offer.model_dump()
    assert requests[0]["capabilities"] == {"agent": True, "gpu": False}
    assert json.loads(client.offer_request_path("consent-wire").read_text()) == requests[0]
    client.http.close()


def test_task_cannot_expand_the_cli_offers_named_access():
    offer = Offer(project_id="consent-fixture", allowed_projects=["consent-fixture"],
                  execution_profiles=["analysis-v1"], asset_labels=["approved-map"])
    task = {"project_id": "consent-fixture", "kind": "cpu", "operation": "workbench_compute",
            **{key: getattr(offer, key) for key in ("budget_seconds", "memory_mb", "cpu_cores", "seed", "resume_from")},
            "compute": {"profile": "analysis-v1", "assets": ["approved-map"]}}
    assert validate_task_envelope(task, offer, "consent-fixture") == task
    with pytest.raises(ValueError, match="local assets"):
        validate_task_envelope({**task, "compute": {"profile": "analysis-v1", "assets": ["private-map"]}}, offer, "consent-fixture")


def test_failed_offer_retry_keeps_original_agreement_and_exact_saved_body(tmp_path, monkeypatch):
    client = RemoteClient(directory=tmp_path)
    client.save({"identity": {"id": "fixture-identity"}})
    calls, unavailable = [], [True]

    def receive(method, path, body):
        calls.append(json.loads(json.dumps(body)))
        if unavailable[0]:
            raise PlatformResponseError(503, "Synthetic unavailable gateway")
        return {"id": "original-grant", "state": "ready"}

    monkeypatch.setattr(client, "call", receive)
    original = Offer(kind="agent", allow_network=True, budget_seconds=90, memory_mb=512)
    with pytest.raises(PlatformResponseError):
        client.grant(original, agent=True, request_id="same-request")
    path = client.offer_request_path("same-request")
    saved, metadata = path.read_bytes(), path.stat()
    for offer, agent in [(original.model_copy(update={"memory_mb": 1024}), True),
                         (original.model_copy(update={"budget_seconds": 91}), True), (original, False)]:
        with pytest.raises(OfferRequestConflict, match="new request ID"):
            client.grant(offer, agent=agent, request_id="same-request")
        assert path.read_bytes() == saved
        assert path.stat().st_ino == metadata.st_ino and path.stat().st_mtime_ns == metadata.st_mtime_ns
    assert len(calls) == 1
    unavailable[0] = False
    # Revalidation converts default integer weights to floats, as the gateway does.
    equivalent = Offer.model_validate(original.model_dump())
    assert client.grant(equivalent, agent=1, request_id="same-request")["id"] == "original-grant"
    assert json.dumps(calls[0], sort_keys=True) == json.dumps(calls[1], sort_keys=True)
    assert path.read_bytes() == saved and path.stat().st_mtime_ns == metadata.st_mtime_ns
    client.http.close()


def test_same_request_label_is_separate_for_distinct_approved_identities(tmp_path, monkeypatch):
    clients = [RemoteClient(connection=name, directory=tmp_path) for name in ("first", "second")]
    calls = []
    for index, client in enumerate(clients):
        client.save({"identity": {"id": f"fixture-{index}"}})
        monkeypatch.setattr(client, "call", lambda method, path, body: calls.append(body) or {"state": "ready"})
        client.grant(Offer(budget_seconds=90 + index), request_id="same-label")
    assert clients[0].offer_request_path("same-label") != clients[1].offer_request_path("same-label")
    assert [json.loads(client.offer_request_path("same-label").read_text())["offer"]["budget_seconds"]
            for client in clients] == [90, 91]
    assert len(calls) == 2
    for client in clients:
        client.http.close()


def test_linked_connections_cannot_race_different_offers_into_one_request(tmp_path, monkeypatch):
    clients = [RemoteClient(connection=name, directory=tmp_path) for name in ("linked-a", "linked-b")]
    calls = []
    for client in clients:
        client.save({"identity": {"id": "same-approved-identity"}})
        monkeypatch.setattr(client, "call", lambda method, path, body: calls.append(body) or {"state": "ready"})
    assert clients[0].offer_request_path("shared") == clients[1].offer_request_path("shared")

    def attempt(index):
        try:
            return clients[index].grant(Offer(budget_seconds=90 + index), request_id="shared")
        except OfferRequestConflict:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, [0, 1]))
    assert sum(value is not None for value in results) == 1 and len(calls) == 1
    assert json.loads(clients[0].offer_request_path("shared").read_text()) == calls[0]
    for client in clients:
        client.http.close()


def test_pre_upgrade_request_retries_without_attributing_or_changing_legacy_file(tmp_path, monkeypatch):
    client = RemoteClient(directory=tmp_path)
    client.save({"identity": {"id": "fixture-identity"}})
    offer = Offer(budget_seconds=90)
    legacy = client.directory / "requests" / "outstanding.json"
    body = {"request_id": "outstanding", "offer": offer.model_dump(), "capabilities": {"agent": False, "gpu": False}}
    private_json(legacy, body)
    preserved = legacy.read_bytes()
    calls = []
    monkeypatch.setattr(client, "call", lambda method, path, request: calls.append(request) or {"id": "existing-grant"})
    equivalent = Offer.model_validate(offer.model_dump())
    assert client.grant(equivalent, request_id="outstanding")["id"] == "existing-grant"
    assert client.grant(offer, request_id="outstanding")["id"] == "existing-grant"
    assert legacy.read_bytes() == preserved
    assert client.offer_request_path("outstanding") != legacy
    assert calls[0] == calls[1]
    assert json.loads(client.offer_request_path("outstanding").read_text()) == calls[0]
    client.http.close()


def test_ambiguous_legacy_conflict_does_not_guess_owner_or_mutate_remote_state(tmp_path, monkeypatch):
    client = RemoteClient(connection="another-connection", directory=tmp_path)
    client.save({"identity": {"id": "different-approved-identity"}})
    legacy = client.directory / "requests" / "ambiguous.json"
    private_json(legacy, {"request_id": "ambiguous", "offer": Offer(budget_seconds=90).model_dump(),
                          "capabilities": {"agent": False, "gpu": False}})
    preserved = legacy.read_bytes()
    monkeypatch.setattr(client, "call", lambda *args, **kwargs: pytest.fail("Ambiguous legacy request reached the gateway"))
    with pytest.raises(OfferRequestConflict, match="unknown connection ownership"):
        client.grant(Offer(budget_seconds=91), request_id="ambiguous")
    assert legacy.read_bytes() == preserved and not client.offer_request_path("ambiguous").exists()
    client.http.close()


def test_unreadable_saved_request_is_retained_and_blocks_transmission(tmp_path, monkeypatch):
    client = RemoteClient(directory=tmp_path)
    path = client.offer_request_path("unreadable")
    path.parent.mkdir(parents=True)
    path.write_text("{invalid fixture")
    monkeypatch.setattr(client, "call", lambda *args, **kwargs: pytest.fail("Unreadable agreement was transmitted"))
    with pytest.raises(OfferRequestConflict, match="cannot be read"):
        client.grant(Offer(), request_id="unreadable")
    assert path.read_text() == "{invalid fixture"
    client.http.close()
