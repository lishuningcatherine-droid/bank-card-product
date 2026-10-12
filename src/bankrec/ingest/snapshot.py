"""Content-addressed snapshots and change-detection hashing (DESIGN §21.2)."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

VOLATILE = [
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",  # uuids
    r"\b[0-9a-f]{24,}\b",  # long hex tokens / nonces
    r"\b\d{10,13}\b",  # unix timestamps
    r"reference #\s*[\w.]+",
    r"\b\d{1,2}:\d{2}(?::\d{2})?\s*(?:am|pm)?\s*(?:et|est|edt|pt|ct|utc)?\b",
    r"©\s*\d{4}(?:\s*-\s*\d{4})?",
]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def content_hash(text: str, extra_volatile: list[str] | None = None) -> str:
    """Hash of normalized visible text: whitespace collapsed, volatile tokens removed."""
    t = text.lower()
    for pat in VOLATILE + (extra_volatile or []):
        t = re.sub(pat, " ", t, flags=re.IGNORECASE)
    t = re.sub(r"\s+", " ", t).strip()
    return sha256(t.encode("utf-8"))


@dataclass
class StoredSnapshot:
    snapshot_id: str
    raw_path: Path
    text_path: Path
    raw_sha256: str
    content_sha256: str


def store(data_dir: Path, run_id: str, body: bytes, text: str, ext: str, *,
          supporting: list[dict[str, object]] | None = None, extra_volatile: list[str] | None = None) -> StoredSnapshot:
    raw_sha = sha256(body)
    d = data_dir / "raw" / run_id
    d.mkdir(parents=True, exist_ok=True)
    raw_path = d / f"{raw_sha}.{ext}"
    text_path = d / f"{raw_sha}.txt"
    if not raw_path.exists():
        raw_path.write_bytes(body)
    if not text_path.exists():
        text_path.write_text(text, encoding="utf-8")
    if supporting:
        (d / f"{raw_sha}.xhr.json").write_text(json.dumps(supporting, indent=1), encoding="utf-8")
    return StoredSnapshot(f"{run_id}/{raw_sha}", raw_path, text_path, raw_sha, content_hash(text, extra_volatile))
