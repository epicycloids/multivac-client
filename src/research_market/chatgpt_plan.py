"""Local ChatGPT sign-in and plan access through OAuth and Responses.

This installation obtains its own OAuth credentials and keeps them out of contributions.
"""

from __future__ import annotations

import asyncio
import base64
import fcntl
import hashlib
import json
import os
import re
import secrets
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlencode, urlparse

import httpx
import jwt

from .remote_client import private_json

AUTH = "https://auth.openai.com"
RESOURCE = "https://api.openai.com/v1"
AUTHORIZE = AUTH + "/api/accounts/authorize"
TOKEN = AUTH + "/api/accounts/oauth/token"
USAGE_URL = "https://chatgpt.com/settings/usage"
PLAN_SCOPE = "chatgpt.tokens.use.direct"
SCOPES = "openid profile email offline_access resource.invoke " + PLAN_SCOPE
TOKEN_FIELDS = {"access_token", "refresh_token", "id_token", "expires_at", "scopes"}
TERMINAL_REFRESH_ERRORS = {
    "invalid_grant",
    "invalid_refresh_token",
    "token_expired",
    "refresh_token_expired",
    "refresh_token_invalidated",
    "refresh_token_reused",
}


class PlanError(ValueError):
    """A diagnostic that omits OAuth URLs, tokens, and response bodies."""

    def __init__(self, code, *, status=None, request_id=None, shape=None):
        self.code = code if re.fullmatch(r"[a-zA-Z0-9_.-]{1,120}", str(code)) else "request_failed"
        self.status = status
        self.request_id = request_id
        self.shape = shape
        guidance = {
            "subscription_sharing_usage_limit_exceeded": "Usage limit reached. Review your app limit in ChatGPT Usage settings.",
            "subscription_sharing_user_not_eligible": "This account or workspace is not eligible for ChatGPT plan access.",
            "subscription_sharing_usage_unavailable": "OpenAI cannot check usage right now. No request was retried.",
            "plan_access_disabled": "Sign-in does not authorize ChatGPT plan use. Enable it explicitly before research.",
            "sign_in_required": "Connect this ChatGPT account before research.",
            "stream_interrupted": "The response did not complete. Any consumed usage is unknown; no research result was submitted.",
            "time_allowance_reached": "The local time allowance ended. The provider may have consumed usage; no completed result was reported.",
        }.get(
            self.code, "ChatGPT plan request stopped. No other account or billing method was used."
        )
        super().__init__(f"{guidance} ({self.code})")

    def diagnostic(self):
        return {
            "code": self.code,
            "http_status": self.status,
            "request_id": self.request_id,
            "body_shape": self.shape,
            "manage_usage": USAGE_URL,
        }


def provider_error(value, status=None, request_id=None):
    nested = value.get("error") if isinstance(value, dict) else None
    code = nested.get("code") if isinstance(nested, dict) else nested
    # OAuth errors use a string; Responses errors normally use a nested object.
    return PlanError(
        code or "request_failed",
        status=status,
        request_id=request_id,
        shape=sorted(value) if isinstance(value, dict) else type(value).__name__,
    )


@dataclass
class Authorization:
    url: str = field(repr=False)
    state: str = field(repr=False)
    nonce: str = field(repr=False)
    verifier: str = field(repr=False)
    redirect_uri: str
    client_id: str
    subject: str | None
    expires_at: float
    consumed: bool = False


class PlanClient:
    def __init__(self, directory: Path, account="default", *, http=None):
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,60}", account):
            raise ValueError("Use a simple, distinct label for each ChatGPT account/workspace.")
        self.directory = Path(directory)
        self.account = account
        self.path = self.directory / "accounts" / (account + ".json")
        self.http = http or httpx.Client(timeout=20, follow_redirects=False)

    @contextmanager
    def locked(self):
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = self.directory / ".lock"
        fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        with os.fdopen(fd, "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def saved(self):
        return json.loads(self.path.read_text()) if self.path.exists() else {}

    def status(self):
        value = self.saved()
        return {
            "account": self.account,
            "email": value.get("email"),
            "client_id": value.get("client_id"),
            "connected": bool(value.get("access_token")),
            "plan_use_authorized": PLAN_SCOPE in value.get("scopes", []),
            "access_expires_at": value.get("expires_at"),
            "manage_usage": USAGE_URL,
            "research_started_by_this_command": False,
        }

    def begin(self, redirect_uri, *, enable_plan=False):
        parsed = urlparse(redirect_uri)
        if (
            parsed.scheme != "http"
            or parsed.hostname != "127.0.0.1"
            or not parsed.port
            or parsed.path != "/auth/callback"
            or parsed.query
            or parsed.fragment
            or parsed.username
            or parsed.password
        ):
            raise ValueError("Use a listening 127.0.0.1 HTTP callback at /auth/callback.")
        with self.locked():
            host_path = self.directory / "host.json"
            if not host_path.exists():
                private_json(host_path, {"ext_agent_host_id": "urn:uuid:" + str(uuid.uuid4())})
            host_id = json.loads(host_path.read_text())["ext_agent_host_id"]
            saved = self.saved()
        verifier, state, nonce = (secrets.token_urlsafe(32) for _ in range(3))
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        client_id = saved.get("client_id", "dynamic_agent_client")
        params = {
            "client_id": client_id,
            "ext_agent_host_id": host_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "scope": SCOPES,
            "resource": RESOURCE,
            "state": state,
            "nonce": nonce,
            "code_challenge_method": "S256",
            "code_challenge": challenge,
        }
        if client_id == "dynamic_agent_client":
            params["agent_name_hint"] = "Multivac"
        elif saved.get("id_token"):
            params["id_token_hint"] = saved["id_token"]
        if enable_plan:
            params["prompt"] = "consent"
        return Authorization(
            AUTHORIZE + "?" + urlencode(params),
            state,
            nonce,
            verifier,
            redirect_uri,
            client_id,
            saved.get("subject"),
            time.time() + 600,
        )

    def _json(self, method, url, **kwargs):
        try:
            response = self.http.request(method, url, **kwargs)
        except httpx.HTTPError:
            raise PlanError("network_unavailable") from None
        try:
            body = response.json()
        except ValueError:
            raise PlanError("invalid_provider_response", status=response.status_code) from None
        if not response.is_success:
            raise provider_error(body, response.status_code, response.headers.get("x-request-id"))
        if not isinstance(body, dict):
            raise PlanError("invalid_provider_response")
        return body

    def _identity(self, token, client_id, nonce=None):
        keys = self._json("GET", AUTH + "/.well-known/jwks.json")
        try:
            header = jwt.get_unverified_header(token)
            key = next(
                k for k in jwt.PyJWKSet.from_dict(keys).keys if k.key_id == header.get("kid")
            )
            claims = jwt.decode(
                token,
                key.key,
                algorithms=["RS256"],
                audience=client_id,
                issuer=AUTH,
                leeway=30,
                options={"require": ["iss", "aud", "sub", "exp", "iat"]},
            )
            if not isinstance(claims["sub"], str) or not claims["sub"]:
                raise ValueError("Missing identity")
            if claims.get("azp", client_id) != client_id or (
                isinstance(claims["aud"], list)
                and len(claims["aud"]) > 1
                and claims.get("azp") != client_id
            ):
                raise ValueError("Wrong authorized party")
            if nonce is not None and not secrets.compare_digest(
                str(claims.get("nonce", "")), nonce
            ):
                raise ValueError("Nonce mismatch")
        except (ValueError, KeyError, StopIteration, jwt.PyJWTError):
            raise PlanError("invalid_identity_token") from None
        return claims

    @staticmethod
    def _tokens(value, previous=None):
        previous = previous or {}
        expiry = value.get("expires_in")
        if (
            str(value.get("token_type", "")).lower() != "bearer"
            or not isinstance(value.get("access_token"), str)
            or not value["access_token"]
            or not isinstance(expiry, (int, float))
            or isinstance(expiry, bool)
            or not 0 < expiry <= 86400
        ):
            raise PlanError("invalid_token_response")
        scope = value.get("scope")
        if scope is not None and not isinstance(scope, str):
            raise PlanError("invalid_token_response")
        result = {
            "access_token": value["access_token"],
            "expires_at": time.time() + expiry,
            "scopes": scope.split() if scope is not None else previous.get("scopes", []),
        }
        for name in ("id_token", "refresh_token"):
            token = value.get(name, previous.get(name))
            if token is not None:
                if not isinstance(token, str) or not token:
                    raise PlanError("invalid_token_response")
                result[name] = token
        return result

    def finish(self, pending: Authorization, params):
        if pending.consumed or time.time() > pending.expires_at:
            raise PlanError("authorization_expired")
        if not secrets.compare_digest(params.get("state", ""), pending.state):
            raise PlanError("invalid_oauth_state")
        pending.consumed = True
        if params.get("error"):
            raise PlanError("authorization_declined")
        new = pending.client_id == "dynamic_agent_client"
        client_id = params.get("client_id", pending.client_id)
        if (
            not re.fullmatch(r"[a-zA-Z0-9_-]{1,200}", client_id)
            or client_id == "dynamic_agent_client"
            or (not new and client_id != pending.client_id)
            or not params.get("code")
        ):
            raise PlanError("invalid_oauth_callback")
        with self.locked():
            current = self.saved()
            if current.get("client_id") not in {None, pending.client_id}:
                raise PlanError("account_changed_during_sign_in")
            tokens = self._json(
                "POST",
                TOKEN,
                data={
                    "grant_type": "authorization_code",
                    "client_id": client_id,
                    "code": params["code"],
                    "code_verifier": pending.verifier,
                    "redirect_uri": pending.redirect_uri,
                    "resource": RESOURCE,
                },
            )
            identity = self._identity(tokens.get("id_token", ""), client_id, pending.nonce)
            if pending.subject and identity["sub"] != pending.subject:
                raise PlanError("account_identity_changed")
            private_json(
                self.path,
                {
                    "issuer": AUTH,
                    "subject": identity["sub"],
                    "email": identity.get("email"),
                    "client_id": client_id,
                    **self._tokens(tokens),
                },
            )
        return self.status()

    def access_token(self):
        with self.locked():
            saved = self.saved()
            if not saved.get("access_token"):
                raise PlanError("sign_in_required")
            if PLAN_SCOPE not in saved.get("scopes", []):
                raise PlanError("plan_access_disabled")
            if saved.get("expires_at", 0) > time.time() + 60:
                return saved["access_token"]
            if not saved.get("refresh_token"):
                raise PlanError("sign_in_required")
            try:
                replacement = self._json(
                    "POST",
                    TOKEN,
                    data={
                        "grant_type": "refresh_token",
                        "client_id": saved["client_id"],
                        "refresh_token": saved["refresh_token"],
                        "resource": RESOURCE,
                    },
                )
            except PlanError as error:
                if error.code in TERMINAL_REFRESH_ERRORS:
                    private_json(
                        self.path, {k: v for k, v in saved.items() if k not in TOKEN_FIELDS}
                    )
                raise
            if not replacement.get("refresh_token"):
                raise PlanError("invalid_token_response")
            if replacement.get("id_token"):
                identity = self._identity(replacement["id_token"], saved["client_id"])
                if identity["sub"] != saved["subject"]:
                    raise PlanError("account_identity_changed")
            renewed = {**saved, **self._tokens(replacement, saved)}
            private_json(self.path, renewed)
            if PLAN_SCOPE not in renewed["scopes"]:
                raise PlanError("plan_access_disabled")
            return renewed["access_token"]

    def models(self):
        result = self._json(
            "GET",
            RESOURCE + "/models",
            headers={
                "Authorization": "Bearer " + self.access_token(),
            },
        )
        if not isinstance(result.get("models"), list):
            raise PlanError("invalid_model_catalog")
        return [
            {"slug": m["slug"], "display_name": m.get("display_name", m["slug"])}
            for m in result["models"]
            if isinstance(m, dict)
            and m.get("visibility") == "list"
            and isinstance(m.get("slug"), str)
        ]

    def disconnect(self):
        confirmed = False
        with self.locked():
            saved = self.saved()
            if saved.get("refresh_token"):
                try:
                    config = self._json("GET", AUTH + "/.well-known/openid-configuration")
                    endpoint = urlparse(config.get("revocation_endpoint", ""))
                    if (
                        endpoint.scheme != "https"
                        or endpoint.netloc != "auth.openai.com"
                        or endpoint.query
                        or endpoint.fragment
                    ):
                        raise PlanError("invalid_revocation_endpoint")
                    response = self.http.post(
                        endpoint.geturl(),
                        data={
                            "token": saved["refresh_token"],
                            "token_type_hint": "refresh_token",
                            "client_id": saved["client_id"],
                        },
                    )
                    confirmed = response.status_code == 200
                except (PlanError, httpx.HTTPError):
                    pass
            if saved:
                private_json(self.path, {k: v for k, v in saved.items() if k not in TOKEN_FIELDS})
        return {
            "local_tokens_cleared": True,
            "remote_revocation_confirmed": confirmed,
            "manage_usage": USAGE_URL,
            "note": "Disconnect the app in ChatGPT Usage settings if remote revocation was not confirmed.",
        }

    async def respond(self, *, model, instructions, messages, seconds, web_search=False, http=None):
        """Send one authorized inference request, with retries and billing fallback disabled."""
        if not model or not 1 <= seconds <= 900:
            raise ValueError("Choose a model and a request allowance between 1 and 900 seconds.")
        body = {
            "model": model,
            "instructions": instructions,
            "input": messages,
            "store": False,
            "stream": True,
        }
        if web_search:
            body["tools"] = [{"type": "web_search"}]
        client = http or httpx.AsyncClient(follow_redirects=False, timeout=None)
        started = time.monotonic()
        try:
            async with asyncio.timeout(seconds):
                access = await asyncio.to_thread(self.access_token)
                async with client.stream(
                    "POST",
                    RESOURCE + "/responses",
                    json=body,
                    headers={"Authorization": "Bearer " + access},
                ) as response:
                    if not response.is_success:
                        await response.aread()
                        try:
                            value = response.json()
                        except ValueError:
                            value = None
                        raise provider_error(
                            value, response.status_code, response.headers.get("x-request-id")
                        )
                    data = []
                    async for line in response.aiter_lines():
                        if line.startswith("data:"):
                            data.append(line[5:].lstrip())
                            if sum(map(len, data)) > 4_000_000:
                                raise PlanError("response_too_large")
                        elif line == "" and data:
                            try:
                                event = json.loads("\n".join(data))
                            except ValueError:
                                raise PlanError("invalid_stream_event") from None
                            data = []
                            if not isinstance(event, dict):
                                raise PlanError("invalid_stream_event")
                            kind = event.get("type")
                            result = event.get("response", {})
                            if not isinstance(result, dict):
                                raise PlanError("invalid_stream_event")
                            if kind in {"response.failed", "error"}:
                                raise provider_error(
                                    result if kind == "response.failed" else event,
                                    request_id=response.headers.get("x-request-id"),
                                )
                            if kind == "response.incomplete":
                                raise PlanError("response_incomplete")
                            if kind == "response.completed":
                                if result.get("status") != "completed":
                                    raise PlanError("invalid_completed_response")
                                output = result.get("output")
                                if not isinstance(output, list):
                                    raise PlanError("invalid_completed_response")
                                texts = []
                                for item in output:
                                    if not isinstance(item, dict) or item.get("type") != "message":
                                        continue
                                    content = item.get("content")
                                    if not isinstance(content, list):
                                        raise PlanError("invalid_completed_response")
                                    for part in content:
                                        if (
                                            not isinstance(part, dict)
                                            or part.get("type") != "output_text"
                                        ):
                                            continue
                                        if not isinstance(part.get("text"), str):
                                            raise PlanError("invalid_completed_response")
                                        texts.append(part["text"])
                                report = "\n".join(texts)
                                if not report.strip() or len(report) > 200_000:
                                    raise PlanError("invalid_research_report")
                                return {
                                    "report": report,
                                    "model": result.get("model", model),
                                    "response_id": result.get("id"),
                                    "provider_usage": result.get("usage"),
                                    "wall_seconds": time.monotonic() - started,
                                    "execution": "live",
                                    "billing_source": "chatgpt_plan",
                                    "harness": "Multivac Responses report",
                                    "web_search_enabled": web_search,
                                }
            raise PlanError("stream_interrupted")
        except TimeoutError:
            raise PlanError("time_allowance_reached") from None
        except httpx.HTTPError:
            raise PlanError("stream_interrupted") from None
        finally:
            if http is None:
                await client.aclose()
