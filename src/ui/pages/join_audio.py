# -*- coding: utf-8 -*-
"""Join Audio page — merge multiple audio files into one output."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Signal, Slot
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QHeaderView,
    QComboBox,
)

from src.core import audio_utils

logger = logging.getLogger(__name__)


class JoinAudioPage(QWidget):
    """Dedicated page for joining audio files."""

    status_message = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._files: list[str] = []
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(0, 0, 0, 0)

        top_row = QHBoxLayout()
        self.btn_add = QPushButton("Thêm file")
        self.btn_add.setObjectName("btn_secondary")
        self.btn_add.clicked.connect(self._add_files)
        top_row.addWidget(self.btn_add)

        self.btn_clear = QPushButton("Xoá tất cả")
        self.btn_clear.setObjectName("btn_secondary")
        self.btn_clear.clicked.connect(self._clear)
        top_row.addWidget(self.btn_clear)

        top_row.addStretch()
        layout.addLayout(top_row)

        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["#", "File", "Thời lượng"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table)

        ctrl = QHBoxLayout()
        self.btn_up = QPushButton("↑ Lên")
        self.btn_up.setObjectName("btn_secondary")
        self.btn_up.clicked.connect(self._move_up)
        ctrl.addWidget(self.btn_up)

        self.btn_down = QPushButton("↓ Xuống")
        self.btn_down.setObjectName("btn_secondary")
        self.btn_down.clicked.connect(self._move_down)
        ctrl.addWidget(self.btn_down)

        self.btn_remove = QPushButton("Xoá mục")
        self.btn_remove.setObjectName("btn_secondary")
        self.btn_remove.clicked.connect(self._remove_selected)
        ctrl.addWidget(self.btn_remove)

        ctrl.addStretch()

        ctrl.addWidget(QLabel("Định dạng:"))
        self.combo_format = QComboBox()
        self.combo_format.addItem("WAV (Lossless)", ".wav")
        self.combo_format.addItem("MP3 (Compressed)", ".mp3")
        self.combo_format.addItem("FLAC (Lossless Compressed)", ".flac")
        self.combo_format.addItem("OGG Vorbis", ".ogg")
        ctrl.addWidget(self.combo_format)

        layout.addLayout(ctrl)

        bottom = QHBoxLayout()
        self.lbl_total = QLabel("Tổng thời lượng: 0.0s")
        self.lbl_total.setObjectName("lbl_progress")
        bottom.addWidget(self.lbl_total)

        bottom.addStretch()

        self.btn_merge = QPushButton("Merge & Export")
        self.btn_merge.setObjectName("btn_primary")
        self.btn_merge.clicked.connect(self._merge_export)
        self.btn_merge.setEnabled(False)
        bottom.addWidget(self.btn_merge)

        layout.addLayout(bottom)

    @Slot()
    def _add_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Chọn nhiều file audio",
            "",
            "Audio Files (*.wav *.mp3 *.flac *.ogg *.m4a *.aac *.wma);;All Files (*)",
        )
        if not files:
            return
        self.load_files(files)

    def load_files(self, files: list[str]) -> None:
        added = 0
        for p in files:
            if p and Path(p).exists() and p not in self._files:
                self._files.append(p)
                added += 1
        if added > 0:
            self._refresh_table()
            self.status_message.emit(f"Đã nạp {added} file vào Join Audio")

    @Slot()
    def _clear(self) -> None:
        self._files.clear()
        self._refresh_table()

    @Slot()
    def _remove_selected(self) -> None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._files):
            return
        self._files.pop(row)
        self._refresh_table()

    @Slot()
    def _move_up(self) -> None:
        row = self.table.currentRow()
        if row <= 0:
            return
        self._files[row - 1], self._files[row] = self._files[row], self._files[row - 1]
        self._refresh_table(select_row=row - 1)

    @Slot()
    def _move_down(self) -> None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._files) - 1:
            return
        self._files[row + 1], self._files[row] = self._files[row], self._files[row + 1]
        self._refresh_table(select_row=row + 1)

    def _refresh_table(self, select_row: int | None = None) -> None:
        self.table.setRowCount(len(self._files))
        total = 0.0

        for i, p in enumerate(self._files):
            self.table.setItem(i, 0, QTableWidgetItem(str(i + 1)))
            self.table.setItem(i, 1, QTableWidgetItem(Path(p).name))
            try:
                d = float(audio_utils.get_duration(p))
            except Exception:
                d = 0.0
            total += d
            self.table.setItem(i, 2, QTableWidgetItem(f"{d:.1f}s" if d > 0 else "—"))

        self.lbl_total.setText(f"Tổng thời lượng: {total:.1f}s")
        self.btn_merge.setEnabled(len(self._files) >= 2)

        if select_row is not None and 0 <= select_row < len(self._files):
            self.table.selectRow(select_row)

    @Slot()
    def _merge_export(self) -> None:
        if len(self._files) < 2:
            QMessageBox.warning(self, "Thiếu file", "Cần ít nhất 2 file để merge.")
            return

        ext = self.combo_format.currentData() or ".wav"
        out_path, _ = QFileDialog.getSaveFileName(
            self,
            "Lưu file merged",
            str(Path.home() / f"joined_audio{ext}"),
            f"Audio (*{ext});;All Files (*)",
        )
        if not out_path:
            return

        if not out_path.lower().endswith(ext):
            out_path += ext

        try:
            final = audio_utils.join_audio_files(
                input_paths=self._files,
                output_path=out_path,
                output_format=ext,
            )
            self.status_message.emit(f"Merge thành công: {final}")
            QMessageBox.information(self, "Thành công", f"Đã merge file:\n{final}")
        except Exception as e:
            logger.error("Join audio failed: %s", e)
            QMessageBox.warning(self, "Lỗi merge", f"Không thể merge audio:\n{e}")

    def stop_playback(self) -> None:
        pass
