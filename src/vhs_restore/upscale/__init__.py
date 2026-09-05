"""Local Vulkan-first and classical upscaling backends."""

from .base import (
    UpscaleBackend,
    get_upscale_backend,
    prepare_upscale_paths,
    raise_for_command_failure,
    select_backend,
    select_upscale_backend,
    validate_scale,
)
from .classical import ClassicalBackend, FFmpegBackend
from .realesrgan import RealESRGANBackend, RealEsrganBackend
from .video2x import Video2XBackend, Video2xBackend

__all__ = [
    "UpscaleBackend",
    "ClassicalBackend",
    "FFmpegBackend",
    "RealESRGANBackend",
    "RealEsrganBackend",
    "Video2XBackend",
    "Video2xBackend",
    "get_upscale_backend",
    "prepare_upscale_paths",
    "raise_for_command_failure",
    "select_backend",
    "select_upscale_backend",
    "validate_scale",
]
