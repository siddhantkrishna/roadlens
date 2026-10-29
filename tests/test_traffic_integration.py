import json
from pathlib import Path

import cv2
import pytest

from roadlens.config import Config, SourceConfig
from roadlens.pipeline import Pipeline
from roadlens.preview import run_preview
from roadlens.traffic.models import AnalyticsConfig
from roadlens.traffic.service import render_heatmap
from roadlens.traffic.store import TrafficStore
from roadlens.traffic.validation import (
    CrossingLabel,
    FootageAnnotations,
    score_crossings,
    validate_footage,
)

ROOT = Path(__file__).resolve().parents[1]
SCENE = ROOT / "assets/traffic.scene.json"
ANNOTATIONS = ROOT / "assets/traffic.annotations.json"


@pytest.mark.model
def test_annotated_real_footage_accuracy(model_path, vehicle_video, tmp_path):
    report = validate_footage(
        vehicle_video, SCENE, ANNOTATIONS, Path(model_path), tmp_path / "accuracy.json"
    )
    assert report["processed_frames"] == 12
    assert report["expected_crossings"] == report["observed_crossings"] == 1
    assert report["false_positives"] == report["false_negatives"] == 0
    assert report["predictions"][0]["category"] == "car"
    assert report["predictions"][0]["direction"] == "image_up"
    assert report["precision"] == report["recall"] == 1


@pytest.mark.model
def test_two_actual_overlapping_feeds_never_become_a_global_unique_count(
    model_path, vehicle_video, tmp_path
):
    database = tmp_path / "actual.sqlite3"
    config = Config(model=model_path, analytics=AnalyticsConfig(database=str(database)))
    pipelines = [
        Pipeline(SourceConfig(name, "video", str(vehicle_video), False, str(SCENE)), config)
        for name in ("first", "overlapping")
    ]
    assert run_preview(pipelines, headless=True, duration=30) == 0
    with TrafficStore(database) as store:
        events = [event for event in store.rows("events") if event["kind"] == "crossing"]
        assert len(events) == 2
        assert store.report()["cross_camera_unique_vehicles"] is None
        for name in ("first", "overlapping"):
            assert len(store.rows("events", name)) == 1
            measurements = store.rows("measurements", name)
            assert len(measurements) == 1 and not measurements[0]["complete"]
            assert 0 < measurements[0]["observed_seconds"] <= 1
            assert all(row["speed_mps"] is None for row in store.rows("trajectories", name))
        assert pipelines[0].traffic.analyzer.baselines.windows == 0
        assert pipelines[0].traffic.analyzer.heatmap.sum() > 0
        key = store.rows("sessions", "first")[0]["id"]
        render_heatmap(store, key, tmp_path / "heatmap.png")
        assert cv2.imread(str(tmp_path / "heatmap.png")).shape == (540, 960, 3)
        store.export(tmp_path / "actual-json", "json", camera_id="first")
        store.export(tmp_path / "actual-csv", "csv", camera_id="first")
        exported = json.loads((tmp_path / "actual-json/events.json").read_text())
        assert exported[0]["category"] == "car"


@pytest.mark.model
def test_database_write_failure_is_visible_and_does_not_create_summary_counts(
    monkeypatch, model_path, vehicle_video, tmp_path
):
    database = tmp_path / "failed.sqlite3"
    config = Config(model=model_path, analytics=AnalyticsConfig(database=str(database)))

    def fail_write(*args):
        raise OSError("injected disk failure")

    monkeypatch.setattr(TrafficStore, "write", fail_write)
    pipeline = Pipeline(
        SourceConfig("traffic", "video", str(vehicle_video), False, str(SCENE)), config
    )
    assert run_preview([pipeline], headless=True, duration=20) == 1
    assert isinstance(pipeline.error, OSError)
    with TrafficStore(database) as store:
        assert store.rows("sessions")[0]["status"] == "failed"
        assert store.rows("measurements") == store.rows("events") == []


def test_validation_does_not_double_match_and_empty_metrics_are_unavailable():
    labels = [CrossingLabel("gate", "car", "up", 0, 2), CrossingLabel("gate", "car", "up", 0, 1.2)]
    predictions = [
        {"object_id": "gate", "category": "car", "direction": "up", "source_time": t}
        for t in (1, 1.5)
    ]
    assert score_crossings(predictions, labels)["true_positives"] == 2
    assert score_crossings(predictions[:1], labels)["false_negatives"] == 1
    empty = score_crossings([], [])
    assert empty["precision"] is None and empty["recall"] is None


def test_annotation_hash_mismatch_prevents_invalid_accuracy_claim(tmp_path):
    altered = tmp_path / "different.avi"
    altered.write_bytes(b"not the reviewed source")
    with pytest.raises(ValueError, match="Annotations do not match"):
        validate_footage(altered, SCENE, ANNOTATIONS, Path("unused.onnx"), tmp_path / "out.json")


def test_annotations_validate_required_fields_and_types(tmp_path):
    path = tmp_path / "invalid.json"
    path.write_text("{}")
    with pytest.raises(TypeError):
        FootageAnnotations.load(path)
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "video_sha256": "invalid",
                "scene_fingerprint": "invalid",
                "reviewed_frames": 12,
            }
        )
    )
    with pytest.raises(ValueError, match="SHA-256"):
        FootageAnnotations.load(path)
