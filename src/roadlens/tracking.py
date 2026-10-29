"""Class-aware ByteTrack state and short, bounded image-space motion histories."""

import math
from collections import deque
from dataclasses import dataclass

from supervision import ByteTrack, Detections

from roadlens.config import Config
from roadlens.detection import VEHICLES


@dataclass(frozen=True)
class Track:
    id: int
    class_id: int
    confidence: float
    bbox: tuple[float, float, float, float]
    direction: tuple[float, float]
    velocity: tuple[float, float]
    trail: tuple[tuple[int, int], ...]


class VehicleTracker:
    def __init__(self, config: Config):
        self.config = config
        self.epoch = 0
        self.reset()

    def reset(self):
        self.epoch += 1
        self.trackers = {
            class_id: ByteTrack(
                track_activation_threshold=self.config.track_activation,
                lost_track_buffer=self.config.track_buffer,
                frame_rate=30,
            )
            for class_id in VEHICLES
        }
        self.identities: dict[tuple[int, int], int] = {}
        self.history: dict[int, deque] = {}
        self.next_id = 1
        self.last_timestamp: float | None = None

    def update(self, detections: Detections, timestamp: float) -> list[Track]:
        if self.last_timestamp is not None and (
            timestamp <= self.last_timestamp
            or timestamp - self.last_timestamp > self.config.max_gap
        ):
            self.reset()
        self.last_timestamp = timestamp
        tracks = []
        active_keys = set()
        for class_id, tracker in self.trackers.items():
            selected = (
                detections[detections.class_id == class_id]
                if len(detections)
                else Detections.empty()
            )
            tracked = tracker.update_with_detections(selected)
            alive = tracker.tracked_tracks + tracker.lost_tracks
            active_keys.update((class_id, t.external_track_id) for t in alive)
            for box, confidence, local_id in zip(
                tracked.xyxy, tracked.confidence, tracked.tracker_id, strict=True
            ):
                key = (class_id, int(local_id))
                if key not in self.identities:
                    self.identities[key] = self.next_id
                    self.next_id += 1
                identity = self.identities[key]
                center = ((float(box[0]) + float(box[2])) / 2, (float(box[1]) + float(box[3])) / 2)
                history = self.history.setdefault(identity, deque(maxlen=6))
                while history and timestamp - history[0][0] > self.config.max_gap:
                    history.popleft()
                history.append((timestamp, center))
                dt = timestamp - history[0][0]
                dx, dy = center[0] - history[0][1][0], center[1] - history[0][1][1]
                distance = math.hypot(dx, dy)
                direction = (dx / distance, dy / distance) if distance >= 2 else (0.0, 0.0)
                velocity = (dx / dt, dy / dt) if dt > 0 and distance >= 2 else (0.0, 0.0)
                # Low-score matches rescue identities but do not pass the display threshold.
                if confidence >= self.config.confidence:
                    tracks.append(
                        Track(
                            identity,
                            class_id,
                            float(confidence),
                            tuple(map(float, box)),
                            direction,
                            velocity,
                            tuple((round(c[0]), round(c[1])) for _, c in history),
                        )
                    )
        expired = set(self.identities) - active_keys
        for key in expired:
            self.history.pop(self.identities.pop(key), None)
        return tracks
