"""FFmpeg ``idet`` sampling and field-order classification."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from vhs_restore.utils.process import run_command


SAMPLE_POSITIONS: tuple[float, ...] = (0.15, 0.50, 0.85)
_IDET_LINE_RE = re.compile(
    r"(?P<kind>single|multi)\s+frame\s+detection\s*:\s*"
    r"TFF\s*:\s*(?P<tff>\d+)\s+"
    r"BFF\s*:\s*(?P<bff>\d+)\s+"
    r"Progressive\s*:\s*(?P<progressive>\d+)\s+"
    r"Undetermined\s*:\s*(?P<undetermined>\d+)",
    re.IGNORECASE,
)
_IDET_COUNTS_RE = re.compile(
    r"TFF\s*:\s*(?P<tff>\d+)\s+"
    r"BFF\s*:\s*(?P<bff>\d+)\s+"
    r"Progressive\s*:\s*(?P<progressive>\d+)\s+"
    r"Undetermined\s*:\s*(?P<undetermined>\d+)",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class InterlaceSample:
    """One ``idet`` observation at a source-relative position."""

    position: float
    timestamp: float
    tff: int = 0
    bff: int = 0
    progressive: int = 0
    undetermined: int = 0
    classification: str = "Unknown"
    raw_output: str = ""
    error: str | None = None

    @property
    def percent(self) -> float:
        """Return the sample position as a percentage of the source."""

        return self.position * 100.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "position": self.position,
            "percent": self.percent,
            "timestamp": self.timestamp,
            "tff": self.tff,
            "bff": self.bff,
            "progressive": self.progressive,
            "undetermined": self.undetermined,
            "classification": self.classification,
            "error": self.error,
        }


SampleAnalysis = InterlaceSample


@dataclass(frozen=True, slots=True)
class InterlaceAnalysis:
    """Multi-point ``idet`` result used for deinterlace decisions."""

    classification: str
    confidence: float
    samples: tuple[InterlaceSample, ...] = ()
    warnings: tuple[str, ...] = ()
    metadata_field_order: str | None = None

    @property
    def field_order(self) -> str:
        """Return the selected classification using the field-order vocabulary."""

        return self.classification

    @property
    def is_interlaced(self) -> bool:
        """Return whether the result contains a usable interlaced signal."""

        return self.classification in {"TFF", "BFF", "Mixed"}

    def with_metadata_field_order(self, value: str | None) -> InterlaceAnalysis:
        """Attach metadata and add a warning when it conflicts with idet."""

        return replace(
            self,
            metadata_field_order=value,
            warnings=tuple(
                dict.fromkeys((*self.warnings, *_metadata_warnings(value, self.classification)))
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "classification": self.classification,
            "field_order": self.classification,
            "confidence": self.confidence,
            "metadata_field_order": self.metadata_field_order,
            "samples": [sample.to_dict() for sample in self.samples],
            "warnings": list(self.warnings),
        }


def normalize_field_order(value: str | None) -> str | None:
    """Map common ffprobe field-order values to TFF/BFF/Progressive."""

    if value is None:
        return None
    normalized = str(value).strip().casefold()
    if not normalized or normalized in {"unknown", "n/a", "na"}:
        return None
    if normalized in {"progressive", "p", "prog"}:
        return "Progressive"
    if normalized in {"tff", "top", "top-first", "top field first"}:
        return "TFF"
    if normalized in {"bff", "bottom", "bottom-first", "bottom field first"}:
        return "BFF"
    if normalized.startswith("t"):
        return "TFF"
    if normalized.startswith("b"):
        return "BFF"
    return None


def _result_output(result: object) -> str:
    chunks: list[str] = []
    for attribute in ("stdout", "stderr"):
        value = getattr(result, attribute, None)
        if value:
            chunks.append(str(value))
    return "\n".join(chunks)


def _parse_idet_counts(output: str) -> tuple[int, int, int, int] | None:
    matches = list(_IDET_LINE_RE.finditer(output))
    if matches:
        multi = [match for match in matches if match.group("kind").casefold() == "multi"]
        match = (multi or matches)[-1]
    else:
        matches = list(_IDET_COUNTS_RE.finditer(output))
        if not matches:
            return None
        match = matches[-1]

    return tuple(
        int(match.group(name))
        for name in ("tff", "bff", "progressive", "undetermined")
    )


def _classify_counts(tff: int, bff: int, progressive: int) -> str:
    values = {"TFF": tff, "BFF": bff, "Progressive": progressive}
    detected = {name for name, value in values.items() if value > 0}
    if not detected:
        return "Unknown"
    if len(detected) > 1:
        return "Mixed"
    return next(iter(detected))


def _classify_samples(samples: tuple[InterlaceSample, ...]) -> tuple[str, float]:
    totals = {
        "TFF": sum(sample.tff for sample in samples),
        "BFF": sum(sample.bff for sample in samples),
        "Progressive": sum(sample.progressive for sample in samples),
        "Unknown": sum(sample.undetermined for sample in samples),
    }
    detected = {
        name for name in ("TFF", "BFF", "Progressive") if totals[name] > 0
    }
    if not detected:
        return "Unknown", 0.0

    total = sum(totals.values())
    if len(detected) > 1:
        confidence = max(totals[name] for name in detected) / total if total else 0.0
        return "Mixed", confidence

    classification = next(iter(detected))
    confidence = totals[classification] / total if total else 0.0
    return classification, confidence


def _metadata_warnings(
    metadata_field_order: str | None,
    classification: str,
) -> tuple[str, ...]:
    metadata_classification = normalize_field_order(metadata_field_order)
    if metadata_classification is None or classification == "Unknown":
        return ()
    if metadata_classification == classification:
        return ()
    return (
        "Field order uncertain: metadata reports "
        f"{metadata_classification} but idet detects {classification}.",
        "metadata unreliable: use idet classification or a manual override.",
    )


def _format_timestamp(timestamp: float) -> str:
    return f"{timestamp:.6f}".rstrip("0").rstrip(".") or "0"


def analyze_interlace(
    path: Path,
    duration: float,
    *,
    metadata_field_order: str | None = None,
    ffmpeg_executable: str | Path = "ffmpeg",
) -> InterlaceAnalysis:
    """Sample FFmpeg ``idet`` near 15%, 50%, and 85% of a source."""

    if not math.isfinite(duration) or duration < 0:
        raise ValueError("duration must be a finite, non-negative number")

    source = Path(path)
    samples: list[InterlaceSample] = []
    warnings: list[str] = []
    for position in SAMPLE_POSITIONS:
        timestamp = duration * position
        argv = [
            str(ffmpeg_executable),
            "-hide_banner",
            "-loglevel",
            "info",
            "-ss",
            _format_timestamp(timestamp),
            "-i",
            str(source),
            "-map",
            "0:v:0",
            "-vf",
            "idet",
            "-frames:v",
            "50",
            "-an",
            "-f",
            "null",
            "-",
        ]
        try:
            result = run_command(argv)
        except Exception as exc:
            output = ""
            returncode = None
            error = str(exc)
        else:
            output = _result_output(result)
            returncode = getattr(result, "returncode", 0)
            error = None

        counts = _parse_idet_counts(output)
        if counts is None:
            sample = InterlaceSample(
                position=position,
                timestamp=timestamp,
                raw_output=output,
                error=(
                    error
                    or (
                        f"ffmpeg exited with code {returncode}"
                        if returncode not in (None, 0)
                        else None
                    )
                ),
            )
            if sample.error:
                warnings.append(
                    f"idet sample at {position:.0%} unavailable: {sample.error}."
                )
        else:
            tff, bff, progressive, undetermined = counts
            sample = InterlaceSample(
                position=position,
                timestamp=timestamp,
                tff=tff,
                bff=bff,
                progressive=progressive,
                undetermined=undetermined,
                classification=_classify_counts(tff, bff, progressive),
                raw_output=output,
                error=(
                    f"ffmpeg exited with code {returncode}"
                    if returncode not in (None, 0)
                    else None
                ),
            )
            if sample.error:
                warnings.append(
                    f"idet sample at {position:.0%} completed with warnings: "
                    f"{sample.error}."
                )
        samples.append(sample)

    sample_tuple = tuple(samples)
    classification, confidence = _classify_samples(sample_tuple)
    if classification == "Mixed":
        warnings.append("idet samples disagree; field order is mixed.")
    analysis = InterlaceAnalysis(
        classification=classification,
        confidence=round(confidence, 6),
        samples=sample_tuple,
        warnings=tuple(dict.fromkeys(warnings)),
    )
    return analysis.with_metadata_field_order(metadata_field_order)
