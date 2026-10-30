"""Native Hallmark gates and interactions; public fixtures, never physical cameras."""

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
