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
