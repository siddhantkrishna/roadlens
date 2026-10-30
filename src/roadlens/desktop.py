"""Standalone Qt desktop over the existing local camera and traffic engine."""

import argparse
import hashlib
import json
import logging
import os
import platform
import sys
import tempfile
import time
from dataclasses import asdict, replace
from pathlib import Path

import cv2
from PySide6.QtCore import Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QAction, QDesktopServices, QImage
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from roadlens.cameras import list_cameras
from roadlens.cli import configure_logging
from roadlens.config import Config, SourceConfig, load_config
from roadlens.desktop_data import export_pdf, heatmap_image, qimage, read_history
from roadlens.desktop_design import font
from roadlens.desktop_widgets import FlowChart, Preview, SceneEditor, scene_for_source
from roadlens.traffic.models import AnalyticsConfig
from roadlens.traffic.store import TrafficStore

LOG = logging.getLogger(__name__)
STYLE = """
QMainWindow, QDialog { background: #0e1c25; color: #e8f1f5; }
QWidget { font-size: 13px; }
QLabel, QGroupBox { color: #dce9ef; }
QLabel#brand { font-size: 26px; font-weight: 800; color: #64e0c2; }
QLabel#subtitle { color: #96adb9; }
QLabel#metric { font-size: 23px; font-weight: 700; color: #70e2c5; }
QFrame#card, QGroupBox { background: #152934; border: 1px solid #2b424d;
    border-radius: 8px; padding: 8px; }
QGroupBox { margin-top: 12px; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 4px; }
QPushButton { color: #e6f1f4; background: #243d4a; border: 1px solid #3b5663;
    border-radius: 5px; padding: 7px 12px; }
QPushButton:hover { background: #315566; }
QPushButton:disabled { color: #7a919c; background: #1b2d37; }
QPushButton#primary { background: #18745f; border-color: #35b297; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QListWidget, QTextEdit, QTableWidget {
    color: #e7f0f4; background: #11232d; border: 1px solid #36505d;
    border-radius: 4px; padding: 5px; selection-background-color: #236b64; }
QListWidget::item { padding: 9px 3px; }
QHeaderView::section { background: #253d48; color: #bcd0da; padding: 7px; border: 0; }
QTableWidget { gridline-color: #29404b; }
QTabWidget::pane { border: 1px solid #2b414d; background: #0e1c25; }
QTabBar::tab { background: #1a303c; color: #acbfca; padding: 10px 24px; }
QTabBar::tab:selected { color: #72e8cb; background: #25434e; }
QScrollArea { border: 0; background: #0e1c25; }
QStatusBar { color: #afc6d0; background: #132630; }
QToolTip { color: #ffffff; background: #213f4b; border: 1px solid #5a7b8a; }
"""


def default_config(data_dir: Path) -> Config:
    resources = (
        Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[2]
    )
    return Config(
        model=str(resources / "models/yolov8n.onnx"),
        analytics=AnalyticsConfig(database=str(data_dir / "traffic.sqlite3")),
    )


def read_preferences(path: Path) -> Config:
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError("Desktop preferences must be a JSON object")
    data["sources"] = tuple(SourceConfig(**source) for source in data.get("sources", []))
    data["analytics"] = AnalyticsConfig(**data.get("analytics", {}))
    if data.get("model") == "@bundled":
        data["model"] = default_config(path.parent).model
    return Config(**data)


def save_preferences(path: Path, config: Config):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            values = asdict(config)
            if getattr(sys, "frozen", False) and Path(config.model).is_relative_to(sys._MEIPASS):
                values["model"] = "@bundled"
            json.dump(values, stream, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


class Job(QThread):
    completed = Signal(str, object, object)

    def __init__(self, name, function, parent):
        super().__init__(parent)
        self.name, self.function = name, function

    def run(self):
        try:
            result = self.function()
        except Exception as error:
            LOG.exception("Desktop task %s failed", self.name)
            self.completed.emit(self.name, None, error)
        else:
            self.completed.emit(self.name, result, None)


def table(headers):
    widget = QTableWidget(0, len(headers))
    widget.setHorizontalHeaderLabels(headers)
    widget.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    widget.horizontalHeader().setStretchLastSection(True)
    widget.horizontalHeader().setMinimumSectionSize(72)
    for index, heading in enumerate(headers):
        widget.setColumnWidth(index, max(80, widget.fontMetrics().horizontalAdvance(heading) + 30))
    widget.setWordWrap(False)
    widget.setTextElideMode(Qt.TextElideMode.ElideRight)
    widget.verticalHeader().hide()
    widget.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    widget.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    widget.setAlternatingRowColors(False)
    return widget


def fill_table(widget, rows):
    vertical, horizontal = widget.verticalScrollBar().value(), widget.horizontalScrollBar().value()
    first_rows = widget.rowCount() == 0 and bool(rows)
    widget.setUpdatesEnabled(False)
    widget.setRowCount(len(rows))
    for i, row in enumerate(rows):
        for j, value in enumerate(row):
            item = QTableWidgetItem(str(value) if value is not None else "Unavailable")
            item.setToolTip(item.text())
            widget.setItem(i, j, item)
    if first_rows:
        metrics = widget.fontMetrics()
        for column in range(widget.columnCount()):
            heading = metrics.horizontalAdvance(widget.horizontalHeaderItem(column).text()) + 30
            content = max(
                (metrics.horizontalAdvance(str(row[column])) for row in rows[:200]), default=0
            )
            widget.setColumnWidth(column, max(heading, min(360, content + 20)))
    widget.verticalScrollBar().setValue(vertical)
    widget.horizontalScrollBar().setValue(horizontal)
    widget.setUpdatesEnabled(True)


class SourcePane(QFrame):
    def __init__(self, source):
        super().__init__()
        self.setObjectName("card")
        layout = QVBoxLayout(self)
        self.title = QLabel(source.name)
        self.title.setFont(font("section", bold=True))
        self.title.setWordWrap(True)
        self.title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.title.setToolTip(source.name)
        layout.addWidget(self.title)
        self.preview = Preview()
        layout.addWidget(self.preview, 1)
        self.status = QLabel("Stopped • no camera opened")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)


class DesktopWindow(QMainWindow):
    def __init__(self, config: Config, data_dir: Path, *, pipeline_factory=None):
        super().__init__()
        from roadlens.pipeline import Pipeline

        self.config, self.data_dir = config, data_dir
        self.pipeline_factory = pipeline_factory or Pipeline
        self.sources = list(config.sources)
        self.pipelines = {}
        self.latest = {}
        self.received = {}
        self.panes = {}
        self.jobs = {}
        self.callbacks = {}
        self.closing = False
        self.history_request = 0
        self.history_session = None
        self.history_rows = []
        self.report_data = None
        self.last_read_error = None
        self.last_diagnostic = 0.0
        self.settings_changed = set()
        self.setWindowTitle("ROADLENS • Local traffic intelligence")
        self.resize(1380, 940)
        self.setMinimumSize(1040, 720)
        self.setStyleSheet(STYLE)
        self.build_ui()
        self.sync_sources()
        self.populate_settings()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(60)
        self.history_timer = QTimer(self)
        self.history_timer.timeout.connect(self.refresh_history)
        self.history_timer.start(2000)
        self.refresh_history()

    def build_ui(self):
        content = QWidget()
        outer = QVBoxLayout(content)
        outer.setContentsMargins(20, 16, 20, 12)
        header = QHBoxLayout()
        brand = QLabel("ROADLENS")
        brand.setObjectName("brand")
        header.addWidget(brand)
        subtitle = QLabel("TRAFFIC INTELLIGENCE  /  ON THIS MAC")
        subtitle.setObjectName("subtitle")
        header.addWidget(subtitle)
        header.addStretch()
        self.global_status = QLabel("Ready • local CPU inference")
        header.addWidget(self.global_status)
        outer.addLayout(header)
        self.tabs = QTabWidget()
        outer.addWidget(self.tabs)
        self.tabs.currentChanged.connect(self.refresh_history)
        self.build_monitor()
        self.build_history()
        self.build_settings()
        self.setCentralWidget(content)
        file_menu = self.menuBar().addMenu("File")
        for label, shortcut, callback in (
            ("Import video…", "Ctrl+O", self.import_video),
            ("Import TOML configuration…", "", self.import_config),
            ("Export selected session…", "Ctrl+E", self.export_session),
            ("Close", "Ctrl+W", self.close),
        ):
            action = QAction(label, self)
            if shortcut:
                action.setShortcut(shortcut)
            action.triggered.connect(callback)
            file_menu.addAction(action)
        help_menu = self.menuBar().addMenu("Help")
        action = help_menu.addAction("Camera permissions and Continuity Camera")
        action.triggered.connect(self.camera_help)
        action = help_menu.addAction("Open source license")
        action.triggered.connect(self.open_license)
        action = help_menu.addAction("About ROADLENS")
        action.triggered.connect(
            lambda: QMessageBox.about(
                self,
                "About ROADLENS",
                "ROADLENS 0.1.0\nCopyright (C) 2026 ROADLENS contributors\n"
                "AGPL-3.0-only. You may copy, modify and redistribute under that license.\n"
                "Provided WITHOUT ANY WARRANTY. Help → Open source license shows the terms.\n"
                "PySide6 / OpenCV DNN / ByteTrack / SQLite\n"
                "No cloud inference. Model: Ultralytics YOLOv8n (AGPL-3.0/commercial).\n"
                "PySide6/Qt: LGPLv3/GPLv3/commercial. See bundled licenses.",
            )
        )
        self.statusBar().showMessage(f"Database: {self.config.analytics.database}")

    def button(self, title, callback, layout, *, primary=False):
        button = QPushButton(title)
        button.clicked.connect(callback)
        if primary:
            button.setObjectName("primary")
        layout.addWidget(button)
        return button

    def build_monitor(self):
        page = QWidget()
        layout = QHBoxLayout(page)
        side = QVBoxLayout()
        layout.addLayout(side, 1)
        side.addWidget(QLabel("SOURCES"))
        self.source_list = QListWidget()
        self.source_list.setMinimumWidth(190)
        self.source_list.setMaximumWidth(280)
        self.source_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.source_list.setAccessibleName("Sources; selected source drives live statistics")
        self.source_list.currentRowChanged.connect(self.selection_changed)
        side.addWidget(self.source_list, 1)
        self.camera_selector = QComboBox()
        self.camera_selector.setAccessibleName("Discovered MacBook and iPhone cameras")
        side.addWidget(self.camera_selector)
        self.discover_button = self.button("Discover cameras", self.discover_cameras, side)
        self.button("Add selected camera", self.add_camera, side)
        self.button("Import video…", self.import_video, side)
        self.start_button = self.button("Start selected", self.start_selected, side, primary=True)
        self.button("Start all", self.start_all, side)
        self.stop_button = self.button("Stop selected", self.stop_selected, side)
        self.button("Stop all", self.stop_all, side)
        self.edit_button = self.button("Configure scene…", self.edit_scene, side)
        self.remove_button = self.button("Remove source", self.remove_source, side)
        hint = QLabel(
            "Select a source for its counts.\nTwo feeds recommended on Intel.\n"
            "Unconfigured zones/lines show unavailable metrics."
        )
        hint.setWordWrap(True)
        side.addWidget(hint)
        main = QVBoxLayout()
        layout.addLayout(main, 4)
        self.gallery_widget = QWidget()
        self.gallery_widget.setStyleSheet("background: #0e1c25;")
        self.gallery = QGridLayout(self.gallery_widget)
        self.empty = QLabel(
            "Add a camera or import a video to begin.\nCamera discovery never starts capture."
        )
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.gallery.addWidget(self.empty, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.gallery_widget)
        main.addWidget(scroll, 4)
        cards = QHBoxLayout()
        self.metrics = {}
        for title in ("Visible tracks", "Crossing events", "Queued vehicles", "Congestion"):
            card = QFrame()
            card.setObjectName("card")
            stack = QVBoxLayout(card)
            stack.addWidget(QLabel(title.upper()))
            value = QLabel("—")
            value.setObjectName("metric")
            value.setWordWrap(True)
            value.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            value.setAccessibleName(title)
            stack.addWidget(value)
            cards.addWidget(card)
            self.metrics[title] = value
        main.addLayout(cards)
        self.live_status = QLabel("No source selected")
        self.live_status.setWordWrap(True)
        main.addWidget(self.live_status)
        details = QSplitter(Qt.Orientation.Horizontal)
        self.count_table = table(["Line", "Vehicle", "Direction", "Crossings"])
        self.zone_table = table(["Zone", "Vehicles", "Image occupancy", "Queue", "Congestion"])
        details.addWidget(self.count_table)
        details.addWidget(self.zone_table)
        main.addWidget(details, 2)
        self.tabs.addTab(page, "Monitor")

    def build_history(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        toolbar = QHBoxLayout()
        self.history_camera = QLineEdit()
        self.history_camera.setPlaceholderText("Exact camera name or ID; empty = all cameras")
        self.history_camera.setAccessibleName("Filter session history by camera")
        self.history_camera.returnPressed.connect(self.reset_history)
        toolbar.addWidget(self.history_camera, 1)
        self.button("Refresh / filter", self.reset_history, toolbar)
        self.export_format = QComboBox()
        self.export_format.addItems(["PDF", "CSV", "JSON"])
        self.export_format.setAccessibleName("Session export format")
        toolbar.addWidget(self.export_format)
        self.export_button = self.button("Export selected session…", self.export_session, toolbar)
        self.heatmap_export_button = self.button(
            "Export heatmap PNG…", self.export_heatmap, toolbar
        )
        layout.addLayout(toolbar)
        self.sessions = table(["Camera", "Started (UTC)", "Status", "Clock", "Session"])
        self.sessions.setMaximumHeight(200)
        self.sessions.itemSelectionChanged.connect(self.history_selected)
        layout.addWidget(self.sessions)
        self.history_status = QLabel("No saved sessions yet")
        self.history_status.setWordWrap(True)
        layout.addWidget(self.history_status)
        flow_controls = QHBoxLayout()
        flow_controls.addWidget(QLabel("Flow series:"))
        self.flow_series = QComboBox()
        self.flow_series.setAccessibleName(
            "Counting line, direction and vehicle class for flow chart"
        )
        self.flow_series.currentTextChanged.connect(self.change_flow_series)
        flow_controls.addWidget(self.flow_series, 1)
        layout.addLayout(flow_controls)
        charts = QHBoxLayout()
        self.chart = FlowChart()
        charts.addWidget(self.chart)
        heatmap_box = QVBoxLayout()
        self.heatmap = Preview()
        heatmap_box.addWidget(self.heatmap, 1)
        self.heatmap_caption = QLabel("Heatmap unavailable until observations are saved")
        self.heatmap_caption.setWordWrap(True)
        heatmap_box.addWidget(self.heatmap_caption)
        charts.addLayout(heatmap_box)
        layout.addLayout(charts, 2)
        self.history_counts = table(["Line", "Vehicle", "Direction", "Crossings"])
        self.history_counts.setMaximumHeight(135)
        layout.addWidget(self.history_counts)
        self.events = table(["Source time (s)", "Event / anomaly", "Object", "Vehicle", "Details"])
        layout.addWidget(self.events, 1)
        note = QLabel(
            "Latest 200 sessions, 200 events and 240 measurement windows shown. "
            "CSV/JSON include all records for the selected session. Rates use observed time; "
            "camera overlap is not deduplicated."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        self.tabs.addTab(page, "History and analysis")

    def build_settings(self):
        page = QWidget()
        layout = QHBoxLayout(page)
        group = QGroupBox("Camera and inference settings • apply between sessions")
        form = QFormLayout(group)
        self.model_edit = QLineEdit()
        self.database_edit = QLineEdit()
        for label, widget, callback in (
            ("ONNX model", self.model_edit, self.choose_model),
            ("SQLite database", self.database_edit, self.choose_database),
        ):
            row = QHBoxLayout()
            row.addWidget(widget)
            self.button("Browse…", callback, row)
            form.addRow(label, row)
        self.settings_fields = {}
        for key, label, low, high, decimals in (
            ("width", "Requested width", 160, 3840, 0),
            ("height", "Requested height", 120, 2160, 0),
            ("capture_fps", "Requested camera FPS", 1, 120, 0),
            ("inference_fps", "Inference cap / source", 0.1, 30, 1),
            ("threads", "OpenCV CPU threads", 1, 16, 0),
            ("confidence", "Display confidence", 0.1, 0.99, 2),
            ("detection_floor", "Detection floor", 0.1, 0.98, 2),
            ("track_activation", "Track activation", 0.11, 0.99, 2),
            ("retention_days", "Session retention (days)", 1, 36500, 0),
            ("window_seconds", "Flow window (seconds)", 0.1, 3600, 1),
            ("queue_min_vehicles", "Minimum queue vehicles", 1, 1000, 0),
            ("queue_seconds", "Queue persistence (seconds)", 0.1, 3600, 1),
            ("congestion_occupancy", "Congestion image occupancy", 0.01, 1, 2),
        ):
            widget = QDoubleSpinBox() if decimals else QSpinBox()
            widget.setRange(low, high)
            if decimals:
                widget.setDecimals(decimals)
                widget.setSingleStep(0.01 if decimals == 2 else 0.1)
            widget.setAccessibleName(label)
            widget.valueChanged.connect(lambda _, key=key: self.settings_changed.add(key))
            widget.lineEdit().textEdited.connect(lambda _, key=key: self.settings_changed.add(key))
            self.settings_fields[key] = widget
            form.addRow(label, widget)
        self.apply_button = QPushButton("Apply and save settings")
        self.apply_button.setObjectName("primary")
        self.apply_button.clicked.connect(self.apply_settings)
        form.addRow(self.apply_button)
        button = QPushButton("Import existing TOML configuration…")
        button.clicked.connect(self.import_config)
        form.addRow(button)
        note = QLabel(
            "Resolution/FPS are requests negotiated by macOS. "
            "CPU defaults: 2 threads, 8 inferences/sec per source. "
            "Completed sessions older than retention are pruned by the existing service "
            "when a new analysis starts. Export valuable history before reducing retention."
        )
        note.setWordWrap(True)
        form.addRow(note)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(group)
        layout.addWidget(scroll, 1)
        diagnostics = QVBoxLayout()
        layout.addLayout(diagnostics, 1)
        diagnostics.addWidget(QLabel("DIAGNOSTICS"))
        self.diagnostics = QTextEdit()
        self.diagnostics.setReadOnly(True)
        self.diagnostics.setToolTip(
            "Live diagnostics update once per second; pause while focused for copying."
        )
        diagnostics.addWidget(self.diagnostics, 1)
        self.button("Camera permission help", self.camera_help, diagnostics)
        self.button("Open local data folder", self.open_data, diagnostics)
        self.tabs.addTab(page, "Settings and diagnostics")

    def selected_source(self):
        index = self.source_list.currentRow()
        return self.sources[index] if 0 <= index < len(self.sources) else None

    def active(self, name):
        pipeline = self.pipelines.get(name)
        return pipeline is not None and not pipeline.done.is_set()

    def any_active(self):
        return any(self.active(name) for name in self.pipelines)

    def persist(self):
        try:
            self.config = replace(self.config, sources=tuple(self.sources))
            save_preferences(self.data_dir / "desktop.json", self.config)
            return True
        except (OSError, ValueError, TypeError) as error:
            self.show_error(error)
            return False

    def sync_sources(self):
        previous = self.selected_source()
        self.source_list.blockSignals(True)
        self.source_list.clear()
        for source in self.sources:
            self.source_list.addItem(
                f"{source.name}\n{source.kind} • {source.camera_id or source.name}"
            )
            self.source_list.item(self.source_list.count() - 1).setToolTip(
                f"{source.name}\n{source.value}\nCamera ID: {source.camera_id or source.name}"
            )
        for name, pane in list(self.panes.items()):
            if name not in {s.name for s in self.sources}:
                self.gallery.removeWidget(pane)
                pane.deleteLater()
                del self.panes[name]
        self.empty.setVisible(not self.sources)
        for index, source in enumerate(self.sources):
            if source.name not in self.panes:
                self.panes[source.name] = SourcePane(source)
            self.gallery.addWidget(self.panes[source.name], index // 2, index % 2)
        selected = next(
            (i for i, s in enumerate(self.sources) if previous and s.name == previous.name), 0
        )
        self.source_list.setCurrentRow(selected if self.sources else -1)
        self.source_list.blockSignals(False)
        self.selection_changed()

    def selection_changed(self):
        if not hasattr(self, "live_status"):
            return
        source = self.selected_source()
        result = self.latest.get(source.name) if source else None
        self.update_live(result)

    def add_source(self, source):
        try:
            replace(self.config, sources=(*self.sources, source))
        except ValueError as error:
            self.show_error(error)
            return
        self.sources.append(source)
        self.sync_sources()
        self.source_list.setCurrentRow(len(self.sources) - 1)
        self.persist()

    def discover_cameras(self):
        self.discover_button.setEnabled(False)
        self.statusBar().showMessage("Discovering AVFoundation devices…")
        self.launch_job("cameras", list_cameras, self.cameras_discovered)

    def cameras_discovered(self, devices):
        self.camera_selector.clear()
        for device in devices:
            kind = "iPhone" if "Continuity" in device["type"] else "Mac / external"
            self.camera_selector.addItem(f"{device['name']} ({kind})", device)
        self.statusBar().showMessage(f"{len(devices)} camera(s) available; no capture started")

    def add_camera(self):
        device = self.camera_selector.currentData()
        if not device:
            self.show_error(
                ValueError("Discover cameras first. An absent iPhone must be enabled in macOS.")
            )
            return
        identity = hashlib.sha256(device["id"].encode()).hexdigest()[:12]
        name = device["name"]
        if any(s.name == name and s.value != device["id"] for s in self.sources):
            name = f"{name} [{identity[:5]}]"
        self.add_source(SourceConfig(name, "camera", device["id"], camera_id=f"camera-{identity}"))

    def import_video(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Import video", "", "Video (*.mp4 *.mov *.m4v *.avi *.mkv);;All files (*)"
        )
        for path in paths:
            identity = hashlib.sha256(str(Path(path).resolve()).encode()).hexdigest()[:12]
            self.add_source(
                SourceConfig(
                    f"{Path(path).stem} [{identity[:5]}]",
                    "video",
                    str(Path(path).resolve()),
                    realtime=False,
                    camera_id=f"video-{identity}",
                )
            )
        if paths:
            self.statusBar().showMessage("Video imported. Start selected to analyze every frame.")

    def start_source(self, source):
        if self.closing or self.active(source.name):
            return
        try:
            if not Path(self.config.model).is_file():
                raise FileNotFoundError(
                    "Choose a local ONNX model in Settings. Development setup: roadlens fetch-model"
                )
            scene = scene_for_source(source.scene)
            scene_path = self.data_dir / "scenes" / f"{scene.fingerprint}.json"
            scene.save(scene_path)
            runtime = replace(source, scene=str(scene_path))
            config = replace(self.config, sources=tuple(self.sources))
            pipeline = self.pipeline_factory(runtime, config)
            self.pipelines[source.name] = pipeline
            self.latest.pop(source.name, None)
            self.received.pop(source.name, None)
            self.panes[source.name].preview.set_image(QImage())
            if source == self.selected_source():
                self.update_live(None)
            pipeline.start()
            self.statusBar().showMessage(f"Starting {source.name}…")
        except (OSError, ValueError, TypeError, RuntimeError) as error:
            self.show_error(error)

    def start_selected(self):
        if source := self.selected_source():
            self.start_source(source)

    def start_all(self):
        for source in self.sources:
            self.start_source(source)

    def stop_selected(self):
        if (source := self.selected_source()) and self.active(source.name):
            self.pipelines[source.name].stop()

    def stop_all(self):
        for pipeline in self.pipelines.values():
            if not pipeline.done.is_set():
                pipeline.stop()

    def remove_source(self):
        source = self.selected_source()
        if not source or self.active(source.name):
            return
        self.sources.remove(source)
        self.pipelines.pop(source.name, None)
        self.latest.pop(source.name, None)
        self.received.pop(source.name, None)
        self.sync_sources()
        self.persist()

    def edit_scene(self):
        source = self.selected_source()
        if not source or self.active(source.name):
            return
        try:
            editor = SceneEditor(
                scene_for_source(source.scene), self.panes[source.name].preview.image, self
            )
            if editor.exec() == QDialog.DialogCode.Accepted:
                path = self.data_dir / "scenes" / f"{editor.scene.fingerprint}.json"
                editor.scene.save(path)
                self.sources[self.sources.index(source)] = replace(source, scene=str(path))
                if self.persist():
                    self.statusBar().showMessage(
                        "Scene saved. Start the source to begin a new session."
                    )
        except (OSError, ValueError, TypeError, KeyError) as error:
            self.show_error(error)

    def update_live(self, result):
        if result is None:
            for label in self.metrics.values():
                label.setText("—")
            fill_table(self.count_table, [])
            fill_table(self.zone_table, [])
            self.live_status.setText("Start the selected source to see its measurements.")
            return
        snapshot = result.analysis
        self.metrics["Visible tracks"].setText(str(len(result.tracks)))
        if snapshot is None:
            self.update_live(None)
            self.metrics["Visible tracks"].setText(str(len(result.tracks)))
            self.live_status.setText("Traffic analysis unavailable for this result.")
            return
        self.metrics["Crossing events"].setText(
            str(sum(c.count for c in snapshot.counts))
            if snapshot.counting_available
            else "No lines"
        )
        queues = [z.queued_vehicles for z in snapshot.zones if z.queued_vehicles is not None]
        # Overlapping zones can contain the same queue; never sum them as unique vehicles.
        self.metrics["Queued vehicles"].setText(str(max(queues)) if queues else "No queue zone")
        conditions = {z.congestion for z in snapshot.zones}
        congestion = next(
            (state for state in ("congested", "observing", "free") if state in conditions),
            "Unavailable" if conditions else "No road zone",
        )
        self.metrics["Congestion"].setText(congestion or "No road zone")
        fill_table(
            self.count_table,
            [(c.line_id, c.category, c.direction, c.count) for c in snapshot.counts],
        )
        fill_table(
            self.zone_table,
            [
                (
                    z.zone_id,
                    z.vehicles,
                    f"{z.image_occupancy:.1%}" if z.image_occupancy is not None else None,
                    z.queued_vehicles,
                    z.congestion,
                )
                for z in snapshot.zones
            ],
        )
        available = [s.mps for s in snapshot.speeds if s.mps is not None]
        speed = (
            f"Mean calibrated speed {sum(available) / len(available):.2f} m/s"
            if available
            else (
                "Speed unavailable: "
                + (snapshot.speed_unavailable_reason or "insufficient observations")
            )
        )
        baseline = (
            "ready" if snapshot.baseline_ready else f"warming ({snapshot.baseline_windows} windows)"
        )
        self.live_status.setText(
            f"Source time {snapshot.source_time:.2f}s • {speed} • "
            f"Anomaly baseline {baseline}. Queue card = largest zone queue."
        )

    def tick(self):
        now = time.monotonic()
        for source in self.sources:
            pipeline = self.pipelines.get(source.name)
            if pipeline is None:
                continue
            result = pipeline.results.get(timeout=0)
            if result is not None:
                self.latest[source.name] = result
                self.received[source.name] = now
                self.panes[source.name].preview.set_image(qimage(result.image))
                if source == self.selected_source():
                    self.update_live(result)
            if pipeline.error:
                state = "failed"
            elif pipeline.done.is_set():
                state = "completed" if pipeline.capture.state == "eof" else "stopped"
            elif pipeline.stop_event.is_set():
                state = "stopping"
            else:
                state = pipeline.capture.state
            age = now - self.received[source.name] if source.name in self.received else None
            if (
                state == "running"
                and age is not None
                and age > max(2, 2 / pipeline.config.inference_fps)
            ):
                state = "stale / waiting for frames"
            status = f"{state.upper()} • {pipeline.processed} frames • "
            status += f"last frame {age:.1f}s ago" if age is not None else "waiting for first frame"
            if pipeline.error:
                status += f" • {pipeline.error}"
            elif pipeline.capture.last_error:
                status += f" • {pipeline.capture.last_error}"
            self.panes[source.name].status.setText(status)
        source = self.selected_source()
        running = bool(source and self.active(source.name))
        self.start_button.setEnabled(bool(source) and not running and not self.closing)
        self.stop_button.setEnabled(running)
        self.edit_button.setEnabled(bool(source) and not running)
        self.remove_button.setEnabled(bool(source) and not running)
        self.apply_button.setEnabled(not self.any_active())
        self.discover_button.setEnabled("cameras" not in self.jobs and not self.closing)
        export_ready = bool(self.history_session and self.report_data) and "export" not in self.jobs
        self.export_button.setEnabled(export_ready)
        self.heatmap_export_button.setEnabled(export_ready)
        active = sum(self.active(name) for name in self.pipelines)
        self.global_status.setText(f"{active} active source(s) • CPU • local SQLite")
        if self.tabs.currentIndex() == 2 and now - self.last_diagnostic >= 1:
            self.last_diagnostic = now
            self.update_diagnostics()
        for name, job in list(self.jobs.items()):
            if job.isFinished() and name not in self.callbacks:
                del self.jobs[name]
                job.deleteLater()
        if self.closing and not self.any_active() and not self.jobs:
            self.close()

    def update_diagnostics(self):
        if self.diagnostics.hasFocus():
            return
        lines = [
            f"ROADLENS 0.1.0 | Python {platform.python_version()} | {platform.machine()}",
            f"{platform.platform()} | OpenCV {cv2.__version__}",
            f"Model: {self.config.model}",
            f"Database: {self.config.analytics.database}",
            f"Data folder: {self.data_dir}",
            f"Threads: {self.config.threads} | inference cap: {self.config.inference_fps}/sec",
            "No live hardware validation is implied by camera discovery.",
        ]
        for name, pipeline in self.pipelines.items():
            result = self.latest.get(name)
            capture = pipeline.capture
            lines.extend(
                [
                    f"\n{name}: {capture.state} | resolved device: {capture.device_id}",
                    f"capture {capture.capture_fps:.2f} fps | "
                    f"output {pipeline.inference_fps:.2f} fps",
                    f"processed {pipeline.processed} | drops {capture.frames.dropped} | "
                    f"reconnects {capture.reconnects}",
                ]
            )
            if result:
                lines.append(
                    f"inference {result.inference_ms:.1f} ms | "
                    f"frame age {result.latency_ms:.1f} ms | epoch {result.epoch}"
                )
            if pipeline.error:
                lines.append(f"ERROR: {pipeline.error}")
            elif capture.last_error:
                lines.append(f"Last capture error: {capture.last_error}")
        self.diagnostics.setPlainText("\n".join(lines))

    def launch_job(self, name, function, callback):
        if name in self.jobs or self.closing:
            return False
        job = Job(name, function, self)
        self.jobs[name] = job
        self.callbacks[name] = callback
        job.completed.connect(self.job_completed)
        job.start()
        return True

    @Slot(str, object, object)
    def job_completed(self, name, result, error):
        callback = self.callbacks.pop(name, None)
        if self.closing:
            return
        try:
            if error:
                raise error
            if callback:
                callback(result)
        except Exception as failure:
            LOG.exception("Desktop task %s completion failed", name)
            if name == "history":
                self.report_data = None
                self.chart.set_windows([])
                self.heatmap.set_image(QImage())
                self.heatmap_caption.setText("Heatmap unavailable while history cannot be read")
                fill_table(self.history_counts, [])
                fill_table(self.events, [])
                self.history_status.setText(f"History unavailable: {failure}")
                if str(failure) != self.last_read_error:
                    self.statusBar().showMessage(f"History unavailable: {failure}")
                    self.last_read_error = str(failure)
            else:
                self.show_error(failure)

    def reset_history(self):
        self.history_session = None
        self.history_request += 1
        self.refresh_history()

    def history_selected(self):
        index = self.sessions.currentRow()
        if 0 <= index < len(self.history_rows):
            self.history_session = self.history_rows[index]["id"]
            self.history_request += 1
            self.refresh_history()

    def refresh_history(self, *args):
        if not hasattr(self, "history_camera") or self.closing:
            return
        request = self.history_request
        session = self.history_session
        # On Monitor, follow the selected source's current session in the background.
        if self.tabs.currentIndex() == 0 and (source := self.selected_source()):
            pipeline = self.pipelines.get(source.name)
            if pipeline and pipeline.traffic and pipeline.traffic.session_id:
                session = pipeline.traffic.session_id
        database = Path(self.config.analytics.database)
        camera = self.history_camera.text().strip()
        self.launch_job(
            "history",
            lambda: (request, read_history(database, camera, session)),
            self.history_loaded,
        )

    def history_loaded(self, payload):
        request, data = payload
        if request != self.history_request:
            return
        self.last_read_error = None
        self.report_data = data
        self.history_rows = data["sessions"]
        selected = data["session"]
        self.history_session = selected["id"] if selected else None
        self.sessions.blockSignals(True)
        fill_table(
            self.sessions,
            [
                (r["name"], r["started_at"], r["status"], r["clock_kind"], r["id"])
                for r in self.history_rows
            ],
        )
        for index, row in enumerate(self.history_rows):
            if row["id"] == self.history_session:
                self.sessions.selectRow(index)
                break
        self.sessions.blockSignals(False)
        series = sorted({key for w in data["windows"] for key in w["flow_per_minute"]})
        selected_series = self.flow_series.currentText()
        if selected_series not in series and series:
            selected_series = max(
                series,
                key=lambda key: max(
                    (w["flow_per_minute"].get(key) or 0 for w in data["windows"]), default=0
                ),
            )
        self.flow_series.blockSignals(True)
        self.flow_series.clear()
        self.flow_series.addItems(series)
        self.flow_series.setCurrentText(selected_series)
        self.flow_series.blockSignals(False)
        self.chart.series = selected_series
        self.chart.set_windows(data["windows"])
        image, maximum = heatmap_image(data["heatmap"])
        self.heatmap.set_image(image)
        self.heatmap_caption.setText(
            f"Observed dwell • relative scale 0–{maximum:.3f} vehicle-seconds/cell"
            if not image.isNull()
            else "No saved dwell observations yet"
        )
        fill_table(
            self.history_counts,
            [(c["object_id"], c["category"], c["direction"], c["count"]) for c in data["counts"]],
        )
        fill_table(
            self.events,
            [
                (
                    f"{e['source_time']:.2f}",
                    e["kind"],
                    e["object_id"],
                    e["category"],
                    e["details_json"] if e["kind"] != "crossing" else e["direction"],
                )
                for e in data["events"]
            ],
        )
        if selected:
            settings = json.loads(selected["settings_json"])
            parameters = settings.get("parameters", {})
            latest = data["windows"][-1] if data["windows"] else {}
            baseline = latest.get("baseline_ready")
            self.history_status.setText(
                f"{selected['name']} • {selected['status']} • session {selected['id']} • "
                f"{data['event_total']} recorded event(s) • "
                f"baseline {'ready' if baseline else 'warming / unavailable'} • "
                f"window {parameters.get('window_seconds', '?')}s"
            )
        else:
            self.history_status.setText("No saved sessions match this camera.")

    def change_flow_series(self, series):
        if hasattr(self, "chart"):
            self.chart.series = series
            self.chart.update()

    def export_session(self):
        if "export" in self.jobs:
            self.statusBar().showMessage("An export is already running.")
            return
        if not self.history_session or not self.report_data:
            self.show_error(ValueError("Select a saved session in History and analysis first"))
            return
        database = Path(self.config.analytics.database)
        session = self.history_session
        format = self.export_format.currentText().lower()
        if format == "pdf":
            path, _ = QFileDialog.getSaveFileName(
                self, "Export PDF session summary", f"ROADLENS-{session[:12]}.pdf", "PDF (*.pdf)"
            )
            if not path:
                return

            def function():
                return export_pdf(database, session, Path(path))
        else:
            directory = QFileDialog.getExistingDirectory(self, "Choose parent export folder")
            if not directory:
                return
            destination = Path(directory) / f"ROADLENS-{session[:12]}-{time.time_ns()}"

            def function():
                if not database.is_file():
                    raise FileNotFoundError(database)
                with TrafficStore(database) as store:
                    if not store.rows("sessions", session_id=session):
                        raise ValueError("The selected session no longer exists")
                    return store.export(destination, format, session_id=session)

        self.launch_job("export", function, self.export_finished)

    def export_heatmap(self):
        if "export" in self.jobs:
            self.statusBar().showMessage("An export is already running.")
            return
        if not self.history_session or not self.report_data:
            return
        from roadlens.traffic.service import render_heatmap

        session = self.history_session
        database = Path(self.config.analytics.database)
        path, _ = QFileDialog.getSaveFileName(
            self, "Export collected heatmap", "heatmap.png", "PNG (*.png)"
        )
        if path:

            def export():
                if not database.is_file():
                    raise FileNotFoundError(database)
                with TrafficStore(database) as store:
                    render_heatmap(store, session, Path(path))
                return Path(path)

            self.launch_job("export", export, self.export_finished)

    def export_finished(self, result):
        paths = ", ".join(str(p) for p in result) if isinstance(result, list) else str(result)
        self.statusBar().showMessage(f"Exported: {paths}")
        QMessageBox.information(self, "Export complete", paths)

    def populate_settings(self):
        self.model_edit.setText(self.config.model)
        self.database_edit.setText(self.config.analytics.database or "")
        self.settings_changed.clear()
        for key, widget in self.settings_fields.items():
            configured = (
                getattr(self.config, key)
                if hasattr(self.config, key)
                else getattr(self.config.analytics, key)
            )
            widget.setToolTip(
                f"Exact configured value: {configured}; retained until this field is edited."
            )
            widget.blockSignals(True)
            widget.setValue(max(widget.minimum(), min(widget.maximum(), configured)))
            widget.blockSignals(False)

    def apply_settings(self):
        if self.any_active():
            self.show_error(ValueError("Stop all sources before applying settings"))
            return
        try:
            values = {
                key: widget.value()
                for key, widget in self.settings_fields.items()
                if hasattr(self.config, key) and key in self.settings_changed
            }
            analytics = {
                key: widget.value()
                for key, widget in self.settings_fields.items()
                if not hasattr(self.config, key) and key in self.settings_changed
            }
            if not self.database_edit.text().strip():
                raise ValueError("Choose a SQLite database path")
            model = str(Path(self.model_edit.text()).expanduser().resolve())
            database = str(Path(self.database_edit.text()).expanduser().resolve())
            config = replace(
                self.config,
                **values,
                model=model,
                analytics=replace(self.config.analytics, **analytics, database=database),
            )
            save_preferences(
                self.data_dir / "desktop.json", replace(config, sources=tuple(self.sources))
            )
            self.config = config
            self.populate_settings()
            cv2.setNumThreads(config.threads)
            self.history_session = None
            self.history_request += 1
            self.refresh_history()
            self.statusBar().showMessage(f"Settings saved • database: {database}")
        except (OSError, ValueError, TypeError) as error:
            self.show_error(error)

    def choose_model(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose trusted YOLOv8 ONNX model", "", "ONNX (*.onnx)"
        )
        if path:
            self.model_edit.setText(path)

    def choose_database(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Open existing or create SQLite database",
            self.database_edit.text(),
            "SQLite (*.sqlite3 *.db)",
            options=QFileDialog.Option.DontConfirmOverwrite,
        )
        if path:
            self.database_edit.setText(path)

    def import_config(self):
        if self.any_active():
            self.show_error(ValueError("Stop all sources before importing configuration"))
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Import ROADLENS configuration", "", "TOML (*.toml)"
        )
        if path:
            try:
                config = load_config(Path(path))
                config = replace(
                    config,
                    model=str(Path(config.model).expanduser().resolve()),
                    analytics=replace(
                        config.analytics,
                        database=str(
                            Path(config.analytics.database or self.config.analytics.database)
                            .expanduser()
                            .resolve()
                        ),
                    ),
                    sources=tuple(
                        replace(
                            s,
                            value=str(Path(s.value).expanduser().resolve())
                            if s.kind == "video"
                            else s.value,
                            scene=str(Path(s.scene).expanduser().resolve()) if s.scene else None,
                        )
                        for s in config.sources
                    ),
                )
                save_preferences(self.data_dir / "desktop.json", config)
                self.config, self.sources = config, list(config.sources)
                self.pipelines.clear()
                self.latest.clear()
                self.received.clear()
                cv2.setNumThreads(config.threads)
                self.sync_sources()
                self.populate_settings()
                self.reset_history()
            except (OSError, ValueError, TypeError) as error:
                self.show_error(error)

    def open_license(self):
        from PySide6.QtCore import QUrl

        path = (
            Path(sys._MEIPASS) / "licenses/LICENSE"
            if getattr(sys, "frozen", False)
            else Path(__file__).resolve().parents[2] / "LICENSE"
        )
        if not path.is_file():
            self.show_error(FileNotFoundError("The ROADLENS license file is missing"))
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def open_data(self):
        from PySide6.QtCore import QUrl

        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.data_dir)))

    def camera_help(self):
        QMessageBox.information(
            self,
            "Camera access on macOS",
            "Click Discover cameras, add the actual device, then Start. "
            "Accept the macOS camera prompt.\n\n"
            "If denied: System Settings → Privacy & Security → Camera. Enable ROADLENS / "
            "ROADLENS Camera or the launching terminal, then restart capture.\n\n"
            "For iPhone: enable Continuity Camera in Settings → General → AirPlay & Continuity. "
            "Use the same Apple Account with two-factor authentication; "
            "enable Wi-Fi and Bluetooth, "
            "keep the iPhone nearby, locked and mounted, or use a trusted USB cable. "
            "Discovery can only show devices made available by macOS.\n\n"
            "Camera hardware, reconnects and permissions require "
            "physical verification on your Mac.",
        )

    def show_error(self, error):
        LOG.error("%s", error)
        self.statusBar().showMessage(str(error))
        QMessageBox.warning(self, "ROADLENS", str(error))

    def closeEvent(self, event):
        if self.any_active() or self.jobs:
            event.ignore()
            self.closing = True
            self.history_timer.stop()
            self.stop_all()
            self.centralWidget().setEnabled(False)
            self.statusBar().showMessage("Stopping workers and finalizing SQLite sessions…")
        else:
            self.persist()
            self.timer.stop()
            event.accept()


def main(argv=None):
    parser = argparse.ArgumentParser(description="ROADLENS native desktop")
    parser.add_argument("--config", type=Path, help="Existing ROADLENS TOML config")
    parser.add_argument(
        "--data-dir", type=Path, default=Path.home() / "Library/Application Support/ROADLENS"
    )
    parser.add_argument(
        "--smoke-test", type=Path, help="Process a real video, then exit with a result code"
    )
    parser.add_argument("--scene", type=Path, help="Scene for --smoke-test")
    args = parser.parse_args(argv)
    app = QApplication([sys.argv[0]])
    app.setApplicationName("ROADLENS")
    app.setOrganizationName("ROADLENS")
    app.setApplicationVersion("0.1.0")
    app.setFont(font())
    args.data_dir = args.data_dir.expanduser().resolve()
    args.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    configure_logging("INFO", args.data_dir / "logs/roadlens.log")
    preferences = args.data_dir / "desktop.json"
    try:
        config = (
            load_config(args.config)
            if args.config
            else (
                read_preferences(preferences)
                if preferences.is_file()
                else default_config(args.data_dir)
            )
        )
        if not config.analytics.database:
            config = replace(
                config,
                analytics=replace(
                    config.analytics, database=str(args.data_dir / "traffic.sqlite3")
                ),
            )
        if args.smoke_test:
            source = SourceConfig(
                "Smoke test recording",
                "video",
                str(args.smoke_test.resolve()),
                realtime=False,
                scene=str(args.scene.resolve()) if args.scene else None,
            )
            config = replace(config, sources=(source,))
        cv2.setNumThreads(config.threads)
        window = DesktopWindow(config, args.data_dir)
        window.show()
        if args.smoke_test:
            window.start_all()
            deadline = time.monotonic() + 90
            check = QTimer(window)

            def complete():
                if window.pipelines and all(p.done.is_set() for p in window.pipelines.values()):
                    window.tick()
                    code = int(any(p.error or not p.processed for p in window.pipelines.values()))
                    app.exit(code)
                elif time.monotonic() > deadline:
                    window.stop_all()
                    app.exit(2)

            check.timeout.connect(complete)
            check.start(100)
        code = app.exec()
        window.stop_all()
        # Event-loop exits from smoke testing still finish all background work before destruction.
        for pipeline in window.pipelines.values():
            pipeline.join(timeout=config.read_timeout + 5)
        for job in window.jobs.values():
            job.wait()
        return code
    except (OSError, ValueError, TypeError, RuntimeError) as error:
        LOG.exception("Desktop startup failed")
        QMessageBox.critical(None, "ROADLENS could not start", str(error))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
