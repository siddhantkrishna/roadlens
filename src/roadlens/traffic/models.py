"""Typed analytics inputs, measurements and persistence messages; no frame storage."""

from dataclasses import dataclass, field

from roadlens.traffic.scene import finite_number


@dataclass(frozen=True)
class AnalyticsConfig:
    database: str | None = None
    window_seconds: float = 10.0
    max_gap: float = 2.0
    stationary_speed: float = 0.005
    stationary_seconds: float = 3.0
    stalled_seconds: float = 30.0
    queue_min_vehicles: int = 3
    queue_link_distance: float = 0.12
    queue_seconds: float = 3.0
    congestion_occupancy: float = 0.5
    trajectory_interval: float = 0.5
    baseline_min_windows: int = 20
    baseline_max_windows: int = 120
    anomaly_z: float = 3.5
    retention_days: int = 7
    grid_width: int = 64
    grid_height: int = 36

    def __post_init__(self):
        for key in (
            "window_seconds",
            "max_gap",
            "stationary_speed",
            "stationary_seconds",
            "stalled_seconds",
            "queue_link_distance",
            "queue_seconds",
            "trajectory_interval",
            "anomaly_z",
        ):
            finite_number(getattr(self, key), key, 0.000001)
        for key in (
            "queue_min_vehicles",
            "baseline_min_windows",
            "baseline_max_windows",
            "retention_days",
            "grid_width",
            "grid_height",
        ):
            if type(getattr(self, key)) is not int or getattr(self, key) < 1:
                raise ValueError(f"{key} must be a positive integer")
        if self.baseline_min_windows < 5 or self.baseline_max_windows < self.baseline_min_windows:
            raise ValueError("Baselines require at least five prior windows and enough history")
        if self.grid_width > 256 or self.grid_height > 144:
            raise ValueError("Maximum analytics grid is 256x144")
        if self.stalled_seconds < self.stationary_seconds:
            raise ValueError("stalled_seconds cannot be shorter than stationary_seconds")
        finite_number(self.congestion_occupancy, "congestion_occupancy", 0.000001)
        if self.congestion_occupancy > 1:
            raise ValueError("congestion_occupancy cannot exceed 1")
        if self.database is not None and (not isinstance(self.database, str) or not self.database):
            raise ValueError("database must be a path or null")


@dataclass(frozen=True)
class TrafficEvent:
    key: str
    kind: str
    source_time: float
    object_id: str | None = None
    category: str | None = None
    direction: str | None = None
    track_key: str | None = None
    details: dict = field(default_factory=dict)


@dataclass(frozen=True)
class TrajectoryPoint:
    track_key: str
    source_time: float
    category: str
    x: float
    y: float
    speed_mps: float | None
    speed_unavailable_reason: str | None = None


@dataclass(frozen=True)
class Count:
    line_id: str
    category: str
    direction: str
    count: int


@dataclass(frozen=True)
class ZoneStatus:
    zone_id: str
    vehicles: int
    categories: dict[str, int]
    image_occupancy: float | None
    slow_vehicles: int
    queued_vehicles: int | None
    queue_active: bool | None
    congestion: str


@dataclass(frozen=True)
class Speed:
    track_key: str
    mps: float | None
    unavailable_reason: str | None


@dataclass(frozen=True)
class TrafficSnapshot:
    source_time: float
    counts: tuple[Count, ...]
    counting_available: bool
    zones: tuple[ZoneStatus, ...]
    speeds: tuple[Speed, ...]
    speed_unavailable_reason: str | None
    baseline_windows: int
    baseline_ready: bool


@dataclass(frozen=True)
class Measurement:
    start_time: float
    end_time: float
    observed_seconds: float
    samples: int
    complete: bool
    counts: tuple[Count, ...]
    flow_per_minute: dict[str, float | None]
    zones: dict[str, dict]
    baseline_windows: int | None = None
    baseline_ready: bool | None = None


@dataclass(frozen=True)
class AnalysisUpdate:
    snapshot: TrafficSnapshot
    events: tuple[TrafficEvent, ...] = ()
    trajectories: tuple[TrajectoryPoint, ...] = ()
    measurements: tuple[Measurement, ...] = ()
    heatmap: tuple[tuple[float, ...], ...] | None = None
