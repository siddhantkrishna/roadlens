"""Native UI contracts and real-recording integration; never open a physical camera."""

import json
import os
import threading
import time
from dataclasses import asdict, replace
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt, QThread, QTimer
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog

from roadlens.config import SourceConfig
from roadlens.desktop import DesktopWindow, default_config, read_preferences, save_preferences
from roadlens.desktop_data import export_pdf, heatmap_image, read_history
from roadlens.desktop_widgets import Preview, SceneEditor
from roadlens.traffic.scene import CountingLine, Scene, Zone
from roadlens.traffic.store import TrafficStore

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def qt_app():
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("ROADLENS tests")
    return app


def spin(app, condition, timeout=30):
    deadline = time.monotonic() + timeout
    while not condition():
        app.processEvents()
        if time.monotonic() > deadline:
            raise AssertionError("Qt operation timed out")
        time.sleep(0.005)
    app.processEvents()


@pytest.fixture
def window(qt_app, tmp_path):
    window = DesktopWindow(default_config(tmp_path), tmp_path)
    errors = []
    window.show_error = errors.append
    window.test_errors = errors
    window.show()
    yield window
    window.close()
    spin(qt_app, lambda: not window.any_active() and not window.jobs)
    window.close()
    window.deleteLater()
    qt_app.processEvents()


def image():
    result = QImage(640, 360, QImage.Format.Format_RGB32)
    result.fill(QColor("#183c4d"))
    return result


def test_preferences_roundtrip_and_validation(tmp_path):
    config = replace(
        default_config(tmp_path), sources=(SourceConfig("phone", "camera", "stable-id"),)
    )
    path = tmp_path / "desktop.json"
    save_preferences(path, config)
    assert read_preferences(path) == config
    assert path.stat().st_mode & 0o777 == 0o600
    invalid = json.loads(path.read_text())
    invalid["threads"] = 100
    path.write_text(json.dumps(invalid))
    with pytest.raises(ValueError, match="threads"):
        read_preferences(path)


def test_letterbox_coordinates_and_pointer_keyboard_editing(qt_app):
    preview = Preview()
    preview.resize(800, 600)
    preview.editable = True
    preview.set_image(image())
    preview.show()
    qt_app.processEvents()
    rect = preview.image_rect()
    assert rect == preview.image_rect() and rect.height() == 450
    assert preview.normalized(QPointF(400, 20)) is None
    assert preview.normalized(QPointF(400, 300)) == (0.5, 0.5)
    QTest.mouseClick(preview, Qt.MouseButton.LeftButton, pos=QPoint(400, 300))
    assert preview.points == [(0.5, 0.5)]
    QTest.keyClick(preview, Qt.Key.Key_Right)
    assert preview.points[0][0] == 0.501
    QTest.keyClick(preview, Qt.Key.Key_Backspace)
    assert not preview.points
    preview.close()


def test_scene_editor_validates_edits_deletes_and_preserves_calibration(qt_app):
    original = Scene.load(ROOT / "assets/traffic.scene.json")
    editor = SceneEditor(original, image())
    editor.canvas.points = [(0, 0), (1, 1)]
    editor.apply_geometry()
    assert "three" in editor.status.text()
    assert editor.scene == original
    editor.kind.setCurrentText("queue")
    editor.identifier.setText("queue-new")
    editor.name.setText("Stopped vehicles")
    editor.canvas.points = [(0.1, 0.1), (0.8, 0.1), (0.8, 0.8), (0.1, 0.8)]
    editor.apply_geometry()
    assert editor.scene.zones[-1].kind == "queue"
    assert editor.scene.calibration == original.calibration
    editor.kind.setCurrentText("line")
    editor.identifier.setText("new-line")
    editor.canvas.points = [(0.1, 0.5), (0.9, 0.5)]
    editor.apply_geometry()
    assert editor.scene.lines[-1].side((0.5, 0.8)) == 1
    index = len(editor.scene.zones) + len(editor.scene.lines) - 1
    editor.select_geometry(index)
    editor.forward.setText("southbound")
    editor.apply_geometry()
    assert editor.scene.lines[-1].forward == "southbound"
    editor.select_geometry(index)
    editor.delete()
    assert not any(line.id == "new-line" for line in editor.scene.lines)
    editor.close()


def test_source_import_discovery_failure_and_settings_boundaries(
    window, qt_app, monkeypatch, tmp_path
):
    monkeypatch.setattr(
        QFileDialog, "getOpenFileNames", lambda *a: ([str(ROOT / "assets/traffic.avi")], "")
    )
    opened = []
    monkeypatch.setattr(
        "roadlens.desktop.QDesktopServices.openUrl",
        lambda url: opened.append(url.toLocalFile()) or True,
    )
    window.open_license()
    assert opened == [str(ROOT / "LICENSE")]
    window.import_video()
    assert len(window.sources) == 1 and not window.sources[0].realtime
    window.import_video()
    assert len(window.sources) == 1 and window.test_errors
    window.test_errors.clear()
    devices = [{"id": "actual-native-id", "name": "iPhone", "type": "ContinuityCamera"}]
    window.cameras_discovered(devices)
    window.add_camera()
    assert window.sources[-1].value == "actual-native-id"
    assert not window.pipelines  # discovery and import do not pretend to capture
    window.remove_source()
    window.settings_fields["confidence"].setValue(0.1)
    window.apply_settings()
    assert window.test_errors and window.config.confidence == 0.35
    window.populate_settings()
    window.database_edit.setText(str(tmp_path / "existing.sqlite3"))
    window.apply_settings()
    assert window.config.analytics.database.endswith("existing.sqlite3")
    assert read_preferences(tmp_path / "desktop.json").sources == tuple(window.sources)

    def unavailable():
        raise RuntimeError("Native camera unavailable")

    monkeypatch.setattr("roadlens.desktop.list_cameras", unavailable)
    window.discover_cameras()
    spin(qt_app, lambda: not window.jobs)
    assert "Native camera unavailable" in str(window.test_errors[-1])


def test_background_jobs_do_not_block_ui_and_close_waits(window, qt_app):
    release = threading.Event()
    observed = []

    def work():
        assert QThread.currentThread() != qt_app.thread()
        release.wait(5)
        return 3

    assert window.launch_job("slow", work, observed.append)
    beats = []
    timer = QTimer()
    timer.timeout.connect(lambda: beats.append(1))
    timer.start(5)
    spin(qt_app, lambda: len(beats) > 4)
    assert not observed
    window.close()
    assert window.closing and window.isVisible()
    release.set()
    spin(qt_app, lambda: not window.jobs and not window.isVisible())
    timer.stop()


@pytest.mark.model
def test_real_qt_video_pipeline_counts_history_exports_and_failure_isolation(
    window, qt_app, model_path, vehicle_video, tmp_path, monkeypatch
):
    window.config = replace(window.config, model=model_path)
    window.add_source(
        SourceConfig(
            "Recording", "video", str(vehicle_video), False, str(ROOT / "assets/traffic.scene.json")
        )
    )
    window.add_source(SourceConfig("Broken source", "video", str(tmp_path / "missing.avi"), False))
    window.source_list.setCurrentRow(0)
    beats = []
    timer = QTimer()
    timer.timeout.connect(lambda: beats.append(1))
    timer.start(10)
    window.start_all()
    spin(
        qt_app,
        lambda: (
            len(window.pipelines) == 2 and all(p.done.is_set() for p in window.pipelines.values())
        ),
    )
    window.tick()
    timer.stop()
    assert len(beats) > 5
    good = window.pipelines["Recording"]
    assert good.processed == 12 and good.error is None
    assert window.pipelines["Broken source"].error is not None
    assert window.metrics["Crossing events"].text() == "1"
    assert not window.panes["Recording"].preview.image.isNull()
    assert "FAILED" in window.panes["Broken source"].status.text()
    assert good.source.scene != window.sources[0].scene  # immutable session copy
    assert Scene.load(Path(good.source.scene)) == Scene.load(ROOT / "assets/traffic.scene.json")
    spin(qt_app, lambda: not window.jobs)
    window.refresh_history()
    spin(qt_app, lambda: not window.jobs)
    data = window.report_data
    assert data["session"]["status"] == "completed"
    assert data["counts"][0]["count"] == 1
    assert data["counts"][0]["direction"] == "image_up"
    assert window.events.rowCount() == 1
    assert window.history_counts.rowCount() == 1
    assert window.chart.windows and not window.heatmap.image.isNull()
    assert window.history_session == good.traffic.session_id
    database = Path(window.config.analytics.database)
    with TrafficStore(database) as store:
        assert store.rows("sessions")[0]["status"] == "completed"
        for format in ("csv", "json"):
            paths = store.export(tmp_path / format, format, session_id=window.history_session)
            assert len(paths) == 6 and all(path.stat().st_size > 0 for path in paths)
    output = export_pdf(database, window.history_session, tmp_path / "summary.pdf")
    assert output.read_bytes().startswith(b"%PDF-") and b"%%EOF" in output.read_bytes()
    with pytest.raises(FileExistsError):
        export_pdf(database, window.history_session, output)
    # Exercise the actual UI action and PDF worker, including its queued completion.
    completed = []
    window.export_finished = completed.append
    ui_pdf = tmp_path / "ui-export.pdf"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **kw: (str(ui_pdf), ""))
    window.export_format.setCurrentText("PDF")
    window.export_session()
    spin(qt_app, lambda: not window.jobs)
    assert completed == [ui_pdf] and ui_pdf.read_bytes().startswith(b"%PDF-")
    window.grab().save(str(tmp_path / "desktop.png"))


def test_history_is_bounded_filtered_and_never_creates_database(tmp_path):
    database = tmp_path / "history.sqlite3"
    assert read_history(database)["sessions"] == []
    assert not database.exists()
    with TrafficStore(database) as store:
        scene = Scene(
            zones=(Zone("road", "Road", ((0, 0), (1, 0), (1, 1))),),
            lines=(CountingLine("line", (0, 0.5), (1, 0.5)),),
        )
        for _ in range(205):
            session = store.start_session(
                "camera", "Camera", {}, asdict(scene), "key", "video_seconds", "fingerprint"
            )
            store.finish_session(session, "completed")
        store.start_session("other", "Other", {}, asdict(scene), "key", "video_seconds", "other")
    data = read_history(database, camera="Camera")
    assert len(data["sessions"]) == 200
    assert all(row["camera_id"] == "camera" for row in data["sessions"])
    assert read_history(database, camera="absent")["session"] is None
    assert read_history(database, session="' OR 1=1 --")["session"] is None
    empty_image, maximum = heatmap_image(None)
    assert empty_image.isNull() and maximum == 0


def test_frozen_camera_helper_requires_no_build_tools(tmp_path, monkeypatch):
    import sys

    from roadlens.cameras import bridge_path, build_bridge

    executable = tmp_path / "ROADLENS.app/Contents/MacOS/ROADLENS"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(executable))
    helper = bridge_path()
    assert (
        helper
        == executable.parent.parent / "Helpers/ROADLENS Camera.app/Contents/MacOS/roadlens-camera"
    )
    with pytest.raises(FileNotFoundError, match="Bundled camera helper"):
        build_bridge()
    helper.parent.mkdir(parents=True)
    helper.write_bytes(b"test executable fixture")
    assert build_bridge() == helper


def test_bundled_preferences_survive_application_move(tmp_path, monkeypatch):
    import sys

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "first/Resources"), raising=False)
    path = tmp_path / "desktop.json"
    save_preferences(path, default_config(tmp_path))
    assert json.loads(path.read_text())["model"] == "@bundled"
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "moved/Resources"))
    assert read_preferences(path).model == str(tmp_path / "moved/Resources/models/yolov8n.onnx")
    custom = replace(default_config(tmp_path), model=str(tmp_path / "missing-custom.onnx"))
    save_preferences(path, custom)
    assert read_preferences(path).model == custom.model


def test_packaged_entry_uses_persistent_font_cache(tmp_path, monkeypatch):
    import runpy

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr("roadlens.desktop.main", lambda: 0)
    monkeypatch.setenv("MPLCONFIGDIR", "/temporary/bundler/cache")
    with pytest.raises(SystemExit) as result:
        runpy.run_path(str(ROOT / "scripts/desktop_entry.py"))
    assert result.value.code == 0
    cache = tmp_path / "Library/Caches/ROADLENS/matplotlib"
    assert cache.is_dir() and os.environ["MPLCONFIGDIR"] == str(cache)
