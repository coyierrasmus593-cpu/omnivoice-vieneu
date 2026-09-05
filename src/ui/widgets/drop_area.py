# -*- coding: utf-8 -*-
"""Drag-and-drop area widget for reference audio files."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from src.core.audio_utils import SUPPORTED_FORMATS


class DropArea(QWidget):
    """A drop zone that accepts audio files via drag-and-drop or click.

    Signals:
        file_dropped(str): Emitted with the file path when a valid audio file is dropped.
    """

    file_dropped = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setObjectName("drop_area")
        self._setup_ui()
        self._is_hovering = False

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.label = QLabel("Kéo thả file âm thanh vào đây\nhoặc nhấn Duyệt")
        self.label.setObjectName("drop_label")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setWordWrap(True)
        layout.addWidget(self.label)

        self.setMinimumHeight(80)

    # ------------------------------------------------------------------
    # Drag & Drop
    # ------------------------------------------------------------------
    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if any(self._is_valid_audio(u.toLocalFile()) for u in urls):
                event.acceptProposedAction()
                self._set_hover(True)
                return
        event.ignore()

    def dragLeaveEvent(self, event) -> None:
        self._set_hover(False)

    def dropEvent(self, event) -> None:
        self._set_hover(False)
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if self._is_valid_audio(path):
                self.file_dropped.emit(path)
                return

    # ------------------------------------------------------------------
    # Visual feedback
    # ------------------------------------------------------------------
    def _set_hover(self, hovering: bool) -> None:
        self._is_hovering = hovering
        if hovering:
            self.setProperty("hover", True)
        else:
            self.setProperty("hover", False)
        # Force style refresh
        self.style().unpolish(self)
        self.style().polish(self)

    def set_file_info(self, filename: str, duration: str) -> None:
        """Update label to show loaded file info."""
        self.label.setText(f"Giọng mẫu: {filename}\nThời lượng: {duration}")
        self.setMinimumHeight(50)
        self.setMaximumHeight(60)

    def reset(self) -> None:
        """Reset to default state."""
        self.label.setText("Kéo thả file âm thanh vào đây\nhoặc nhấn Duyệt")
        self.setMinimumHeight(80)
        self.setMaximumHeight(16777215)  # QWIDGETSIZE_MAX

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _is_valid_audio(path: str) -> bool:
        return Path(path).suffix.lower() in SUPPORTED_FORMATS
