"""Regressions for the release audit; synthetic unit data and the public fixture only."""

import json
from dataclasses import asdict, replace
from pathlib import Path

import cv2
import numpy as np
import pytest
from PySide6.QtWidgets import QDialog
from test_desktop import image
from test_desktop import qt_app as qt_app
from test_desktop import window as window

from roadlens.config import SourceConfig
from roadlens.desktop import fill_table, read_preferences, table
from roadlens.desktop_data import heatmap_image, read_history
from roadlens.desktop_widgets import SceneEditor
from roadlens.drawing import fit_text
from roadlens.pipeline import Result, annotate
from roadlens.tracking import Track
from roadlens.traffic.models import Count, TrafficSnapshot
from roadlens.traffic.scene import Scene, Zone
from roadlens.traffic.store import TrafficStore


@pytest.mark.parametrize("width", [0, 10, 40, 160, 640])
def test_overlay_text_fits_its_pixel_budget(width):
    result = fit_text("A long source name " * 100, width)
    assert not result or cv2.getTextSize(result, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)[0][0] <= width


def test_vehicle_label_is_compact_and_source_independent(monkeypatch):
    messages, positions = [], []
    original = cv2.putText

    def record(canvas, text, *args):
        messages.append(text)
        positions.append(args[0])
        return original(canvas, text, *args)

    monkeypatch.setattr(cv2, "putText", record)
    track = Track(12, 2, 0.87, (5, 30, 100, 110), (0, 0), (0, 0), ())
    canvas = annotate(
        np.zeros((360, 200, 3), np.uint8), [track], "recording-name-" * 30, 1, "diagnostics"
    )
    assert messages[0] == "Car #12 | 0.87"
    assert "recording" not in messages[0]
    assert canvas.any()
    assert positions[0][1] > track.bbox[3]


@pytest.mark.parametrize("value", [None, [], "not an object"])
def test_invalid_preference_root_is_a_handled_validation_error(tmp_path, value):
    path = tmp_path / "desktop.json"
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="JSON object"):
        read_preferences(path)


def test_scene_save_applies_draft_and_new_ids_do_not_collide(qt_app, tmp_path):
    polygon = ((0.1, 0.1), (0.8, 0.1), (0.8, 0.8))
    original = Scene(
        zones=(Zone("geometry-1", "One", polygon), Zone("geometry-3", "Three", polygon))
    )
    editor = SceneEditor(original, image())
    editor.new_geometry()
    assert editor.identifier.text() == "geometry-2"
    editor.canvas.points = list(polygon)
    editor.save()
    assert editor.result() == QDialog.DialogCode.Accepted
    assert len(editor.scene.zones) == 3
    path = tmp_path / "scene.json"
    editor.scene.save(path)
    assert Scene.load(path) == editor.scene
    editor.select_geometry(0)
    revision = editor.scene.revision
    assert editor.apply_geometry()
    assert editor.scene.revision == revision
    editor.close()


def test_invalid_scene_draft_does_not_close_the_editor(qt_app):
    editor = SceneEditor(Scene(), image())
    editor.canvas.points = [(0.1, 0.1), (0.2, 0.2)]
    editor.save()
    assert editor.result() != QDialog.DialogCode.Accepted
    assert not editor.scene.zones and "three" in editor.status.text()
    editor.close()


def test_table_headings_remain_readable_and_scroll_position_is_preserved(qt_app):
    headings = ["Zone", "Vehicles", "Image occupancy", "Queue", "Congestion"]
    widget = table(headings)
    widget.resize(360, 160)
    widget.show()
    fill_table(widget, [(i, 0, "0%", 0, "free") for i in range(200)])
    qt_app.processEvents()
    for i, heading in enumerate(headings):
        assert widget.columnWidth(i) >= widget.fontMetrics().horizontalAdvance(heading) + 20
    widget.verticalScrollBar().setValue(50)
    fill_table(widget, [(i, 1, "10%", 0, "free") for i in range(200)])
    assert widget.verticalScrollBar().value() == 50
    widget.close()


def test_history_session_cannot_bypass_camera_filter(tmp_path):
    path = tmp_path / "traffic.sqlite3"
    with TrafficStore(path) as store:
        first = store.start_session(
            "one", "First", {}, asdict(Scene()), "key", "video_seconds", "one"
        )
        store.start_session("two", "Second", {}, asdict(Scene()), "key", "video_seconds", "two")
    assert read_history(path, camera="Second", session=first)["session"] is None
    assert read_history(path, camera="First", session=first)["session"]["id"] == first


@pytest.mark.parametrize(
    "grid", [[], [1, 2], [[-1]], [[float("nan")]], [[float("inf")]], [[0]] * 145]
)
def test_corrupt_heatmaps_are_rejected_instead_of_becoming_false_zeroes(grid):
    with pytest.raises(ValueError):
        heatmap_image({"grid_json": json.dumps(grid)})


def test_camera_sources_with_the_same_display_name_keep_distinct_identity(window):
    devices = [
        {"id": key, "name": "External camera", "type": "External"} for key in ("first", "second")
    ]
    window.cameras_discovered(devices)
    for index in range(2):
        window.camera_selector.setCurrentIndex(index)
        window.add_camera()
    assert len(window.sources) == 2
    assert len({s.name for s in window.sources}) == 2
    assert len({s.camera_id for s in window.sources}) == 2
    assert {s.value for s in window.sources} == {"first", "second"}


@pytest.mark.model
def test_restart_resets_metrics_and_long_names_do_not_expand_the_window(window, qt_app, model_path):
    window.config = replace(window.config, model=model_path)
    root = Path(__file__).resolve().parents[1]
    source = SourceConfig(
        "long-source-name-" * 20, "video", str(root / "assets/traffic.avi"), False
    )
    window.add_source(source)
    snapshot = TrafficSnapshot(
        1, (Count("line", "car", "up", 10),), True, (), (), "no calibration", 0, False
    )
    old = Result(np.zeros((120, 160, 3), np.uint8), (), 1, 1, 10, 0, snapshot)
    window.latest[source.name] = old
    window.update_live(old)
    assert window.metrics["Crossing events"].text() == "10"
    window.start_selected()
    assert window.metrics["Crossing events"].text() == "—"
    qt_app.processEvents()
    assert window.minimumSizeHint().width() <= window.width()
    window.stop_all()


def test_history_callback_failure_is_visible_and_does_not_escape_into_qt(window):
    def corrupt(_):
        raise ValueError("Corrupt saved measurements")

    window.report_data = {"session": "old unit fixture"}
    fill_table(window.history_counts, [("old", "car", "up", 5)])
    window.callbacks["history"] = corrupt
    window.job_completed("history", {}, None)
    assert "Corrupt saved measurements" in window.history_status.text()
    assert window.report_data is None and window.history_counts.rowCount() == 0
    assert not window.test_errors  # periodic history failures do not spawn repeated modal dialogs


def test_diagnostics_pause_while_selected_for_copying(window, qt_app):
    window.tabs.setCurrentIndex(2)
    window.diagnostics.setPlainText("Selected diagnostics stay readable")
    window.diagnostics.setFocus()
    qt_app.processEvents()
    window.diagnostics.selectAll()
    window.update_diagnostics()
    assert window.diagnostics.textCursor().selectedText() == "Selected diagnostics stay readable"
