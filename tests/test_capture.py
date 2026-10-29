import os
import threading
import time

import pytest

from roadlens.cameras import select_camera
from roadlens.capture import CaptureWorker, FrameSlot, OpenCVCapture, read_exact
from roadlens.config import Config, SourceConfig

DEVICES = [
    {"id": "mac-id", "name": "FaceTime HD Camera", "type": "BuiltInWideAngleCamera"},
    {"id": "phone-id", "name": "Alice iPhone", "type": "ContinuityCamera"},
]


def test_device_selection_uses_id_not_index():
    assert select_camera("phone-id", DEVICES)["name"] == "Alice iPhone"
    assert select_camera("iphone", DEVICES)["id"] == "phone-id"
    assert select_camera("default", DEVICES)["id"] == "mac-id"
    with pytest.raises(RuntimeError, match="ambiguous"):
        select_camera("camera", [{**d, "name": "camera"} for d in DEVICES])
    with pytest.raises(RuntimeError, match="unavailable"):
        select_camera("iphone", DEVICES[:1])


def test_live_slot_overwrites_and_offline_slot_stops():
    slot = FrameSlot()
    stop = threading.Event()
    for i in range(20):
        slot.put(i, stop)
    assert slot.get() == 19
    assert slot.dropped == 19
    slot.put(1, stop)
    thread = threading.Thread(target=slot.put, args=(2, stop), kwargs={"latest": False})
    thread.start()
    assert slot.get() == 1
    thread.join(timeout=1)
    assert not thread.is_alive()
    assert slot.get() == 2
    slot.put(3, stop)
    thread = threading.Thread(target=slot.put, args=(4, stop), kwargs={"latest": False})
    thread.start()
    stop.set()
    thread.join(timeout=1)
    assert not thread.is_alive()


def test_native_pipe_fragmentation_eof_and_timeout():
    read_fd, write_fd = os.pipe()
    with os.fdopen(read_fd, "rb", buffering=0) as stream:

        def write_fragments():
            os.write(write_fd, b"a")
            time.sleep(0.01)
            os.write(write_fd, b"bc")

        thread = threading.Thread(target=write_fragments)
        thread.start()
        assert read_exact(stream, 3, time.monotonic() + 1) == b"abc"
        thread.join(timeout=1)
        with pytest.raises(TimeoutError):
            read_exact(stream, 1, time.monotonic() + 0.02)
        os.close(write_fd)
        with pytest.raises(EOFError):
            read_exact(stream, 1, time.monotonic() + 1)


def test_pipe_read_can_be_cancelled():
    read_fd, write_fd = os.pipe()
    stop = threading.Event()
    stop.set()
    try:
        with os.fdopen(read_fd, "rb", buffering=0) as stream:
            with pytest.raises(InterruptedError):
                read_exact(stream, 1, time.monotonic() + 30, stop)
    finally:
        os.close(write_fd)


def test_actual_video_capture_and_eof(vehicle_video):
    source = SourceConfig("clip", "video", str(vehicle_video), realtime=False)
    capture = OpenCVCapture(source, Config())
    try:
        for _ in range(12):
            assert capture.read().ndim == 3
        with pytest.raises(EOFError):
            capture.read()
    finally:
        capture.close()


def test_offline_capture_preserves_frames(vehicle_video):
    worker = CaptureWorker(SourceConfig("clip", "video", str(vehicle_video), False), Config())
    worker.start()
    frames = []
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            frame = worker.frames.get(timeout=0.05)
            if frame is not None:
                frames.append(frame)
            elif worker.done.is_set():
                break
    finally:
        worker.stop()
        worker.join(timeout=2)
    assert len(frames) == 12
    assert worker.frames.dropped == 0
    assert worker.state == "eof"
    assert [f.sequence for f in frames] == list(range(12))
    probe = OpenCVCapture(worker.source, Config())
    try:
        assert frames[-1].timestamp == pytest.approx(11 / probe.fps)
    finally:
        probe.close()


def test_live_reconnect_and_shutdown_on_missing_device(monkeypatch):
    # Fault injection exercises the real reconnect loop; no mock camera stream.
    monkeypatch.setattr("roadlens.capture.list_cameras", lambda: [])
    worker = CaptureWorker(
        SourceConfig("missing", "camera", "iphone"), Config(reconnect_delay=0.01)
    )
    worker.start()
    deadline = time.monotonic() + 1
    while worker.reconnects < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    worker.stop()
    worker.join(timeout=1)
    assert worker.reconnects >= 2
    assert worker.done.is_set()
    assert worker.frames.get(timeout=0) is None


def test_stop_during_discovery_never_opens_a_camera(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    opened = []

    def discover():
        entered.set()
        assert release.wait(2)
        return DEVICES

    monkeypatch.setattr("roadlens.capture.list_cameras", discover)
    monkeypatch.setattr("roadlens.capture.NativeCapture", lambda *a: opened.append(a))
    worker = CaptureWorker(SourceConfig("cancelled", "camera", "phone-id"), Config())
    worker.start()
    assert entered.wait(2)
    worker.stop()
    release.set()
    worker.join(timeout=2)
    assert worker.done.is_set() and not worker.is_alive()
    assert not opened
