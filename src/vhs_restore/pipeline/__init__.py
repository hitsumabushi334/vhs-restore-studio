"""Shared restoration pipeline planning and stage builders."""

from .deinterlace import DeinterlaceDecision, decide_deinterlace, generate_qtgmc_script
from .dvd import plan_dvd_video_bitrate
from .encode import build_encode_args
from .pipeline import PipelinePlan, build_pipeline, describe_processing_plan
from .geometry import build_geometry_filters, resolve_target_size

__all__ = [
    "DeinterlaceDecision",
    "PipelinePlan",
    "build_encode_args",
    "build_pipeline",
    "decide_deinterlace",
    "generate_qtgmc_script",
    "plan_dvd_video_bitrate",
    "build_geometry_filters",
    "resolve_target_size",
    "describe_processing_plan",
]
