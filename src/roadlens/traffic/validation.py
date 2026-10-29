"""Reproducible crossing accuracy against reviewed, footage-bound annotations."""

import hashlib
import json
import re
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path

import cv2

from roadlens.config import Config, SourceConfig
from roadlens.detection import VEHICLES
from roadlens.pipeline import Pipeline
from roadlens.preview import run_preview
from roadlens.traffic.models import AnalyticsConfig
from roadlens.traffic.scene import Scene, finite_number, identifier
from roadlens.traffic.store import TrafficStore


@dataclass(frozen=True)
class CrossingLabel:
    line_id: str
    category: str
    direction: str
    earliest: float
    latest: float

    def __post_init__(self):
        identifier(self.line_id)
        if self.category not in VEHICLES.values() or not self.direction:
            raise ValueError("Invalid annotated category/direction")
        finite_number(self.earliest, "earliest")
        finite_number(self.latest, "latest", self.earliest)


@dataclass(frozen=True)
class FootageAnnotations:
    version: int
    video_sha256: str
    scene_fingerprint: str
    reviewed_frames: int
    crossings: tuple[CrossingLabel, ...]
    notes: str = ""

    def __post_init__(self):
        if type(self.version) is not int or self.version != 1:
            raise ValueError("Unsupported annotations version")
        if type(self.reviewed_frames) is not int or self.reviewed_frames < 1:
            raise ValueError("reviewed_frames must be a positive integer")
        for digest in (self.video_sha256, self.scene_fingerprint):
            if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValueError("Annotations require valid SHA-256 fingerprints")
        if not isinstance(self.notes, str):
            raise ValueError("Annotation notes must be text")

    @classmethod
    def load(cls, path: Path) -> "FootageAnnotations":
        data = json.loads(path.read_text())
        data["crossings"] = tuple(CrossingLabel(**label) for label in data.get("crossings", ()))
        return cls(**data)


def file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def score_crossings(predictions: list[dict], labels: list[CrossingLabel]) -> dict:
    # Maximum-cardinality matching avoids counting one prediction against two labels.
    matches: dict[int, int] = {}

    def assign(index: int, visited: set[int]) -> bool:
        prediction = predictions[index]
        for j, label in enumerate(labels):
            if j in visited:
                continue
            if (
                prediction["object_id"] != label.line_id
                or prediction["category"] != label.category
                or prediction["direction"] != label.direction
                or not label.earliest <= prediction["source_time"] <= label.latest
            ):
                continue
            visited.add(j)
            if j not in matches or assign(matches[j], visited):
                matches[j] = index
                return True
        return False

    for i in range(len(predictions)):
        assign(i, set())
    true_positive = len(matches)
    return {
        "expected_crossings": len(labels),
        "observed_crossings": len(predictions),
        "true_positives": true_positive,
        "false_positives": len(predictions) - true_positive,
        "false_negatives": len(labels) - true_positive,
        "precision": true_positive / len(predictions) if predictions else None,
        "recall": true_positive / len(labels) if labels else None,
        "absolute_count_error": abs(len(predictions) - len(labels)),
        "matched_pairs": [{"label": j, "prediction": i} for j, i in sorted(matches.items())],
    }


def validate_footage(
    video: Path, scene_path: Path, annotations: Path, model: Path, output: Path
) -> dict:
    if output.exists():
        raise FileExistsError(output)
    data = FootageAnnotations.load(annotations)
    if file_hash(video) != data.video_sha256:
        raise ValueError("Annotations do not match this video/version")
    scene = Scene.load(scene_path)
    if scene.fingerprint != data.scene_fingerprint:
        raise ValueError("Annotations do not match this scene geometry")
    labels = list(data.crossings)
    lines = {line.id: line for line in scene.lines}
    for label in labels:
        if label.line_id not in lines or label.direction not in (
            lines[label.line_id].forward,
            lines[label.line_id].reverse,
        ):
            raise ValueError("Annotated line or direction is not in the scene")
    cv2.setNumThreads(2)
    with tempfile.TemporaryDirectory(prefix="roadlens-validation-") as temporary:
        database = Path(temporary) / "analysis.sqlite3"
        config = replace(
            Config(model=str(model)), analytics=AnalyticsConfig(database=str(database))
        )
        pipeline = Pipeline(
            SourceConfig("validation", "video", str(video), False, str(scene_path)), config
        )
        status = run_preview([pipeline], headless=True)
        if status != 0:
            raise RuntimeError(f"Footage validation pipeline failed: {pipeline.error}")
        if pipeline.processed != data.reviewed_frames or pipeline.capture.frames.dropped:
            raise ValueError("Processed coverage does not match the reviewed footage")
        with TrafficStore(database) as store:
            predictions = [event for event in store.rows("events") if event["kind"] == "crossing"]
        report = score_crossings(predictions, labels)
        report.update(
            {
                "video_sha256": data.video_sha256,
                "scene_fingerprint": scene.fingerprint,
                "processed_frames": pipeline.processed,
                "predictions": predictions,
                "scope": "crossing category, direction and time on this reviewed clip only",
                "speed_validation": "unavailable without measured ground-plane calibration",
                "review_notes": data.notes,
            }
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x") as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write("\n")
    return report
