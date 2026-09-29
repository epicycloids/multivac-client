from __future__ import annotations

import fcntl
import os
import secrets
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(os.environ.get("MARKET_DATA_DIR", ROOT / ".research-market")).resolve()
PLATFORM_PORT = int(os.environ.get("MARKET_PORT", "8710"))
PROJECT_PORTS = {"trefethen-arena": 8714, "trefethen-autonomous": 8715}
PLATFORM_URL = os.environ.get("MARKET_URL", f"http://127.0.0.1:{PLATFORM_PORT}")


def prepare_data() -> Path:
    DATA.mkdir(parents=True, exist_ok=True, mode=0o700)
    return DATA


def local_token() -> str:
    if value := os.environ.get("MARKET_TOKEN"):
        return value
    path = prepare_data() / "access-token"
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(fd, "r+") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        value = stream.read().strip()
        if not value:
            value = secrets.token_urlsafe(32)
            stream.seek(0)
            stream.write(value)
            stream.flush()
        return value


def project_url(project_id: str) -> str:
    value = os.environ.get(f"MARKET_PROJECT_{project_id.upper()}_URL")
    if value is None:
        if project_id in PROJECT_PORTS:
            value = f"http://127.0.0.1:{PROJECT_PORTS[project_id]}"
        else:
            from .store import Store

            registration = Store().get("registration", project_id)
            if not registration:
                raise ValueError("Unknown project; register its local MCP endpoint first.")
            value = registration["endpoint"]
    parsed = urlparse(value)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost"}
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "This local prototype only connects to loopback HTTP project services; local credentials are never forwarded to remote hosts."
        )
    return value.rstrip("/")
