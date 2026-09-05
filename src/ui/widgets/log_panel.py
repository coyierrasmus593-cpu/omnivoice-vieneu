# -*- coding: utf-8 -*-
"""Log Panel widget — real-time log display with color-coded levels."""

from __future__ import annotations

import logging
from datetime import datetime

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)

# Level → color mapping (Catppuccin Mocha palette)
LEVEL_COLORS = {
    "INFO": "#a6adc8",      # muted gray
    "WARNING": "#f9e2af",   # yellow
    "ERROR": "#f38ba8",     # red/pink
    "SUCCESS": "#a6e3a1",   # green
    "DEBUG": "#6c7086",     # dim gray
    "PROGRESS": "#89b4fa",  # blue (accent)
}


class _LogSignalBridge(QObject):
    """Thread-safe bridge: emits a signal from any thread, received on GUI thread."""
    log_received = Signal(str, str)  # (message, level)


class LogPanelHandler(logging.Handler):
    """Custom logging handler that pipes log records into the LogPanel widget.

    Uses a Qt Signal to safely cross thread boundaries (background → GUI).
    Filters out noisy messages from third-party libraries.
    """

    # Logger names to skip (too noisy)
    _SKIP_LOGGERS = {"transformers", "huggingface_hub", "urllib3", "filelock", "tqdm"}

    def __init__(self, bridge: _LogSignalBridge):
        super().__init__()
        self._bridge = bridge

    def emit(self, record: logging.LogRecord) -> None:
        try:
            # Skip noisy third-party loggers
            top_module = record.name.split(".")[0]
            if top_module in self._SKIP_LOGGERS:
                return

            msg = self.format(record)
            level = record.levelname
            self._bridge.log_received.emit(msg, level)
        except Exception:
            self.handleError(record)


class LogPanel(QWidget):
    """Right-side log panel showing timestamped, color-coded log entries."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("log_panel")

        # Thread-safe bridge for logging handler
        self._bridge = _LogSignalBridge(self)
        self._bridge.log_received.connect(self.append_log)

        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        # Header row
        header = QHBoxLayout()
        title = QLabel("Nhật ký")
        title.setObjectName("log_title")
        title.setStyleSheet("font-weight: bold; font-size: 13px; color: #89b4fa;")
        header.addWidget(title)

        header.addStretch()

        self.btn_clear = QPushButton("Xoá")
        self.btn_clear.setObjectName("btn_secondary")
        self.btn_clear.setFixedHeight(24)
        self.btn_clear.setMinimumWidth(50)
        self.btn_clear.clicked.connect(self.clear_log)
        header.addWidget(self.btn_clear)

        layout.addLayout(header)

        # Log text area
        self.log_text = QPlainTextEdit()
        self.log_text.setObjectName("log_text")
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumBlockCount(2000)  # keep memory bounded
        self.log_text.setFont(QFont("Consolas", 9))
        self.log_text.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        layout.addWidget(self.log_text)

    @Slot(str, str)
    def append_log(self, message: str, level: str = "INFO") -> None:
        """Append a timestamped, color-coded log entry.

        Args:
            message: Log message text.
            level: Log level (INFO, WARNING, ERROR, SUCCESS, PROGRESS, DEBUG).
        """
        timestamp = datetime.now().strftime("%H:%M:%S")
        color = LEVEL_COLORS.get(level.upper(), LEVEL_COLORS["INFO"])

        # Build colored HTML line
        escaped = (
            message.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
        html = (
            f'<span style="color:#585b70">{timestamp}</span> '
            f'<span style="color:{color}">{escaped}</span>'
        )
        self.log_text.appendHtml(html)

        # Auto-scroll to bottom
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    @Slot()
    def clear_log(self) -> None:
        """Clear all log entries."""
        self.log_text.clear()
        self.append_log("Đã xoá nhật ký", "INFO")

    def create_logging_handler(self, level: int = logging.INFO) -> LogPanelHandler:
        """Create a Python logging.Handler that pipes into this panel.

        Thread-safe: uses a Qt Signal bridge to marshal messages to the GUI thread.
        """
        handler = LogPanelHandler(self._bridge)
        handler.setLevel(level)
        formatter = logging.Formatter("%(message)s")
        handler.setFormatter(formatter)
        return handler
