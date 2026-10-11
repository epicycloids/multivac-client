"""Pinned numerical integration. Project verification is independent of donor execution."""

from __future__ import annotations

import json
import math
import os
import subprocess
import tempfile
import time
from decimal import Decimal, localcontext
from pathlib import Path

from .cpu_profile import TREFETHEN_REV, trefethen_path


class TrefethenExecutionUnavailable(RuntimeError):
    """The pinned verifier could not run; this is not an artifact rejection."""


def ready():
    root = trefethen_path()
    return (root / ".venv/bin/python").is_file() and (root / "certificate/integrity.json").is_file()


def require_environment():
    """Check the pinned source as the invoking user without numerical execution."""
    root = trefethen_path()
    if not ready():
        raise TrefethenExecutionUnavailable(
            "Prepare the pinned numerical environment with multivac-cpu prepare-cpu "
            "(or multivac-client prepare-cpu in the full private runner)."
        )
    try:
        revision = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True,
            stderr=subprocess.PIPE, timeout=10,
        ).strip()
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        raise TrefethenExecutionUnavailable(
            "Cannot verify the pinned numerical source as this user; check source availability and Git ownership/permissions."
        ) from error
    if revision != TREFETHEN_REV:
        raise TrefethenExecutionUnavailable("The numerical source does not match the pinned Trefethen revision.")
    return root


def compute(mode="certificate", start=0, timeout=120):
    if (
        mode not in {"certificate", "gram-batch"}
        or type(start) is not int
        or start not in range(0, 670, 32)
    ):
        raise ValueError("Unsupported certificate recomputation request.")
    root = require_environment()
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="trefethen-contribution-") as directory:
        output = Path(directory) / "result.json"
        result = subprocess.run(
            [
                str(root / ".venv/bin/python"),
                "-P",
                str(Path(__file__).with_name("trefethen_kernel.py")),
                str(root),
                "--mode",
                mode,
                "--start",
                str(start),
                "--output",
                str(output),
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1"},
        )
        if result.returncode or not output.exists():
            raise TrefethenExecutionUnavailable(
                "The pinned Trefethen recomputation failed; inspect the project verifier environment."
            )
        artifact = json.loads(output.read_text())
    artifact["source_revision"] = TREFETHEN_REV
    artifact["execution_seconds"] = time.monotonic() - started
    return artifact


def verify_artifact(artifact: dict):
    if (
        artifact.get("source_revision") != TREFETHEN_REV
        or artifact.get("format") != "trefethen-certificate-contribution-v1"
    ):
        raise ValueError("Unrecognized Trefethen certificate artifact.")
    mode = artifact.get("mode")
    start = artifact.get("start") if mode == "gram-batch" else 0
    fresh = compute(mode, start)
    for key in ["endpoint", "batch", "context_sha256", "manifest_sha256"]:
        if artifact.get(key) != fresh[key]:
            raise ValueError("The independently recomputed certificate differs in " + key + ".")
    endpoint = fresh["endpoint"]
    with localcontext() as context:
        context.prec = 80
        numerator = int(endpoint["decimal_upper_numerator"]) - int(
            endpoint["decimal_lower_numerator"]
        )
        width = Decimal(numerator) / Decimal(endpoint["decimal_denominator"])
        score = float(-width.log10())
        width_text = str(width)
    if not math.isfinite(score):
        raise ValueError("Invalid certificate precision.")
    return {
        "valid": True,
        "score": score,
        "metric": "Certified enclosure precision",
        "direction": "maximize",
        "unit": "decimal orders",
        "interval_width": width_text,
        "common_decimal_places": endpoint["common_decimal_places"],
        "new_research_claim": endpoint["common_decimal_places"] > 870,
        "verification_scope": "Independent replay of this pinned certificate computation; reused proof inputs are disclosed.",
        "recomputed": fresh["recomputed"],
        "reused_inputs": fresh["reused_inputs"],
        "verifier_wall_seconds": fresh["execution_seconds"],
    }
