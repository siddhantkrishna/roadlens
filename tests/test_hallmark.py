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
