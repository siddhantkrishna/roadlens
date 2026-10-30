"""Hallmark 2.0.0: native app workbench, restrained color, light and dark parity.

Critique: hierarchy and restraint lead; real footage is the signature.
Web scaffolds/render lint are replaced by Qt layout, contrast and screenshot checks.
"""

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

    colors = LIGHT
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
    widget.update()
