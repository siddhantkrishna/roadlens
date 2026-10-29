"""Validated TOML configuration. Unknown keys are errors, including per-source keys."""

import math
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from roadlens.traffic.models import AnalyticsConfig


@dataclass(frozen=True)
class SourceConfig:
    name: str
    kind: str
    value: str
    realtime: bool = True
    scene: str | None = None
    camera_id: str | None = None

    def __post_init__(self):
        if not isinstance(self.name, str) or not isinstance(self.value, str):
            raise ValueError("Source name and value must be strings")
        if not self.name.strip() or not self.value.strip():
            raise ValueError("Source name and value must be nonempty")
        if self.kind not in {"camera", "opencv", "video"}:
            raise ValueError("Source kind must be camera, opencv, or video")
        if self.kind == "opencv" and (not self.value.isdecimal()):
            raise ValueError("OpenCV camera value must be a nonnegative index")
        if not isinstance(self.realtime, bool):
            raise ValueError("realtime must be a boolean")
        for key in ("scene", "camera_id"):
            value = getattr(self, key)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"{key} must be a nonempty string or null")


@dataclass(frozen=True)
class Config:
    model: str = "models/yolov8n.onnx"
    input_size: int = 640
    confidence: float = 0.35
    detection_floor: float = 0.1
    nms_iou: float = 0.45
    track_activation: float = 0.25
    track_buffer: int = 20
    max_gap: float = 2.0
    width: int = 1280
    height: int = 720
    capture_fps: int = 15
    inference_fps: float = 8.0
    threads: int = 2
    reconnect_delay: float = 2.0
    read_timeout: float = 5.0
    diagnostics_interval: float = 5.0
    sources: tuple[SourceConfig, ...] = field(default_factory=tuple)
    analytics: AnalyticsConfig = field(default_factory=AnalyticsConfig)

    def __post_init__(self):
        for key in ("input_size", "track_buffer", "width", "height", "capture_fps", "threads"):
            value = getattr(self, key)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{key} must be a positive integer")
        if self.input_size % 32:
            raise ValueError("input_size must be divisible by 32 and match the ONNX export")
        if self.width > 3840 or self.height > 2160 or self.threads > 16:
            raise ValueError("Maximum capture size is 3840x2160; maximum threads is 16")
        if self.capture_fps > 120:
            raise ValueError("capture_fps cannot exceed 120")
        for key in ("confidence", "detection_floor", "nms_iou", "track_activation"):
            value = getattr(self, key)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{key} must be numeric")
            if not math.isfinite(value) or not 0 < value < 1:
                raise ValueError(f"{key} must be between 0 and 1")
        if not 0.1 <= self.detection_floor < self.track_activation <= self.confidence:
            raise ValueError("Require 0.1 <= detection_floor < track_activation <= confidence")
        for key in (
            "inference_fps",
            "max_gap",
            "reconnect_delay",
            "read_timeout",
            "diagnostics_interval",
        ):
            value = getattr(self, key)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{key} must be numeric")
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{key} must be finite and positive")
        if not isinstance(self.model, str) or not self.model:
            raise ValueError("model must be a path")
        names = [s.name for s in self.sources]
        identities = [(s.kind, s.value) for s in self.sources]
        if len(names) != len(set(names)) or len(identities) != len(set(identities)):
            raise ValueError("Source names and inputs must be unique")
        camera_ids = [source.camera_id or source.name for source in self.sources]
        if len(camera_ids) != len(set(camera_ids)):
            raise ValueError("Each simultaneous source requires a distinct camera_id")


def load_config(path: Path | None) -> Config:
    if path is None:
        return Config()
    with path.open("rb") as stream:
        data = tomllib.load(stream)
    sources = tuple(SourceConfig(**source) for source in data.pop("sources", []))
    analytics = AnalyticsConfig(**data.pop("analytics", {}))
    return Config(**data, sources=sources, analytics=analytics)
