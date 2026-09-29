"""Contributor-owned pilot connection, outbound MCP bridge, and bounded execution."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import signal
import subprocess
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

import httpx
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .config import DATA
from .models import Offer
from .wire import fingerprint

DEFAULT_ORIGIN = "https://multivac.onrender.com"


def private_json(path: Path, value: dict):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
    temporary.replace(path)


def owner_key(create=False):
    path = DATA / "remote" / "owner-key.json"
    if path.exists():
        key = Ed25519PrivateKey.from_private_bytes(
            base64.b64decode(json.loads(path.read_text())["key"])
        )
    elif create:
        key = Ed25519PrivateKey.generate()
        private_json(
            path,
            {
                "key": base64.b64encode(
                    key.private_bytes(
                        serialization.Encoding.Raw,
                        serialization.PrivateFormat.Raw,
                        serialization.NoEncryption(),
                    )
                ).decode()
            },
        )
    else:
        raise ValueError("Create the owner key first with market remote owner-key.")
    return key


class RemoteClient:
    def __init__(
        self, origin=DEFAULT_ORIGIN, connection="device", *, directory: Path | None = None
    ):
        import re

        parsed = urlparse(origin)
        if (
            (
                parsed.scheme != "https"
                and not (parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"})
            )
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("Use an HTTPS platform origin, without credentials, query, or path.")
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,60}", connection):
            raise ValueError(
                "Choose a simple connection name using letters, numbers, hyphens, and underscores."
            )
        self.origin = origin.rstrip("/")
        self.api_origin = self.origin
        self.transport_headers = {}
        private_host = os.environ.get("MARKET_INTERNAL_API_HOST")
        if private_host and os.environ.get("MARKET_PROJECT_RUNTIME") == "cloud":
            # Only the operator-configured Render worker uses this transport.
            # Keep the public origin for connection storage and owner assertions.
            if not re.fullmatch(
                r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", private_host
            ) or self.origin != os.environ.get("MARKET_PUBLIC_ORIGIN", "").rstrip("/"):
                raise ValueError(
                    "Configure the cloud worker's private service host and public origin together."
                )
            self.api_origin = f"http://{private_host}:10000"
            self.transport_headers = {"Host": parsed.netloc}
        # Assistant hosts choose their own working directory. Pin the connection
        # location now so a printed MCP configuration can be reused elsewhere.
        root = (directory or DATA / "remote").expanduser().absolute()
        self.directory = root / fingerprint({"origin": self.origin})[:16]
        self.path = self.directory / (connection + ".json")
        self.config = json.loads(self.path.read_text()) if self.path.exists() else {}
        # Reuse HTTPS connections. Retry only connection establishment failures,
        # before a request can have reached the application; never replay an
        # uncertain mutation automatically.
        self.http = httpx.Client(transport=httpx.HTTPTransport(retries=2), follow_redirects=False)

    def save(self, value):
        self.config = value
        private_json(self.path, value)

    def headers(self):
        if not self.config.get("token"):
            raise ValueError("Connect this device first with multivac remote connect.")
        return {**self.transport_headers, "Authorization": "Bearer " + self.config["token"]}

    def call(self, method: str, path: str, body=None, *, public=False, timeout=90):
        response = self.http.request(
            method,
            self.api_origin + "/api/pilot" + path,
            json=body,
            headers=self.transport_headers if public else self.headers(),
            timeout=httpx.Timeout(timeout, connect=min(timeout, 10)),
            follow_redirects=False,
        )
        if response.is_error:
            try:
                detail = response.json().get("detail", "Request failed.")
            except ValueError:
                detail = "The hosted service is temporarily unavailable."
            raise ValueError(f"Platform response {response.status_code}: {detail}")
        return response.json()

    def login_owner(self):
        stamp = int(time.time())
        assertion = jwt.encode(
            {
                "sub": "owner",
                "iss": "research-market-owner",
                "aud": self.origin,
                "iat": stamp,
                "exp": stamp + 60,
                "jti": uuid.uuid4().hex,
            },
            owner_key(),
            algorithm="EdDSA",
        )
        result = self.call("POST", "/owner/session", {"assertion": assertion}, public=True)
        self.save(result)
        return result["identity"]

    def connect(self, label, *, renew=False):
        renewing = renew or bool(self.config.get("renewal_pairing"))
        if renewing and not self.config.get("identity"):
            raise ValueError("Renew an existing connection, or omit --renew for a new invitation.")
        if self.config.get("token") and not renewing:
            return self.poll()
        key = "renewal_pairing" if renewing else "pairing"
        previous = self.config.get(key)
        if previous and previous["expires_at"] > time.time():
            pairing = previous
        else:
            pairing = self.call("POST", "/pairings", {"label": label}, public=True)
            self.save({**self.config, key: pairing} if renewing else {key: pairing})
        result = {k: pairing[k] for k in ("code", "expires_at")}
        if renewing:
            result["renew_identity_id"] = self.config["identity"]["id"]
        return result

    def poll(self):
        if self.config.get("token") and not self.config.get("renewal_pairing"):
            return {"state": "approved", **self.call("GET", "/session")}
        pair = self.config.get("renewal_pairing") or self.config.get("pairing")
        if not pair:
            raise ValueError("Start a connection request first.")
        result = self.call(
            "POST",
            f"/pairings/{pair['pairing_id']}/poll",
            {"device_secret": pair["device_secret"]},
            public=True,
        )
        if result["state"] == "approved":
            self.save({"token": result["token"], "identity": result["identity"]})
        return {k: v for k, v in result.items() if k != "token"}

    def grant(self, offer: Offer, *, agent=False, request_id=None):
        import re

        identifier = request_id or uuid.uuid4().hex
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", identifier):
            raise ValueError(
                "Choose a simple request ID using letters, numbers, hyphens, and underscores."
            )
        request = {
            "request_id": identifier,
            "offer": offer.model_dump(),
            "capabilities": {"agent": agent, "gpu": False},
        }
        # Save before transmission, so even an uncertain response can be retried
        # without allocating a second project task.
        private_json(self.directory / "requests" / (identifier + ".json"), request)
        return self.call("POST", "/contributions", request)

    def contribution(self, identifier, *, timeout=90, summary=False):
        path = "/contributions/" + identifier + ("?view=summary" if summary else "")
        return self.call("GET", path, timeout=timeout)

    def save_context(self, identifier, destination=None):
        from .context_bundle import save_bundle

        record = self.contribution(identifier)
        bundle = (record.get("task") or {}).get("context_bundle")
        if not bundle:
            raise ValueError("This task has no project-published context snapshot.")
        if bundle.get("project_id") != record["project_id"]:
            raise ValueError("The context snapshot belongs to a different project.")
        # The fixed default path is derived from content, never an unchecked task path.
        from .context_bundle import validate_bundle

        validate_bundle(bundle)
        destination = destination or self.directory / "context" / bundle["sha256"]
        manifest = save_bundle(bundle, destination)
        return {"directory": str(Path(destination).absolute()), **manifest}

    def run_cpu(self, identifier):
        try:
            from .contracts import validate_task
            from .resources import executor_command
        except ImportError:
            raise ValueError(
                "CPU execution requires the full Multivac runner; this portable client uses your existing assistant."
            ) from None

        record = self.contribution(identifier)
        offer = Offer.model_validate(record["offer"])
        task = validate_task(record["task"], offer, record["project_id"])
        if task["kind"] != "cpu":
            raise ValueError(
                "This runner executes only the reviewed CPU profile. Use your own assistant for agent work."
            )
        directory = self.directory / "work" / identifier
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        output, attempted = directory / "output.json", directory / "attempt.json"
        if output.exists():
            return self.call(
                "POST", f"/contributions/{identifier}/result", json.loads(output.read_text())
            )
        if attempted.exists():
            raise ValueError(
                "This task has an earlier execution attempt without a saved result. It will not be run again automatically; cancel it or inspect its private workspace."
            )
        record = self.call("POST", f"/contributions/{identifier}/start")
        remaining = int(record["deadline"] - time.time())
        if remaining < 1:
            raise ValueError("The execution deadline has passed.")
        task = {**task, "budget_seconds": min(task["budget_seconds"], remaining)}
        private_json(directory / "task.json", task)
        # Atomic exclusive creation prevents two local processes executing the same grant.
        fd = os.open(attempted, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump({"started_at": time.time(), "deadline": record["deadline"]}, stream)
        with (directory / "execution.log").open("w") as log:
            process = subprocess.Popen(
                executor_command(directory / "task.json", task),
                stdout=log,
                stderr=log,
                start_new_session=True,
            )

            def stop_execution():
                if process.poll() is not None:
                    return
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                except ProcessLookupError:
                    pass

            watchdog = threading.Timer(max(0, record["deadline"] - time.time()), stop_execution)
            watchdog.daemon = True
            watchdog.start()
            next_check = time.monotonic() + 5
            try:
                while process.poll() is None:
                    if time.time() >= record["deadline"]:
                        raise ValueError("The contribution reached its execution deadline.")
                    if time.monotonic() >= next_check:
                        try:
                            current = self.contribution(
                                identifier,
                                timeout=min(2, max(0.1, record["deadline"] - time.time())),
                                summary=True,
                            )
                            if current["state"] != "running":
                                raise ValueError(
                                    "The platform has cancelled or closed this contribution."
                                )
                        except httpx.TransportError:
                            pass  # Local deadline still applies while disconnected.
                        next_check = time.monotonic() + 5
                    time.sleep(0.1)
            finally:
                watchdog.cancel()
                stop_execution()
                watchdog.join(timeout=3)
        if not output.is_file():
            raise ValueError(
                "Execution did not save a result. The private execution log contains details; retrying will not repeat the work."
            )
        return self.call(
            "POST", f"/contributions/{identifier}/result", json.loads(output.read_text())
        )


async def bridge(
    client: RemoteClient, project: str, endpoint: str, endpoint_token: str | None = None
):
    """Only this allowlisted MCP contribution surface is forwarded to the local project."""
    from .mcp_client import call_endpoint

    parsed = urlparse(endpoint)
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("The pilot bridge connects to an explicit local MCP endpoint.")
    headers = {"Authorization": "Bearer " + endpoint_token} if endpoint_token else {}
    allowed = {"claim_work", "submit_result", "release_work"}
    async with httpx.AsyncClient(
        base_url=client.api_origin + "/api/pilot/",
        headers=client.headers(),
        timeout=90,
        follow_redirects=False,
        trust_env=client.api_origin == client.origin,
    ) as http:

        async def publish():
            while True:
                try:
                    metadata = await call_endpoint(endpoint, "describe_project", headers=headers)
                    opportunities = await call_endpoint(
                        endpoint, "list_opportunities", headers=headers
                    )
                    response = await http.post(
                        f"projects/{project}/heartbeat",
                        json={"metadata": metadata, "opportunities": opportunities},
                    )
                    response.raise_for_status()
                except Exception:
                    print(
                        "Project heartbeat unavailable; reconnecting. No research state was discarded.",
                        flush=True,
                    )
                await asyncio.sleep(20)

        pulse = asyncio.create_task(publish())
        pending = None
        try:
            while True:
                try:
                    if pending:
                        response = await http.post(
                            f"projects/{project}/commands/{pending['id']}/complete",
                            json=pending["body"],
                        )
                        if response.status_code == 409:
                            # Lease redelivery superseded this attempt; the project
                            # result is durable and the next call retrieves it.
                            pending = None
                            continue
                        response.raise_for_status()
                        pending = None
                    response = await http.post(f"projects/{project}/commands/next?wait_seconds=20")
                    response.raise_for_status()
                    command = response.json()["command"]
                    if not command:
                        await asyncio.sleep(2)
                        continue
                    if command["tool"] not in allowed:
                        raise ValueError(
                            "The platform requested a tool outside the contribution interface."
                        )
                    body = {"delivery_token": command["delivery_token"]}
                    try:
                        body["result"] = await call_endpoint(
                            endpoint, command["tool"], command["arguments"], headers
                        )
                    except ValueError as error:
                        message = str(error)
                        for secret in (endpoint_token, client.config.get("token")):
                            if secret:
                                message = message.replace(secret, "[redacted]")
                        body["error"] = message[:1000]
                    pending = {"id": command["id"], "body": body}
                except asyncio.CancelledError:
                    raise
                except Exception:
                    print(
                        "Project bridge interrupted; reconnecting with durable command IDs.",
                        flush=True,
                    )
                    await asyncio.sleep(5)
        finally:
            pulse.cancel()
            await asyncio.gather(pulse, return_exceptions=True)
