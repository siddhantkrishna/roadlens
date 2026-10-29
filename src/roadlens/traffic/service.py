"""Per-camera analytics and persistence lifecycle; data stays on this machine."""

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

import cv2
import numpy as np

from roadlens.config import SourceConfig
from roadlens.drawing import fit_text
from roadlens.tracking import Track
from roadlens.traffic.analyzer import TrafficAnalyzer
from roadlens.traffic.models import AnalyticsConfig, TrafficSnapshot
from roadlens.traffic.scene import Scene
from roadlens.traffic.store import TrafficStore, encode


class TrafficService:
    def __init__(
        self,
        source: SourceConfig,
        config: AnalyticsConfig,
        context: dict,
        device_id: str | None = None,
    ):
        self.source = source
        self.scene = Scene.load(Path(source.scene)) if source.scene else Scene()
        self.analyzer = TrafficAnalyzer(self.scene, config)
        self.origin: float | None = 0.0 if source.kind == "video" else None
        self.store: TrafficStore | None = None
        self.session_id: str | None = None
        self.failed_write = False
        if config.database is not None:
            self.store = TrafficStore(Path(config.database))
            try:
                parameters = asdict(config)
                parameters.pop("database")
                parameters.pop("retention_days")
                clock = "video_seconds" if source.kind == "video" else "session_monotonic_seconds"
                key = hashlib.sha256(
                    encode(
                        {
                            "scene": asdict(self.scene),
                            "analytics_version": 1,
                            "parameters": parameters,
                            "context": context,
                            "clock": clock,
                        }
                    ).encode()
                ).hexdigest()
                identity = device_id or source.value
                fingerprint = hashlib.sha256(f"{source.kind}:{identity}".encode()).hexdigest()
                camera_id = source.camera_id or source.name
                settings = {
                    "source_kind": source.kind,
                    "overlap_group": self.scene.overlap_group,
                    "parameters": parameters,
                    "vision": context,
                    "device_fingerprint": fingerprint if source.kind != "video" else None,
                }
                self.store.prune(config.retention_days)
                for values in self.store.baseline_history(
                    camera_id, key, config.baseline_max_windows
                ):
                    self.analyzer.baselines.observe(values, detect=False)
                self.session_id = self.store.start_session(
                    camera_id, source.name, settings, asdict(self.scene), key, clock, fingerprint
                )
            except Exception:
                self.store.close()
                raise

    def update(
        self, tracks: list[Track], timestamp: float, epoch: int, shape: tuple[int, ...]
    ) -> TrafficSnapshot:
        if self.origin is None:
            self.origin = timestamp
        update = self.analyzer.update(tracks, timestamp - self.origin, epoch, shape)
        if self.store is not None:
            try:
                self.store.write(self.session_id, update)
            except Exception:
                self.failed_write = True
                raise
        return update.snapshot

    def close(self, status: str) -> None:
        if self.store is not None:
            try:
                if not self.failed_write:
                    self.store.write(self.session_id, self.analyzer.finish())
                self.store.finish_session(self.session_id, status)
            finally:
                self.store.close()
                self.store = None

    def overlay(self, image: np.ndarray, snapshot: TrafficSnapshot) -> np.ndarray:
        height, width = image.shape[:2]
        for zone in self.scene.zones:
            polygon = np.rint(np.asarray(zone.polygon) * (width - 1, height - 1)).astype(np.int32)
            color = (100, 100, 100) if zone.kind == "exclude" else (100, 240, 100)
            cv2.polylines(image, [polygon], True, color, 2)
            cv2.putText(
                image,
                fit_text(zone.id, width - max(0, int(polygon[0][0])) - 8),
                (max(0, int(polygon[0][0])), min(height - 8, max(90, int(polygon[0][1]) - 8))),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                color,
                1,
                cv2.LINE_AA,
            )
        for line in self.scene.lines:
            a = tuple(
                round(n * size) for n, size in zip(line.start, (width - 1, height - 1), strict=True)
            )
            b = tuple(
                round(n * size) for n, size in zip(line.end, (width - 1, height - 1), strict=True)
            )
            cv2.line(image, a, b, (0, 230, 255), 2)
            cv2.putText(
                image,
                fit_text(
                    f"{line.id}: {line.forward} / {line.reverse}", width - max(0, a[0]) - 8, 0.45
                ),
                (max(0, a[0]), max(65, a[1] - 8)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                (0, 230, 255),
                1,
                cv2.LINE_AA,
            )
        total = sum(count.count for count in snapshot.counts)
        counting = (
            f"crossing events {total}"
            if snapshot.counting_available
            else "counting unavailable: no lines"
        )
        available_speeds = [speed.mps for speed in snapshot.speeds if speed.mps is not None]
        if available_speeds:
            speed = f"speed mean {sum(available_speeds) / len(available_speeds):.1f} m/s"
        else:
            reason = snapshot.speed_unavailable_reason or "insufficient calibrated observations"
            speed = "speed unavailable: " + reason
        baseline = (
            "baseline ready"
            if snapshot.baseline_ready
            else (
                f"baseline warming {snapshot.baseline_windows}/"
                f"{self.analyzer.config.baseline_min_windows}"
            )
        )
        summaries = [counting + " | " + speed, baseline]
        summaries.extend(
            f"{zone.zone_id}: {zone.vehicles} vehicles | occupancy "
            f"{zone.image_occupancy:.0%} | {zone.congestion}"
            if zone.image_occupancy is not None
            else f"{zone.zone_id}: occupancy unavailable"
            for zone in snapshot.zones
        )
        for index, summary in enumerate(summaries[:4]):
            y = max(80, height - 42 - 19 * (len(summaries[:4]) - index - 1))
            cv2.rectangle(image, (0, y - 15), (width, y + 3), (20, 20, 20), -1)
            cv2.putText(
                image,
                fit_text(summary, width - 16, 0.42),
                (8, y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.42,
                (255, 255, 255),
                1,
                cv2.LINE_AA,
            )
        return image


def heatmap_pixels(values) -> tuple[np.ndarray, float]:
    grid = np.asarray(values, np.float64)
    if (
        grid.ndim != 2
        or not grid.size
        or grid.shape[0] > 144
        or grid.shape[1] > 256
        or not np.isfinite(grid).all()
        or (grid < 0).any()
    ):
        raise ValueError("Heatmap must be a finite, nonnegative grid of at most 256x144 cells")
    maximum = float(grid.max())
    pixels = (grid / maximum * 255).astype(np.uint8) if maximum else np.zeros_like(grid, np.uint8)
    return cv2.applyColorMap(pixels, cv2.COLORMAP_INFERNO), maximum


def render_heatmap(store: TrafficStore, session_id: str, output: Path) -> None:
    rows = store.rows("heatmaps", session_id=session_id)
    if not rows:
        raise ValueError("No observed heatmap for that session")
    pixels, maximum = heatmap_pixels(json.loads(rows[0]["grid_json"]))
    image = cv2.resize(pixels, (960, 540), interpolation=cv2.INTER_NEAREST)
    cv2.rectangle(image, (0, 0), (960, 44), (20, 20, 20), -1)
    cv2.putText(
        image,
        f"Observed vehicle-seconds/cell | maximum {maximum:.3f} | session {session_id[:12]}",
        (8, 26),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (255, 255, 255),
        1,
        cv2.LINE_AA,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    ok, encoded = cv2.imencode(".png", image)
    if not ok:
        raise OSError(f"Failed to encode heatmap: {output}")
    with output.open("xb") as stream:
        stream.write(encoded.tobytes())
