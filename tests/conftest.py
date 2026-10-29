import os
import shutil
from pathlib import Path

import cv2
import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session", autouse=True)
def cpu_threads():
    cv2.setNumThreads(2)


@pytest.fixture(scope="session")
def model_path():
    path = Path(os.environ.get("ROADLENS_TEST_MODEL", ROOT / "models/yolov8n.onnx"))
    if not path.is_file():
        pytest.skip("Run roadlens fetch-model for real-model integration tests")
    return str(path)


@pytest.fixture(scope="session")
def bus_image():
    image = cv2.imread(str(ROOT / "assets/bus.jpg"))
    assert image is not None, "Real-image integration fixture missing"
    return image


@pytest.fixture
def vehicle_video(tmp_path):
    path = tmp_path / "traffic.avi"
    shutil.copyfile(ROOT / "assets/traffic.avi", path)
    return path
