# -*- coding: utf-8 -*-
"""License info popup — shows current license details."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from src.core.license_models import LicenseInfo


class LicenseInfoDialog(QDialog):
    """Popup showing current license information."""

    license_deactivated = Signal()  # Emitted when user deactivates license

    def __init__(self, license_info: LicenseInfo, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Thông tin bản quyền")
        self.setFixedSize(460, 360)
        self._info = license_info
        self._build_ui()
        self._apply_style()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 20, 28, 20)
        layout.setSpacing(8)

        # Title
        title = QLabel("📋 Thông tin bản quyền")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #89b4fa; background: transparent;")
        layout.addWidget(title)
        layout.addSpacing(12)

        # Fields
        fields = [
            ("License Key:", self._mask_key(self._info.license_key)),
            ("Khách hàng:", self._info.username or "—"),
            ("Email:", self._info.email or "—"),
            ("Hạn sử dụng:", self._format_expiry()),
            ("Machine ID:", self._short_machine_id()),
            ("Trạng thái:", self._format_status()),
        ]

        for label_text, value_text in fields:
            row = QHBoxLayout()
            lbl = QLabel(label_text)
            lbl.setFixedWidth(110)
            lbl.setStyleSheet("color: #a6adc8; font-size: 12px; background: transparent;")
            row.addWidget(lbl)

            val = QLabel(value_text)
            val.setStyleSheet("color: #cdd6f4; font-size: 12px; font-weight: bold; background: transparent;")
            val.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            val.setWordWrap(True)
            row.addWidget(val, stretch=1)
            layout.addLayout(row)

        layout.addStretch()

        # Buttons
        btn_row = QHBoxLayout()

        btn_copy = QPushButton("Sao chép Machine ID")
        btn_copy.setMinimumWidth(140)
        btn_copy.clicked.connect(
            lambda: QApplication.clipboard().setText(self._info.machine_id)
        )
        btn_row.addWidget(btn_copy)

        btn_deactivate = QPushButton("Huỷ kích hoạt")
        btn_deactivate.setObjectName("btn_danger")
        btn_deactivate.setMinimumWidth(110)
        btn_deactivate.clicked.connect(self._on_deactivate)
        btn_row.addWidget(btn_deactivate)

        btn_row.addStretch()

        btn_close = QPushButton("Đóng")
        btn_close.setObjectName("btn_primary")
        btn_close.setMinimumWidth(80)
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_close)

        layout.addLayout(btn_row)

    def _apply_style(self) -> None:
        self.setStyleSheet("""
            QDialog {
                background-color: #1e1e2e;
            }
            QPushButton {
                background-color: #45475a;
                color: #cdd6f4;
                border: 1px solid #585b70;
                border-radius: 6px;
                padding: 7px 16px;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #585b70;
                border-color: #89b4fa;
            }
            QPushButton#btn_primary {
                background-color: #89b4fa;
                color: #1e1e2e;
                font-weight: bold;
                border: none;
            }
            QPushButton#btn_primary:hover {
                background-color: #74c7ec;
            }
            QPushButton#btn_danger {
                background-color: #f38ba8;
                color: #1e1e2e;
                font-weight: bold;
                border: none;
                border-radius: 6px;
            }
            QPushButton#btn_danger:hover {
                background-color: #eba0ac;
            }
        """)

    def _mask_key(self, key: str) -> str:
        if not key or key == "__token_ok__":
            return "****-****-****-****"
        if len(key) > 8:
            return key[:4] + "-****-****-" + key[-4:]
        return key

    def _format_expiry(self) -> str:
        exp = self._info.expires_at or "—"
        days = self._info.days_remaining
        if days >= 0:
            return f"{exp} (còn {days} ngày)"
        return exp

    def _short_machine_id(self) -> str:
        mid = self._info.machine_id
        if len(mid) > 16:
            return mid[:16] + "..."
        return mid or "—"

    def _format_status(self) -> str:
        from src.core.license_models import LicenseStatus
        status_map = {
            LicenseStatus.VALID: "✅ Đang hoạt động",
            LicenseStatus.TRIAL: "🔄 Dùng thử",
            LicenseStatus.EXPIRED: "❌ Hết hạn",
            LicenseStatus.INVALID: "⛔ Không hợp lệ",
            LicenseStatus.NO_LICENSE: "🔒 Chưa kích hoạt",
            LicenseStatus.UNKNOWN: "❓ Không xác định",
        }
        return status_map.get(self._info.status, "❓ Không xác định")

    def _on_deactivate(self) -> None:
        reply = QMessageBox.question(
            self,
            "Xác nhận huỷ kích hoạt",
            "Bạn có chắc muốn huỷ kích hoạt bản quyền?\n\n"
            "App sẽ đóng lại và yêu cầu nhập License Key mới khi mở lại.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        from src.core.license_client import get_license_manager
        mgr = get_license_manager()
        mgr.clear()

        self.license_deactivated.emit()
        self.accept()
