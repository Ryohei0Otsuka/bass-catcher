from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from app.main_window import MainWindow


def resource_path(relative: str) -> Path:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    return root / relative


def create_runtime_icon() -> QIcon:
    icon_path = resource_path("assets/bass_catcher.ico")
    if icon_path.exists():
        return QIcon(str(icon_path))

    pixmap = QPixmap(64, 64)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setPen(QColor("#00F6FF"))
    painter.setBrush(QColor("#06141C"))
    painter.drawRoundedRect(4, 4, 56, 56, 12, 12)
    painter.setPen(QColor("#FF2BD6"))
    painter.setBrush(QColor("#FF2BD6"))
    painter.drawRoundedRect(14, 18, 8, 30, 3, 3)
    painter.drawRoundedRect(28, 24, 8, 24, 3, 3)
    painter.drawRoundedRect(42, 11, 8, 37, 3, 3)
    painter.end()
    return QIcon(pixmap)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Bass Catcher")
    app.setOrganizationName("Ryohei0Otsuka")
    app.setWindowIcon(create_runtime_icon())

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
