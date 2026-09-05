# -*- coding: utf-8 -*-
"""License activation dialog — shown before app starts."""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QApplication,
)

from src.core.license_client import get_license_manager, get_machine_id
from src.core.license_models import LicenseInfo

logger = logging.getLogger(__name__)


class LicenseDialog(QDialog):
    """Modal dialog for license activation at startup."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI86.PRO — Kích hoạt bản quyền")
        self.setFixedSize(500, 430)
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.CustomizeWindowHint
        )

        self._license_info: dict | None = None
        self._mgr = get_license_manager()

        self._build_ui()
        self._apply_style()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(12)

        # Logo + Title
        from pathlib import Path
        icon_path = Path(__file__).parent.parent.parent.parent / "Applogo.png"
        if icon_path.exists():
            logo = QLabel()
            pixmap = QPixmap(str(icon_path)).scaled(
                64, 64, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            logo.setPixmap(pixmap)
            logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(logo)

        title = QLabel("AI86.PRO Voice Cloner & TTS")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #89b4fa; background: transparent;")
        layout.addWidget(title)

        subtitle = QLabel("Vui lòng nhập License Key để kích hoạt phần mềm")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet("font-size: 12px; color: #a6adc8; background: transparent;")
        layout.addWidget(subtitle)

        layout.addSpacing(8)

        # License Key input
        lbl_key = QLabel("License Key:")
        lbl_key.setStyleSheet("color: #bac2de; font-size: 13px; background: transparent;")
        layout.addWidget(lbl_key)

        self.input_key = QLineEdit()
        self.input_key.setObjectName("license_key_input")
        self.input_key.setPlaceholderText("XXXX-XXXX-XXXX-XXXX")
        self.input_key.setMinimumHeight(36)
        self.input_key.returnPressed.connect(self._on_activate)
        layout.addWidget(self.input_key)

        # Activate button
        self.btn_activate = QPushButton("Kích hoạt")
        self.btn_activate.setObjectName("btn_primary")
        self.btn_activate.setMinimumHeight(40)
        self.btn_activate.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_activate.clicked.connect(self._on_activate)
        layout.addWidget(self.btn_activate)

        # Status
        self.lbl_status = QLabel("")
        self.lbl_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setStyleSheet("font-size: 12px; background: transparent;")
        layout.addWidget(self.lbl_status)

        layout.addStretch()

        # Machine ID (bottom)
        machine_row = QHBoxLayout()
        lbl_mid = QLabel("Machine ID:")
        lbl_mid.setStyleSheet("color: #585b70; font-size: 11px; background: transparent;")
        machine_row.addWidget(lbl_mid)

        machine_id = get_machine_id()
        self.lbl_machine = QLabel(machine_id[:16] + "..." if len(machine_id) > 16 else machine_id)
        self.lbl_machine.setStyleSheet("color: #6c7086; font-size: 11px; font-family: Consolas; background: transparent;")
        self.lbl_machine.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.lbl_machine.setToolTip(machine_id)
        machine_row.addWidget(self.lbl_machine)

        btn_copy = QPushButton("Sao chép")
        btn_copy.setFixedHeight(22)
        btn_copy.setMinimumWidth(60)
        btn_copy.setStyleSheet("font-size: 10px; padding: 2px 8px;")
        btn_copy.clicked.connect(lambda: QApplication.clipboard().setText(machine_id))
        machine_row.addWidget(btn_copy)

        machine_row.addStretch()
        layout.addLayout(machine_row)

        # Close button
        btn_close = QPushButton("Đóng")
        btn_close.setMinimumHeight(32)
        btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_close.clicked.connect(self.reject)
        layout.addWidget(btn_close)

    def _apply_style(self) -> None:
        self.setStyleSheet("""
            QDialog {
                background-color: #1e1e2e;
            }
            QLineEdit#license_key_input {
                background-color: #313244;
                color: #cdd6f4;
                border: 1px solid #45475a;
                border-radius: 6px;
                padding: 8px 12px;
                font-size: 15px;
                font-family: "Consolas", "Courier New", monospace;
                selection-background-color: #89b4fa;
                selection-color: #1e1e2e;
            }
            QLineEdit#license_key_input:focus {
                border-color: #89b4fa;
            }
            QPushButton#btn_primary {
                background-color: #89b4fa;
                color: #1e1e2e;
                font-weight: bold;
                font-size: 14px;
                border: none;
                border-radius: 6px;
                padding: 8px 22px;
            }
            QPushButton#btn_primary:hover {
                background-color: #74c7ec;
            }
            QPushButton#btn_primary:pressed {
                background-color: #89dceb;
            }
            QPushButton#btn_primary:disabled {
                background-color: #45475a;
                color: #585b70;
            }
            QPushButton {
                background-color: #45475a;
                color: #cdd6f4;
                border: 1px solid #585b70;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #585b70;
            }
        """)

    @Slot()
    def _on_activate(self) -> None:
        key = self.input_key.text().strip()
        if not key:
            self.lbl_status.setStyleSheet("color: #f38ba8; font-size: 12px; background: transparent;")
            self.lbl_status.setText("Vui lòng nhập License Key")
            return

        self.btn_activate.setEnabled(False)
        self.btn_activate.setText("Đang xác thực...")
        self.lbl_status.setStyleSheet("color: #89b4fa; font-size: 12px; background: transparent;")
        self.lbl_status.setText("⏳ Đang kết nối server...")
        QApplication.processEvents()

        try:
            result = self._mgr.verify(key)
        except Exception as e:
            result = {"valid": False, "message": str(e)}

        self.btn_activate.setEnabled(True)
        self.btn_activate.setText("Kích hoạt")

        if result.get("valid"):
            self._license_info = result
            self._license_info["machine_id"] = get_machine_id()
            days = result.get("days_left", "?")
            self.lbl_status.setStyleSheet("color: #a6e3a1; font-size: 12px; background: transparent;")
            self.lbl_status.setText(f"✅ Kích hoạt thành công! Còn {days} ngày sử dụng.")
            logger.info("License activated successfully")
            # Auto-close after short delay
            from PySide6.QtCore import QTimer
            QTimer.singleShot(1000, self.accept)
        else:
            msg = result.get("message", "Không thể xác thực")
            self.lbl_status.setStyleSheet("color: #f38ba8; font-size: 12px; background: transparent;")
            self.lbl_status.setText(f"❌ {msg}")
            logger.warning(f"License activation failed: {msg}")

    def get_license_info(self) -> dict | None:
        return self._license_info

    def try_auto_verify(self) -> bool:
        """Try to verify stored token. Returns True if valid."""
        stored = self._mgr.load()
        if not stored:
            return False

        try:
            result = self._mgr.verify(stored)
            if result.get("valid"):
                self._license_info = result
                self._license_info["machine_id"] = get_machine_id()
                return True
        except Exception:
            pass
        return False
