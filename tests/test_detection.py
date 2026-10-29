import hashlib

import cv2
import numpy as np
import pytest

from roadlens.detection import MODEL_SHA256, VehicleDetector, decode, download_model, letterbox


def test_letterbox_round_trip():
    frame = np.zeros((200, 400, 3), np.uint8)
    canvas, scale, left, top = letterbox(frame, 640)
    assert canvas.shape == (640, 640, 3)
    assert (scale, left, top) == (1.6, 0, 160)
    output = np.zeros((1, 84, 5), np.float32)
    output[0, :4, :] = np.array([320, 320, 320, 160])[:, None]
    output[0, 6, 0:2] = [0.9, 0.8]  # duplicate cars: keep one
    output[0, 9, 2] = 0.85  # overlapping bus survives class-aware NMS
    output[0, 4, 3] = 0.99  # person excluded
    output[0, 6, 4] = 0.05  # low confidence excluded
    result = decode(output, frame.shape, scale, left, top, 0.1, 0.45)
    assert len(result) == 2
    assert set(result.class_id) == {2, 5}
    np.testing.assert_allclose(result.xyxy[0], [100, 50, 300, 150])


def test_invalid_and_empty_output():
    with pytest.raises(ValueError, match="Expected"):
        decode(np.zeros((1, 6, 20)), (100, 100, 3), 1, 0, 0, 0.1, 0.45)
    output = np.zeros((1, 84, 4), np.float32)
    output[0, 6] = 0.9
    output[0, :4] = np.nan
    assert not len(decode(output, (100, 100, 3), 1, 0, 0, 0.1, 0.45))


def test_model_download_does_not_overwrite_custom_file(tmp_path):
    path = tmp_path / "custom.onnx"
    path.write_bytes(b"custom")
    with pytest.raises(ValueError, match="different checksum"):
        download_model(path)
    assert path.read_bytes() == b"custom"


def test_bad_download_is_discarded(monkeypatch, tmp_path):
    class BadResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def raise_for_status(self):
            pass

        def iter_content(self, size):
            yield b"corrupt download"

    monkeypatch.setattr("roadlens.detection.requests.get", lambda *a, **kw: BadResponse())
    path = tmp_path / "model.onnx"
    with pytest.raises(ValueError, match="checksum"):
        download_model(path)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.model
def test_real_bus_detection(model_path, bus_image):
    assert hashlib.sha256(open(model_path, "rb").read()).hexdigest() == MODEL_SHA256
    detector = VehicleDetector(model_path)
    detections = detector.detect(bus_image)
    buses = detections[detections.class_id == 5]
    assert len(buses) >= 1
    assert max(buses.confidence) > 0.6
    assert len(detector.detect(np.zeros((480, 640, 3), np.uint8))) == 0
    assert cv2.__version__.startswith("4.")
