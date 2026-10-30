"""Native Hallmark gates and interactions; public fixtures, never physical cameras."""

from roadlens.desktop_design import LIGHT, contrast


def test_light_tokens_cover_text_fields_and_focus_contrast():
    for role in ("text", "muted"):
        for surface in ("background", "surface", "raised"):
            assert contrast(LIGHT[role], LIGHT[surface]) >= 4.5
    for role in ("border", "focus", "chart"):
        assert contrast(LIGHT[role], LIGHT["surface"]) >= 3
    assert contrast(LIGHT["accent"], LIGHT["accent_ink"]) >= 4.5
