"""Native Hallmark gates and interactions; public fixtures, never physical cameras."""

import pytest
from test_desktop import qt_app as qt_app
from test_desktop import window as window

from roadlens.desktop_design import LIGHT, contrast


def test_light_tokens_cover_text_fields_and_focus_contrast():
    for role in ("text", "muted"):
        for surface in ("background", "surface", "raised"):
            assert contrast(LIGHT[role], LIGHT[surface]) >= 4.5
    for role in ("border", "focus", "chart"):
        assert contrast(LIGHT[role], LIGHT["surface"]) >= 3
    assert contrast(LIGHT["accent"], LIGHT["accent_ink"]) >= 4.5


def test_dark_tokens_have_full_contrast_parity():
    from roadlens.desktop_design import DARK

    assert DARK.keys() == LIGHT.keys()
    for role in ("text", "muted"):
        for surface in ("background", "surface", "raised"):
            assert contrast(DARK[role], DARK[surface]) >= 4.5
    for role in ("border", "focus", "chart"):
        assert contrast(DARK[role], DARK["surface"]) >= 3
    assert contrast(DARK["accent"], DARK["accent_ink"]) >= 4.5


def test_svg_icons_render_for_every_action():
    from PySide6.QtWidgets import QApplication

    from roadlens.desktop_design import PATHS, icon

    app = QApplication.instance() or QApplication([])
    assert app
    for name in PATHS:
        assert not icon(name, LIGHT["text"]).pixmap(36, 36).isNull()


def test_focus_outline_preserves_input_dimensions():
    from PySide6.QtWidgets import QApplication, QLineEdit, QVBoxLayout, QWidget

    from roadlens.desktop_design import FocusOutline, apply_appearance

    app = QApplication.instance() or QApplication([])
    window = QWidget()
    form = QVBoxLayout(window)
    first, second = QLineEdit(), QLineEdit()
    form.addWidget(first)
    form.addWidget(second)
    outline = FocusOutline(window)
    apply_appearance(window)
    window.show()
    app.processEvents()
    before = first.size()
    second.setFocus()
    first.setFocus()
    app.processEvents()
    assert outline.frame.widget() == first
    assert first.size() == before
    window.close()


def test_video_onboarding_reads_a_real_frame_before_start(tmp_path):
    from pathlib import Path

    from PySide6.QtWidgets import QApplication
    from test_desktop import spin

    from roadlens.config import SourceConfig
    from roadlens.desktop import DesktopWindow, default_config

    app = QApplication.instance() or QApplication([])
    window = DesktopWindow(default_config(tmp_path), tmp_path)
    video = Path(__file__).resolve().parents[1] / "assets/traffic.avi"
    window.add_source(SourceConfig("Recording", "video", str(video), False))
    spin(app, lambda: not window.jobs)
    assert not window.pipelines
    assert not window.panes["Recording"].raw_image.isNull()
    window.close()


def test_recorded_pause_resume_and_stop_keep_frame_integrity():
    import time
    from pathlib import Path

    from roadlens.config import Config, SourceConfig
    from roadlens.pipeline import Pipeline

    root = Path(__file__).resolve().parents[1]
    source = SourceConfig("Video", "video", str(root / "assets/traffic.avi"), False)
    config = Config(model=str(root / "models/yolov8n.onnx"))
    pipeline = Pipeline(source, config)
    pipeline.set_paused(True)
    pipeline.start()
    time.sleep(0.1)
    assert pipeline.processed == 0
    pipeline.set_paused(False)
    pipeline.join(20)
    assert pipeline.done.is_set() and pipeline.processed == 12 and not pipeline.error
    assert pipeline.capture.frames.dropped == 0
    stopped = Pipeline(source, config)
    stopped.set_paused(True)
    stopped.start()
    stopped.stop()
    stopped.join(10)
    assert stopped.done.is_set() and not stopped.error


def test_compact_desktop_overlay_leaves_header_and_footer_unpainted(monkeypatch):
    import numpy as np

    from roadlens.pipeline import annotate
    from roadlens.tracking import Track

    labels = []
    import cv2

    original = cv2.putText

    def record(canvas, text, *args):
        labels.append(text)
        return original(canvas, text, *args)

    monkeypatch.setattr(cv2, "putText", record)
    canvas = annotate(
        np.zeros((360, 640, 3), np.uint8),
        [Track(12, 2, 0.87, (100, 100, 200, 200), (0, 0), (0, 0), ())],
        "long source",
        3,
        "technical diagnostics",
        compact=True,
    )
    assert labels == ["Car 12"]
    assert not canvas[:40].any() and not canvas[-40:].any()


def test_geometry_visibility_is_independent_of_real_analysis(window):
    from roadlens.config import SourceConfig

    window.geometry_action.setChecked(False)
    window.add_source(SourceConfig("Unopened camera", "camera", "unit-device-id"))
    assert not window.panes["Unopened camera"].preview.show_geometry
    window.geometry_action.setChecked(True)
    assert window.panes["Unopened camera"].preview.show_geometry
    assert not window.pipelines


def test_monitor_flow_uses_selected_line_without_combining_lines(window, qt_app, model_path):
    from dataclasses import replace
    from pathlib import Path

    from test_desktop import spin

    from roadlens.config import SourceConfig
    from roadlens.traffic.scene import CountingLine, Scene

    root = Path(__file__).resolve().parents[1]
    scene = Scene.load(root / "assets/traffic.scene.json")
    scene = scene.with_line(CountingLine("second", (0.1, 0.8), (0.9, 0.8)))
    path = window.data_dir / "two-lines.json"
    scene.save(path)
    window.config = replace(window.config, model=model_path)
    window.add_source(
        SourceConfig("Two lines", "video", str(root / "assets/traffic.avi"), False, str(path))
    )
    spin(qt_app, lambda: not window.jobs)
    window.start_all()
    spin(qt_app, lambda: not window.any_active())
    window.tick()
    spin(qt_app, lambda: not window.jobs)
    window.refresh_history()
    spin(qt_app, lambda: not window.jobs)
    assert window.monitor_line.count() == 2
    for index in range(2):
        window.monitor_line.setCurrentIndex(index)
        line = window.monitor_line.currentData()
        rates = window.report_data["windows"][-1]["flow_per_minute"]
        expected = sum(v for key, v in rates.items() if key.split("/")[0] == line and v is not None)
        assert window.metrics["Traffic flow"].text() == f"{expected:.1f}"


def test_counting_tool_draws_and_saves_without_geometry_fields(qt_app):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QDialog, QDialogButtonBox
    from test_desktop import image

    from roadlens.desktop_widgets import SceneEditor
    from roadlens.traffic.scene import Scene

    editor = SceneEditor(Scene(), image())
    editor.show()
    qt_app.processEvents()
    editor.count_tool.click()
    for point in ((0.1, 0.5), (0.9, 0.5)):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.mapped(point).toPoint()
        )
    editor.buttons.button(QDialogButtonBox.StandardButton.Save).click()
    assert editor.result() == QDialog.DialogCode.Accepted and len(editor.scene.lines) == 1
    editor.close()


@pytest.fixture(autouse=True)
def stable_qt_lifetime(qt_app):
    """macOS Qt must retain one QApplication across the complete UI test session."""
    yield qt_app


def test_road_tool_saves_a_real_validated_polygon(qt_app):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from test_desktop import image

    from roadlens.desktop_widgets import SceneEditor
    from roadlens.traffic.scene import Scene

    editor = SceneEditor(Scene(), image())
    editor.show()
    qt_app.processEvents()
    editor.road_tool.click()
    for point in ((0.1, 0.1), (0.8, 0.1), (0.8, 0.8)):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.mapped(point).toPoint()
        )
    editor.save()
    assert len(editor.scene.zones) == 1 and editor.scene.zones[0].kind == "road"
    assert editor.scene.zones[0].contains((0.7, 0.2))
    editor.close()


def test_scene_shape_selection_and_drag_use_letterboxed_coordinates(qt_app):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from test_desktop import image

    from roadlens.desktop_widgets import SceneEditor
    from roadlens.traffic.scene import CountingLine, Scene

    scene = Scene(lines=(CountingLine("line", (0.1, 0.5), (0.9, 0.5)),))
    editor = SceneEditor(scene, image())
    editor.show()
    qt_app.processEvents()
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.mapped((0.5, 0.5)).toPoint()
    )
    assert editor.selected == ("lines", "line")
    start = editor.canvas.mapped((0.1, 0.5)).toPoint()
    end = editor.canvas.mapped((0.2, 0.6)).toPoint()
    QTest.mousePress(editor.canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(editor.canvas, end)
    QTest.mouseRelease(editor.canvas, Qt.MouseButton.LeftButton, pos=end)
    assert abs(editor.canvas.points[0][0] - 0.2) < 0.003
    assert abs(editor.canvas.points[0][1] - 0.6) < 0.003
    editor.close()


def test_scene_undo_restores_deleted_geometry_and_cancel_keeps_original(qt_app):
    from test_desktop import image

    from roadlens.desktop_widgets import SceneEditor
    from roadlens.traffic.scene import CountingLine, Scene

    scene = Scene(lines=(CountingLine("line", (0.1, 0.5), (0.9, 0.5)),))
    editor = SceneEditor(scene, image())
    editor.select_geometry(0)
    editor.delete()
    assert not editor.scene.lines
    editor.undo()
    assert editor.scene == scene
    editor.reject()
    assert scene.lines[0].id == "line"
    editor.close()


def test_scene_load_failure_is_visible_and_preserves_geometry(qt_app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    from test_desktop import image

    from roadlens.desktop_widgets import SceneEditor
    from roadlens.traffic.scene import CountingLine, Scene

    original = Scene(lines=(CountingLine("line", (0.1, 0.5), (0.9, 0.5)),))
    bad = tmp_path / "invalid.json"
    bad.write_text('{"version": 999}')
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a: (str(bad), ""))
    editor = SceneEditor(original, image())
    editor.load_scene()
    assert editor.scene == original and editor.status.property("error")
    editor.count_tool.click()
    editor.canvas.points = [(0.1, 0.5)]
    editor.save()
    assert not editor.result() and len(editor.canvas.points) == 1
    editor.close()


def test_calibration_changes_validate_and_survive_geometry_apply(qt_app):
    import json
    from dataclasses import asdict

    from test_desktop import image

    from roadlens.desktop_widgets import SceneEditor
    from roadlens.traffic.scene import Calibration, Scene

    editor = SceneEditor(Scene(), image())
    calibration = Calibration(
        ((0, 0), (1, 0), (1, 1), (0, 1)), ((0, 0), (10, 0), (10, 10), (0, 10)), (640, 360), True
    )
    editor.calibration_edit.setPlainText(json.dumps(asdict(calibration)))
    editor.canvas.points = [(0, 0), (1, 0), (1, 1)]
    assert editor.apply_geometry()
    editor.save()
    assert editor.scene.calibration == calibration
    invalid = SceneEditor(Scene(), image())
    invalid.calibration_edit.setPlainText('{"verified": true}')
    invalid.save()
    assert invalid.result() != 1 and "Calibration" in invalid.status.text()
    editor.close()
    invalid.close()


def test_heatmap_legend_distinguishes_missing_zero_and_observed_dwell(qt_app):
    from roadlens.desktop_widgets import HeatmapLegend

    legend = HeatmapLegend()
    for value in (None, 0, 0.083333):
        legend.set_scale(value)
        assert legend.scale_max == value
        assert not legend.grab().isNull()
    assert "0.0833" in legend.accessibleDescription()
    legend.close()


def test_event_records_show_real_units_and_handle_unreadable_details():
    import json

    from roadlens.desktop_data import event_row

    record = {
        "kind": "queue_started",
        "source_time": 4.5,
        "object_id": "road",
        "category": None,
        "direction": None,
        "details_json": json.dumps({"vehicles": 4}),
    }
    assert event_row(record)[1] == "Queue formed"
    assert event_row(record)[4] == "4 vehicles in the queue"
    record.update(kind="observation_gap", details_json=json.dumps({"seconds": 2.5}))
    assert "2.5 s" in event_row(record)[4]
    record["details_json"] = "invalid"
    assert "could not be read" in event_row(record)[4]


def test_session_comparison_uses_only_matching_observed_sessions(window, qt_app):
    from dataclasses import asdict
    from pathlib import Path

    from test_desktop import spin

    from roadlens.desktop_data import read_history
    from roadlens.traffic.models import AnalysisUpdate, TrafficEvent, TrafficSnapshot
    from roadlens.traffic.scene import CountingLine, Scene
    from roadlens.traffic.store import TrafficStore

    spin(qt_app, lambda: not window.jobs)
    path = Path(window.config.analytics.database)
    scene = Scene(lines=(CountingLine("one", (0, 0.5), (1, 0.5)),))
    snapshot = TrafficSnapshot(1, (), True, (), (), "no calibration", 0, False)
    with TrafficStore(path) as store:
        sessions = []
        for key, fingerprint in (
            ("same", "same"),
            ("same", "same"),
            ("other", "same"),
            ("same", "different"),
        ):
            session = store.start_session(
                "camera", "Camera", {}, asdict(scene), key, "video_seconds", fingerprint
            )
            store.write(
                session,
                AnalysisUpdate(
                    snapshot, (TrafficEvent("one", "crossing", 1, "one", "car", "forward"),)
                ),
            )
            store.finish_session(session, "completed")
            sessions.append(session)
    window.tabs.setCurrentIndex(1)
    window.history_request += 1
    window.history_loaded((window.history_request, read_history(path, session=sessions[0])))
    assert window.compare_selector.count() == 2
    window.compare_selector.setCurrentIndex(1)
    spin(qt_app, lambda: not window.jobs)
    assert "1 in this session" in window.comparison_status.text()
    assert "1 in the comparison" in window.comparison_status.text()
    window.history_camera.setText("absent")
    window.reset_history()
    spin(qt_app, lambda: not window.jobs)
    assert window.analysis_empty.isVisible() and not window.analysis_scroll.isVisible()
