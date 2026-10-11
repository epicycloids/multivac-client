"""Source and setup for the existing reviewed numerical CPU profile."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .config import DATA, prepare_data

TREFETHEN_REV = "d30e732f63a3d308fb6ab2fcb5a3948011bbe42e"
CPU_PROJECTS = ("trefethen-arena", "trefethen-autonomous")


def trefethen_path():
    return Path(os.environ.get("MARKET_TREFETHEN_DIR", DATA / "upstreams" / "trefethen-constant"))


def ensure_source(url, target, revision):
    """Prepare a separate pinned checkout; never reset an existing checkout."""
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        subprocess.run(["git", "clone", url, str(target)], check=True)
        subprocess.run(["git", "checkout", "--detach", revision], cwd=target, check=True)
    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=target, text=True).strip()
    if actual != revision:
        raise ValueError(f"{target.name} is at another revision; use a separate MARKET_DATA_DIR.")


def prepare_cpu():
    """Install the pinned numerical environment without starting a contribution."""
    prepare_data()
    ensure_source(
        "https://github.com/epicycloids/trefethen-constant.git", trefethen_path(), TREFETHEN_REV
    )
    # The numerical project owns its interpreter independently of the donor client.
    environment = {k: v for k, v in os.environ.items() if k not in {"UV_PYTHON", "VIRTUAL_ENV"}}
    subprocess.run(["uv", "sync", "--frozen"], cwd=trefethen_path(), env=environment, check=True)
