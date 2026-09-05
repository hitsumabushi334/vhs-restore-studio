"""Persistent job manifests and source/settings identity hashes."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from vhs_restore.settings import RestoreSettings


MANIFEST_VERSION = 1
_HASH_CHUNK_SIZE = 1024 * 1024


def _json_value(value: Any) -> Any:
    """Convert settings-like values into deterministic JSON-compatible data."""

    if isinstance(value, RestoreSettings):
        return _json_value(value.to_dict())
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value):
        return _json_value(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise TypeError(f"value of type {type(value).__name__} is not JSON-compatible")


def settings_payload(settings: RestoreSettings | Mapping[str, Any]) -> dict[str, Any]:
    """Return a normalized settings mapping suitable for storage and hashing."""

    value = _json_value(settings)
    if not isinstance(value, dict):
        raise TypeError("settings must be a RestoreSettings instance or mapping")
    return value


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def settings_hash(settings: RestoreSettings | Mapping[str, Any]) -> str:
    """Return a stable SHA-256 digest for the complete restore settings."""

    return hashlib.sha256(_canonical_json(settings_payload(settings))).hexdigest()


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(_HASH_CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def source_hash(source: str | os.PathLike[str] | Path) -> str:
    """Return a content hash for a source media file.

    Hashing the bytes rather than only mtime/size makes a resumed job safe
    when a capture is replaced in place.  The operation is deliberately
    path-based and does not open the media through a shell command.
    """

    path = Path(source)
    if not path.is_file():
        raise FileNotFoundError(f"source media does not exist: {path}")
    return _hash_file(path)


def artifact_hash(path: str | os.PathLike[str] | Path) -> str:
    """Return a deterministic hash for a cached file or directory artifact."""

    path = Path(path)
    if path.is_file():
        return _hash_file(path)
    if path.is_dir():
        digest = hashlib.sha256()
        for child in sorted(item for item in path.rglob("*") if item.is_file()):
            relative = child.relative_to(path).as_posix().encode("utf-8")
            digest.update(relative)
            digest.update(b"\0")
            with child.open("rb") as handle:
                while True:
                    chunk = handle.read(_HASH_CHUNK_SIZE)
                    if not chunk:
                        break
                    digest.update(chunk)
        return digest.hexdigest()
    raise FileNotFoundError(f"artifact does not exist: {path}")


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return path


class JobManifest:
    """JSON-persisted identity and stage state for one restore job."""

    def __init__(
        self,
        source: str | os.PathLike[str] | Path | None = None,
        output: str | os.PathLike[str] | Path | None = None,
        settings: RestoreSettings | Mapping[str, Any] | None = None,
        *,
        source_path: str | os.PathLike[str] | Path | None = None,
        output_path: str | os.PathLike[str] | Path | None = None,
        job_id: str = "",
        source_hash: str | None = None,
        settings_hash: str | None = None,
        status: str = "pending",
        stages: Mapping[str, Mapping[str, Any]] | None = None,
        created_at: float | None = None,
        updated_at: float | None = None,
        manifest_version: int = MANIFEST_VERSION,
    ) -> None:
        selected_source = source_path if source_path is not None else source
        selected_output = output_path if output_path is not None else output
        if selected_source is None:
            raise TypeError("source or source_path is required")
        if selected_output is None:
            raise TypeError("output or output_path is required")
        if settings is None:
            settings = {}

        self.job_id = str(job_id)
        self.source_path = Path(selected_source)
        self.output_path = Path(selected_output)
        self.settings = settings_payload(settings)
        self.source_hash = source_hash or globals()["source_hash"](self.source_path)
        self.settings_hash = settings_hash or globals()["settings_hash"](self.settings)
        self.status = str(status)
        self.stages: dict[str, dict[str, Any]] = {
            str(name): dict(record) for name, record in (stages or {}).items()
        }
        self.created_at = float(created_at if created_at is not None else time.time())
        self.updated_at = float(updated_at if updated_at is not None else self.created_at)
        self.manifest_version = int(manifest_version)

    @classmethod
    def create(
        cls,
        source: str | os.PathLike[str] | Path,
        output: str | os.PathLike[str] | Path,
        settings: RestoreSettings | Mapping[str, Any],
        *,
        job_id: str = "",
    ) -> "JobManifest":
        """Create a new manifest after hashing the source and settings."""

        return cls(source, output, settings, job_id=job_id)

    @property
    def source(self) -> Path:
        """Alias for the source media path."""

        return self.source_path

    @property
    def output(self) -> Path:
        """Alias for the final output path."""

        return self.output_path

    @property
    def settings_data(self) -> dict[str, Any]:
        """Return a copy of the JSON-safe settings mapping."""

        return dict(self.settings)

    def can_resume(
        self,
        source: str | os.PathLike[str] | Path,
        settings: RestoreSettings | Mapping[str, Any],
    ) -> bool:
        """Return whether this manifest still describes the requested job."""

        try:
            return (
                globals()["source_hash"](source) == self.source_hash
                and globals()["settings_hash"](settings) == self.settings_hash
            )
        except (FileNotFoundError, TypeError, ValueError):
            return False

    def mark_stage(
        self,
        name: str,
        *,
        status: str,
        artifact: str | os.PathLike[str] | Path | None = None,
        error: str | None = None,
        **metadata: Any,
    ) -> dict[str, Any]:
        """Record stage state and, when present, the artifact's content hash."""

        record: dict[str, Any] = {"status": str(status)}
        if artifact is not None:
            artifact_path = Path(artifact)
            record["artifact_path"] = str(artifact_path)
            if artifact_path.exists():
                record["artifact_hash"] = artifact_hash(artifact_path)
        if error:
            record["error"] = str(error)
        record.update(metadata)
        self.stages[str(name)] = record
        self.updated_at = time.time()
        return record

    def stage_is_valid(self, name: str) -> bool:
        """Return whether a completed stage still has its recorded artifact."""

        record = self.stages.get(str(name))
        if not record or record.get("status") != "completed":
            return False
        value = record.get("artifact_path")
        expected = record.get("artifact_hash")
        if not value or not expected:
            return False
        path = Path(value)
        try:
            return path.exists() and artifact_hash(path) == expected
        except OSError:
            return False

    def to_dict(self) -> dict[str, Any]:
        """Return the complete JSON-compatible manifest payload."""

        return {
            "manifest_version": self.manifest_version,
            "job_id": self.job_id,
            "source_path": str(self.source_path),
            "output_path": str(self.output_path),
            "source": str(self.source_path),
            "output": str(self.output_path),
            "source_hash": self.source_hash,
            "settings_hash": self.settings_hash,
            "settings": self.settings,
            "status": self.status,
            "stages": self.stages,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "JobManifest":
        """Load a manifest payload while preserving its original hashes."""

        if not isinstance(payload, Mapping):
            raise ValueError("manifest must be a JSON object")
        source = payload.get("source_path", payload.get("source"))
        output = payload.get("output_path", payload.get("output"))
        if source is None or output is None:
            raise ValueError("manifest must contain source and output paths")
        settings = payload.get("settings", {})
        if not isinstance(settings, Mapping):
            raise ValueError("manifest settings must be a JSON object")
        try:
            version = int(payload.get("manifest_version", MANIFEST_VERSION))
        except (TypeError, ValueError) as exc:
            raise ValueError("manifest_version must be an integer") from exc
        stages = payload.get("stages", {})
        if not isinstance(stages, Mapping):
            raise ValueError("manifest stages must be a JSON object")
        return cls(
            source_path=source,
            output_path=output,
            settings=settings,
            job_id=str(payload.get("job_id", "")),
            source_hash=(
                str(payload["source_hash"])
                if payload.get("source_hash") is not None
                else None
            ),
            settings_hash=(
                str(payload["settings_hash"])
                if payload.get("settings_hash") is not None
                else None
            ),
            status=str(payload.get("status", "pending")),
            stages={
                str(name): dict(record)
                for name, record in stages.items()
                if isinstance(record, Mapping)
            },
            created_at=float(payload["created_at"])
            if payload.get("created_at") is not None
            else None,
            updated_at=float(payload["updated_at"])
            if payload.get("updated_at") is not None
            else None,
            manifest_version=version,
        )

    def save(self, path: str | os.PathLike[str] | Path) -> Path:
        """Atomically write this manifest as UTF-8 JSON."""

        self.updated_at = time.time()
        return _atomic_write_json(Path(path), self.to_dict())

    @classmethod
    def load(cls, path: str | os.PathLike[str] | Path) -> "JobManifest":
        """Read and validate one UTF-8 JSON manifest."""

        manifest_path = Path(path)
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid manifest JSON: {manifest_path}") from exc
        return cls.from_dict(payload)


def create_manifest(
    source: str | os.PathLike[str] | Path,
    output: str | os.PathLike[str] | Path,
    settings: RestoreSettings | Mapping[str, Any],
    *,
    job_id: str = "",
) -> JobManifest:
    """Functional alias for :meth:`JobManifest.create`."""

    return JobManifest.create(source, output, settings, job_id=job_id)


def save_manifest(
    manifest: JobManifest,
    path: str | os.PathLike[str] | Path,
) -> Path:
    """Persist a manifest and return its path."""

    if not isinstance(manifest, JobManifest):
        raise TypeError("manifest must be a JobManifest")
    return manifest.save(path)


def load_manifest(path: str | os.PathLike[str] | Path) -> JobManifest:
    """Load a manifest from disk."""

    return JobManifest.load(path)


manifest_path = lambda job_dir: Path(job_dir) / "manifest.json"
hash_settings = settings_hash
hash_source = source_hash
sha256_file = source_hash


__all__ = [
    "JobManifest",
    "MANIFEST_VERSION",
    "artifact_hash",
    "create_manifest",
    "hash_settings",
    "hash_source",
    "load_manifest",
    "manifest_path",
    "save_manifest",
    "settings_hash",
    "settings_payload",
    "sha256_file",
    "source_hash",
]
