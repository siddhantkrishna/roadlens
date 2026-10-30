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
