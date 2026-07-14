from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QWidget


class CyberPanel(QFrame):
    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        accent: str = "#00F6FF",
    ) -> None:
        super().__init__(parent)
        self._accent = QColor(accent)
        self.setObjectName("cyberPanel")
        self.setAttribute(Qt.WA_StyledBackground, True)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        rect = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)
        path = QPainterPath()
        path.addRoundedRect(rect, 10.0, 10.0)

        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        gradient.setColorAt(0.0, QColor(5, 16, 24, 244))
        gradient.setColorAt(0.62, QColor(5, 8, 15, 248))
        gradient.setColorAt(1.0, QColor(20, 4, 24, 244))
        painter.fillPath(path, gradient)

        painter.setPen(QPen(QColor(37, 90, 105, 170), 1.0))
        painter.drawPath(path)

        self._draw_corners(painter, rect)

    def _draw_corners(self, painter: QPainter, rect: QRectF) -> None:
        length = 17.0
        segments = [
            (rect.topLeft(), rect.topLeft() + QPointF(length, 0)),
            (rect.topLeft(), rect.topLeft() + QPointF(0, length)),
            (rect.topRight(), rect.topRight() + QPointF(-length, 0)),
            (rect.topRight(), rect.topRight() + QPointF(0, length)),
            (rect.bottomLeft(), rect.bottomLeft() + QPointF(length, 0)),
            (rect.bottomLeft(), rect.bottomLeft() + QPointF(0, -length)),
            (rect.bottomRight(), rect.bottomRight() + QPointF(-length, 0)),
            (rect.bottomRight(), rect.bottomRight() + QPointF(0, -length)),
        ]

        glow = QColor(self._accent)
        glow.setAlpha(55)
        painter.setPen(QPen(glow, 5))
        for start, end in segments:
            painter.drawLine(start, end)

        color = QColor(self._accent)
        color.setAlpha(225)
        painter.setPen(QPen(color, 1.4))
        for start, end in segments:
            painter.drawLine(start, end)
