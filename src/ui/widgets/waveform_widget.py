# -*- coding: utf-8 -*-
"""Waveform visualization widget using QPainter."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QWidget


class WaveformWidget(QWidget):
    """Draws an audio waveform from pre-computed envelope data."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data: np.ndarray = np.zeros(200)
        self._progress: float = 0.0  # 0.0–1.0 playback position
        self._bar_color = QColor("#4FC3F7")
        self._played_color = QColor("#81D4FA")
        self._bg_color = QColor("transparent")
        self.setMinimumHeight(48)
        self.setMaximumHeight(80)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_data(self, envelope: np.ndarray) -> None:
        """Set waveform envelope data (values in [0, 1])."""
        self._data = envelope
        self.update()

    def set_progress(self, progress: float) -> None:
        """Set playback progress (0.0–1.0) for cursor position."""
        self._progress = max(0.0, min(1.0, progress))
        self.update()

    def clear(self) -> None:
        """Clear waveform."""
        self._data = np.zeros(200)
        self._progress = 0.0
        self.update()

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------
    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        n = len(self._data)

        if n == 0 or w == 0:
            painter.end()
            return

        bar_w = max(1.5, (w - n) / n)
        gap = max(0.5, bar_w * 0.3)
        total_bar_w = bar_w + gap
        center_y = h / 2.0

        played_x = self._progress * w

        for i in range(n):
            x = i * total_bar_w
            if x > w:
                break

            amp = self._data[i]
            bar_h = max(2, amp * (h * 0.9))  # at least 2px visible

            rect = QRectF(x, center_y - bar_h / 2, bar_w, bar_h)

            if x < played_x:
                painter.setBrush(self._played_color)
            else:
                painter.setBrush(self._bar_color)

            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(rect, bar_w / 2, bar_w / 2)

        # Playback cursor line
        if self._progress > 0:
            pen = QPen(QColor("#FFFFFF"), 1.5)
            painter.setPen(pen)
            cx = int(played_x)
            painter.drawLine(cx, 2, cx, h - 2)

        painter.end()
