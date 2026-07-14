from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QMouseEvent, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from app.models import AnalysisResult, RootEvent


class PitchTimeline(QWidget):
    note_selected = Signal(int)
    seek_requested = Signal(int)

    LOW_MIDI = 23
    HIGH_MIDI = 60
    PIXELS_PER_SECOND = 96.0

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._duration_ms = 0
        self._position_ms = 0
        self._result: AnalysisResult | None = None
        self._selected_index: int | None = None
        self._phase = 0.0

        self.setMinimumSize(560, 340)
        self.setMouseTracking(True)

        self._timer = QTimer(self)
        self._timer.setInterval(90)
        self._timer.timeout.connect(self._animate)
        self._timer.start()

    def sizeHint(self) -> QSize:
        return QSize(860, 520)

    def set_duration(self, duration_ms: int) -> None:
        self._duration_ms = max(0, duration_ms)
        self.update()

    def set_position(self, position_ms: int) -> None:
        self._position_ms = max(0, position_ms)
        self.update()

    def set_result(self, result: AnalysisResult | None) -> None:
        self._result = result
        self._selected_index = None
        if result is not None:
            self._duration_ms = int(result.duration * 1000)
        self.update()

    def set_selected_index(self, index: int | None) -> None:
        self._selected_index = index
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        self._draw_background(painter)
        self._draw_grid(painter)
        self._draw_time_grid(painter)
        self._draw_roots(painter)
        self._draw_playhead(painter)
        self._draw_scanlines(painter)
        self._draw_state_text(painter)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if event.button() != Qt.LeftButton:
            return

        clicked_index = self._root_index_at(event.position())
        if clicked_index is not None:
            self._selected_index = clicked_index
            self.note_selected.emit(clicked_index)
            self.update()
            return

        center_x = self.width() / 2
        seconds = (self._position_ms / 1000) + (
            (event.position().x() - center_x) / self.PIXELS_PER_SECOND
        )
        seconds = max(0.0, min(seconds, self._duration_ms / 1000))
        self.seek_requested.emit(int(seconds * 1000))

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        clicked_index = self._root_index_at(event.position())
        if clicked_index is not None and self._result is not None:
            root = self._result.roots[clicked_index]
            self.seek_requested.emit(int(root.start * 1000))

    def _draw_background(self, painter: QPainter) -> None:
        gradient = QLinearGradient(0, 0, self.width(), self.height())
        gradient.setColorAt(0.0, QColor("#02060B"))
        gradient.setColorAt(0.55, QColor("#07131B"))
        gradient.setColorAt(1.0, QColor("#150417"))
        painter.fillRect(self.rect(), gradient)

    def _draw_grid(self, painter: QPainter) -> None:
        rows = self.HIGH_MIDI - self.LOW_MIDI + 1
        row_height = self.height() / rows

        for row in range(rows + 1):
            y = row * row_height
            midi = self.HIGH_MIDI - row
            octave_line = midi % 12 == 0
            color = QColor(0, 246, 255, 62) if octave_line else QColor(18, 64, 76, 105)
            painter.setPen(QPen(color, 1.2 if octave_line else 0.7))
            painter.drawLine(0, int(y), self.width(), int(y))

    def _draw_time_grid(self, painter: QPainter) -> None:
        center_x = self.width() / 2
        current_seconds = self._position_ms / 1000
        left_seconds = current_seconds - center_x / self.PIXELS_PER_SECOND
        right_seconds = current_seconds + (self.width() - center_x) / self.PIXELS_PER_SECOND

        first_second = math.floor(left_seconds) - 1
        last_second = math.ceil(right_seconds) + 1

        font = QFont("Consolas", 8)
        painter.setFont(font)

        for second in range(first_second, last_second + 1):
            x = center_x + (second - current_seconds) * self.PIXELS_PER_SECOND
            if not 0 <= x <= self.width():
                continue

            major = second % 5 == 0
            painter.setPen(
                QPen(
                    QColor(255, 43, 214, 82) if major else QColor(31, 74, 84, 85),
                    1,
                )
            )
            painter.drawLine(int(x), 0, int(x), self.height())

            if major and second >= 0:
                painter.setPen(QColor("#C94BC0"))
                painter.drawText(
                    QRectF(x + 5, 5, 70, 18),
                    Qt.AlignLeft | Qt.AlignVCenter,
                    self._format_seconds(second),
                )

    def _draw_roots(self, painter: QPainter) -> None:
        if self._result is None:
            self._draw_standby_signal(painter)
            return

        for index, root in enumerate(self._result.roots):
            rect = self._root_rect(root)
            if rect.right() < 0 or rect.left() > self.width():
                continue

            selected = index == self._selected_index
            low_confidence = root.confidence < 0.42

            if root.midi is None:
                fill = QColor(89, 45, 92, 80)
                border = QColor("#89457F")
            elif low_confidence:
                fill = QColor(255, 43, 214, 85)
                border = QColor("#FF4BDA")
            else:
                fill = QColor(0, 246, 255, 88)
                border = QColor("#00F6FF")

            if root.manually_edited:
                border = QColor("#F6FF75")

            if selected:
                glow = QColor(border)
                glow.setAlpha(55)
                painter.setPen(QPen(glow, 9))
                painter.setBrush(Qt.NoBrush)
                painter.drawRoundedRect(rect, 4, 4)

            painter.setBrush(fill)
            painter.setPen(QPen(border, 1.4 if selected else 1.0))
            painter.drawRoundedRect(rect, 4, 4)

            painter.setPen(QColor("#FFFFFF"))
            font = QFont("Consolas", 8)
            font.setBold(True)
            painter.setFont(font)
            label = "休符" if root.midi is None else root.note_name
            painter.drawText(rect.adjusted(3, 0, -3, 0), Qt.AlignCenter, label)

    def _draw_standby_signal(self, painter: QPainter) -> None:
        center_y = self.height() * 0.68
        path = QPainterPath()
        path.moveTo(0, center_y)

        for x in range(0, self.width() + 4, 4):
            y = center_y
            y += math.sin(x * 0.04 + self._phase) * 8
            y += math.sin(x * 0.012 - self._phase * 0.6) * 5
            path.lineTo(x, y)

        painter.setPen(QPen(QColor(255, 43, 214, 42), 8))
        painter.drawPath(path)
        painter.setPen(QPen(QColor(255, 43, 214, 125), 1.2))
        painter.drawPath(path)

    def _draw_playhead(self, painter: QPainter) -> None:
        x = self.width() / 2
        glow = QColor("#00F6FF")
        glow.setAlpha(70 + int(25 * (1 + math.sin(self._phase))))
        painter.setPen(QPen(glow, 10))
        painter.drawLine(int(x), 0, int(x), self.height())

        painter.setPen(QPen(QColor("#E5FFFF"), 1.4))
        painter.drawLine(int(x), 0, int(x), self.height())

        painter.setBrush(QColor("#00F6FF"))
        painter.setPen(Qt.NoPen)
        painter.drawPolygon(
            [QPointF(x - 8, 0), QPointF(x + 8, 0), QPointF(x, 12)]
        )

    def _draw_scanlines(self, painter: QPainter) -> None:
        painter.setPen(QPen(QColor(255, 255, 255, 7), 1))
        for y in range(2, self.height(), 4):
            painter.drawLine(0, y, self.width(), y)

    def _draw_state_text(self, painter: QPainter) -> None:
        if self._result is None:
            heading = "ルート音解析 待機中"
            subtext = "音源を読み込み、ルート音解析を実行してください"
        else:
            return

        heading_font = QFont("Yu Gothic UI", 15)
        heading_font.setBold(True)
        painter.setFont(heading_font)
        painter.setPen(QColor("#BFFAFF"))
        painter.drawText(
            QRectF(20, self.height() * 0.36, self.width() - 40, 30),
            Qt.AlignCenter,
            heading,
        )

        painter.setFont(QFont("Yu Gothic UI", 9))
        painter.setPen(QColor("#697F8C"))
        painter.drawText(
            QRectF(20, self.height() * 0.36 + 34, self.width() - 40, 24),
            Qt.AlignCenter,
            subtext,
        )

    def _root_rect(self, root: RootEvent) -> QRectF:
        center_x = self.width() / 2
        current_seconds = self._position_ms / 1000

        start_x = center_x + (root.start - current_seconds) * self.PIXELS_PER_SECOND
        end_x = center_x + (root.end - current_seconds) * self.PIXELS_PER_SECOND
        width = max(12.0, end_x - start_x - 2.0)

        if root.midi is None:
            y = self.height() - 18
            height = 12
        else:
            rows = self.HIGH_MIDI - self.LOW_MIDI + 1
            row_height = self.height() / rows
            row = self.HIGH_MIDI - root.midi
            y = row * row_height + 1
            height = max(7.0, row_height - 2)

        return QRectF(start_x + 1, y, width, height)

    def _root_index_at(self, point: QPointF) -> int | None:
        if self._result is None:
            return None
        for index, root in enumerate(self._result.roots):
            if self._root_rect(root).adjusted(-2, -2, 2, 2).contains(point):
                return index
        return None

    def _animate(self) -> None:
        self._phase += 0.18
        self.update()

    @staticmethod
    def _format_seconds(seconds: int) -> str:
        minutes, seconds = divmod(max(0, seconds), 60)
        return f"{minutes:02d}:{seconds:02d}"
