"""Native, aspect-correct previews, scene editing and traffic charts."""

import math
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from roadlens.traffic.scene import CountingLine, Scene, Zone


class Preview(QWidget):
    finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.image = QImage()
        self.scene = Scene()
        self.points: list[tuple[float, float]] = []
        self.editable = False
        self.polygon = True
        self.drag = None
        self.setMinimumSize(320, 180)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("Camera preview and scene drawing canvas")
        self.setToolTip(
            "Click to draw; drag vertices; Enter finishes; Backspace undoes; "
            "arrow keys move the selected vertex; Escape clears the draft."
        )

    def image_rect(self) -> QRectF:
        if self.image.isNull():
            return QRectF()
        size = self.image.size().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
        return QRectF(
            (self.width() - size.width()) / 2,
            (self.height() - size.height()) / 2,
            size.width(),
            size.height(),
        )

    def normalized(self, position: QPointF):
        rect = self.image_rect()
        if rect.isEmpty() or not rect.contains(position):
            return None
        return ((position.x() - rect.x()) / rect.width(), (position.y() - rect.y()) / rect.height())

    def mapped(self, point):
        rect = self.image_rect()
        return QPointF(rect.x() + point[0] * rect.width(), rect.y() + point[1] * rect.height())

    def set_image(self, image: QImage):
        self.image = image
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#0b161e"))
        if self.image.isNull():
            painter.setPen(QColor("#afc5cf"))
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter,
                "No frames yet\nStart a source to see its actual camera or video.",
            )
            return
        painter.drawImage(self.image_rect(), self.image)
        if self.editable:
            for zone in self.scene.zones:
                painter.setPen(QPen(QColor("#56cdb1"), 2))
                painter.drawPolygon(QPolygonF([self.mapped(p) for p in zone.polygon]))
                painter.drawText(self.mapped(zone.polygon[0]), zone.id)
            for line in self.scene.lines:
                painter.setPen(QPen(QColor("#ffca70"), 2))
                painter.drawLine(self.mapped(line.start), self.mapped(line.end))
                painter.drawText(self.mapped(line.start), line.id)
            if self.points:
                painter.setPen(QPen(QColor("#ffffff"), 2))
                polygon = QPolygonF([self.mapped(p) for p in self.points])
                if self.polygon and len(self.points) > 2:
                    painter.setBrush(QColor(70, 200, 170, 40))
                    painter.drawPolygon(polygon)
                else:
                    painter.drawPolyline(polygon)
                painter.setBrush(QColor("#ffffff"))
                for point in self.points:
                    painter.drawEllipse(self.mapped(point), 5, 5)

    def mousePressEvent(self, event):
        if not self.editable or event.button() != Qt.MouseButton.LeftButton:
            return
        self.setFocus()
        point = self.normalized(event.position())
        if point is None:
            return
        self.drag = None
        for index, vertex in enumerate(self.points):
            if math.dist(self.mapped(vertex).toTuple(), event.position().toTuple()) <= 10:
                self.drag = index
                break
        if self.drag is None and (self.polygon or len(self.points) < 2):
            self.points.append(point)
            self.drag = len(self.points) - 1
        self.update()

    def mouseMoveEvent(self, event):
        if self.editable and self.drag is not None and event.buttons() & Qt.MouseButton.LeftButton:
            point = self.normalized(event.position())
            if point is not None:
                self.points[self.drag] = point
                self.update()

    def keyPressEvent(self, event):
        if not self.editable:
            return super().keyPressEvent(event)
        key = event.key()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.finished.emit()
        elif key == Qt.Key.Key_Escape:
            self.points.clear()
            self.drag = None
        elif key in (Qt.Key.Key_Backspace, Qt.Key.Key_Delete):
            if self.points:
                self.points.pop(self.drag if self.drag is not None else -1)
            self.drag = None
        elif self.drag is not None and key in (
            Qt.Key.Key_Left,
            Qt.Key.Key_Right,
            Qt.Key.Key_Up,
            Qt.Key.Key_Down,
        ):
            x, y = self.points[self.drag]
            x += 0.001 * ((key == Qt.Key.Key_Right) - (key == Qt.Key.Key_Left))
            y += 0.001 * ((key == Qt.Key.Key_Down) - (key == Qt.Key.Key_Up))
            self.points[self.drag] = (max(0, min(1, x)), max(0, min(1, y)))
        self.update()


class SceneEditor(QDialog):
    def __init__(self, scene: Scene, image: QImage, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configure road scene")
        self.resize(1080, 720)
        self.scene = scene
        self.selected = None
        layout = QVBoxLayout(self)
        instructions = QLabel(
            "Draw over a stopped frame. Click vertices, drag to adjust, then Apply. "
            "For a left-to-right line, forward crosses down the image. "
            "Changes apply to the next session."
        )
        instructions.setWordWrap(True)
        layout.addWidget(instructions)
        body = QHBoxLayout()
        layout.addLayout(body, 1)
        self.canvas = Preview()
        self.canvas.editable = True
        self.canvas.scene = scene
        self.canvas.set_image(image)
        self.canvas.finished.connect(self.apply_geometry)
        body.addWidget(self.canvas, 3)
        controls = QVBoxLayout()
        body.addLayout(controls, 1)
        self.items = QListWidget()
        self.items.setAccessibleName("Existing scene geometry")
        self.items.currentRowChanged.connect(self.select_geometry)
        controls.addWidget(self.items)
        form = QFormLayout()
        controls.addLayout(form)
        self.kind = QComboBox()
        self.kind.addItems(["road", "lane", "queue", "exclude", "line"])
        self.kind.currentTextChanged.connect(self.kind_changed)
        self.identifier = QLineEdit("zone-1")
        self.name = QLineEdit("Road zone")
        self.forward = QLineEdit("forward")
        self.reverse = QLineEdit("reverse")
        self.hysteresis = QDoubleSpinBox()
        self.hysteresis.setDecimals(3)
        self.hysteresis.setRange(0.001, 0.05)
        self.hysteresis.setSingleStep(0.001)
        self.hysteresis.setValue(0.005)
        for label, widget in (
            ("Kind", self.kind),
            ("ID", self.identifier),
            ("Name", self.name),
            ("Forward label", self.forward),
            ("Reverse label", self.reverse),
            ("Line deadband", self.hysteresis),
        ):
            form.addRow(label, widget)
        for title, callback in (
            ("New geometry", self.new_geometry),
            ("Apply geometry", self.apply_geometry),
            ("Undo last vertex", self.undo),
            ("Delete selected", self.delete),
            ("Load scene JSON…", self.load_scene),
        ):
            button = QPushButton(title)
            button.clicked.connect(callback)
            controls.addWidget(button)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.save)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.refresh()

    def refresh(self):
        self.items.blockSignals(True)
        self.items.clear()
        for zone in self.scene.zones:
            self.items.addItem(f"{zone.kind} / {zone.id}")
        for line in self.scene.lines:
            self.items.addItem(f"line / {line.id}")
        self.items.blockSignals(False)
        self.canvas.scene = self.scene
        self.canvas.update()

    def kind_changed(self, kind):
        self.canvas.polygon = kind != "line"
        self.canvas.points.clear()
        self.canvas.drag = None
        self.canvas.update()

    def new_geometry(self):
        self.selected = None
        self.identifier.setReadOnly(False)
        self.canvas.points.clear()
        self.canvas.drag = None
        existing = {item.id for item in (*self.scene.zones, *self.scene.lines)}
        index = 1
        while f"geometry-{index}" in existing:
            index += 1
        self.identifier.setText(f"geometry-{index}")
        self.canvas.update()

    def select_geometry(self, index):
        objects = (*self.scene.zones, *self.scene.lines)
        if not 0 <= index < len(objects):
            return
        item = objects[index]
        self.selected = ("lines" if isinstance(item, CountingLine) else "zones", item.id)
        self.kind.setCurrentText("line" if isinstance(item, CountingLine) else item.kind)
        self.identifier.setText(item.id)
        self.identifier.setReadOnly(True)
        if isinstance(item, CountingLine):
            self.canvas.points = [item.start, item.end]
            self.forward.setText(item.forward)
            self.reverse.setText(item.reverse)
            self.hysteresis.setValue(item.hysteresis)
        else:
            self.canvas.points = list(item.polygon)
            self.name.setText(item.name)
        self.canvas.drag = None
        self.canvas.update()

    def apply_geometry(self):
        try:
            kind = self.kind.currentText()
            identifier = self.identifier.text().strip()
            collection = "lines" if kind == "line" else "zones"
            if self.selected != (collection, identifier) and any(
                item.id == identifier for item in getattr(self.scene, collection)
            ):
                raise ValueError("That ID exists; select it in the list to edit it")
            if kind == "line":
                if len(self.canvas.points) != 2:
                    raise ValueError("A counting line needs exactly two points")
                geometry = CountingLine(
                    identifier,
                    *self.canvas.points,
                    self.forward.text(),
                    self.reverse.text(),
                    self.hysteresis.value(),
                )
                updated = (
                    self.scene if geometry in self.scene.lines else self.scene.with_line(geometry)
                )
            else:
                geometry = Zone(identifier, self.name.text(), tuple(self.canvas.points), kind)
                updated = (
                    self.scene if geometry in self.scene.zones else self.scene.with_zone(geometry)
                )
            if self.selected and self.selected[0] != collection:
                updated = updated.without(self.selected[1], collection=self.selected[0])
            self.scene = updated
            self.status.setText("Geometry validated. Save to use it in the next session.")
            self.refresh()
            self.new_geometry()
            return True
        except (ValueError, TypeError) as error:
            self.status.setText(str(error))
            return False

    def undo(self):
        if self.canvas.points:
            self.canvas.points.pop()
        self.canvas.drag = None
        self.canvas.update()

    def delete(self):
        if self.selected:
            self.scene = self.scene.without(self.selected[1], collection=self.selected[0])
            self.refresh()
            self.new_geometry()

    def load_scene(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load scene", "", "Scene JSON (*.json)")
        if path:
            try:
                self.scene = Scene.load(Path(path))
                self.refresh()
                self.new_geometry()
            except (OSError, ValueError, TypeError, KeyError) as error:
                self.status.setText(str(error))

    def save(self):
        if self.canvas.points and not self.apply_geometry():
            return
        self.accept()


class FlowChart(QWidget):
    COLORS = ("#59dbc0", "#ffcc7b", "#89b5ff", "#ef93b4", "#bda8ff")

    def __init__(self):
        super().__init__()
        self.windows = []
        self.series = ""
        self.setMinimumSize(360, 210)
        self.setAccessibleName("Traffic flow chart, vehicles per observed minute")
        self.setToolTip(
            "Rates use observed time in saved measurement windows. "
            "Gaps and unavailable rates are not plotted as zero."
        )

    def set_windows(self, windows):
        self.windows = windows[-240:]
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#12232e"))
        painter.setPen(QColor("#bfd3dc"))
        painter.drawText(16, 24, "TRAFFIC FLOW  /  vehicles per observed minute")
        points = [w for w in self.windows if w["observed_seconds"] > 0]
        categories = [self.series] if self.series else []
        rates = [
            w["flow_per_minute"][key]
            for w in points
            for key in categories
            if w["flow_per_minute"].get(key) is not None
        ]
        if not rates:
            painter.drawText(
                self.rect(), Qt.AlignmentFlag.AlignCenter, "Waiting for a measured counting window"
            )
            return
        graph = QRectF(50, 44, self.width() - 72, self.height() - 95)
        maximum = max(1, max(rates))
        left = min(w["start_time"] for w in points)
        right = max(left + 1, max(w["end_time"] for w in points))
        painter.setPen(QPen(QColor("#334650"), 1))
        for index in range(4):
            y = graph.bottom() - graph.height() * index / 3
            painter.setPen(QPen(QColor("#334650"), 1))
            painter.drawLine(QPointF(graph.left(), y), QPointF(graph.right(), y))
            painter.setPen(QColor("#9db5c1"))
            painter.drawText(
                QRectF(0, y - 8, 44, 18), Qt.AlignmentFlag.AlignRight, f"{maximum * index / 3:.1f}"
            )
        painter.drawText(50, self.height() - 29, f"{left:.1f}s")
        painter.drawText(self.width() - 80, self.height() - 29, f"{right:.1f}s")
        for index, category in enumerate(categories):
            painter.setPen(QPen(QColor(self.COLORS[index % len(self.COLORS)]), 2))
            path = QPainterPath()
            previous = None
            for window in points:
                value = window["flow_per_minute"].get(category)
                if value is None:
                    previous = None
                    continue
                x = graph.left() + (window["end_time"] - left) / (right - left) * graph.width()
                y = graph.bottom() - value / maximum * graph.height()
                if previous is None or window["start_time"] > previous + 0.001:
                    path.moveTo(x, y)
                else:
                    path.lineTo(x, y)
                painter.drawEllipse(QPointF(x, y), 2.5, 2.5)
                previous = window["end_time"]
            painter.drawPath(path)
            legend = painter.fontMetrics().elidedText(
                category, Qt.TextElideMode.ElideRight, self.width() - 36
            )
            painter.drawText(18, self.height() - 8, legend)


def scene_for_source(path: str | None) -> Scene:
    return Scene.load(Path(path)) if path else Scene()
