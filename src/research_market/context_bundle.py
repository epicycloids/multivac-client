"""Publish and save immutable snapshots of project-selected text resources."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from pathlib import Path, PurePosixPath
from urllib.parse import quote

MAX_BYTES = 600_000
MAX_FILES = 60
TEXT_TYPES = {
    ".py": "text/x-python",
    ".md": "text/markdown",
    ".txt": "text/plain",
    ".json": "application/json",
    ".csv": "text/csv",
    ".tex": "text/plain",
}


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False).encode()
    ).hexdigest()


def resource_path(value):
    if not isinstance(value, str) or "\\" in value:
        raise ValueError("Context files need relative POSIX paths.")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or path.as_posix() != value
        or len(path.parts) < 2
        or path.parts[0] not in {"research", "source", "work"}
        or any(part.startswith(".") or part == "__pycache__" for part in path.parts)
        or path.suffix not in TEXT_TYPES
    ):
        raise ValueError("Select non-hidden text files within research/, source/, or work/.")
    return path


def build_bundle(workspace, paths, *, project_id, source_revision, evidence_status):
    """Copy the selected regular files into a context snapshot."""
    if not 1 <= len(paths) <= MAX_FILES or len(set(paths)) != len(paths):
        raise ValueError(f"Select between 1 and {MAX_FILES} different context files.")
    if not isinstance(evidence_status, str) or not 20 <= len(evidence_status) <= 4000:
        raise ValueError("Describe the evidence status and assumptions in 20–4000 characters.")
    workspace = Path(workspace).resolve()
    resources = []
    total = 0
    for name in sorted(paths):
        relative = resource_path(name)
        path = workspace.joinpath(*relative.parts)
        current = workspace
        for part in relative.parts:
            current /= part
            if current.is_symlink():
                raise ValueError("Shared inputs and symlinked context files cannot be published.")
        if not path.is_file() or not path.resolve().is_relative_to(workspace):
            raise ValueError(f"Selected context file is unavailable: {name}")
        with path.open("rb") as stream:
            data = stream.read(MAX_BYTES + 1)
        total += len(data)
        if total > MAX_BYTES:
            raise ValueError("Selected context exceeds the 600 KB pilot transport budget.")
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError("Context resources must be UTF-8 text.") from error
        sha = hashlib.sha256(data).hexdigest()
        # Embed the full resource using the MCP EmbeddedResource shape.
        # The URI identifies the content by its hash.
        resources.append(
            {
                "type": "resource",
                "resource": {
                    "uri": f"research://{quote(project_id, safe='')}/sha256/{sha}/{quote(name)}",
                    "mimeType": TEXT_TYPES[relative.suffix],
                    "text": text,
                },
                "_meta": {"path": name, "sha256": sha, "bytes": len(data)},
            }
        )
    bundle = {
        "format": "project-context-v1",
        "project_id": project_id,
        "starting_source_revision": source_revision,
        "evidence_status": evidence_status,
        "resources": resources,
    }
    # Escaping text can expand JSON beyond its original byte count.
    if len(json.dumps(bundle).encode()) > MAX_BYTES:
        raise ValueError("Encoded context exceeds the 600 KB pilot transport budget.")
    return {**bundle, "sha256": digest(bundle)}


def validate_bundle(bundle):
    if not isinstance(bundle, dict) or bundle.get("format") != "project-context-v1":
        raise ValueError("The project has not included a supported context snapshot.")
    if len(json.dumps(bundle).encode()) > MAX_BYTES + 100:
        raise ValueError("Context snapshot exceeds the transport budget.")
    if bundle.get("sha256") != digest({k: v for k, v in bundle.items() if k != "sha256"}):
        raise ValueError("Context snapshot checksum does not match.")
    resources = bundle.get("resources", [])
    if not isinstance(resources, list) or not 1 <= len(resources) <= MAX_FILES:
        raise ValueError("Invalid context resource count.")
    seen = set()
    for item in resources:
        if not isinstance(item, dict):
            raise ValueError("Invalid embedded context resource.")
        meta = item.get("_meta", {})
        if not isinstance(meta, dict) or not isinstance(item.get("resource"), dict):
            raise ValueError("Invalid embedded context metadata.")
        path = resource_path(meta.get("path"))
        text = item.get("resource", {}).get("text")
        if item.get("type") != "resource" or not isinstance(text, str):
            raise ValueError("Only embedded text context resources can be saved.")
        data = text.encode("utf-8")
        if (
            path in seen
            or meta.get("bytes") != len(data)
            or meta.get("sha256") != hashlib.sha256(data).hexdigest()
        ):
            raise ValueError("Context file is duplicated or its checksum does not match.")
        seen.add(path)
    return bundle


def bundle_manifest(bundle):
    return {
        **{k: v for k, v in bundle.items() if k != "resources"},
        "files": [item["_meta"] for item in bundle["resources"]],
    }


def save_bundle(bundle, destination):
    """Verify and save a snapshot, preserving any existing local edits."""
    bundle = validate_bundle(bundle)
    manifest = bundle_manifest(bundle)
    destination = Path(destination).absolute()
    if destination.is_symlink():
        raise ValueError("Choose a new context directory, not a symlink.")
    if destination.exists():
        try:
            saved = json.loads((destination / "MANIFEST.json").read_text())
            if saved != manifest:
                raise ValueError("The destination contains a different context snapshot.")
            for item in bundle["resources"]:
                path = destination / item["_meta"]["path"]
                if (
                    path.is_symlink()
                    or not path.resolve().is_relative_to(destination.resolve())
                    or hashlib.sha256(path.read_bytes()).hexdigest() != item["_meta"]["sha256"]
                ):
                    raise ValueError("Saved context was changed; choose a new directory.")
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError("The destination is not an intact context snapshot.") from error
        return manifest
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".market-context-", dir=destination.parent))
    try:
        for item in bundle["resources"]:
            path = temporary / item["_meta"]["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(item["resource"]["text"].encode("utf-8"))
        (temporary / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n")
        temporary.rename(destination)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return manifest
