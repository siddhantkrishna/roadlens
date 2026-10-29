"""Pixel-bounded text for OpenCV previews; full names remain in source metadata."""

import cv2


def fit_text(text: str, width: int, scale: float = 0.5) -> str:
    text = " ".join(text.split()).encode("ascii", "replace").decode("ascii")

    def size(value):
        return cv2.getTextSize(value, cv2.FONT_HERSHEY_SIMPLEX, scale, 1)[0][0]

    if size(text) <= width:
        return text
    if size("...") > width:
        return ""
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if size(text[:middle] + "...") <= width:
            low = middle
        else:
            high = middle - 1
    return text[:low] + "..."
