"""Hallmark 2.0.0: native app workbench, restrained color, light and dark parity.

Critique: hierarchy and restraint lead; real footage is the signature.
Web scaffolds/render lint are replaced by Qt layout, contrast and screenshot checks.
"""

from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QPainter, QPalette, QPen
from PySide6.QtWidgets import QApplication, QFocusFrame, QPushButton, QVBoxLayout, QWidget

LIGHT = {
    "background": "#f3f4ef",
    "surface": "#fafbf7",
    "raised": "#e9ece4",
    "text": "#252923",
    "muted": "#5c6558",
    "border": "#7b8475",
    "rule": "#d3d8cd",
    "accent": "#355d47",
    "accent_ink": "#f5f7f0",
    "selection": "#dfe8dc",
    "disabled": "#78816f",
    "focus": "#355d47",
    "preview": "#1e241d",
    "preview_ink": "#e5ecdf",
    "geometry": "#c8dac3",
    "line": "#e7d8ad",
    "draft": "#f1f4ec",
    "chart": "#42694f",
    "error": "#9a3830",
}


DARK = {
    "background": "#20261f",
    "surface": "#2a3228",
    "raised": "#343e32",
    "text": "#edf1e7",
    "muted": "#b9c3af",
    "border": "#93a088",
    "rule": "#495442",
    "accent": "#b3cdb3",
    "accent_ink": "#202b21",
    "selection": "#3d503d",
    "disabled": "#9aa58f",
    "focus": "#b3cdb3",
    "preview": "#1e241d",
    "preview_ink": "#e5ecdf",
    "geometry": "#c8dac3",
    "line": "#e7d8ad",
    "draft": "#f1f4ec",
    "chart": "#b3cdb3",
    "error": "#f0ada4",
}


def contrast(first, second):
    """WCAG relative luminance, used for text and interactive-edge verification."""

    def luminance(value):
        channels = [int(value[i : i + 2], 16) / 255 for i in (1, 3, 5)]
        channels = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in channels]
        return sum(v * w for v, w in zip(channels, (0.2126, 0.7152, 0.0722), strict=True))

    values = sorted((luminance(first), luminance(second)))
    return (values[1] + 0.05) / (values[0] + 0.05)


# Logical pixels scale with Qt's device-pixel ratio; no bundled or remote font.
TYPE = {"body": 14, "caption": 12, "section": 16, "title": 23, "metric": 29}
SPACE = {"xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 24, "page": 28}
DIMENSIONS = {"control": 34, "navigation": 38, "radius": 4, "row": 34, "icon": 18}


def font(role="body", *, bold=False):
    from PySide6.QtGui import QFont, QFontDatabase

    result = QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont)
    result.setPixelSize(TYPE[role])
    result.setWeight(QFont.Weight.DemiBold if bold else QFont.Weight.Normal)
    return result


def label(text, role="", *, wrap=True):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QLabel, QSizePolicy

    result = QLabel(text)
    result.setObjectName(role)
    result.setTextFormat(Qt.TextFormat.PlainText)
    result.setWordWrap(wrap)
    result.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    return result


def heading(layout, title, description=None):
    layout.addWidget(label(title, "pageTitle"))
    if description:
        layout.addWidget(label(description, "subtitle"))


def apply_appearance(widget, dark=False):
    from PySide6.QtGui import QColor, QPalette

    colors = DARK if dark else LIGHT
    palette = QPalette(widget.palette())
    for role, key in (
        (QPalette.ColorRole.Window, "background"),
        (QPalette.ColorRole.Base, "surface"),
        (QPalette.ColorRole.AlternateBase, "raised"),
        (QPalette.ColorRole.Button, "surface"),
        (QPalette.ColorRole.WindowText, "text"),
        (QPalette.ColorRole.Text, "text"),
        (QPalette.ColorRole.ButtonText, "text"),
        (QPalette.ColorRole.Highlight, "selection"),
        (QPalette.ColorRole.HighlightedText, "text"),
        (QPalette.ColorRole.Mid, "rule"),
        (QPalette.ColorRole.Link, "accent"),
        (QPalette.ColorRole.PlaceholderText, "muted"),
    ):
        palette.setColor(role, QColor(colors[key]))
    widget.setPalette(palette)
    c = colors
    widget.setStyleSheet(f"""
        QWidget {{ color: {c["text"]}; font-size: {TYPE["body"]}px; }}
        QMainWindow, QDialog, QWidget#page {{ background: {c["background"]}; }}
        QLabel#brand {{ font-size: {TYPE["section"]}px; font-weight: 600; }}
        QLabel#pageTitle {{ font-size: {TYPE["title"]}px; font-weight: 600; }}
        QLabel#subtitle, QLabel#muted {{ color: {c["muted"]}; }}
        QLabel[error="true"] {{ color: {c["error"]}; }}
        QLabel#metric {{ font-size: {TYPE["metric"]}px; font-weight: 500; }}
        QFrame#metricStrip {{ border-top: 1px solid {c["rule"]};
            border-bottom: 1px solid {c["rule"]};
            }}
        QFrame#sourcePane {{ background: transparent; }}
        QGroupBox {{ border: 0; margin-top: 20px; }}
        QGroupBox::title {{ subcontrol-origin: margin; padding: 0; }}
        QPushButton {{ background: {c["surface"]}; border: 1px solid {c["border"]};
            border-radius: {DIMENSIONS["radius"]}px; padding: 6px 12px; min-height: 20px; }}
        QPushButton:hover {{ background: {c["raised"]}; }}
        QPushButton:pressed, QPushButton:checked {{ background: {c["selection"]}; }}
        QPushButton:focus, QComboBox:focus, QLineEdit:focus, QSpinBox:focus,
        QDoubleSpinBox:focus, QTextEdit:focus, QListWidget:focus {{ border-color: {c["focus"]};
            }}
        QPushButton:disabled {{ color: {c["disabled"]};
            background: {c["background"]};
            border-color: {c["rule"]};
            }}
        QPushButton#primary {{ background: {c["accent"]};
            color: {c["accent_ink"]};
            border-color: {c["accent"]};
            font-weight: 600;
            }}
        QPushButton#primary:disabled {{ background: {c["selection"]};
            color: {c["disabled"]};
            border-color: {c["rule"]};
            }}
        QPushButton#navigation {{ border: 0;
            border-radius: 0;
            background: transparent;
            padding: 10px 18px;
            }}
        QPushButton#navigation:checked {{ border-bottom: 2px solid {c["accent"]};
            font-weight: 600;
            }}
        QPushButton#disclosure {{ text-align: left;
            border: 0;
            background: transparent;
            padding: 8px 0;
            font-weight: 600;
            }}
        QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTextEdit, QListWidget {{
            background: {c["surface"]};
            border: 1px solid {c["border"]};
            border-radius: {DIMENSIONS["radius"]}px;
            padding: 6px; selection-background-color: {c["selection"]}; }}
        QComboBox {{ min-height: 20px; }}
        QComboBox QAbstractItemView {{ background: {c["surface"]}; color: {c["text"]};
            selection-background-color: {c["selection"]}; selection-color: {c["text"]}; }}
        QListWidget::item {{ padding: 8px; }}
        QTableWidget {{ background: {c["surface"]}; border: 0; gridline-color: {c["rule"]};
            selection-background-color: {c["selection"]}; selection-color: {c["text"]}; }}
        QHeaderView::section {{ background: {c["background"]};
            color: {c["muted"]};
            padding: 9px 12px;
            border: 0; border-bottom: 1px solid {c["rule"]}; }}
        QScrollArea {{ border: 0; background: transparent; }}
        QSplitter::handle {{ background: {c["rule"]}; }}
        QTabWidget::pane {{ border: 0; }}
        QTabBar::tab {{ padding: 8px 20px;
            background: {c["background"]};
            color: {c["text"]};
            }}
        QTabBar::tab:selected {{ border-bottom: 2px solid {c["accent"]}; }}
        QMenuBar, QMenu {{ background: {c["background"]}; color: {c["text"]}; }}
        QMenuBar::item:selected, QMenu::item:selected {{ background: {c["selection"]}; }}
        QStatusBar {{ background: {c["background"]}; color: {c["muted"]}; border: 0; }}
        QToolTip {{ background: {c["surface"]};
            color: {c["text"]};
            border: 1px solid {c["border"]};
            padding: 4px;
            }}
    """)
    from PySide6.QtCore import QSize
    from PySide6.QtWidgets import QPushButton

    for button in widget.findChildren(QPushButton):
        name = button.property("iconName")
        if name:
            color = c["accent_ink"] if button.objectName() == "primary" else c["text"]
            button.setIcon(icon(name, color))
            button.setIconSize(QSize(DIMENSIONS["icon"], DIMENSIONS["icon"]))
    widget.update()


PATHS = {
    "monitor": '<rect x="3" y="4" width="18" height="13" rx="2"/><path d="M8 21h8m-4-4v4"/>',
    "analysis": '<path d="M4 3v17h17M8 15v-4m5 4V7m5 8V4"/>',
    "settings": '<path d="M4 7h16M4 17h16"/><circle cx="9" cy="7" r="3"/>'
    '<circle cx="15" cy="17" r="3"/>',
    "play": '<path d="m8 5 11 7-11 7Z"/>',
    "pause": '<path d="M8 5v14M16 5v14"/>',
    "stop": '<rect x="6" y="6" width="12" height="12" rx="1"/>',
    "import": '<path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"/>',
    "road": '<path d="M9 3 4 21M15 3l5 18M12 3v3m0 4v4m0 4v3"/>',
    "camera": '<rect x="3" y="5" width="13" height="14" rx="2"/><path d="m16 10 5-3v10l-5-3"/>',
}


def icon(name, color):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QIcon, QPainter, QPixmap
    from PySide6.QtSvg import QSvgRenderer

    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
        f'fill="none" stroke="{color}" stroke-width="1.6" '
        f'stroke-linecap="round" stroke-linejoin="round">{PATHS[name]}</svg>'
    )
    pixmap = QPixmap(48, 48)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    QSvgRenderer(svg.encode()).render(painter)
    painter.end()
    result = QIcon(pixmap)
    return result


class FocusFrame(QFocusFrame):
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(self.palette().color(QPalette.ColorRole.Link), 2))
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -2, -2), 4, 4)


class FocusOutline(QObject):
    """A native focus overlay never changes a field's border or layout dimensions."""

    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.frame = FocusFrame(owner)
        self.frame.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        QApplication.instance().focusChanged.connect(self.changed)

    def changed(self, previous, current):
        if isinstance(current, QWidget) and self.owner.isAncestorOf(current):
            self.frame.setWidget(current)
        else:
            self.frame.setWidget(None)


class Foldout(QWidget):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.toggle = QPushButton()
        self.toggle.setObjectName("disclosure")
        self.toggle.setCheckable(True)
        self.toggle.setAccessibleName(title)
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, SPACE["sm"], 0, SPACE["sm"])
        self.body_layout.setSpacing(SPACE["lg"])
        layout.addWidget(self.toggle)
        layout.addWidget(self.body)
        self.toggle.toggled.connect(lambda opened: self.set_open(title, opened))
        self.set_open(title, False)

    def set_open(self, title, opened):
        self.toggle.setText(f"{'▾' if opened else '▸'}  {title}")
        self.body.setVisible(opened)


def colors_for(widget):
    return DARK if widget.palette().color(QPalette.ColorRole.Window).lightness() < 128 else LIGHT


def feedback(widget, text, *, error=False):
    widget.setText(text)
    widget.setProperty("error", error)
    widget.setAccessibleDescription(text)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
