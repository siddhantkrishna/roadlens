import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace

import pytest
from test_traffic_counting import LINE, SHAPE, vehicle

from roadlens.config import SourceConfig
from roadlens.traffic.analyzer import TrafficAnalyzer
from roadlens.traffic.models import AnalyticsConfig, TrajectoryPoint
from roadlens.traffic.scene import Scene
from roadlens.traffic.service import TrafficService
from roadlens.traffic.store import MIGRATIONS, TrafficStore


def session(store, camera="one", *, fingerprint="device", key="analysis"):
    return store.start_session(
        camera,
        camera,
        {"device_fingerprint": fingerprint, "overlap_group": "shared-road"},
        asdict(Scene(lines=(LINE,))),
        key,
        "video_seconds",
        "source",
    )


def observed_crossing():
    analyzer = TrafficAnalyzer(Scene(lines=(LINE,)), AnalyticsConfig(window_seconds=1))
    analyzer.update([vehicle(0.4)], 0, 1, SHAPE)
    return analyzer, analyzer.update([vehicle(0.6)], 0.5, 1, SHAPE)


def test_migrations_upgrade_and_foreign_keys(tmp_path):
    path = tmp_path / "old.sqlite3"
    with sqlite3.connect(path) as connection:
        for statement in MIGRATIONS[0]:
            connection.execute(statement)
        connection.execute("PRAGMA user_version=1")
    with TrafficStore(path) as store:
        assert store.connection.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)
        assert store.connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert store.rows("heatmaps") == []
        with pytest.raises(sqlite3.IntegrityError):
            store.write("missing-session", observed_crossing()[1])
    assert path.stat().st_mode & 0o777 == 0o600


def test_newer_schema_refused(tmp_path):
    path = tmp_path / "future.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version=999")
    with pytest.raises(ValueError, match="newer"):
        TrafficStore(path)


def test_atomic_idempotent_events_measurements_and_camera_isolation(tmp_path):
    with TrafficStore(tmp_path / "traffic.sqlite3") as store:
        first, second = session(store), session(store, "two")
        analyzer, update = observed_crossing()
        store.write(first, update)
        store.write(first, update)
        store.write(first, analyzer.finish())
        assert len(store.rows("events", "one")) == 1
        assert store.rows("events", "two") == []
        assert len(store.rows("trajectories", "one")) == 1
        assert len(store.rows("measurements", "one")) == 1
        assert len(store.rows("heatmaps", "one")) == 1
        report = store.report()
        assert report["cross_camera_unique_vehicles"] is None
        assert len(report["cameras"]) == 2
        assert store.rows("sessions", session_id=second)[0]["camera_id"] == "two"
        store.finish_session(first, "completed")
        assert store.rows("sessions", "one")[0]["status"] == "completed"


def test_write_rolls_back_all_records_on_invalid_point(tmp_path):
    with TrafficStore(tmp_path / "traffic.sqlite3") as store:
        key = session(store)
        _, update = observed_crossing()
        invalid = replace(
            update, trajectories=(TrajectoryPoint("1:1:1", 0.5, "car", 2, 0.5, None),)
        )
        with pytest.raises(sqlite3.IntegrityError):
            store.write(key, invalid)
        assert store.rows("events") == store.rows("trajectories") == []


def test_live_camera_alias_cannot_silently_merge_other_device(tmp_path):
    with TrafficStore(tmp_path / "traffic.sqlite3") as store:
        session(store, fingerprint="first-device")
        with pytest.raises(ValueError, match="different live device"):
            session(store, fingerprint="second-device")
        session(
            store, fingerprint=None
        )  # An explicitly associated recording preserves the live binding.
        with pytest.raises(ValueError):
            session(store, fingerprint="second-device")
        assert len(store.rows("sessions")) == 2


def test_export_actual_rows_and_session_filter_without_overwrite(tmp_path):
    with TrafficStore(tmp_path / "traffic.sqlite3") as store:
        first = session(store)
        session(store, "two")
        store.write(first, observed_crossing()[1])
        directory = tmp_path / "json"
        store.export(directory, "json", session_id=first)
        events = json.loads((directory / "events.json").read_text())
        cameras = json.loads((directory / "cameras.json").read_text())
        assert len(events) == 1 and events[0]["category"] == "car"
        assert events[0]["details"]["identity_scope"] == "session_track_lifecycle"
        assert [row["id"] for row in cameras] == ["one"]
        with pytest.raises(FileExistsError):
            store.export(directory, "json")
        store.export(tmp_path / "csv", "csv", camera_id="one")
        assert "car" in (tmp_path / "csv/events.csv").read_text()
        with pytest.raises(ValueError):
            store.rows("events; DROP TABLE cameras")


def test_concurrent_camera_writers_and_schema_initialization(tmp_path):
    path = tmp_path / "concurrent.sqlite3"

    def write_camera(camera):
        with TrafficStore(path) as store:
            key = session(store, camera)
            store.write(key, observed_crossing()[1])
            store.finish_session(key, "completed")

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(write_camera, ["one", "two"]))
    with TrafficStore(path) as store:
        assert len(store.rows("events")) == 2
        assert len(store.rows("sessions")) == 2


def test_retention_cascades_only_finished_sessions(tmp_path):
    with TrafficStore(tmp_path / "traffic.sqlite3") as store:
        old = session(store)
        active = session(store, "two")
        store.write(old, observed_crossing()[1])
        with store.connection:
            store.connection.execute(
                "UPDATE sessions SET ended_at='2000-01-01',status='completed' WHERE id=?", (old,)
            )
        assert store.prune(7) == 1
        assert store.rows("events") == []
        assert store.rows("sessions")[0]["id"] == active


def test_baselines_reuse_only_compatible_camera_and_analysis(tmp_path):
    with TrafficStore(tmp_path / "traffic.sqlite3") as store:
        key = session(store)
        analyzer, update = observed_crossing()
        store.write(key, update)
        store.write(key, analyzer.update([], 1, 1, SHAPE))
        assert len(store.baseline_history("one", "analysis", 20)) == 1
        assert store.baseline_history("two", "analysis", 20) == []
        assert store.baseline_history("one", "changed-calibration", 20) == []


def test_service_writes_summaries_and_restores_no_fake_baseline(tmp_path):
    scene_path = tmp_path / "scene.json"
    Scene(lines=(LINE,)).save(scene_path)
    path = tmp_path / "traffic.sqlite3"
    source = SourceConfig("first", "video", "actual.mp4", False, str(scene_path), "fixed-camera")
    service = TrafficService(source, AnalyticsConfig(database=str(path)), {"model": "test-context"})
    assert service.analyzer.baselines.windows == 0
    service.update([vehicle(0.4)], 0, 1, SHAPE)
    service.update([vehicle(0.6)], 0.5, 1, SHAPE)
    service.close("completed")
    with TrafficStore(path) as store:
        assert len(store.rows("events", "fixed-camera")) == 1
        assert store.rows("trajectories")[0]["speed_mps"] is None
        session_row = store.rows("sessions")[0]
        assert session_row["clock_kind"] == "video_seconds"
        assert json.loads(session_row["settings_json"])["vision"] == {"model": "test-context"}
        assert (
            store.rows("trajectories")[0]["speed_unavailable_reason"]
            == "no verified scene calibration"
        )
        assert "actual.mp4" not in json.dumps(store.rows("cameras"))


def test_export_streams_without_loading_history_into_a_list(monkeypatch, tmp_path):
    with TrafficStore(tmp_path / "traffic.sqlite3") as store:
        key = session(store)
        store.write(key, observed_crossing()[1])

        def forbid_list(*args, **kwargs):
            raise AssertionError("Export must stream its rows")

        monkeypatch.setattr(store, "rows", forbid_list)
        store.export(tmp_path / "json", "json")
        assert len(json.loads((tmp_path / "json/events.json").read_text())) == 1


def test_heatmap_export_never_overwrites_even_if_an_existence_check_would_race(
    tmp_path, monkeypatch
):
    from pathlib import Path

    from roadlens.traffic.service import render_heatmap

    with TrafficStore(tmp_path / "traffic.sqlite3") as store:
        key = session(store)
        analyzer, update = observed_crossing()
        store.write(key, update)
        store.write(key, analyzer.finish())
        output = tmp_path / "existing.png"
        output.write_bytes(b"preserve existing file")
        original = Path.exists
        monkeypatch.setattr(
            Path, "exists", lambda path: False if path == output else original(path)
        )
        with pytest.raises(FileExistsError):
            render_heatmap(store, key, output)
        assert output.read_bytes() == b"preserve existing file"
