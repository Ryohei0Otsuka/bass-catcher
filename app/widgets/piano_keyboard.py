from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QWidget

from app.models import midi_to_note_name


class PianoKeyboard(QWidget):
    LOW_MIDI = 23
    HIGH_MIDI = 60
    BLACK_CLASSES = {1, 3, 6, 8, 10}

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedWidth(96)
        self.setMinimumHeight(340)

    def sizeHint(self) -> QSize:
        return QSize(96, 520)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)

        gradient = QLinearGradient(0, 0, self.width(), 0)
        gradient.setColorAt(0, QColor("#03050A"))
        gradient.setColorAt(1, QColor("#0A1822"))
        painter.fillRect(self.rect(), gradient)

        count = self.HIGH_MIDI - self.LOW_MIDI + 1
        row_height = self.height() / count

        font = QFont("Consolas", 8)
        font.setBold(True)
        painter.setFont(font)

        for row, midi in enumerate(range(self.HIGH_MIDI, self.LOW_MIDI - 1, -1)):
            y = row * row_height
            rect = QRectF(0, y, self.width(), row_height)
            pitch_class = midi % 12
            is_black = pitch_class in self.BLACK_CLASSES
            is_c = pitch_class == 0

            fill = QColor("#070910") if is_black else QColor("#101924")
            if is_c:
                fill = QColor("#0C2833")
            painter.fillRect(rect, fill)

            if is_black:
                black_rect = QRectF(0, y + 1, self.width() * 0.52, max(2, row_height - 2))
                painter.fillRect(black_rect, QColor("#020307"))
                painter.setPen(QPen(QColor("#4A214C"), 1))
                painter.drawRect(black_rect)

            painter.setPen(QPen(QColor("#174653") if is_c else QColor("#172B37"), 1))
            painter.drawLine(0, int(rect.bottom()), self.width(), int(rect.bottom()))

            painter.setPen(QColor("#00F6FF") if is_c else QColor("#B9D9E0"))
            painter.drawText(
                rect.adjusted(4, 0, -7, 0),
                Qt.AlignVCenter | Qt.AlignRight,
                midi_to_note_name(midi),
            )

        painter.setPen(QPen(QColor(0, 246, 255, 50), 6))
        painter.drawLine(self.width() - 2, 0, self.width() - 2, self.height())
        painter.setPen(QPen(QColor("#00F6FF"), 1))
        painter.drawLine(self.width() - 1, 0, self.width() - 1, self.height())
