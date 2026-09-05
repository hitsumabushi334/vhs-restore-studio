"""Data models and persistence for source analysis results."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping

from .interlace import InterlaceAnalysis


@dataclass(frozen=True, slots=True)
class SourceInfo:
    """The media metadata needed by later restore-pipeline decisions."""

    path: Path
    duration: float | None = None
    width: int | None = None
    height: int | None = None
    frame_rate: float | None = None
    field_order: str | None = None
    codec_name: str | None = None
    pixel_format: str | None = None
    format_name: str | None = None
    format_long_name: str | None = None
    size_bytes: int | None = None
    bit_rate: int | None = None
    audio_streams: int = 0
    metadata: Mapping[str, str] = field(default_factory=dict)
    raw: Mapping[str, Any] = field(default_factory=dict)
    video_stream_index: int | None = None
    interlace: InterlaceAnalysis | None = None
    warnings: tuple[str, ...] = ()

    @property
    def fps(self) -> float | None:
        """Alias for the parsed average video frame rate."""

        return self.frame_rate

    @property
    def codec(self) -> str | None:
        """Alias for the video codec name."""

        return self.codec_name

    def with_interlace(self, analysis: InterlaceAnalysis) -> SourceInfo:
        """Return this metadata with an interlace result attached."""

        if analysis.metadata_field_order is None:
            analysis = analysis.with_metadata_field_order(self.field_order)
        return replace(
            self,
            interlace=analysis,
            warnings=tuple(dict.fromkeys((*self.warnings, *analysis.warnings))),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation of the analysis."""

        return {
            "source_path": str(self.path),
            "path": str(self.path),
            "duration": self.duration,
            "width": self.width,
            "height": self.height,
            "frame_rate": self.frame_rate,
            "field_order": self.field_order,
            "codec_name": self.codec_name,
            "pixel_format": self.pixel_format,
            "format_name": self.format_name,
            "format_long_name": self.format_long_name,
            "size_bytes": self.size_bytes,
            "bit_rate": self.bit_rate,
            "audio_streams": self.audio_streams,
            "metadata": dict(self.metadata),
            "video_stream_index": self.video_stream_index,
            "interlace": None if self.interlace is None else self.interlace.to_dict(),
            "warnings": list(self.warnings),
            "raw": dict(self.raw),
        }

    def to_json(self) -> str:
        """Serialize this analysis using UTF-8-friendly JSON."""

        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)


def save_analysis_json(info: SourceInfo, destination: Path) -> Path:
    """Persist ``info`` to a sidecar JSON file without touching source media."""

    destination = Path(destination)
    try:
        source_resolved = info.path.resolve()
        destination_resolved = destination.resolve()
    except OSError:
        source_resolved = info.path.absolute()
        destination_resolved = destination.absolute()

    if source_resolved == destination_resolved:
        raise ValueError("analysis JSON destination must not overwrite source media")

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(info.to_json() + "\n", encoding="utf-8")
    return destination


persist_analysis_json = save_analysis_json
