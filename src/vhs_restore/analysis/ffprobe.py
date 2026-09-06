"""FFprobe JSON parsing for source-media metadata."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from vhs_restore.utils.process import run_command

from .source_info import SourceInfo


def _result_stdout(result: object) -> str:
    value = getattr(result, "stdout", None)
    return str(value) if value else ""


def _result_diagnostics(result: object) -> str:
    chunks: list[str] = []
    for attribute in ("stderr", "stdout"):
        value = getattr(result, attribute, None)
        if value:
            chunks.append(str(value))
    return "\n".join(chunks)


def _as_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        result = float(str(value))
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _as_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return None


def _parse_ratio(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.casefold() in {"n/a", "na", "0/0"}:
        return None
    if "/" in text:
        numerator, denominator = text.split("/", 1)
        try:
            denominator_value = float(denominator)
            if denominator_value == 0:
                return None
            result = float(numerator) / denominator_value
        except ValueError:
            return None
    else:
        result = _as_float(text)
        if result is None:
            return None
    return result if math.isfinite(result) else None


def _string_mapping(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): str(item) for key, item in value.items()}


def _first_mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def probe_source(
    path: Path,
    *,
    ffprobe_executable: str | Path = "ffprobe",
) -> SourceInfo:
    """Run ffprobe and parse the first video stream into ``SourceInfo``."""

    source = Path(path)
    argv = [
        str(ffprobe_executable),
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(source),
    ]
    try:
        result = run_command(argv)
    except Exception as exc:
        raise RuntimeError(f"ffprobe failed for {source}: {exc}") from exc

    output = _result_stdout(result)
    if getattr(result, "returncode", 0) != 0:
        detail = " ".join(_result_diagnostics(result).split())
        suffix = f": {detail}" if detail else ""
        raise RuntimeError(
            f"ffprobe failed for {source} with exit code "
            f"{getattr(result, 'returncode', 'unknown')}{suffix}"
        )
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"ffprobe returned invalid JSON for {source}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"ffprobe returned an unexpected JSON value for {source}")

    streams = payload.get("streams")
    if not isinstance(streams, list):
        streams = []
    video_stream_index: int | None = None
    video_stream: dict[str, Any] = {}
    audio_streams = 0
    for stream in streams:
        if not isinstance(stream, dict):
            continue
        if stream.get("codec_type") == "audio":
            audio_streams += 1
        if video_stream_index is None and stream.get("codec_type") == "video":
            video_stream_index = _as_int(stream.get("index"))
            video_stream = stream
    if not video_stream:
        raise RuntimeError(f"ffprobe found no video stream in {source}")

    format_info = _first_mapping(payload.get("format"))
    duration = _as_float(format_info.get("duration"))
    if duration is None:
        duration = _as_float(video_stream.get("duration"))

    tags = _string_mapping(format_info.get("tags"))
    tags.update(_string_mapping(video_stream.get("tags")))

    return SourceInfo(
        path=source,
        duration=duration,
        width=_as_int(video_stream.get("width")),
        height=_as_int(video_stream.get("height")),
        frame_rate=_parse_ratio(
            video_stream.get("avg_frame_rate") or video_stream.get("r_frame_rate")
        ),
        field_order=(
            str(video_stream["field_order"])
            if video_stream.get("field_order") is not None
            else None
        ),
        codec_name=(
            str(video_stream["codec_name"])
            if video_stream.get("codec_name") is not None
            else None
        ),
        pixel_format=(
            str(video_stream["pix_fmt"])
            if video_stream.get("pix_fmt") is not None
            else None
        ),
        format_name=(
            str(format_info["format_name"])
            if format_info.get("format_name") is not None
            else None
        ),
        format_long_name=(
            str(format_info["format_long_name"])
            if format_info.get("format_long_name") is not None
            else None
        ),
        size_bytes=_as_int(format_info.get("size")),
        bit_rate=_as_int(format_info.get("bit_rate")),
        audio_streams=audio_streams,
        metadata=tags,
        raw=payload,
        video_stream_index=video_stream_index,
    )
