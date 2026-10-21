"""Shared source fingerprint helpers for XboxXBERecomp build manifests."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
CONFIGURATIONS = ("Debug", "RelWithDebInfo", "Release")


class ProvenanceError(ValueError):
    pass


def checked_file(path: Path) -> Path:
    if not path.is_file():
        raise ProvenanceError(f"Required input is missing: {path}")
    if path.is_symlink():
        raise ProvenanceError(f"Provenance input is a symbolic link: {path}")
    return path


def fingerprint(path: Path) -> tuple[int, int, int]:
    stat = checked_file(path).stat()
    return stat.st_size, stat.st_mtime_ns, stat.st_ino


def file_record(root: Path, path: Path) -> dict:
    before = fingerprint(path)
    with path.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    if before != fingerprint(path):
        raise ProvenanceError(f"Input changed while hashing: {path}")
    return {"path": path.relative_to(root).as_posix(), "size": before[0], "sha256": digest}


def read_json(root: Path, path: Path) -> tuple[dict, dict]:
    before = fingerprint(path)
    raw = path.read_bytes()
    if before != fingerprint(path):
        raise ProvenanceError(f"Input changed while reading: {path}")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ProvenanceError(f"Expected a JSON object: {path}")
    record = {"path": path.relative_to(root).as_posix(), "size": len(raw),
              "sha256": hashlib.sha256(raw).hexdigest()}
    return value, record


def valid_digest(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def tree_record(root: Path, paths: list[Path]) -> dict:
    files = [file_record(root, path) for path in sorted(paths, key=lambda p: p.relative_to(root).as_posix())]
    # Canonical tree identity: UTF-8 relative path, NUL, lowercase SHA256, LF.
    canonical = "".join(f"{entry['path']}\0{entry['sha256']}\n" for entry in files).encode("utf-8")
    return {"file_count": len(files), "total_bytes": sum(entry["size"] for entry in files),
            "tree_sha256": hashlib.sha256(canonical).hexdigest(),
            "tree_hash_format": "UTF-8 path + NUL + lowercase SHA256 + LF, sorted by relative path",
            "files": files}


def git_bytes(toolkit: Path, *args: str) -> bytes:
    result = subprocess.run(["git", "-c", f"safe.directory={toolkit.as_posix()}",
                             "-C", str(toolkit), *args], check=False, capture_output=True)
    if result.returncode:
        raise ProvenanceError(f"Cannot inspect toolkit Git state: {result.stderr.decode('utf-8', errors='replace').strip()}")
    return result.stdout


