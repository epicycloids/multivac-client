"""Isolated OAuth/Responses fixtures; no real account access or inference."""

import asyncio
import base64
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest
from click import unstyle
from cryptography.hazmat.primitives.asymmetric import rsa
from typer.testing import CliRunner

from research_market.chatgpt_plan import (
    AUTH,
    RESOURCE,
    SCOPES,
    TOKEN,
    PlanClient,
    PlanError,
)
from research_market.plan_cli import app, login_local
from research_market.remote_client import private_json


@pytest.fixture
def provider(tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    jwk.update(kid="fixture", use="sig", alg="RS256")
    state = {"calls": [], "nonce": "", "claims": {}, "scope": SCOPES}

    def token():
        now = int(time.time())
        return jwt.encode(
            {
                "iss": AUTH,
                "aud": "oaiapp_fixture",
                "sub": "fixture-user",
                "iat": now,
                "exp": now + 3600,
                "nonce": state["nonce"],
                "email": "fixture@example.invalid",
                **state["claims"],
            },
            key,
            algorithm="RS256",
            headers={"kid": "fixture"},
        )

    def receive(request):
        state["calls"].append(request)
        if request.url.path.endswith("jwks.json"):
            return httpx.Response(200, json={"keys": [jwk]})
        if request.url.path.endswith("openid-configuration"):
            return httpx.Response(200, json={"revocation_endpoint": AUTH + "/revoke"})
        if request.url.path == "/revoke":
            return httpx.Response(state.get("revoke_status", 200))
        if request.url.path == "/v1/models":
            return httpx.Response(
                200,
                json={
                    "models": [
                        {
                            "slug": "fixture-astra",
                            "display_name": "Fixture Astra",
                            "visibility": "list",
                        },
                        {"slug": "hidden", "visibility": "hidden"},
                    ]
                },
            )
        assert str(request.url) == TOKEN
        if state.get("network_error"):
            raise httpx.ConnectError("SECRET_SENTINEL", request=request)
        if state.get("error"):
            return httpx.Response(
                400, json={"error": state["error"], "error_description": "SECRET_SENTINEL"}
            )
        form = parse_qs(request.content.decode())
        refresh = form["grant_type"] == ["refresh_token"]
        assert form["client_id"] == ["oaiapp_fixture"]
        assert form["resource"] == [RESOURCE]
        assert "client_secret" not in form
        if refresh:
            assert "scope" not in form
        else:
            assert form["redirect_uri"] == [state["redirect_uri"]]
            assert form["code_verifier"] == [state["verifier"]]
        return httpx.Response(
            200,
            json={
                "token_type": "Bearer",
                "expires_in": 3600,
                "scope": state["scope"],
                "access_token": "fixture-access-renewed" if refresh else "fixture-access",
                "refresh_token": "fixture-refresh-renewed" if refresh else "fixture-refresh",
                "id_token": token(),
            },
        )

    http = httpx.Client(transport=httpx.MockTransport(receive))
    plan = PlanClient(tmp_path / "chatgpt", http=http)
    state.update(plan=plan, receive=receive)
    yield state
    http.close()


def pending(provider):
    auth = provider["plan"].begin("http://127.0.0.1:41999/auth/callback")
    provider.update(nonce=auth.nonce, verifier=auth.verifier, redirect_uri=auth.redirect_uri)
    return auth


def finish(provider, auth=None):
    auth = auth or pending(provider)
    return provider["plan"].finish(
        auth, {"state": auth.state, "code": "fixture-code", "client_id": "oaiapp_fixture"}
    )


def test_first_sign_in_pkce_identity_scope_and_secret_free_status(provider):
    auth = pending(provider)
    params = parse_qs(urlparse(auth.url).query)
    assert params["client_id"] == ["dynamic_agent_client"]
    assert params["agent_name_hint"] == ["Multivac"]
    assert params["ext_agent_host_id"][0].startswith("urn:uuid:")
    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(auth.verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    assert params["code_challenge"] == [expected]
    assert params["code_challenge_method"] == ["S256"]
    status = finish(provider, auth)
    assert status["connected"] and status["plan_use_authorized"]
    assert status["research_started_by_this_command"] is False
    assert "fixture-access" not in json.dumps(status)
    plan = provider["plan"]
    assert plan.path.stat().st_mode & 0o777 == 0o600
    assert plan.path.parent.stat().st_mode & 0o777 == 0o700
    new = plan.begin("http://127.0.0.1:41000/auth/callback", enable_plan=True)
    repeated = parse_qs(urlparse(new.url).query)
    assert repeated["ext_agent_host_id"] == params["ext_agent_host_id"]
    assert repeated["client_id"] == ["oaiapp_fixture"]
    assert repeated["prompt"] == ["consent"]
    assert "agent_name_hint" not in repeated
    assert new.state != auth.state and new.nonce != auth.nonce
    assert "fixture-access" not in repr(new) and new.url not in repr(new)
    assert plan.models() == [{"slug": "fixture-astra", "display_name": "Fixture Astra"}]


@pytest.mark.parametrize(
    "uri",
    [
        "http://localhost:41999/auth/callback",
        "https://127.0.0.1:41999/auth/callback",
        "http://127.0.0.1:41999/wrong",
        "http://127.0.0.1:41999/auth/callback?code=secret",
        "http://evil.example/auth/callback",
    ],
)
def test_only_loopback_callback_is_accepted(provider, uri):
    with pytest.raises(ValueError, match="127.0.0.1"):
        provider["plan"].begin(uri)
    assert not provider["calls"]


def test_bad_state_cannot_consume_sign_in_but_callback_cannot_be_replayed(provider):
    auth = pending(provider)
    with pytest.raises(PlanError, match="invalid_oauth_state"):
        provider["plan"].finish(auth, {"state": "wrong"})
    assert not provider["calls"] and not auth.consumed
    finish(provider, auth)
    calls = len(provider["calls"])
    with pytest.raises(PlanError, match="authorization_expired"):
        finish(provider, auth)
    assert len(provider["calls"]) == calls


@pytest.mark.parametrize(
    "claims",
    [
        {"nonce": "wrong"},
        {"aud": "other-client"},
        {"iss": "https://attacker.invalid"},
        {"exp": 1},
        {"iat": 4000000000},
        {"sub": ""},
        {"azp": "other-client"},
        {"aud": ["oaiapp_fixture", "other-client"]},
    ],
)
def test_identity_validation_rejects_invalid_claims_without_storing(provider, claims):
    provider["claims"] = claims
    with pytest.raises(PlanError, match="invalid_identity_token"):
        finish(provider)
    assert not provider["plan"].path.exists()


def test_account_binding_and_identity_only_authorization(provider):
    provider["scope"] = "openid profile email"
    assert finish(provider)["plan_use_authorized"] is False
    with pytest.raises(PlanError, match="plan_access_disabled"):
        provider["plan"].access_token()
    original = provider["plan"].path.read_bytes()
    provider["claims"] = {"sub": "different-user-same-email"}
    with pytest.raises(PlanError, match="account_identity_changed"):
        finish(provider)
    assert provider["plan"].path.read_bytes() == original


def expire(provider):
    plan = provider["plan"]
    private_json(plan.path, {**plan.saved(), "expires_at": 0})


def test_refresh_rotation_is_serialized_and_does_not_switch_accounts(provider):
    finish(provider)
    expire(provider)
    plan = provider["plan"]
    second = PlanClient(plan.directory, http=plan.http)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda client: client.access_token(), [plan, second]))
    assert results == ["fixture-access-renewed"] * 2
    assert plan.saved()["refresh_token"] == "fixture-refresh-renewed"
    refreshes = [r for r in provider["calls"] if b"grant_type=refresh_token" in r.content]
    assert len(refreshes) == 1
    assert PlanClient(plan.directory, "other", http=plan.http).status()["connected"] is False


@pytest.mark.parametrize("mode", ["invalid_grant", "refresh_token_reused", "network"])
def test_refresh_failures_preserve_registration_and_hide_provider_details(provider, mode):
    finish(provider)
    expire(provider)
    provider["network_error"] = mode == "network"
    provider["error"] = None if mode == "network" else mode
    with pytest.raises(PlanError) as caught:
        provider["plan"].access_token()
    assert "SECRET_SENTINEL" not in str(caught.value)
    saved = provider["plan"].saved()
    assert saved["client_id"] == "oaiapp_fixture"
    assert ("refresh_token" in saved) == (mode == "network")


@pytest.mark.parametrize("status", [200, 503])
def test_disconnect_distinguishes_local_clearance_from_remote_revocation(provider, status):
    finish(provider)
    provider["revoke_status"] = status
    outcome = provider["plan"].disconnect()
    assert outcome["remote_revocation_confirmed"] is (status == 200)
    assert "refresh_token" not in provider["plan"].saved()
    assert provider["plan"].saved()["client_id"] == "oaiapp_fixture"
    revoke = provider["calls"][-1]
    assert parse_qs(revoke.content.decode())["token_type_hint"] == ["refresh_token"]


def completed_event():
    return {
        "type": "response.completed",
        "response": {
            "id": "fixture-response",
            "model": "fixture-astra",
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "Synthetic protocol report. This is not scientific research.",
                        }
                    ],
                }
            ],
            "usage": {"input_tokens": 12, "output_tokens": 11},
        },
    }


def sse(*events):
    return "".join("data: " + json.dumps(e) + "\n\n" for e in events)


async def test_response_uses_correct_api_and_returns_only_completed_evidence(provider):
    finish(provider)

    def respond(request):
        assert str(request.url) == RESOURCE + "/responses"
        assert request.headers["authorization"] == "Bearer fixture-access"
        body = json.loads(request.content)
        assert body == {
            "model": "fixture-astra",
            "instructions": "fixture instructions",
            "input": [{"role": "user", "content": "synthetic task"}],
            "store": False,
            "stream": True,
            "tools": [{"type": "web_search"}],
        }
        return httpx.Response(
            200,
            text=sse(
                {"type": "response.output_text.delta", "delta": "Discard this partial text"},
                completed_event(),
            ),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        result = await provider["plan"].respond(
            model="fixture-astra",
            instructions="fixture instructions",
            messages=[{"role": "user", "content": "synthetic task"}],
            seconds=5,
            web_search=True,
            http=http,
        )
    assert "partial" not in result["report"]
    assert result["provider_usage"] == {"input_tokens": 12, "output_tokens": 11}
    assert result["billing_source"] == "chatgpt_plan"


@pytest.mark.parametrize(
    "events,code",
    [
        (
            [{"type": "response.output_text.delta", "delta": "Unfinished report"}],
            "stream_interrupted",
        ),
        (
            [
                {
                    "type": "response.failed",
                    "response": {
                        "error": {
                            "code": "subscription_sharing_usage_limit_exceeded",
                            "message": "SECRET_SENTINEL",
                        }
                    },
                }
            ],
            "subscription_sharing_usage_limit_exceeded",
        ),
        ([{"type": "response.incomplete", "response": {}}], "response_incomplete"),
        ([[]], "invalid_stream_event"),
        (
            [{"type": "response.completed", "response": {"status": "completed", "output": None}}],
            "invalid_completed_response",
        ),
    ],
)
async def test_interrupted_or_failed_stream_is_never_success(provider, events, code):
    finish(provider)
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, text=sse(*events), headers={"x-request-id": "fixture-request"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        with pytest.raises(PlanError, match=code) as caught:
            await provider["plan"].respond(
                model="fixture-astra", instructions="fixture", messages=[], seconds=3, http=http
            )
    assert len(requests) == 1
    assert "SECRET_SENTINEL" not in str(caught.value)


async def test_deadline_closes_an_inactive_stream(provider):
    finish(provider)

    class SilentStream(httpx.AsyncByteStream):
        closed = False

        async def __aiter__(self):
            await asyncio.sleep(30)
            yield b""

        async def aclose(self):
            self.closed = True

    stream = SilentStream()
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=stream))
    ) as http:
        with pytest.raises(PlanError, match="time_allowance_reached"):
            await provider["plan"].respond(
                model="fixture-astra", instructions="fixture", messages=[], seconds=1, http=http
            )
    assert stream.closed


def test_local_sign_in_listener_checks_host_state_and_redacts_logs(provider, capsys):
    addresses = []

    def ready(origin):
        addresses.append(origin)

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(login_local, provider["plan"], open_browser=False, ready=ready)
        limit = time.monotonic() + 3
        while not addresses and time.monotonic() < limit:
            time.sleep(0.01)
        assert addresses
        with httpx.Client(base_url=addresses[0], trust_env=False) as local:
            assert local.get("/", headers={"Host": "evil.invalid"}).status_code == 400
            landing = local.get("/")
            assert "Continue with ChatGPT" in landing.text
            assert landing.headers["referrer-policy"] == "no-referrer"
            authorize = local.get("/authorize")
            params = parse_qs(urlparse(authorize.headers["location"]).query)
            provider.update(nonce=params["nonce"][0], redirect_uri=params["redirect_uri"][0])
            # The verifier is intentionally not sent to the browser. Capture it
            # only inside this synthetic provider's token exchange assertion.
            original = provider["receive"]

            def exchange(request):
                if str(request.url) == TOKEN:
                    provider["verifier"] = parse_qs(request.content.decode())["code_verifier"][0]
                return original(request)

            provider["plan"].http.close()
            provider["plan"].http = httpx.Client(transport=httpx.MockTransport(exchange))
            assert local.get("/auth/callback?state=wrong").status_code == 400
            assert local.get("/auth/callback?state=a&state=b").status_code == 400
            response = local.get(
                "/auth/callback",
                params={
                    "state": params["state"][0],
                    "client_id": "oaiapp_fixture",
                    "code": "SECRET_CALLBACK_CODE",
                },
            )
            assert response.status_code == 200
            assert "No research has started" in response.text
        assert future.result(timeout=3)["plan_use_authorized"]
    provider["plan"].http.close()
    output = capsys.readouterr()
    assert "SECRET_CALLBACK_CODE" not in output.out + output.err


def test_portable_cli_can_inspect_without_account_or_inference(tmp_path):
    result = CliRunner().invoke(app, ["--data-dir", str(tmp_path), "status"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["connected"] is False
    result = CliRunner().invoke(app, ["run-report", "--help"])
    assert result.exit_code == 0, result.output
    assert "--model" in unstyle(result.output)
