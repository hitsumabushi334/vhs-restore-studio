from pathlib import Path

from vhs_restore.jobs.cache import JobCache
from vhs_restore.jobs.manifest import (
    JobManifest,
    load_manifest,
    save_manifest,
    settings_hash,
    source_hash,
)
from vhs_restore.settings import RestoreSettings


def test_manifest_round_trip_and_resume_rejects_source_or_settings_changes(
    tmp_path: Path,
):
    source = tmp_path / "日本語 capture (raw) [01].avi"
    source.write_bytes("元の映像".encode("utf-8"))
    output = tmp_path / "restored output.mkv"
    settings = RestoreSettings()

    manifest = JobManifest.create(source, output, settings, job_id="job-01")
    manifest_path = save_manifest(manifest, tmp_path / "manifest.json")
    loaded = load_manifest(manifest_path)

    assert loaded.source_path == source
    assert loaded.output_path == output
    assert loaded.source_hash == source_hash(source)
    assert loaded.settings_hash == settings_hash(settings)
    assert loaded.can_resume(source, settings)

    source.write_bytes("変更された映像".encode("utf-8"))
    assert not loaded.can_resume(source, settings)

    source.write_bytes("元の映像".encode("utf-8"))
    changed = RestoreSettings(denoise_strength=0.4)
    assert not loaded.can_resume(source, changed)


def test_cache_lookup_requires_matching_hashes_and_intact_artifact(tmp_path: Path):
    source = tmp_path / "capture.mp4"
    source.write_bytes(b"source")
    artifact = tmp_path / "restore.mkv"
    artifact.write_bytes(b"intermediate")
    cache = JobCache(tmp_path / "cache")

    cache.store(
        "restore",
        artifact,
        source_hash=source_hash(source),
        settings_hash=settings_hash(RestoreSettings()),
    )

    assert (
        cache.lookup(
            "restore",
            source_hash=source_hash(source),
            settings_hash=settings_hash(RestoreSettings()),
        )
        == artifact
    )
    assert (
        cache.lookup(
            "restore",
            source_hash=source_hash(source),
            settings_hash=settings_hash(RestoreSettings(denoise_strength=0.4)),
        )
        is None
    )

    artifact.write_bytes(b"corrupted")
    assert (
        cache.lookup(
            "restore",
            source_hash=source_hash(source),
            settings_hash=settings_hash(RestoreSettings()),
        )
        is None
    )
