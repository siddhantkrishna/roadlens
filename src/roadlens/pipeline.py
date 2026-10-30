"""Independent capture/inference lifecycle per source, with bounded preview output."""

import hashlib
import logging
import threading
import time
from dataclasses import dataclass

import cv2
import numpy as np

from roadlens.capture import CaptureWorker, FrameSlot
from roadlens.config import Config, SourceConfig
from roadlens.detection import VEHICLES, VehicleDetector
from roadlens.drawing import OVERLAY, fit_text
from roadlens.tracking import Track, VehicleTracker
from roadlens.traffic.models import TrafficSnapshot
from roadlens.traffic.service import TrafficService

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class Result:
    image: np.ndarray
    tracks: tuple[Track, ...]
    epoch: int
    sequence: int
    inference_ms: float
    latency_ms: float
    analysis: TrafficSnapshot | None = None
    raw_image: np.ndarray | None = None


def annotate(
    image: np.ndarray,
    tracks: list[Track],
    source: str,
    epoch: int,
    diagnostic: str,
    *,
    compact=False,
) -> np.ndarray:
    canvas = image.copy()
    for track in tracks:
        x1, y1, x2, y2 = map(round, track.bbox)
        color = (
            OVERLAY["box"]
            if compact
            else ((track.id * 67) % 180 + 75, (track.id * 37) % 180 + 75, 70)
        )
        cv2.rectangle(canvas, (x1, y1), (x2, y2), color, 2)
        label = fit_text(
            (
                f"{VEHICLES[track.class_id].title()} {track.id}"
                if compact
                else f"{VEHICLES[track.class_id].title()} #{track.id} | {track.confidence:.2f}"
            ),
            canvas.shape[1] - 8,
        )
        (label_width, label_height), baseline = cv2.getTextSize(
            label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1
        )
        label_x = max(0, min(x1, canvas.shape[1] - label_width - 4))
        label_y = (
            y1 - 7 if y1 - label_height - 12 >= (0 if compact else 46) else y2 + label_height + 8
        )
        label_y = min(
            canvas.shape[0] - baseline - 3, max(label_height + 5 if compact else 62, label_y)
        )
        cv2.rectangle(
            canvas,
            (label_x, label_y - label_height - 4),
            (label_x + label_width + 4, label_y + baseline + 2),
            OVERLAY["plate"] if compact else (20, 20, 20),
            -1,
        )
        cv2.putText(
            canvas,
            label,
            (label_x + 2, label_y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            OVERLAY["ink"] if compact else (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
        if len(track.trail) > 1:
            cv2.polylines(canvas, [np.asarray(track.trail, np.int32)], False, color, 2)
        if track.direction != (0.0, 0.0):
            center = ((x1 + x2) // 2, (y1 + y2) // 2)
            end = (
                round(center[0] + track.direction[0] * 45),
                round(center[1] + track.direction[1] * 45),
            )
            cv2.arrowedLine(canvas, center, end, color, 2, tipLength=0.3)
    if compact:
        return canvas
    cv2.rectangle(canvas, (0, 0), (canvas.shape[1], 46), (20, 20, 20), -1)
    cv2.putText(
        canvas,
        fit_text(f"ROADLENS | {source} | epoch {epoch}", canvas.shape[1] - 16),
        (8, 18),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.5,
        (255, 255, 255),
        1,
        cv2.LINE_AA,
    )
    cv2.putText(
        canvas,
        fit_text(diagnostic, canvas.shape[1] - 16, 0.42),
        (8, 38),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.42,
        (210, 230, 230),
        1,
        cv2.LINE_AA,
    )
    return canvas


class Pipeline(threading.Thread):
    def __init__(self, source: SourceConfig, config: Config, max_frames: int | None = None):
        super().__init__(name=f"vision-{source.name}", daemon=True)
        self.source, self.config, self.max_frames = source, config, max_frames
        self.capture = CaptureWorker(source, config)
        self.results = FrameSlot()
        self.stop_event = self.capture.stop_event
        self.done = threading.Event()
        self.error: Exception | None = None
        self.paused = threading.Event()
        self.resume_generation = 0
        self.desktop_preview = False
        self.processed = 0
        self.inference_fps = 0.0
        self.traffic: TrafficService | None = None

    def run(self):
        try:
            self._run()
        except Exception as error:
            self.error = error
            LOG.exception("[%s] pipeline failed", self.source.name)
        finally:
            self.capture.stop()
            if self.capture.ident is not None:
                # Native discovery/build calls have their own timeouts; keep shutdown off the UI.
                self.capture.join(
                    timeout=None if self.source.kind == "camera" else self.config.read_timeout + 3
                )
                if self.capture.is_alive():
                    self.error = self.error or RuntimeError(
                        "Capture driver did not stop within timeout"
                    )
                    LOG.error("[%s] %s", self.source.name, self.error)
            if self.traffic is not None:
                try:
                    status = (
                        "failed"
                        if self.error
                        else ("completed" if self.capture.state == "eof" else "stopped")
                    )
                    self.traffic.close(status)
                except Exception as error:
                    self.error = error
                    LOG.exception("[%s] could not finalize analytics", self.source.name)
            self.done.set()

    def _run(self):
        detector = VehicleDetector(
            self.config.model,
            self.config.input_size,
            self.config.detection_floor,
            self.config.nms_iou,
        )
        tracker = VehicleTracker(self.config)
        generation = None
        resume_generation = 0
        frame_shape = None
        last_report = None
        count = 0
        self.capture.start()
        while not self.stop_event.is_set():
            while self.paused.is_set() and not self.stop_event.wait(0.05):
                pass
            if self.stop_event.is_set():
                return
            if resume_generation != self.resume_generation:
                tracker.reset()
                resume_generation = self.resume_generation
            frame = self.capture.frames.get()
            if frame is None:
                if self.capture.done.is_set():
                    if self.capture.error is not None:
                        raise self.capture.error
                    return
                continue
            started = time.monotonic()
            if last_report is None:
                last_report = started
            if generation is not None and (
                generation != frame.generation or frame_shape != frame.image.shape
            ):
                tracker.reset()
            generation = frame.generation
            frame_shape = frame.image.shape
            detections = detector.detect(frame.image)
            inference_ms = (time.monotonic() - started) * 1000
            tracks = tracker.update(detections, frame.timestamp)
            analysis = None
            if self.source.scene or self.config.analytics.database:
                if self.traffic is None:
                    with open(self.config.model, "rb") as model_stream:
                        model_hash = hashlib.file_digest(model_stream, "sha256").hexdigest()
                    self.traffic = TrafficService(
                        self.source,
                        self.config.analytics,
                        {
                            "model_sha256": model_hash,
                            "input_size": self.config.input_size,
                            "confidence": self.config.confidence,
                            "detection_floor": self.config.detection_floor,
                            "nms_iou": self.config.nms_iou,
                            "track_activation": self.config.track_activation,
                            "track_buffer": self.config.track_buffer,
                            "max_gap": self.config.max_gap,
                            "inference_fps": self.config.inference_fps,
                            "capture_fps": self.config.capture_fps,
                            "requested_size": [self.config.width, self.config.height],
                            "sampling": "all_frames"
                            if self.source.kind == "video" and not self.source.realtime
                            else "latest_frame",
                        },
                        self.capture.device_id,
                    )
                    LOG.info(
                        "[%s] analysis session %s",
                        self.source.name,
                        self.traffic.session_id or "in-memory",
                    )
                analysis = self.traffic.update(
                    tracks, frame.timestamp, tracker.epoch, frame.image.shape
                )
            latency_ms = (
                (time.monotonic() - frame.timestamp) * 1000 if self.source.kind != "video" else 0.0
            )
            self.processed += 1
            count += 1
            now = time.monotonic()
            if now - last_report >= self.config.diagnostics_interval:
                self.inference_fps = count / (now - last_report)
                LOG.info(
                    "[%s] state=%s capture=%.1ffps processed=%.1ffps infer=%.1fms "
                    "latency=%.1fms dropped=%d reconnects=%d tracks=%d",
                    self.source.name,
                    self.capture.state,
                    self.capture.capture_fps,
                    self.inference_fps,
                    inference_ms,
                    latency_ms,
                    self.capture.frames.dropped,
                    self.capture.reconnects,
                    len(tracks),
                )
                count, last_report = 0, now
            capture_rate = f"{self.capture.capture_fps:.1f}" if self.capture.capture_fps else "--"
            output_rate = f"{self.inference_fps:.1f}" if self.inference_fps else "--"
            diagnostic = (
                f"cap {capture_rate} fps | infer {inference_ms:.0f} ms | "
                f"out {output_rate} fps | "
                + (
                    "video time | "
                    if self.source.kind == "video"
                    else f"age {latency_ms:.0f} ms | "
                )
                + f"drop {self.capture.frames.dropped}"
            )
            image = annotate(
                frame.image,
                tracks,
                self.source.name,
                tracker.epoch,
                diagnostic,
                compact=self.desktop_preview,
            )
            if analysis is not None:
                image = self.traffic.overlay(image, analysis)
            self.results.put(
                Result(
                    image,
                    tuple(tracks),
                    tracker.epoch,
                    frame.sequence,
                    inference_ms,
                    latency_ms,
                    analysis,
                    frame.image if self.desktop_preview else None,
                ),
                self.stop_event,
            )
            if self.max_frames is not None and self.processed >= self.max_frames:
                return
            offline = self.source.kind == "video" and not self.source.realtime
            if not offline:
                self.stop_event.wait(
                    max(0, 1 / self.config.inference_fps - (time.monotonic() - started))
                )

    def stop(self):
        self.capture.stop()

    def set_paused(self, paused):
        if paused:
            self.paused.set()
        else:
            if self.paused.is_set() and (self.source.kind != "video" or self.source.realtime):
                self.resume_generation += 1
                self.capture.frames.clear()
            self.paused.clear()
