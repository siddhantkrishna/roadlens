"""YOLOv8 nano ONNX inference using OpenCV's CPU backend (no PyTorch)."""

import hashlib
import tempfile
from pathlib import Path

import cv2
import numpy as np
import requests
from supervision import Detections

VEHICLES = {1: "bicycle", 2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}
MODEL_URL = (
    "https://huggingface.co/webml/yolov8n/resolve/"
    "85bc8d7ab30d4065a41909d756c42819b67b4388/onnx/yolov8n.onnx"
)
MODEL_SHA256 = "190ba5f1e61411a001683e349d6b2cdb0804c0dc67a5e34cd8ff6fd00ee54b4d"


def download_model(path: Path) -> Path:
    if path.exists():
        if hashlib.sha256(path.read_bytes()).hexdigest() != MODEL_SHA256:
            raise ValueError(f"{path} exists with a different checksum; choose another destination")
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        digest = hashlib.sha256()
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as output:
            temporary = Path(output.name)
            with requests.get(MODEL_URL, stream=True, timeout=(15, 60)) as response:
                response.raise_for_status()
                size = 0
                for chunk in response.iter_content(1024 * 1024):
                    size += len(chunk)
                    if size > 32 * 1024 * 1024:
                        raise ValueError("Model download exceeds 32 MiB")
                    digest.update(chunk)
                    output.write(chunk)
        if digest.hexdigest() != MODEL_SHA256:
            raise ValueError("Model checksum failed; download discarded")
        temporary.replace(path)
        return path
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def letterbox(frame: np.ndarray, size: int):
    height, width = frame.shape[:2]
    scale = min(size / width, size / height)
    resized = cv2.resize(frame, (round(width * scale), round(height * scale)))
    left = (size - resized.shape[1]) // 2
    top = (size - resized.shape[0]) // 2
    canvas = np.full((size, size, 3), 114, np.uint8)
    canvas[top : top + resized.shape[0], left : left + resized.shape[1]] = resized
    return canvas, scale, left, top


def decode(
    output: np.ndarray, shape: tuple, scale: float, left: int, top: int, floor: float, iou: float
) -> Detections:
    if output.ndim != 3 or output.shape[0] != 1 or output.shape[1] != 84:
        raise ValueError(f"Expected COCO YOLOv8 output [1,84,N], got {output.shape}")
    rows = output[0].T
    classes = rows[:, 4:].argmax(axis=1)
    scores = rows[np.arange(len(rows)), classes + 4]
    mask = np.isfinite(rows).all(axis=1) & (scores >= floor) & np.isin(classes, list(VEHICLES))
    rows, classes, scores = rows[mask], classes[mask], scores[mask]
    if not len(rows):
        return Detections.empty()
    boxes = rows[:, :4].copy()
    boxes[:, :2] -= boxes[:, 2:] / 2
    boxes[:, 2:] += boxes[:, :2]
    boxes[:, [0, 2]] = np.clip((boxes[:, [0, 2]] - left) / scale, 0, shape[1])
    boxes[:, [1, 3]] = np.clip((boxes[:, [1, 3]] - top) / scale, 0, shape[0])
    valid = (boxes[:, 2] > boxes[:, 0]) & (boxes[:, 3] > boxes[:, 1])
    boxes, classes, scores = boxes[valid], classes[valid], scores[valid]
    keep = []
    for class_id in VEHICLES:
        indices = np.flatnonzero(classes == class_id)
        xywh = boxes[indices].copy()
        xywh[:, 2:] -= xywh[:, :2]
        selected = cv2.dnn.NMSBoxes(xywh.tolist(), scores[indices].tolist(), floor, iou)
        keep.extend(indices[np.asarray(selected, dtype=int).reshape(-1)].tolist())
    keep = np.asarray(sorted(keep, key=lambda i: -scores[i])[:100], dtype=int)
    return Detections(xyxy=boxes[keep], confidence=scores[keep], class_id=classes[keep])


class VehicleDetector:
    def __init__(self, model: str, size: int = 640, floor: float = 0.1, iou: float = 0.45):
        if not Path(model).is_file():
            raise FileNotFoundError(f"Model missing: {model}. Run `roadlens fetch-model`")
        self.net = cv2.dnn.readNetFromONNX(model)
        self.net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
        self.net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
        self.size, self.floor, self.iou = size, floor, iou
        self.detect(np.zeros((size, size, 3), np.uint8))  # Validate export and warm up once.

    def detect(self, frame: np.ndarray) -> Detections:
        canvas, scale, left, top = letterbox(frame, self.size)
        blob = cv2.dnn.blobFromImage(canvas, 1 / 255.0, (self.size, self.size), swapRB=True)
        self.net.setInput(blob)
        return decode(self.net.forward(), frame.shape, scale, left, top, self.floor, self.iou)
