"""Build an Intel, self-contained ROADLENS.app with an offline model and camera helper."""

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPen

from roadlens.cameras import build_bridge


def main():
    if platform.system() != "Darwin" or platform.machine() != "x86_64":
        raise SystemExit("Build the Intel macOS app on an Intel Mac with the project .venv.")
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QGuiApplication([])
    iconset = root / "build/ROADLENS.iconset"
    iconset.mkdir(parents=True, exist_ok=True)
    for size in (16, 32, 128, 256, 512):
        for scale in (1, 2):
            image = QImage(size * scale, size * scale, QImage.Format.Format_ARGB32)
            image.fill(Qt.GlobalColor.transparent)
            painter = QPainter(image)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.scale(size * scale / 1024, size * scale / 1024)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#102d3b"))
            painter.drawRoundedRect(QRectF(20, 20, 984, 984), 220, 220)
            painter.setBrush(QColor("#1b4b5b"))
            painter.drawEllipse(QRectF(178, 178, 668, 668))
            painter.setPen(QPen(QColor("#68e3c4"), 42))
            painter.drawEllipse(QRectF(242, 242, 540, 540))
            painter.setPen(QPen(QColor("#ffffff"), 35))
            painter.drawLine(QPointF(450, 340), QPointF(350, 690))
            painter.drawLine(QPointF(574, 340), QPointF(674, 690))
            painter.setPen(QPen(QColor("#ffca77"), 20, Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(512, 350), QPointF(512, 690))
            painter.end()
            suffix = "@2x" if scale == 2 else ""
            if not image.save(str(iconset / f"icon_{size}x{size}{suffix}.png")):
                raise OSError("Could not create app icon")
    subprocess.run(
        ["iconutil", "-c", "icns", str(iconset), "-o", str(root / "build/ROADLENS.icns")],
        check=True,
    )
    helper = build_bridge().parents[2]
    subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "ROADLENS.spec"], check=True
    )
    target = root / "dist/ROADLENS.app/Contents/Helpers/ROADLENS Camera.app"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(helper, target)
    subprocess.run(["codesign", "--force", "--sign", "-", str(target)], check=True)
    subprocess.run(
        ["codesign", "--force", "--deep", "--sign", "-", "dist/ROADLENS.app"], check=True
    )
    subprocess.run(["codesign", "--verify", "--deep", "--strict", "dist/ROADLENS.app"], check=True)
    print(f"Built and verified: {root / 'dist/ROADLENS.app'}")
    app.quit()


if __name__ == "__main__":
    main()
