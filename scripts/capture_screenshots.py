"""Reproduce public documentation screenshots using only the licensed Intel fixture."""

import argparse
import os
import tempfile
import time
from dataclasses import replace
from pathlib import Path

from PySide6.QtWidgets import QApplication

from roadlens.config import SourceConfig
from roadlens.desktop import DesktopWindow, default_config
from roadlens.desktop_data import read_history
from roadlens.desktop_design import font
from roadlens.desktop_widgets import SceneEditor
from roadlens.traffic.scene import Scene


def main():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=root / "docs/images")
    parser.add_argument("--review", type=Path, help="Additional actual UI states for visual review")
    args = parser.parse_args()
    output = args.output
    if args.review:
        args.review.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    app.setFont(font())
    app.setApplicationName("ROADLENS")
    with tempfile.TemporaryDirectory(prefix="roadlens-public-") as directory:
        data = Path(directory)
        scene = root / "assets/traffic.scene.json"
        config = replace(
            default_config(data),
            sources=(
                SourceConfig(
                    "Public traffic fixture",
                    "video",
                    str(root / "assets/traffic.avi"),
                    realtime=False,
                    scene=str(scene),
                    camera_id="public-fixture",
                ),
            ),
        )
        window = DesktopWindow(config, data)
        window.history_timer.stop()
        window.appearance.setCurrentText("Light")
        window.show()
        window.start_all()
        captured = False
        deadline = time.monotonic() + 60
        while window.any_active() and time.monotonic() < deadline:
            app.processEvents()
            window.tick()
            result = window.latest.get("Public traffic fixture")
            if (
                not captured
                and result
                and result.tracks
                and result.analysis
                and sum(count.count for count in result.analysis.counts)
            ):
                window.statusBar().showMessage(
                    "Recorded public Intel fixture / local CPU inference"
                )
                assert window.grab().save(str(output / "monitor.png"))
                preview = window.panes["Public traffic fixture"].raw_image.copy()
                detections = window.panes["Public traffic fixture"].preview.image.copy()
                captured = True
            time.sleep(0.01)
        pipeline = window.pipelines["Public traffic fixture"]
        assert pipeline.done.is_set() and not pipeline.error and pipeline.processed == 12
        assert captured, "Expected real tracked crossing was not observed"
        window.tick()
        while window.jobs:
            app.processEvents()
            window.tick()
        session = pipeline.traffic.session_id
        data = read_history(Path(config.analytics.database), session=session)
        assert data["counts"][0]["count"] == 1
        window.tabs.setCurrentIndex(1)
        window.history_request += 1
        window.history_loaded((window.history_request, data))
        window.tick()
        window.statusBar().showMessage("Recorded public fixture / one observed car crossing")
        app.processEvents()
        assert window.grab().save(str(output / "history.png"))
        window.tabs.setCurrentIndex(2)
        app.processEvents()
        assert window.grab().save(str(output / "settings.png"))
        window.appearance.setCurrentText("Dark")
        window.tabs.setCurrentIndex(0)
        app.processEvents()
        assert window.grab().save(str(output / "monitor-dark.png"))
        if args.review:
            window.tabs.setCurrentIndex(1)
            app.processEvents()
            assert window.grab().save(str(args.review / "analysis-dark.png"))
            window.tabs.setCurrentIndex(2)
            app.processEvents()
            assert window.grab().save(str(args.review / "settings-dark.png"))
        window.appearance.setCurrentText("Light")
        editor = SceneEditor(Scene.load(scene), preview, window, detection_image=detections)
        editor.show()
        app.processEvents()
        assert editor.grab().save(str(output / "scene-editor.png"))
        if args.review:
            editor.detections.setChecked(True)
            app.processEvents()
            assert editor.grab().save(str(args.review / "scene-editor-detections.png"))
            editor.detections.setChecked(False)
            window.appearance.setCurrentText("Dark")
            app.processEvents()
            assert editor.grab().save(str(args.review / "scene-editor-dark.png"))
            window.appearance.setCurrentText("Light")
        editor.close()
        if args.review:
            window.tabs.setCurrentIndex(0)
            window.show_all.setChecked(True)
            app.processEvents()
            assert window.grab().save(str(args.review / "monitor-all-sources.png"))
            window.show_all.setChecked(False)
            for width, height in ((880, 650), (1920, 1080)):
                window.resize(width, height)
                app.processEvents()
                assert window.grab().save(str(args.review / f"monitor-{width}.png"))
            window.resize(1280, 850)
            window.live_details.toggle.setChecked(True)
            app.processEvents()
            assert window.grab().save(str(args.review / "monitor-details.png"))
        window.close()
        while window.jobs:
            app.processEvents()
            window.tick()
        window.close()
    for name in (
        "monitor.png",
        "history.png",
        "settings.png",
        "monitor-dark.png",
        "scene-editor.png",
    ):
        print(output / name)


if __name__ == "__main__":
    main()
