"""Bounded capture buffers, paced recordings, and reconnecting live sources."""

import logging
import math
import os
import queue
import selectors
import struct
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

import cv2
import numpy as np

from roadlens.cameras import build_bridge, list_cameras, select_camera
from roadlens.config import Config, SourceConfig

LOG = logging.getLogger(__name__)
HEADER = struct.Struct("!4sIII")


@dataclass(frozen=True)
class Frame:
    image: np.ndarray
    timestamp: float
    generation: int
    sequence: int


class FrameSlot:
    """One pending frame; a slow live consumer always receives the newest image."""

    def __init__(self):
        self.queue: queue.Queue = queue.Queue(maxsize=1)
        self.dropped = 0

    def put(self, frame, stop: threading.Event, *, latest: bool = True) -> None:
        while not stop.is_set():
            try:
                self.queue.put(frame, timeout=0.05 if not latest else 0)
                return
            except queue.Full:
                if latest:
                    try:
                        self.queue.get_nowait()
                        self.dropped += 1
                    except queue.Empty:
                        pass

    def get(self, timeout: float = 0.1):
        try:
            return self.queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def clear(self):
        while True:
            try:
                self.queue.get_nowait()
            except queue.Empty:
                return


def read_exact(
    stream: BinaryIO, count: int, deadline: float, stop: threading.Event | None = None
) -> bytes:
    data = bytearray()
    with selectors.DefaultSelector() as selector:
        selector.register(stream, selectors.EVENT_READ)
        while len(data) < count:
            if stop is not None and stop.is_set():
                raise InterruptedError("Capture stopped")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Camera stopped delivering frames")
            if not selector.select(min(remaining, 0.1)):
                continue
            chunk = os.read(stream.fileno(), count - len(data))
            if not chunk:
                raise EOFError("Native camera process exited")
            data.extend(chunk)
    return bytes(data)


class NativeCapture:
    def __init__(self, device_id: str, config: Config, stop: threading.Event | None = None):
        self.timeout = config.read_timeout
        self.first_frame = True
        self.stop = stop
        self.process = subprocess.Popen(
            [
                str(build_bridge()),
                "capture",
                device_id,
                str(config.width),
                str(config.height),
                str(config.capture_fps),
            ],
            stdout=subprocess.PIPE,
            stderr=None,
            bufsize=0,
        )

    def read(self):
        deadline = time.monotonic() + (max(30, self.timeout) if self.first_frame else self.timeout)
        try:
            magic, width, height, size = HEADER.unpack(
                read_exact(self.process.stdout, HEADER.size, deadline, self.stop)
            )
        except EOFError:
            if self.process.wait(timeout=2) == 3:
                raise PermissionError(
                    "Camera permission denied; enable it in System Settings"
                ) from None
            raise
        if (
            magic != b"RL01"
            or not 0 < width <= 3840
            or not 0 < height <= 2160
            or size != width * height * 4
        ):
            raise ValueError("Invalid native camera frame header")
        raw = read_exact(self.process.stdout, size, deadline, self.stop)
        self.first_frame = False
        return cv2.cvtColor(
            np.frombuffer(raw, np.uint8).reshape(height, width, 4), cv2.COLOR_BGRA2BGR
        )

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2)
        self.process.stdout.close()


class OpenCVCapture:
    def __init__(self, source: SourceConfig, config: Config):
        self.is_file = source.kind == "video"
        if self.is_file:
            path = Path(source.value).expanduser()
            if not path.is_file():
                raise FileNotFoundError(f"Video does not exist: {path}")
            self.capture = cv2.VideoCapture(str(path))
        else:
            # Explicit fallback only: OpenCV indices do not identify Continuity devices.
            self.capture = cv2.VideoCapture(int(source.value), cv2.CAP_AVFOUNDATION)
        if not self.capture.isOpened():
            self.capture.release()
            raise RuntimeError(f"Could not open {source.kind} input {source.value!r}")
        if not self.is_file:
            self.capture.set(cv2.CAP_PROP_FRAME_WIDTH, config.width)
            self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, config.height)
            self.capture.set(cv2.CAP_PROP_FPS, config.capture_fps)
            self.capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        fps = self.capture.get(cv2.CAP_PROP_FPS)
        self.fps = fps if math.isfinite(fps) and fps > 0 else config.capture_fps
        self.index = 0

    def read(self):
        ok, frame = self.capture.read()
        if not ok:
            raise EOFError("End of video" if self.is_file else "Camera read failed")
        self.index += 1
        return frame

    def close(self):
        self.capture.release()


class CaptureWorker(threading.Thread):
    def __init__(self, source: SourceConfig, config: Config):
        super().__init__(name=f"capture-{source.name}", daemon=True)
        self.source, self.config = source, config
        self.frames = FrameSlot()
        self.stop_event = threading.Event()
        self.done = threading.Event()
        self.state = "starting"
        self.error: Exception | None = None
        self.generation = 0
        self.captured = 0
        self.capture_fps = 0.0
        self.reconnects = 0
        self.last_error: str | None = None
        self.device_id: str | None = None

    def run(self):
        try:
            self._run()
        except Exception as error:
            self.error, self.state = error, "failed"
            LOG.exception("[%s] capture failed", self.source.name)
        finally:
            self.done.set()

    def _run(self):
        while not self.stop_event.is_set():
            capture = None
            try:
                self.state = "connecting"
                if self.source.kind == "camera":
                    if self.device_id is None:
                        self.device_id = select_camera(self.source.value, list_cameras())["id"]
                    if self.stop_event.is_set():
                        return
                    # Keep the resolved ID on reconnect; never substitute another camera.
                    capture = NativeCapture(self.device_id, self.config, self.stop_event)
                else:
                    capture = OpenCVCapture(self.source, self.config)
                self.generation += 1
                sequence = 0
                started = last_report = time.monotonic()
                count = 0
                while not self.stop_event.is_set():
                    if self.source.kind == "video" and self.source.realtime:
                        if self.stop_event.wait(
                            max(0, started + sequence / capture.fps - time.monotonic())
                        ):
                            return
                    image = capture.read()
                    now = time.monotonic()
                    if sequence == 0:
                        last_report = now
                    timestamp = sequence / capture.fps if self.source.kind == "video" else now
                    self.frames.put(
                        Frame(image, timestamp, self.generation, sequence),
                        self.stop_event,
                        latest=self.source.kind != "video" or self.source.realtime,
                    )
                    self.state = "running"
                    self.last_error = None
                    self.captured += 1
                    sequence += 1
                    count += int(sequence > 1)
                    if now - last_report >= 1:
                        self.capture_fps = count / (now - last_report)
                        count, last_report = 0, now
            except Exception as error:
                if self.stop_event.is_set():
                    return
                self.last_error = str(error)
                if isinstance(error, PermissionError):
                    raise
                if self.source.kind == "video":
                    if isinstance(error, EOFError):
                        self.state = "eof"
                        return
                    raise
                self.state = "reconnecting"
                self.frames.clear()
                self.reconnects += 1
                LOG.warning(
                    "[%s] %s; reconnecting in %.1fs",
                    self.source.name,
                    error,
                    self.config.reconnect_delay,
                )
            finally:
                if capture is not None:
                    capture.close()
            if self.stop_event.wait(self.config.reconnect_delay):
                return

    def stop(self):
        self.stop_event.set()
