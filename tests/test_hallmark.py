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
