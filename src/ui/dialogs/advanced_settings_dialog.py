# -*- coding: utf-8 -*-
"""Advanced TTS settings dialog."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QRadioButton,
    QSpinBox,
    QPushButton,
    QVBoxLayout,
)

from src.ui.settings import AdvancedTtsSettings, SettingsStore


class AdvancedSettingsDialog(QDialog):
    """Dialog for advanced TTS controls."""

    def __init__(self, settings_store: SettingsStore, parent=None):
        super().__init__(parent)
        self._settings_store = settings_store
        self._settings = settings_store.load_advanced_tts()

        self.setObjectName("advanced_settings_dialog")
        self.setWindowTitle("Cấu hình nâng cao")
        self.setMinimumWidth(500)
        self._build_ui()
        self._load_to_widgets()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Pause settings
        pause_group = QGroupBox("Nhịp nghỉ sau dấu câu (ms)")
        pause_form = QFormLayout(pause_group)
        pause_form.setHorizontalSpacing(12)
        pause_form.setVerticalSpacing(10)
        pause_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        self.spin_pause_comma = QSpinBox()
        self.spin_pause_comma.setRange(0, 2000)
        self.spin_pause_comma.setSingleStep(10)
        pause_form.addRow("Dấu phẩy (,):", self.spin_pause_comma)

        self.spin_pause_mid = QSpinBox()
        self.spin_pause_mid.setRange(0, 2000)
        self.spin_pause_mid.setSingleStep(10)
        pause_form.addRow("Dấu ; :", self.spin_pause_mid)

        self.spin_pause_end = QSpinBox()
        self.spin_pause_end.setRange(0, 2000)
        self.spin_pause_end.setSingleStep(10)
        pause_form.addRow("Dấu . ! ? …:", self.spin_pause_end)

        layout.addWidget(pause_group)

        # SRT overflow
        overflow_group = QGroupBox("SRT: khi audio dài hơn slot timecode")
        overflow_layout = QVBoxLayout(overflow_group)
        overflow_layout.setSpacing(10)
        self.radio_warn = QRadioButton("Chỉ cảnh báo (không tự fit)")
        self.radio_warn.setObjectName("dialog_radio")
        self.radio_speed = QRadioButton("Tự tăng speed để fit trong slot")
        self.radio_speed.setObjectName("dialog_radio")
        self._overflow_buttons = QButtonGroup(self)
        self._overflow_buttons.addButton(self.radio_warn)
        self._overflow_buttons.addButton(self.radio_speed)
        overflow_layout.addWidget(self.radio_warn)
        overflow_layout.addWidget(self.radio_speed)
        overflow_layout.addWidget(QLabel("Lưu ý: speed tự động sẽ bị giới hạn để tránh méo giọng."))
        layout.addWidget(overflow_group)

        # SSML note (scope declaration)
        scope_note = QLabel(
            "SSML hỗ trợ phase 1: <break>, <prosody rate>, <emphasis>.\n"
            "Mẹo: đặt pause = 0ms để dùng nhịp nghỉ mặc định tự nhiên của model."
        )
        scope_note.setObjectName("lbl_progress")
        scope_note.setWordWrap(True)
        scope_note.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(scope_note)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.btn_reset = QPushButton("Mặc định")
        self.btn_reset.setObjectName("btn_secondary")
        self.btn_reset.clicked.connect(self._reset_defaults)
        btn_row.addWidget(self.btn_reset)

        btn_row.addStretch()

        self.btn_cancel = QPushButton("Huỷ")
        self.btn_cancel.setObjectName("btn_secondary")
        self.btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(self.btn_cancel)

        self.btn_save = QPushButton("Áp dụng")
        self.btn_save.setObjectName("btn_primary")
        self.btn_save.clicked.connect(self._save)
        btn_row.addWidget(self.btn_save)

        layout.addLayout(btn_row)

    def _load_to_widgets(self) -> None:
        s = self._settings
        self.spin_pause_comma.setValue(s.punctuation_pause_comma_ms)
        self.spin_pause_mid.setValue(s.punctuation_pause_mid_ms)
        self.spin_pause_end.setValue(s.punctuation_pause_end_ms)
        if s.srt_overflow_policy == "speed_up":
            self.radio_speed.setChecked(True)
        else:
            self.radio_warn.setChecked(True)

    def _reset_defaults(self) -> None:
        self._settings = self._settings_store.default_advanced_tts()
        self._load_to_widgets()

    def _save(self) -> None:
        settings = AdvancedTtsSettings(
            punctuation_pause_comma_ms=int(self.spin_pause_comma.value()),
            punctuation_pause_mid_ms=int(self.spin_pause_mid.value()),
            punctuation_pause_end_ms=int(self.spin_pause_end.value()),
            srt_overflow_policy="speed_up" if self.radio_speed.isChecked() else "warn",
        )
        self._settings_store.save_advanced_tts(settings)
        self.accept()
