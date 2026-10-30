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
from PySide6.QtGui import QAction, QDesktopServices, QImage, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
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
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from roadlens.cameras import list_cameras
from roadlens.cli import configure_logging
from roadlens.config import Config, SourceConfig, load_config
from roadlens.desktop_data import export_pdf, heatmap_image, qimage, read_history
from roadlens.desktop_design import FocusOutline, Foldout, apply_appearance, font, heading, label
from roadlens.desktop_widgets import FlowChart, Preview, SceneEditor, scene_for_source
from roadlens.traffic.models import AnalyticsConfig
from roadlens.traffic.store import TrafficStore

LOG = logging.getLogger(__name__)


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
    for index, title in enumerate(headers):
        widget.setColumnWidth(index, max(80, widget.fontMetrics().horizontalAdvance(title) + 30))
    widget.setWordWrap(False)
    widget.setTextElideMode(Qt.TextElideMode.ElideRight)
    widget.verticalHeader().hide()
    widget.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    widget.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    widget.setAlternatingRowColors(False)
    widget.verticalHeader().setDefaultSectionSize(34)
    widget.setShowGrid(False)
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
        self.setObjectName("sourcePane")
        layout = QVBoxLayout(self)
        self.title = QLabel(source.name)
        self.title.setFont(font("section", bold=True))
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        self.title.setWordWrap(True)
        self.title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.title.setToolTip(source.name)
        layout.addWidget(self.title)
        self.preview = Preview()
        layout.addWidget(self.preview, 1)
        self.status = QLabel("Ready")
        self.raw_image = QImage()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        state_row = QHBoxLayout()
        state_row.addWidget(self.status, 1)
        self.progress = label("", "muted")
        self.progress.setAlignment(Qt.AlignmentFlag.AlignRight)
        state_row.addWidget(self.progress)
        layout.addLayout(state_row)


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
        self.draw_geometry = True
        self.setWindowTitle("ROADLENS • Local traffic intelligence")
        self.resize(1280, 850)
        self.setMinimumSize(960, 680)
        apply_appearance(self)
        self.build_ui()
        self.focus_outline = FocusOutline(self)
        self.sync_sources()
        self.populate_settings()
        appearance = "System"
        try:
            appearance = json.loads((self.data_dir / "appearance.json").read_text())["appearance"]
        except (OSError, ValueError, KeyError, TypeError):
            pass
        self.appearance.setCurrentText(
            appearance if appearance in ("System", "Light", "Dark") else "System"
        )
        self.change_appearance(self.appearance.currentText(), persist=False)
        QApplication.styleHints().colorSchemeChanged.connect(self.system_appearance_changed)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(60)
        self.history_timer = QTimer(self)
        self.history_timer.timeout.connect(self.refresh_history)
        self.history_timer.start(2000)
        self.refresh_history()
        for source in self.sources:
            if source.kind == "video":
                self.load_video_preview(source)

    def build_ui(self):
        content = QWidget()
        outer = QVBoxLayout(content)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        chrome = QWidget()
        chrome.setObjectName("page")
        navigation = QHBoxLayout(chrome)
        navigation.setContentsMargins(28, 8, 28, 0)
        navigation.setSpacing(8)
        brand = label("ROADLENS", "brand")
        brand.setMinimumWidth(132)
        navigation.addWidget(brand)
        self.tabs = QStackedWidget()
        self.nav_buttons = []
        self.navigation_group = QButtonGroup(self)
        for index, title in enumerate(("Monitor", "Analysis", "Settings")):
            button = self.button(title, lambda _, i=index: self.tabs.setCurrentIndex(i), navigation)
            button.setObjectName("navigation")
            button.setCheckable(True)
            button.setAccessibleName(f"Open {title}")
            self.navigation_group.addButton(button, index)
            self.nav_buttons.append(button)
        navigation.addStretch()
        self.global_status = label("Ready", "muted")
        self.global_status.setAlignment(Qt.AlignmentFlag.AlignRight)
        navigation.addWidget(self.global_status)
        outer.addWidget(chrome)
        outer.addWidget(self.tabs, 1)
        self.build_monitor()
        self.build_history()
        self.build_settings()
        self.tabs.currentChanged.connect(self.navigate)
        self.setCentralWidget(content)
        self.navigate(0)
        file_menu = self.menuBar().addMenu("File")
        for title, shortcut, callback in (
            ("Import video…", QKeySequence.StandardKey.Open, self.import_video),
            ("Import configuration…", None, self.import_config),
            ("Export session…", "Ctrl+E", self.export_session),
            ("Close", QKeySequence.StandardKey.Close, self.close),
        ):
            action = QAction(title, self)
            if shortcut:
                action.setShortcut(shortcut)
            action.triggered.connect(callback)
            file_menu.addAction(action)
        playback = self.menuBar().addMenu("Playback")
        for title, shortcut, callback in (
            ("Start / Pause / Resume", "Ctrl+R", self.toggle_playback),
            ("Stop", "Ctrl+.", self.stop_selected),
            ("Start all sources", "Ctrl+Shift+R", self.start_all),
            ("Stop all sources", "Ctrl+Shift+.", self.stop_all),
        ):
            action = playback.addAction(title)
            action.setShortcut(shortcut)
            action.triggered.connect(callback)
        for index, button in enumerate(self.nav_buttons):
            action = QAction(button.text(), self)
            action.setShortcut(f"Ctrl+{index + 1}")
            action.triggered.connect(lambda _, i=index: self.tabs.setCurrentIndex(i))
            self.addAction(action)
        view_menu = self.menuBar().addMenu("View")
        self.geometry_action = view_menu.addAction("Show road geometry")
        self.geometry_action.setCheckable(True)
        self.geometry_action.setChecked(True)
        self.geometry_action.toggled.connect(self.set_geometry_visible)
        help_menu = self.menuBar().addMenu("Help")
        help_menu.addAction("Camera permissions", self.camera_help)
        help_menu.addAction("Open source license", self.open_license)
        help_menu.addAction(
            "About ROADLENS",
            lambda: QMessageBox.about(
                self,
                "About ROADLENS",
                "ROADLENS 0.1.0\nLocal traffic intelligence\n\n"
                "Copyright (C) 2026 ROADLENS contributors. AGPL-3.0-only.\n"
                "You may copy, modify and redistribute under that license.\n"
                "Provided WITHOUT ANY WARRANTY. See Help → Open source license.\n\n"
                "PySide6 / OpenCV DNN / ByteTrack / SQLite\n"
                "Model: Ultralytics YOLOv8n (AGPL-3.0/commercial).\n"
                "Qt: LGPLv3/GPLv3/commercial. See bundled licenses.",
            ),
        )
        self.statusBar().showMessage("Choose a source to begin.")

    def button(self, title, callback, layout, *, primary=False):
        button = QPushButton(title)
        glyph = {
            "Import video…": "import",
            "Import video": "import",
            "Start selected": "play",
            "Start": "play",
            "Pause": "pause",
            "Stop": "stop",
            "Stop selected": "stop",
            "Configure scene…": "road",
            "Configure road": "road",
            "Sources…": "camera",
        }.get(title)
        if glyph:
            button.setProperty("iconName", glyph)
        button.clicked.connect(callback)
        if primary:
            button.setObjectName("primary")
        layout.addWidget(button)
        return button

    def build_monitor(self):
        page, layout = self.page()
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self.source_selector = QComboBox()
        self.source_selector.setMinimumContentsLength(15)
        self.source_selector.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.source_selector.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.source_selector.setAccessibleName("Selected camera or video")
        self.source_selector.setPlaceholderText("Choose a camera or video")
        self.source_selector.currentIndexChanged.connect(self.select_source_index)
        toolbar.addWidget(self.source_selector, 1)
        self.import_button = self.button("Import video", self.import_video, toolbar)
        self.import_button.setProperty("iconName", "import")
        self.camera_button = self.button("Sources…", self.manage_sources, toolbar)
        self.camera_button.setProperty("iconName", "camera")
        layout.addLayout(toolbar)
        controls = QHBoxLayout()
        self.start_button = self.button("Start", self.start_selected, controls, primary=True)
        self.start_button.setProperty("iconName", "play")
        self.pause_button = self.button("Pause", self.pause_selected, controls)
        self.stop_button = self.button("Stop", self.stop_selected, controls)
        self.stop_button.setProperty("iconName", "stop")
        controls.addStretch()
        self.show_all = QCheckBox("All sources")
        self.show_all.toggled.connect(self.selection_changed)
        controls.addWidget(self.show_all)
        self.edit_button = self.button("Configure road", self.edit_scene, controls)
        self.edit_button.setProperty("iconName", "road")
        layout.addLayout(controls)
        self.gallery_widget = QWidget()
        self.gallery_widget.setObjectName("page")
        self.gallery = QGridLayout(self.gallery_widget)
        self.gallery.setContentsMargins(0, 0, 0, 0)
        self.gallery.setSpacing(12)
        self.empty = QWidget()
        empty_layout = QVBoxLayout(self.empty)
        empty_layout.addStretch()
        empty_layout.addWidget(label("Your road, in focus", "pageTitle"))
        empty_layout.addWidget(
            label(
                "Import a recording or connect a camera. Detection works straight away; "
                "add a counting line or road area for traffic measurements.",
                "muted",
            )
        )
        empty_actions = QHBoxLayout()
        self.button("Import a video…", self.import_video, empty_actions, primary=True)
        self.button("Connect a camera…", self.manage_sources, empty_actions)
        empty_actions.addStretch()
        empty_layout.addLayout(empty_actions)
        empty_layout.addStretch()
        self.gallery.addWidget(self.empty, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.gallery_widget)
        layout.addWidget(scroll, 1)
        strip = QFrame()
        strip.setObjectName("metricStrip")
        metrics = QHBoxLayout(strip)
        metrics.setContentsMargins(0, 16, 0, 16)
        self.metrics = {}
        for title, display in (
            ("Crossing events", "Vehicles counted"),
            ("Traffic flow", "Vehicles / min"),
            ("Congestion", "Road conditions"),
        ):
            stack = QVBoxLayout()
            stack.addWidget(label(display, "muted"))
            value = label("—", "metric")
            value.setAccessibleName(title)
            stack.addWidget(value)
            metrics.addLayout(stack, 1)
            self.metrics[title] = value
        layout.addWidget(strip)
        self.monitor_hint = label("Import a video or connect a camera to get started.", "muted")
        layout.addWidget(self.monitor_hint)
        self.live_details = Foldout("Details")
        self.live_status = label("No source selected", "muted")
        self.live_details.body_layout.addWidget(self.live_status)
        self.availability = label(
            "Start a source to see which measurements are available.", "muted"
        )
        self.live_details.body_layout.addWidget(self.availability)
        self.analysis_button = self.button(
            "Open this session in Analysis",
            self.open_current_analysis,
            self.live_details.body_layout,
        )
        secondary = QHBoxLayout()
        for title in ("Visible tracks", "Queued vehicles"):
            secondary.addWidget(label(title, "muted"))
            self.metrics[title] = label("—")
            secondary.addWidget(self.metrics[title])
            secondary.addStretch()
        self.live_details.body_layout.addLayout(secondary)
        flow_choice = QHBoxLayout()
        flow_choice.addWidget(QLabel("Flow counting line"))
        self.monitor_line = QComboBox()
        self.monitor_line.setAccessibleName("Counting line used for the live flow rate")
        self.monitor_line.currentIndexChanged.connect(self.update_flow_metric)
        flow_choice.addWidget(self.monitor_line, 1)
        self.live_details.body_layout.addLayout(flow_choice)
        details = QSplitter(Qt.Orientation.Horizontal)
        self.count_table = table(["Line", "Vehicle", "Direction", "Crossings"])
        self.zone_table = table(["Area", "Vehicles", "Occupancy", "Queue", "Conditions"])
        details.addWidget(self.count_table)
        details.addWidget(self.zone_table)
        details.setMaximumHeight(175)
        self.live_details.body_layout.addWidget(details)
        layout.addWidget(self.live_details)
        self.tabs.addWidget(page)
        self.build_sources_dialog()

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
        self.tabs.addWidget(page)

    def build_settings(self):
        page = QWidget()
        layout = QHBoxLayout(page)
        group = QGroupBox("Camera and inference settings • apply between sessions")
        form = QFormLayout(group)
        self.appearance = QComboBox()
        self.appearance.addItems(["System", "Light", "Dark"])
        self.appearance.setAccessibleName("Appearance")
        self.appearance.currentTextChanged.connect(self.change_appearance)
        form.addRow("Appearance", self.appearance)
        self.model_edit = QLineEdit()
        self.database_edit = QLineEdit()
        for field_title, widget, callback in (
            ("ONNX model", self.model_edit, self.choose_model),
            ("SQLite database", self.database_edit, self.choose_database),
        ):
            row = QHBoxLayout()
            row.addWidget(widget)
            self.button("Browse…", callback, row)
            form.addRow(field_title, row)
        self.settings_fields = {}
        for key, field_title, low, high, decimals in (
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
            widget.setAccessibleName(field_title)
            widget.valueChanged.connect(lambda _, key=key: self.settings_changed.add(key))
            widget.lineEdit().textEdited.connect(lambda _, key=key: self.settings_changed.add(key))
            self.settings_fields[key] = widget
            form.addRow(field_title, widget)
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
        self.tabs.addWidget(page)

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
        self.source_selector.blockSignals(True)
        self.source_selector.clear()
        for source in self.sources:
            self.source_list.addItem(source.name)
            self.source_selector.addItem(source.name)
            self.source_list.item(self.source_list.count() - 1).setToolTip(
                f"{source.name}\n{source.value}\nCamera ID: {source.camera_id or source.name}"
            )
        for name, pane in list(self.panes.items()):
            if name not in {s.name for s in self.sources}:
                self.gallery.removeWidget(pane)
                pane.deleteLater()
                del self.panes[name]
        self.empty.setVisible(not self.sources)
        for source in self.sources:
            if source.name not in self.panes:
                self.panes[source.name] = SourcePane(source)
            try:
                self.panes[source.name].preview.scene = scene_for_source(source.scene)
            except (OSError, ValueError, TypeError, KeyError) as error:
                self.panes[source.name].status.setText(f"Road configuration unavailable: {error}")
            self.panes[source.name].preview.show_geometry = self.draw_geometry
        selected = next(
            (i for i, s in enumerate(self.sources) if previous and s.name == previous.name), 0
        )
        self.source_list.setCurrentRow(selected if self.sources else -1)
        self.source_list.blockSignals(False)
        self.source_selector.blockSignals(False)
        self.selection_changed()

    def selection_changed(self):
        if not hasattr(self, "live_status"):
            return
        source = self.selected_source()
        result = self.latest.get(source.name) if source else None
        self.source_selector.blockSignals(True)
        self.source_selector.setCurrentIndex(self.source_list.currentRow())
        self.source_selector.setToolTip(source.name if source else "Choose a source")
        self.source_selector.blockSignals(False)
        visible = [s for s in self.sources if self.show_all.isChecked() or s == source]
        for item in self.sources:
            pane = self.panes[item.name]
            self.gallery.removeWidget(pane)
            pane.setVisible(item in visible)
            pane.title.setVisible(self.show_all.isChecked())
        for index, item in enumerate(visible):
            self.gallery.addWidget(
                self.panes[item.name],
                index // 2 if len(visible) > 1 else 0,
                index % 2 if len(visible) > 1 else 0,
            )
        previous_line = self.monitor_line.currentData()
        self.monitor_line.blockSignals(True)
        self.monitor_line.clear()
        if source:
            for line in self.panes[source.name].preview.scene.lines:
                self.monitor_line.addItem(line.id, line.id)
        self.monitor_line.setCurrentIndex(max(0, self.monitor_line.findData(previous_line)))
        self.monitor_line.setEnabled(self.monitor_line.count() > 0)
        self.monitor_line.blockSignals(False)
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
        if source.kind == "video":
            self.load_video_preview(source)

    def discover_cameras(self):
        self.discover_button.setEnabled(False)
        self.discover_button.setText("Finding cameras…")
        self.camera_status.setText("Looking for Mac, iPhone and external cameras…")
        self.statusBar().showMessage("Finding cameras…")
        self.launch_job("cameras", list_cameras, self.cameras_discovered)

    def cameras_discovered(self, devices):
        self.camera_selector.clear()
        for device in devices:
            kind = "iPhone" if "Continuity" in device["type"] else "Mac / external"
            self.camera_selector.addItem(f"{device['name']} ({kind})", device)
        self.discover_button.setText("Find cameras")
        self.camera_status.setText(
            f"{len(devices)} camera(s) available. Add one, then press Start in Monitor."
            if devices
            else "No cameras found. Check camera permissions and your iPhone connection."
        )
        self.statusBar().showMessage(self.camera_status.text())

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
            name = Path(path).stem
            if any(s.name == name and s.value != str(Path(path).resolve()) for s in self.sources):
                name = f"{name} [{identity[:5]}]"
            self.add_source(
                SourceConfig(
                    name,
                    "video",
                    str(Path(path).resolve()),
                    realtime=False,
                    camera_id=f"video-{identity}",
                )
            )
        if paths:
            self.statusBar().showMessage("Video imported. Press Start to analyze every frame.")

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
            pipeline.desktop_preview = True
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
            pane = self.panes[source.name]
            if pane.raw_image.isNull():
                self.statusBar().showMessage(
                    "Wait for a video preview, or start and stop the camera once before drawing."
                )
                if source.kind == "video":
                    self.load_video_preview(source)
                return
            editor = SceneEditor(
                scene_for_source(source.scene),
                pane.raw_image,
                self,
                detection_image=pane.preview.image,
            )
            if editor.exec() == QDialog.DialogCode.Accepted:
                path = self.data_dir / "scenes" / f"{editor.scene.fingerprint}.json"
                editor.scene.save(path)
                self.sources[self.sources.index(source)] = replace(source, scene=str(path))
                pane.preview.scene = editor.scene
                pane.preview.update()
                if self.persist():
                    self.statusBar().showMessage(
                        "Scene saved. Start the source to begin a new session."
                    )
        except (OSError, ValueError, TypeError, KeyError) as error:
            self.show_error(error)

    def update_live(self, result):
        if result is None:
            for metric in self.metrics.values():
                metric.setText("—")
                metric.setToolTip("Start a source to record this measurement")
            fill_table(self.count_table, [])
            fill_table(self.zone_table, [])
            self.live_status.setText("Start the selected source to see its measurements.")
            self.availability.setText("Configure a line for counts or a road area for congestion.")
            self.monitor_hint.setText(
                "Press Start for detection. Configure the road to enable counting and congestion."
                if self.selected_source()
                else "Import a video or connect a camera to get started."
            )
            return
        snapshot = result.analysis
        missing = []
        if snapshot is not None:
            if not snapshot.counting_available:
                missing.append("Vehicle counting needs a line across the road.")
            if not snapshot.zones:
                missing.append("Congestion needs a road area.")
            if not any(z.queued_vehicles is not None for z in snapshot.zones):
                missing.append("Queue size needs a queue area, configured in Advanced.")
            if not any(speed.mps is not None for speed in snapshot.speeds):
                missing.append(
                    "Physical speed: "
                    + (snapshot.speed_unavailable_reason or "more observations needed")
                    + "."
                )
        self.availability.setText("\n".join(missing) or "Configured measurements are available.")
        self.metrics["Traffic flow"].setText("—")
        self.metrics["Traffic flow"].setToolTip(
            "A counting line and a saved observation window are required"
        )
        self.metrics["Visible tracks"].setText(str(len(result.tracks)))
        if snapshot is None:
            self.update_live(None)
            self.metrics["Visible tracks"].setText(str(len(result.tracks)))
            self.live_status.setText("Traffic analysis unavailable for this result.")
            return
        self.metrics["Crossing events"].setText(
            str(sum(c.count for c in snapshot.counts)) if snapshot.counting_available else "—"
        )
        queues = [z.queued_vehicles for z in snapshot.zones if z.queued_vehicles is not None]
        # Overlapping zones can contain the same queue; never sum them as unique vehicles.
        self.metrics["Queued vehicles"].setText(str(max(queues)) if queues else "No queue zone")
        conditions = {z.congestion for z in snapshot.zones}
        congestion = next(
            (state for state in ("congested", "observing", "free") if state in conditions),
            "Unavailable" if conditions else "No road zone",
        )
        self.metrics["Congestion"].setText(
            {"free": "Free flowing", "observing": "Observing", "congested": "Congested"}.get(
                congestion, "—"
            )
        )
        self.monitor_hint.setText(
            "Counting vehicles across your line. Flow appears after an observation window is saved."
            if snapshot.counting_available
            else "Detection is running. Draw a line in Configure road to count vehicles."
        )
        if not snapshot.zones:
            self.monitor_hint.setText(
                self.monitor_hint.text() + " Draw a road area to measure congestion."
            )
        self.metrics["Crossing events"].setToolTip(
            "Cumulative crossing events in this session"
            if snapshot.counting_available
            else "Draw a counting line to enable vehicle counts"
        )
        self.metrics["Congestion"].setToolTip(
            "Measured from occupancy in configured road areas"
            if snapshot.zones
            else "Draw a road area to measure congestion"
        )
        self.update_flow_metric()
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
            f"Anomaly baseline {baseline}. Queue = largest road-area queue."
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
                pane = self.panes[source.name]
                pane.preview.set_image(qimage(result.image))
                if result.raw_image is not None:
                    pane.raw_image = qimage(result.raw_image)
                if source == self.selected_source():
                    self.update_live(result)
            if pipeline.error:
                state = "failed"
            elif pipeline.done.is_set():
                state = "completed" if pipeline.capture.state == "eof" else "stopped"
            elif pipeline.stop_event.is_set():
                state = "stopping"
            elif pipeline.paused.is_set():
                state = "paused"
            else:
                state = pipeline.capture.state
            age = now - self.received[source.name] if source.name in self.received else None
            if (
                state == "running"
                and age is not None
                and age > max(2, 2 / pipeline.config.inference_fps)
            ):
                state = "stale / waiting for frames"
            status = {
                "running": "Analyzing",
                "connecting": "Connecting…",
                "starting": "Starting…",
                "paused": "Paused",
                "completed": "Completed",
                "stopped": "Stopped",
                "stopping": "Stopping…",
                "failed": "FAILED",
                "reconnecting": "Reconnecting…",
            }.get(state, state.capitalize())
            self.panes[source.name].progress.setText(f"{pipeline.processed} frames analyzed")
            if pipeline.error:
                status += f": {pipeline.error}"
            elif pipeline.capture.last_error and state not in ("completed", "stopped"):
                status += f": {pipeline.capture.last_error}"
            self.panes[source.name].status.setText(status)
        source = self.selected_source()
        running = bool(source and self.active(source.name))
        self.start_button.setEnabled(bool(source) and not running and not self.closing)
        self.analysis_button.setEnabled(
            bool(source and self.pipelines.get(source.name) and self.pipelines[source.name].traffic)
        )
        self.stop_button.setEnabled(running)
        self.pause_button.setEnabled(
            running and not self.pipelines[source.name].stop_event.is_set() if running else False
        )
        paused = running and self.pipelines[source.name].paused.is_set()
        self.pause_button.setText("Resume" if paused else "Pause")
        self.pause_button.setToolTip(
            "Resume analysis" if paused else "Pause analysis; live cameras remain connected"
        )
        self.start_button.setToolTip(
            "Stop the current analysis before restarting"
            if running
            else "Analyze the selected source"
        )
        self.edit_button.setToolTip(
            "Stop this source to edit the road" if running else "Draw a counting line or road area"
        )
        self.edit_button.setEnabled(bool(source) and not running)
        self.remove_button.setEnabled(bool(source) and not running)
        self.apply_button.setEnabled(not self.any_active())
        self.discover_button.setEnabled("cameras" not in self.jobs and not self.closing)
        export_ready = bool(self.history_session and self.report_data) and "export" not in self.jobs
        self.export_button.setEnabled(export_ready)
        self.export_button.setText("Exporting…" if "export" in self.jobs else "Export…")
        self.export_button.setToolTip(
            "Export the selected session" if export_ready else "Select a saved session to export"
        )
        self.heatmap_export_button.setEnabled(
            export_ready and bool(self.report_data.get("heatmap"))
        )
        self.add_camera_button.setEnabled(self.camera_selector.currentData() is not None)
        active = sum(self.active(name) for name in self.pipelines)
        self.global_status.setText(f"{active} source(s) active" if active else "Ready")
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
                if name == "cameras":
                    self.discover_button.setText("Find cameras")
                    self.camera_status.setText(f"Camera discovery failed: {failure}")
                elif name.startswith("preview:"):
                    source_name = name.removeprefix("preview:")
                    if source_name in self.panes:
                        pane = self.panes[source_name]
                        pane.status.setText(f"Cannot open recording: {failure}")
                        pane.preview.empty_message = (
                            "Could not read this recording.\nCheck its path or import another file."
                        )
                        pane.preview.update()
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
        self.update_flow_metric()

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

    def change_appearance(self, appearance, *, persist=True):
        dark = appearance == "Dark" or (
            appearance == "System"
            and QApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
        )
        apply_appearance(self, dark)
        if persist:
            try:
                self.data_dir.mkdir(parents=True, exist_ok=True)
                (self.data_dir / "appearance.json").write_text(
                    json.dumps({"appearance": appearance})
                )
            except OSError as error:
                self.statusBar().showMessage(f"Could not save appearance: {error}")

    def system_appearance_changed(self, _):
        if self.appearance.currentText() == "System":
            self.change_appearance("System", persist=False)

    def navigate(self, index):
        for position, button in enumerate(self.nav_buttons):
            button.setChecked(position == index)
        self.refresh_history()

    def page(self):
        page = QWidget()
        page.setObjectName("page")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 16)
        layout.setSpacing(16)
        return page, layout

    def select_source_index(self, index):
        self.source_list.setCurrentRow(index)

    def build_sources_dialog(self):
        self.sources_dialog = QDialog(self)
        self.sources_dialog.setWindowTitle("Sources")
        self.sources_dialog.resize(510, 560)
        layout = QVBoxLayout(self.sources_dialog)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)
        heading(layout, "Sources", "Keep recordings and cameras together. Select one to monitor.")
        self.source_list = QListWidget()
        self.source_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.source_list.setAccessibleName("Saved sources")
        self.source_list.currentRowChanged.connect(self.selection_changed)
        layout.addWidget(self.source_list, 1)
        row = QHBoxLayout()
        self.button("Import video…", self.import_video, row)
        self.remove_button = self.button("Remove", self.remove_source, row)
        layout.addLayout(row)
        layout.addWidget(label("Connect a camera", "brand"))
        layout.addWidget(
            label("Find cameras available to macOS, then add your chosen device.", "muted")
        )
        self.camera_selector = QComboBox()
        self.camera_selector.setAccessibleName("Available MacBook and iPhone cameras")
        self.camera_selector.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        layout.addWidget(self.camera_selector)
        row = QHBoxLayout()
        self.discover_button = self.button("Find cameras", self.discover_cameras, row)
        self.add_camera_button = self.button("Add camera", self.add_camera, row)
        layout.addLayout(row)
        self.camera_status = label("Finding cameras does not start recording or capture.", "muted")
        layout.addWidget(self.camera_status)
        self.button("Camera permission help", self.camera_help, layout)
        self.button("Done", self.sources_dialog.accept, layout, primary=True)

    def manage_sources(self):
        self.sources_dialog.open()
        if self.camera_selector.count() == 0:
            self.discover_cameras()

    def load_video_preview(self, source):
        self.panes[source.name].status.setText("Opening recording…")

        def read():
            from roadlens.capture import OpenCVCapture

            capture = OpenCVCapture(source, self.config)
            try:
                return qimage(capture.read())
            finally:
                capture.close()

        def loaded(image):
            if source not in self.sources or self.active(source.name) or source.name in self.latest:
                return
            pane = self.panes[source.name]
            pane.raw_image = image
            pane.preview.set_image(image)
            pane.preview.scene = scene_for_source(source.scene)
            pane.preview.show_geometry = self.draw_geometry
            pane.status.setText("Ready. Configure the road or press Start.")

        self.launch_job(f"preview:{source.name}", read, loaded)

    def pause_selected(self):
        source = self.selected_source()
        if source and self.active(source.name):
            pipeline = self.pipelines[source.name]
            pipeline.set_paused(not pipeline.paused.is_set())
            self.tick()

    def toggle_playback(self):
        if source := self.selected_source():
            if self.active(source.name):
                self.pause_selected()
            else:
                self.start_selected()

    def set_geometry_visible(self, visible):
        self.draw_geometry = visible
        for pane in self.panes.values():
            pane.preview.show_geometry = visible
            pane.preview.update()

    def update_flow_metric(self, *_):
        source = self.selected_source()
        pipeline = self.pipelines.get(source.name) if source else None
        data = self.report_data or {}
        session = data.get("session")
        if not (
            pipeline
            and pipeline.traffic
            and session
            and session["id"] == pipeline.traffic.session_id
        ):
            return
        windows = data.get("windows", [])
        latest = next((w for w in reversed(windows) if w["observed_seconds"] > 0), None)
        if latest and latest["flow_per_minute"]:
            # Each line is a separate observation; select one rather than summing overlapping lines.
            line = self.monitor_line.currentData()
            if line is None:
                return
            values = [
                value
                for key, value in latest["flow_per_minute"].items()
                if key.split("/")[0] == line and value is not None
            ]
            if values:
                self.metrics["Traffic flow"].setText(f"{sum(values):.1f}")
                self.metrics["Traffic flow"].setToolTip(
                    f"Vehicles per observed minute at line {line}; latest saved window"
                )
                self.monitor_hint.setText(
                    f"Counting line {line}. "
                    f"{latest['observed_seconds']:.1f}s observed in the latest window."
                )

    def open_current_analysis(self):
        source = self.selected_source()
        pipeline = self.pipelines.get(source.name) if source else None
        if pipeline and pipeline.traffic and pipeline.traffic.session_id:
            self.history_session = pipeline.traffic.session_id
            self.history_request += 1
            self.tabs.setCurrentIndex(1)
            self.refresh_history()


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
