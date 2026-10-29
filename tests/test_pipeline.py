import os
import platform
import time

import cv2
import pytest

from roadlens.capture import NativeCapture
from roadlens.cli import main
from roadlens.config import Config, SourceConfig
from roadlens.pipeline import Pipeline
from roadlens.preview import run_preview


@pytest.mark.model
def test_real_video_independent_pipelines(model_path, vehicle_video, tmp_path):
    config = Config(model=model_path)
    pipelines = [
        Pipeline(SourceConfig(name, "video", str(vehicle_video), False), config)
        for name in ("first", "second")
    ]
    assert run_preview(pipelines, headless=True, output_dir=tmp_path, duration=30) == 0
    for pipeline in pipelines:
        assert pipeline.error is None
        assert pipeline.processed == 12
        assert pipeline.capture.frames.dropped == 0
        assert pipeline.done.is_set()
        assert not pipeline.capture.is_alive()
    assert cv2.imread(str(tmp_path / "source-1.jpg")) is not None
    assert cv2.imread(str(tmp_path / "source-2.jpg")) is not None


@pytest.mark.model
def test_real_video_vehicle_tracks_and_motion(model_path, vehicle_video):
    pipeline = Pipeline(
        SourceConfig("traffic", "video", str(vehicle_video), False), Config(model=model_path)
    )
    pipeline.start()
    observations = []
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            result = pipeline.results.get(timeout=0.05)
            if result is not None:
                observations.extend(result.tracks)
            elif pipeline.done.is_set():
                break
    finally:
        pipeline.stop()
        pipeline.join(timeout=5)
    assert pipeline.error is None
    cars = [track for track in observations if track.class_id == 2]
    assert len(cars) >= 3, "The actual traffic clip must produce tracked cars"
    assert len({track.id for track in cars}) < len(cars)
    assert any(track.direction != (0.0, 0.0) for track in cars)


@pytest.mark.model
def test_failed_source_does_not_stop_other_source(model_path, vehicle_video, tmp_path):
    config = Config(model=model_path)
    good = Pipeline(SourceConfig("good", "video", str(vehicle_video), False), config, max_frames=4)
    bad = Pipeline(SourceConfig("bad", "video", str(tmp_path / "missing.mp4")), config)
    assert run_preview([good, bad], headless=True, duration=20) == 1
    assert good.processed == 4
    assert good.error is None
    assert isinstance(bad.error, FileNotFoundError)


def test_cli_errors_are_nonzero(tmp_path):
    assert main(["run", "--model", str(tmp_path / "missing.onnx"), "--headless"]) == 1


@pytest.mark.hardware
@pytest.mark.skipif(
    platform.system() != "Darwin" or not os.environ.get("ROADLENS_TEST_CAMERA"),
    reason="Set ROADLENS_TEST_CAMERA to an AVFoundation device ID for real capture",
)
def test_real_mac_camera():
    capture = NativeCapture(os.environ["ROADLENS_TEST_CAMERA"], Config(read_timeout=30))
    started = time.monotonic()
    try:
        image = capture.read()
        assert image.ndim == 3 and image.shape[2] == 3
        assert image.dtype.name == "uint8"
        assert time.monotonic() - started < 30
    finally:
        capture.close()
