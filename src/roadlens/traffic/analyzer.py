"""Timestamp-based traffic measurements downstream of the unchanged vision tracker."""

import math
from collections import Counter, deque
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field

import cv2
import numpy as np

from roadlens.detection import VEHICLES
from roadlens.tracking import Track
from roadlens.traffic.models import (
    AnalysisUpdate,
    AnalyticsConfig,
    Count,
    Measurement,
    Speed,
    TrafficEvent,
    TrafficSnapshot,
    TrajectoryPoint,
    ZoneStatus,
)
from roadlens.traffic.scene import Point, Scene, intersection
from roadlens.traffic.statistics import Baselines, metrics


@dataclass
class CrossingState:
    side: int
    point: Point
    counted: set[str] = field(default_factory=set)


@dataclass
class TrackState:
    key: str
    category: str
    point: Point
    last_time: float
    slow_since: float | None = None
    last_saved: float = -math.inf
    stalled: bool = False
    stall_episode: int = 0
    lines: dict[str, CrossingState] = field(default_factory=dict)
    history: deque = field(default_factory=lambda: deque(maxlen=64))


class TrafficAnalyzer:
    def __init__(self, scene: Scene, config: AnalyticsConfig):
        self.scene, self.config = scene, config
        self.baselines = Baselines(config)
        self.states: dict[int, TrackState] = {}
        self.lifecycle = 0
        self.epoch: int | None = None
        self.last_time: float | None = None
        self.window_start = 0.0
        self.observed_total = 0.0
        self.counts: Counter = Counter(
            {
                (line.id, category, direction): 0
                for line in scene.lines
                for category in VEHICLES.values()
                for direction in (line.forward, line.reverse)
            }
        )
        self.window_counts = self.counts.copy()
        self.observed = 0.0
        self.samples = 0
        self.integrals: dict[str, Counter] = {}
        self.last_zones: tuple[ZoneStatus, ...] = ()
        self.queue_since: dict[str, float] = {}
        self.queue_active: set[str] = set()
        self.queue_episodes: Counter = Counter()
        self.heatmap = np.zeros((config.grid_height, config.grid_width), np.float64)
        self.zone_masks = self._masks()
        self.snapshot = TrafficSnapshot(
            0, (), bool(scene.lines), (), (), "no verified scene calibration", 0, False
        )

    def _masks(self) -> dict[str, np.ndarray]:
        shape = (self.config.grid_height, self.config.grid_width)
        masks = {}
        for zone in self.scene.zones:
            mask = np.zeros(shape, np.uint8)
            polygon = np.rint(np.asarray(zone.polygon) * (shape[1] - 1, shape[0] - 1))
            cv2.fillPoly(mask, [polygon.astype(np.int32)], 1)
            masks[zone.id] = mask.astype(bool)
        excluded = np.zeros(shape, bool)
        for zone in self.scene.zones:
            if zone.kind == "exclude":
                excluded |= masks[zone.id]
        return {
            zone.id: masks[zone.id] & ~excluded
            for zone in self.scene.zones
            if zone.kind != "exclude"
        }

    def _reset_window(self, timestamp: float) -> None:
        self.window_start = timestamp
        self.window_counts = self.counts.copy()
        self.observed, self.samples, self.integrals = 0.0, 0, {}

    def _count_rows(self, counter: Counter) -> tuple[Count, ...]:
        return tuple(Count(*key, value) for key, value in sorted(counter.items()))

    def _close_window(
        self, timestamp: float, complete: bool
    ) -> tuple[Measurement, list[TrafficEvent]]:
        counter = Counter(
            {key: value - self.window_counts[key] for key, value in self.counts.items()}
        )
        rates = {
            f"{key[0]}/{key[2]}/{key[1]}": (
                value * 60 / self.observed if self.observed > 0 else None
            )
            for key, value in counter.items()
        }
        zones = {}
        for zone in self.scene.zones:
            if zone.kind == "exclude":
                continue
            sums = self.integrals.get(zone.id, Counter())
            denominator = self.observed
            zones[zone.id] = {
                "mean_vehicles": sums["vehicles"] / denominator if denominator else None,
                "image_occupancy": (
                    sums["occupancy"] / sums["occupancy_seconds"]
                    if sums["occupancy_seconds"]
                    else None
                ),
                "mean_queued_vehicles": (
                    sums["queued"] / denominator if denominator and zone.kind == "queue" else None
                ),
                "congested_seconds": sums["congested"],
                "category_vehicle_seconds": {
                    category: sums[f"category/{category}"] for category in VEHICLES.values()
                },
            }
        measurement = Measurement(
            self.window_start,
            timestamp,
            self.observed,
            self.samples,
            complete and self.samples >= 2,
            self._count_rows(counter),
            rates,
            zones,
            baseline_windows=self.baselines.windows,
            baseline_ready=self.baselines.windows >= self.config.baseline_min_windows,
        )
        events = []
        if measurement.complete:
            for deviation in self.baselines.observe(metrics(measurement)):
                events.append(
                    TrafficEvent(
                        f"anomaly:{timestamp:.9f}:{deviation.metric}",
                        "anomaly",
                        timestamp,
                        object_id=deviation.metric,
                        details=asdict(deviation),
                    )
                )
        self._reset_window(timestamp)
        return measurement, events

    def _integrate(self, timestamp: float) -> tuple[list[Measurement], list[TrafficEvent]]:
        measurements, events = [], []
        cursor = self.last_time
        while cursor < timestamp:
            boundary = self.window_start + self.config.window_seconds
            end = min(timestamp, boundary)
            dt = end - cursor
            self.observed += dt
            self.observed_total += dt
            for zone in self.last_zones:
                sums = self.integrals.setdefault(zone.zone_id, Counter())
                sums["vehicles"] += zone.vehicles * dt
                if zone.image_occupancy is not None:
                    sums["occupancy"] += zone.image_occupancy * dt
                    sums["occupancy_seconds"] += dt
                if zone.queued_vehicles is not None:
                    sums["queued"] += zone.queued_vehicles * dt
                sums["congested"] += dt * (zone.congestion == "congested")
                for category, count in zone.categories.items():
                    sums[f"category/{category}"] += count * dt
            cursor = end
            if end >= boundary:
                measurement, anomalies = self._close_window(boundary, True)
                measurements.append(measurement)
                events.extend(anomalies)
        return measurements, events

    def _speed(
        self, state: TrackState, timestamp: float, matrix: np.ndarray | None, reason: str | None
    ) -> Speed:
        if matrix is None:
            return Speed(state.key, None, reason)
        hull = cv2.convexHull(np.asarray(self.scene.calibration.image_points, np.float32))
        candidates = [
            (t, p)
            for t, p in state.history
            if 0.2 <= timestamp - t <= min(1.0, self.config.max_gap)
        ]
        if not candidates:
            return Speed(state.key, None, "insufficient continuous observations")
        old_time, old = candidates[0]
        if any(cv2.pointPolygonTest(hull, p, False) < 0 for p in (old, state.point)):
            return Speed(state.key, None, "outside calibrated ground-plane region")
        projected = cv2.perspectiveTransform(np.asarray([[old, state.point]], np.float64), matrix)[
            0
        ]
        if not np.isfinite(projected).all():
            return Speed(state.key, None, "invalid ground-plane projection")
        return Speed(
            state.key,
            float(np.linalg.norm(projected[1] - projected[0]) / (timestamp - old_time)),
            None,
        )

    def _crossings(self, state: TrackState, timestamp: float) -> list[TrafficEvent]:
        events = []
        for line in self.scene.lines:
            side = line.side(state.point)
            if side == 0:
                continue
            previous = state.lines.get(line.id)
            if previous is None:
                state.lines[line.id] = CrossingState(side, state.point)
                continue
            if previous.side != side:
                direction = line.forward if previous.side < side else line.reverse
                location = intersection(previous.point, state.point, line.start, line.end)
                if location is not None and direction not in previous.counted:
                    previous.counted.add(direction)
                    self.counts[line.id, state.category, direction] += 1
                    events.append(
                        TrafficEvent(
                            f"crossing:{state.key}:{line.id}:{direction}",
                            "crossing",
                            timestamp,
                            line.id,
                            state.category,
                            direction,
                            state.key,
                            {"intersection": location, "identity_scope": "session_track_lifecycle"},
                        )
                    )
            previous.side, previous.point = side, state.point
        return events

    def _queue_members(self, candidates: list[TrackState]) -> set[str]:
        remaining = {state.key: state for state in candidates}
        queued = set()
        while remaining:
            _, seed = remaining.popitem()
            component, pending = [seed], [seed]
            while pending:
                current = pending.pop()
                neighbors = [
                    key
                    for key, state in remaining.items()
                    if math.dist(state.point, current.point) <= self.config.queue_link_distance
                ]
                for key in neighbors:
                    state = remaining.pop(key)
                    component.append(state)
                    pending.append(state)
            if len(component) >= self.config.queue_min_vehicles:
                queued.update(state.key for state in component)
        return queued

    def _zones(
        self, tracks: Sequence[Track], current: list[TrackState], timestamp: float
    ) -> tuple[tuple[ZoneStatus, ...], set[str], list[TrafficEvent]]:
        occupancy = np.zeros_like(self.heatmap, np.uint8)
        for track in tracks:
            x1, y1, x2, y2 = self._normalized_boxes[track.id]
            cv2.rectangle(
                occupancy,
                (
                    math.floor(x1 * (occupancy.shape[1] - 1)),
                    math.floor(y1 * (occupancy.shape[0] - 1)),
                ),
                (
                    math.ceil(x2 * (occupancy.shape[1] - 1)),
                    math.ceil(y2 * (occupancy.shape[0] - 1)),
                ),
                1,
                -1,
            )
        statuses, all_queued, events = [], set(), []
        for zone in self.scene.zones:
            if zone.kind == "exclude":
                continue
            inside = [state for state in current if zone.contains(state.point)]
            slow = [
                state
                for state in inside
                if state.slow_since is not None
                and timestamp - state.slow_since >= self.config.stationary_seconds
            ]
            queued = self._queue_members(slow) if zone.kind == "queue" else set()
            if queued:
                self.queue_since.setdefault(zone.id, timestamp)
            else:
                self.queue_since.pop(zone.id, None)
            active = (
                bool(queued) and timestamp - self.queue_since[zone.id] >= self.config.queue_seconds
            )
            if active and zone.id not in self.queue_active:
                self.queue_episodes[zone.id] += 1
                self.queue_active.add(zone.id)
                events.append(
                    TrafficEvent(
                        f"queue:{zone.id}:{self.queue_episodes[zone.id]}",
                        "queue_started",
                        timestamp,
                        zone.id,
                        details={"vehicles": len(queued), "tracks": sorted(queued)},
                    )
                )
            if not active and zone.id in self.queue_active:
                self.queue_active.remove(zone.id)
                events.append(
                    TrafficEvent(
                        f"queue_clear:{zone.id}:{self.queue_episodes[zone.id]}",
                        "queue_cleared",
                        timestamp,
                        zone.id,
                    )
                )
            if active:
                all_queued.update(queued)
            mask = self.zone_masks[zone.id]
            fraction = float(occupancy[mask].mean()) if mask.any() else None
            congestion = (
                "observing"
                if self.observed_total < self.config.stationary_seconds
                else (
                    "congested"
                    if active
                    or (
                        fraction is not None
                        and fraction >= self.config.congestion_occupancy
                        and len(slow) >= self.config.queue_min_vehicles
                    )
                    else "free"
                )
            )
            if fraction is None and not active:
                congestion = "unavailable"
            statuses.append(
                ZoneStatus(
                    zone.id,
                    len(inside),
                    dict(Counter(s.category for s in inside)),
                    fraction,
                    len(slow),
                    len(queued) if active else (0 if zone.kind == "queue" else None),
                    active if zone.kind == "queue" else None,
                    congestion,
                )
            )
        return tuple(statuses), all_queued, events

    def update(
        self, tracks: Sequence[Track], timestamp: float, epoch: int, shape: tuple[int, ...]
    ) -> AnalysisUpdate:
        if (
            isinstance(timestamp, bool)
            or not isinstance(timestamp, (int, float))
            or not math.isfinite(timestamp)
            or timestamp < 0
        ):
            raise ValueError("Source timestamps must be finite and nonnegative")
        if len(shape) < 2 or any(type(n) is not int or n <= 0 for n in shape[:2]):
            raise ValueError("Frame dimensions must be positive integers")
        if type(epoch) is not int or epoch < 1:
            raise ValueError("Tracking epoch must be a positive integer")
        for track in tracks:
            if (
                len(track.bbox) != 4
                or not all(math.isfinite(v) for v in track.bbox)
                or track.bbox[2] <= track.bbox[0]
                or track.bbox[3] <= track.bbox[1]
            ):
                raise ValueError("Track bounding boxes must be finite with positive area")
        if self.last_time is not None and timestamp < self.last_time:
            raise ValueError("Source time rewound; start a new analysis session")
        if self.last_time == timestamp and epoch == self.epoch:
            return AnalysisUpdate(self.snapshot)
        if len({track.id for track in tracks}) != len(tracks):
            raise ValueError("Duplicate track IDs in one observation")
        events, measurements, points = [], [], []
        gap = self.last_time is not None and (
            epoch != self.epoch or timestamp - self.last_time > self.config.max_gap
        )
        if self.last_time is None:
            self._reset_window(timestamp)
        elif gap:
            measurement, anomalies = self._close_window(self.last_time, False)
            measurements.append(measurement)
            events.extend(anomalies)
            events.append(
                TrafficEvent(
                    f"gap:{timestamp:.9f}:{epoch}",
                    "observation_gap",
                    timestamp,
                    details={
                        "seconds": timestamp - self.last_time,
                        "previous_epoch": self.epoch,
                        "epoch": epoch,
                    },
                )
            )
            self.states.clear()
            self.queue_active.clear()
            self.queue_since.clear()
            self._reset_window(timestamp)
        else:
            measurements, events = self._integrate(timestamp)
        self.epoch = epoch
        for identity in list(self.states):
            if timestamp - self.states[identity].last_time > self.config.max_gap:
                del self.states[identity]
        matrix, reason = (
            self.scene.calibration.matrix_for(shape)
            if self.scene.calibration
            else (None, "no verified scene calibration")
        )
        current, speeds, accepted = [], [], []
        self._normalized_boxes = {}
        for track in tracks:
            if track.class_id not in VEHICLES:
                continue
            box = tuple(
                float(np.clip(value / (shape[1] if index % 2 == 0 else shape[0]), 0, 1))
                for index, value in enumerate(track.bbox)
            )
            p = ((box[0] + box[2]) / 2, box[3])
            if any(z.kind == "exclude" and z.contains(p) for z in self.scene.zones):
                self.states.pop(track.id, None)
                continue
            self._normalized_boxes[track.id] = box
            accepted.append(track)
            state = self.states.get(track.id)
            if state is None or state.category != VEHICLES[track.class_id]:
                self.lifecycle += 1
                state = TrackState(
                    f"{epoch}:{track.id}:{self.lifecycle}", VEHICLES[track.class_id], p, timestamp
                )
                self.states[track.id] = state
            else:
                dt = timestamp - state.last_time
                continuous = not gap and state.last_time == self.last_time
                if continuous and dt > 0:
                    if math.dist(state.point, p) / dt <= self.config.stationary_speed:
                        if state.slow_since is None:
                            state.slow_since = state.last_time
                    else:
                        state.slow_since = None
                    x = min(
                        self.config.grid_width - 1, int(state.point[0] * self.config.grid_width)
                    )
                    y = min(
                        self.config.grid_height - 1, int(state.point[1] * self.config.grid_height)
                    )
                    self.heatmap[y, x] += dt
                else:
                    state.slow_since = None
                    state.stalled = False
                    state.history.clear()
                state.point, state.last_time = p, timestamp
            state.history.append((timestamp, p))
            events.extend(self._crossings(state, timestamp))
            speed = self._speed(state, timestamp, matrix, reason)
            speeds.append(speed)
            if timestamp - state.last_saved >= self.config.trajectory_interval:
                points.append(
                    TrajectoryPoint(
                        state.key,
                        timestamp,
                        state.category,
                        *p,
                        speed.mps,
                        speed.unavailable_reason,
                    )
                )
                state.last_saved = timestamp
            current.append(state)
        zones, queued, zone_events = self._zones(accepted, current, timestamp)
        events.extend(zone_events)
        for state in current:
            road = any(
                z.kind in {"road", "lane"} and z.contains(state.point) for z in self.scene.zones
            )
            stalled = (
                road
                and state.key not in queued
                and state.slow_since is not None
                and timestamp - state.slow_since >= self.config.stalled_seconds
            )
            if stalled and not state.stalled:
                state.stall_episode += 1
                events.append(
                    TrafficEvent(
                        f"stall:{state.key}:{state.stall_episode}",
                        "stalled",
                        timestamp,
                        category=state.category,
                        track_key=state.key,
                        details={"stationary_seconds": timestamp - state.slow_since},
                    )
                )
            elif not stalled and state.stalled:
                events.append(
                    TrafficEvent(
                        f"stall_clear:{state.key}:{state.stall_episode}",
                        "stalled_cleared",
                        timestamp,
                        category=state.category,
                        track_key=state.key,
                    )
                )
            state.stalled = stalled
        self.samples += 1
        self.last_time, self.last_zones = timestamp, zones
        self.snapshot = TrafficSnapshot(
            timestamp,
            self._count_rows(self.counts),
            bool(self.scene.lines),
            zones,
            tuple(speeds),
            reason,
            self.baselines.windows,
            self.baselines.windows >= self.config.baseline_min_windows,
        )
        return AnalysisUpdate(
            self.snapshot,
            tuple(events),
            tuple(points),
            tuple(measurements),
            self.heatmap_rows() if measurements else None,
        )

    def heatmap_rows(self) -> tuple[tuple[float, ...], ...]:
        return tuple(tuple(map(float, row)) for row in self.heatmap)

    def finish(self) -> AnalysisUpdate:
        if self.last_time is None:
            return AnalysisUpdate(self.snapshot)
        measurements = []
        if self.samples or self.observed:
            measurement, _ = self._close_window(self.last_time, False)
            measurements.append(measurement)
        return AnalysisUpdate(
            self.snapshot, measurements=tuple(measurements), heatmap=self.heatmap_rows()
        )
