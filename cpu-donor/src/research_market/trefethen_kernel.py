"""Run with the pinned Trefethen environment, separate from the platform runtime."""

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path


def exact_json_numbers(value):
    """Preserve integers beyond JavaScript's exact range across MCP/A2A/arena JSON."""
    if isinstance(value, dict):
        return {key: exact_json_numbers(item) for key, item in value.items()}
    if isinstance(value, list):
        return [exact_json_numbers(item) for item in value]
    if type(value) is int and abs(value) > 2**53 - 1:
        return str(value)
    return value


def compute(root: Path, mode: str, start: int = 0):
    sys.path.insert(0, str(root / "verification"))
    spec = importlib.util.spec_from_file_location("trefethen_public_verify", root / "verify.py")
    verification = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verification)
    endpoint = verification.integrity()
    import computation
    import spectral_compression
    from common import geometry, read
    from flint import ctx

    ctx.prec, ctx.threads = 8192, 1
    cert = root / "certificate"
    raw, scalar, compression, proxy, gram = [
        read(cert / name)
        for name in [
            "sampled.json",
            "scalars.json",
            "compression.json",
            "resolvent.json",
            "gram.json",
        ]
    ]
    spectral_compression.certify(compression, geometry(raw, scalar), scalar["cells"])
    context, _ = computation.prepare(raw, scalar, compression["mass_lower"], proxy["error"])
    batch = None
    if mode == "gram-batch":
        if start not in range(0, len(scalar["cells"]), 32):
            raise ValueError("Choose an existing 32-cell certificate batch.")
        batch = computation.gram_batch(raw, scalar, context, start)
        gram["batches"] = [batch if b["start"] == start else b for b in gram["batches"]]
    result = computation.finish(raw, scalar, context, gram, endpoint["decimal_denominator"])
    keys = [
        "decimal_lower_numerator",
        "decimal_upper_numerator",
        "decimal_denominator",
        "decimal_lower",
        "decimal_upper",
    ]
    bounds = {key: result[key] for key in keys}
    # Count common *decimal places* using exact strings, never binary floats.
    left, right = bounds["decimal_lower"].split("."), bounds["decimal_upper"].split(".")
    places = 0
    if left[0] == right[0]:
        for a, b in zip(left[1], right[1]):
            if a != b:
                break
            places += 1
    bounds["common_decimal_places"] = places
    return {
        "format": "trefethen-certificate-contribution-v1",
        "mode": mode,
        "start": start if mode == "gram-batch" else None,
        "batch": exact_json_numbers(batch),
        "endpoint": bounds,
        "context_sha256": computation.context_hash(context),
        "manifest_sha256": hashlib.sha256((cert / "integrity.json").read_bytes()).hexdigest(),
        "reused_inputs": ["published large-product enclosures", "published scalar defects"]
        + (["other published Gram batches"] if batch else ["published Gram batches"]),
        "recomputed": ["compression", "resolvent", "Gram aggregation", "lift", "infinite tail"]
        + ([f"Gram cells {start + 1}–{batch['stop']}"] if batch else []),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--mode", choices=["certificate", "gram-batch"], default="certificate")
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(json.dumps(compute(args.root, args.mode, args.start), allow_nan=False))
