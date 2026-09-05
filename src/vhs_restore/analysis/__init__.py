"""Source inspection helpers used before building a restore pipeline."""

from .ffprobe import probe_source
from .interlace import (
    InterlaceAnalysis,
    InterlaceSample,
    analyze_interlace,
)
from .source_info import SourceInfo, persist_analysis_json, save_analysis_json

__all__ = [
    "InterlaceAnalysis",
    "InterlaceSample",
    "SourceInfo",
    "analyze_interlace",
    "persist_analysis_json",
    "probe_source",
    "save_analysis_json",
]
