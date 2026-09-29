"""Stable transport fingerprints without importing the hosted server."""

import hashlib
import json


def fingerprint(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()
