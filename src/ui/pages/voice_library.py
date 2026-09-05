# -*- coding: utf-8 -*-
"""Voice Library page — manage saved voice profiles."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from PySide6.QtCore import Qt, Slot, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.core import audio_utils
from src.data.database import Database, VoiceProfile
from src.ui.widgets.audio_player import AudioPlayerWidget
from src.ui.widgets.waveform_widget import WaveformWidget

logger = logging.getLogger(__name__)


class VoiceLibraryPage(QWidget):
    """Voice library: list, preview, add, edit, delete voice profiles."""

    status_message = Signal(str)
    voice_selected_for_tts = Signal(str)  # voice_id → switch to TTS page

    def __init__(self, engine, db: Database, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.db = db
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(0, 0, 0, 0)

        # --- Toolbar ---
        toolbar = QHBoxLayout()

        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("Tìm kiếm giọng...")
        self.txt_search.textChanged.connect(self._on_search)
        toolbar.addWidget(self.txt_search, stretch=1)

        self.btn_add = QPushButton("+ Thêm giọng")
        self.btn_add.setObjectName("btn_primary")
        self.btn_add.clicked.connect(self._add_voice)
        toolbar.addWidget(self.btn_add)

        self.btn_import = QPushButton("Nhập từ JSON")
        self.btn_import.setObjectName("btn_secondary")
        self.btn_import.clicked.connect(self._import_voices_json)
        toolbar.addWidget(self.btn_import)

        layout.addLayout(toolbar)

        # --- Table ---
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["Tên", "Nhãn", "Ngôn ngữ", "Thời lượng", "Thao tác"])
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.currentCellChanged.connect(self._on_row_selected)
        layout.addWidget(self.table)

        # --- Preview ---
        preview_group = QGroupBox("Nghe thử")
        preview_layout = QVBoxLayout(preview_group)

        self.preview_player = AudioPlayerWidget()
        self.preview_waveform = WaveformWidget()
        self.preview_player.playback_position_changed.connect(
            self.preview_waveform.set_progress
        )
        preview_layout.addWidget(self.preview_player)
        preview_layout.addWidget(self.preview_waveform)

        info_row = QHBoxLayout()
        self.lbl_ref_text = QLabel("Lời tham chiếu: —")
        self.lbl_ref_text.setWordWrap(True)
        info_row.addWidget(self.lbl_ref_text)
        preview_layout.addLayout(info_row)

        layout.addWidget(preview_group)

    # ==================================================================
    # Data
    # ==================================================================
    def refresh(self) -> None:
        search = self.txt_search.text().strip()
        model_id = getattr(self.engine, "model_id", "k2-fsa/OmniVoice") if hasattr(self, 'engine') else "k2-fsa/OmniVoice"
        voices = self.db.list_voices(search=search, model_id=model_id)
        self._populate_table(voices)

    def _populate_table(self, voices: list[VoiceProfile]) -> None:
        self.table.setRowCount(len(voices))

        for i, v in enumerate(voices):
            self.table.setItem(i, 0, QTableWidgetItem(v.name))
            self.table.setItem(i, 1, QTableWidgetItem(v.tags))
            self.table.setItem(i, 2, QTableWidgetItem(v.language))

            # Duration
            try:
                dur = audio_utils.get_duration_formatted(v.audio_path)
            except Exception:
                dur = "—"
            self.table.setItem(i, 3, QTableWidgetItem(dur))

            # Actions cell with buttons
            actions = QWidget()
            actions_layout = QHBoxLayout(actions)
            actions_layout.setContentsMargins(4, 2, 4, 2)
            actions_layout.setSpacing(4)

            btn_use = QPushButton("Dùng")
            btn_use.setObjectName("btn_table_action")
            btn_use.clicked.connect(lambda _, vid=v.id: self._use_voice(vid))
            actions_layout.addWidget(btn_use)

            btn_edit = QPushButton("Sửa")
            btn_edit.setObjectName("btn_table_action")
            btn_edit.clicked.connect(lambda _, vid=v.id: self._edit_voice(vid))
            actions_layout.addWidget(btn_edit)

            btn_del = QPushButton("Xoá")
            btn_del.setObjectName("btn_table_danger")
            btn_del.clicked.connect(lambda _, vid=v.id: self._delete_voice(vid))
            actions_layout.addWidget(btn_del)

            self.table.setCellWidget(i, 4, actions)
            self.table.setRowHeight(i, 40)

            # Store voice_id in first column
            item = self.table.item(i, 0)
            item.setData(Qt.ItemDataRole.UserRole, v.id)

    @Slot(str)
    def _on_search(self, text: str) -> None:
        self.refresh()

    @Slot(int, int, int, int)
    def _on_row_selected(self, row: int, col: int, prev_row: int, prev_col: int) -> None:
        if row < 0:
            return

        item = self.table.item(row, 0)
        if not item:
            return

        voice_id = item.data(Qt.ItemDataRole.UserRole)
        voice = self.db.get_voice(voice_id)
        if voice and Path(voice.audio_path).exists():
            self.preview_player.load_file(voice.audio_path)
            try:
                envelope = audio_utils.audio_to_waveform_data(voice.audio_path)
                self.preview_waveform.set_data(envelope)
            except Exception:
                self.preview_waveform.clear()
            self.lbl_ref_text.setText(f"Lời tham chiếu: {voice.ref_text or '—'}")

    # ==================================================================
    # Actions
    # ==================================================================
    def _add_voice(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Chọn file âm thanh", "",
            "File âm thanh (*.wav *.mp3 *.flac *.ogg *.m4a);;Tất cả (*)",
        )
        if not path:
            return

        name, ok = QInputDialog.getText(
            self, "Thêm giọng", "Tên giọng:", text=Path(path).stem,
        )
        if not ok or not name.strip():
            return

        tags, _ = QInputDialog.getText(self, "Thêm giọng", "Nhãn (phân tách bởi dấu phẩy):")

        # Copy to library
        voice_dir = Path.home() / ".omnivoice-cloner" / "voices"
        voice_dir.mkdir(parents=True, exist_ok=True)

        import uuid
        voice_id = uuid.uuid4().hex[:12]
        ext = Path(path).suffix
        dest = voice_dir / f"{voice_id}{ext}"
        shutil.copy2(path, dest)

        voice = VoiceProfile(
            id=voice_id,
            name=name.strip(),
            audio_path=str(dest),
            tags=tags.strip() if tags else "",
            model_id=getattr(self.engine, "model_id", "k2-fsa/OmniVoice") if hasattr(self, 'engine') else "k2-fsa/OmniVoice",
        )
        self.db.save_voice(voice)
        self.refresh()
        self.status_message.emit(f"Đã thêm giọng '{name}'!")

    def _use_voice(self, voice_id: str) -> None:
        self.voice_selected_for_tts.emit(voice_id)

    def _edit_voice(self, voice_id: str) -> None:
        voice = self.db.get_voice(voice_id)
        if not voice:
            return

        name, ok = QInputDialog.getText(
            self, "Sửa giọng", "Tên:", text=voice.name,
        )
        if not ok:
            return

        tags, ok2 = QInputDialog.getText(
            self, "Sửa giọng", "Nhãn:", text=voice.tags,
        )

        voice.name = name.strip() or voice.name
        if ok2:
            voice.tags = tags.strip()

        self.db.save_voice(voice)
        self.refresh()
        self.status_message.emit(f"Đã cập nhật giọng '{voice.name}'")

    def _delete_voice(self, voice_id: str) -> None:
        voice = self.db.get_voice(voice_id)
        if not voice:
            return

        reply = QMessageBox.question(
            self, "Xoá giọng",
            f"Xoá giọng '{voice.name}'?\nĐiều này cũng sẽ xoá file âm thanh.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # Delete file
        try:
            Path(voice.audio_path).unlink(missing_ok=True)
        except Exception:
            pass

        self.db.delete_voice(voice_id)
        self.preview_player.stop()
        self.preview_waveform.clear()
        self.refresh()
        self.status_message.emit(f"Đã xoá giọng '{voice.name}'")

    def stop_playback(self) -> None:
        self.preview_player.stop()

    def _import_voices_json(self) -> None:
        """Import voices from an OmniVoice voices.json file."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Chọn file voices.json", "",
            "JSON Files (*.json);;All Files (*)",
        )
        if not path:
            return

        try:
            count = self.db.import_voices_json(path)
            if count > 0:
                self.refresh()
                self.status_message.emit(f"Đã nhập {count} giọng từ JSON!")
                QMessageBox.information(
                    self, "Nhập thành công",
                    f"Đã nhập {count} giọng nói từ file JSON.",
                )
            else:
                QMessageBox.information(
                    self, "Không có giọng mới",
                    "Tất cả giọng trong file JSON đã có trong thư viện.",
                )
        except Exception as e:
            logger.error("Failed to import voices.json: %s", e)
            QMessageBox.critical(
                self, "Lỗi nhập",
                f"Không thể nhập file JSON:\n{e}",
            )
