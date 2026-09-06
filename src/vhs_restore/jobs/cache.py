"""Content-addressed validation for resumable job artifacts."""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .manifest import _atomic_write_json, artifact_hash


_STAGE_NAME = re.compile(r"[^A-Za-z0-9_.-]+")


def cache_key(source_digest: str, settings_digest: str) -> str:
    """Return a stable cache namespace for source/settings identities."""

    payload = f"{source_digest}\0{settings_digest}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True, slots=True)
class CacheEntry:
    """Validated metadata for one cached stage artifact."""

    stage: str
    artifact: Path
    artifact_hash: str
    source_hash: str
    settings_hash: str
    metadata_path: Path


def _safe_stage_name(stage: str) -> str:
    value = _STAGE_NAME.sub("_", str(stage)).strip("._")
    if not value:
        raise ValueError("stage must contain at least one safe character")
    return value


class JobCache:
    """Store and validate stage metadata under a job-owned cache directory."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def metadata_path(self, stage: str) -> Path:
        return self.root / f"{_safe_stage_name(stage)}.json"

    def store(
        self,
        stage: str,
        artifact: str | Path,
        *,
        source_hash: str,
        settings_hash: str,
        **metadata: Any,
    ) -> Path:
        """Record an artifact's hash and identity metadata atomically."""

        artifact_path = Path(artifact)
        if not artifact_path.exists():
            raise FileNotFoundError(f"cache artifact does not exist: {artifact_path}")
        digest = artifact_hash(artifact_path)
        payload: dict[str, Any] = {
            "cache_version": 1,
            "stage": str(stage),
            "artifact_path": str(artifact_path),
            "artifact_hash": digest,
            "source_hash": str(source_hash),
            "settings_hash": str(settings_hash),
            "updated_at": time.time(),
        }
        payload.update(metadata)
        _atomic_write_json(self.metadata_path(stage), payload)
        return artifact_path

    def read(self, stage: str) -> CacheEntry | None:
        """Read cache metadata without treating it as valid yet."""

        metadata_path = self.metadata_path(stage)
        if not metadata_path.is_file():
            return None
        try:
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        try:
            return CacheEntry(
                stage=str(payload["stage"]),
                artifact=Path(str(payload["artifact_path"])),
                artifact_hash=str(payload["artifact_hash"]),
                source_hash=str(payload["source_hash"]),
                settings_hash=str(payload["settings_hash"]),
                metadata_path=metadata_path,
            )
        except (KeyError, TypeError, ValueError):
            return None

    def lookup(
        self,
        stage: str,
        *,
        source_hash: str,
        settings_hash: str,
    ) -> Path | None:
        """Return a cache artifact only when all identity and content checks pass."""

        entry = self.read(stage)
        if entry is None:
            return None
        if entry.stage != str(stage):
            return None
        if entry.source_hash != str(source_hash):
            return None
        if entry.settings_hash != str(settings_hash):
            return None
        if not entry.artifact.exists():
            return None
        try:
            if artifact_hash(entry.artifact) != entry.artifact_hash:
                return None
        except OSError:
            return None
        return entry.artifact

    def is_valid(
        self,
        stage: str,
        *,
        source_hash: str,
        settings_hash: str,
    ) -> bool:
        """Return whether :meth:`lookup` can reuse the requested stage."""

        return (
            self.lookup(
                stage,
                source_hash=source_hash,
                settings_hash=settings_hash,
            )
            is not None
        )


Cache = JobCache
is_cache_valid = lambda cache, stage, **kwargs: cache.is_valid(stage, **kwargs)


__all__ = ["Cache", "CacheEntry", "JobCache", "cache_key", "is_cache_valid"]
