# -*- coding: utf-8 -*-
"""Trim Audio page — cut reference audio to <=10s for TTS voice prompt."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from src.core import audio_utils
from src.ui.widgets.audio_player import AudioPlayerWidget
from src.ui.widgets.drop_area import DropArea
from src.ui.widgets.waveform_widget import WaveformWidget

logger = logging.getLogger(__name__)


class TrimAudioPage(QWidget):
    """Dedicated page for trimming reference audio."""

    status_message = Signal(str)
    trim_applied_to_tts = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._source_audio_path: str | None = None
        self._trimmed_audio_path: str | None = None
        self._source_duration_sec: float = 0.0
        self._trim_start_sec: float = 0.0
        self._temp_outputs: list[str] = []
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(0, 0, 0, 0)

        top_row = QHBoxLayout()

        self.btn_browse = QPushButton("Duyệt file")
        self.btn_browse.setObjectName("btn_secondary")
        self.btn_browse.clicked.connect(self._browse_audio)
        top_row.addWidget(self.btn_browse)

        self.btn_clear = QPushButton("Xoá")
        self.btn_clear.setObjectName("btn_secondary")
        self.btn_clear.clicked.connect(self._clear)
        top_row.addWidget(self.btn_clear)

        top_row.addStretch()

        self.btn_use_for_tts = QPushButton("Dùng cho TTS")
        self.btn_use_for_tts.setObjectName("btn_primary")
        self.btn_use_for_tts.clicked.connect(self._use_for_tts)
        self.btn_use_for_tts.setEnabled(False)
        top_row.addWidget(self.btn_use_for_tts)

        layout.addLayout(top_row)

        self.drop_area = DropArea()
        self.drop_area.file_dropped.connect(self._on_audio_dropped)
        layout.addWidget(self.drop_area)

        trim_row = QHBoxLayout()
        trim_row.addWidget(QLabel("Cắt mẫu <=10s:"))

        self.slider_trim_start = QSlider(Qt.Orientation.Horizontal)
        self.slider_trim_start.setRange(0, 0)
        self.slider_trim_start.valueChanged.connect(self._on_trim_start_changed)
        trim_row.addWidget(self.slider_trim_start, stretch=1)

        self.lbl_trim = QLabel("0.0s → 0.0s")
        self.lbl_trim.setObjectName("lbl_progress")
        trim_row.addWidget(self.lbl_trim)

        layout.addLayout(trim_row)

        trim_btn_row = QHBoxLayout()
        self.btn_trim_head = QPushButton("Dùng đoạn đầu 10s")
        self.btn_trim_head.setObjectName("btn_secondary")
        self.btn_trim_head.clicked.connect(self._use_head_trim)
        self.btn_trim_head.setEnabled(False)
        trim_btn_row.addWidget(self.btn_trim_head)

        self.btn_apply_trim = QPushButton("Áp dụng cắt")
        self.btn_apply_trim.setObjectName("btn_secondary")
        self.btn_apply_trim.clicked.connect(self._apply_trim)
        self.btn_apply_trim.setEnabled(False)
        trim_btn_row.addWidget(self.btn_apply_trim)

        trim_btn_row.addStretch()
        layout.addLayout(trim_btn_row)

        info_row = QHBoxLayout()
        self.lbl_source = QLabel("Nguồn: chưa nạp")
        self.lbl_source.setObjectName("lbl_progress")
        info_row.addWidget(self.lbl_source)

        info_row.addStretch()

        self.lbl_result = QLabel("Đầu ra: dùng file nguồn")
        self.lbl_result.setObjectName("lbl_progress")
        info_row.addWidget(self.lbl_result)

        layout.addLayout(info_row)

        self.preview_player = AudioPlayerWidget()
        self.preview_waveform = WaveformWidget()
        self.preview_player.playback_position_changed.connect(self.preview_waveform.set_progress)
        layout.addWidget(self.preview_player)
        layout.addWidget(self.preview_waveform)

        layout.addStretch()

    # ==================================================================
    # Public API
    # ==================================================================
    def load_source_audio(self, path: str, ref_text: str = "") -> None:
        del ref_text  # reserved for future UX labels
        self._set_source_audio(path)

    def cleanup_temp_files(self) -> None:
        for p in self._temp_outputs:
            try:
                Path(p).unlink(missing_ok=True)
            except Exception:
                pass
        self._temp_outputs.clear()

    # ==================================================================
    # Source loading
    # ==================================================================
    @Slot()
    def _browse_audio(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Chọn file audio để cắt",
            "",
            "Audio Files (*.wav *.mp3 *.flac *.ogg *.m4a *.aac *.wma);;All Files (*)",
        )
        if path:
            self._set_source_audio(path)

    @Slot(str)
    def _on_audio_dropped(self, path: str) -> None:
        self._set_source_audio(path)

    def _set_source_audio(self, path: str) -> None:
        if not path or not Path(path).exists():
            return

        self._source_audio_path = path
        self._trimmed_audio_path = None
        self._trim_start_sec = 0.0

        try:
            self._source_duration_sec = float(audio_utils.get_duration(path))
            source_dur = audio_utils.get_duration_formatted(path)
        except Exception:
            self._source_duration_sec = 0.0
            source_dur = "?"

        self.drop_area.set_file_info(Path(path).name, source_dur)
        self.lbl_source.setText(f"Nguồn: {Path(path).name} ({source_dur})")
        self.lbl_result.setText("Đầu ra: dùng file nguồn")

        self._update_trim_ui_state()
        self._load_preview(path)
        self.btn_use_for_tts.setEnabled(True)

        if self._source_duration_sec > 10.0:
            self.status_message.emit(
                "Đã nạp file nguồn. Chọn đoạn <=10s rồi bấm 'Áp dụng cắt' hoặc 'Dùng cho TTS'."
            )
        else:
            self.status_message.emit("Đã nạp file nguồn (<=10s), có thể dùng ngay cho TTS")

    # ==================================================================
    # Trim logic
    # ==================================================================
    @Slot(int)
    def _on_trim_start_changed(self, value: int) -> None:
        self._trim_start_sec = max(0.0, value / 10.0)
        end_sec = min(self._source_duration_sec, self._trim_start_sec + 10.0)
        self.lbl_trim.setText(f"{self._trim_start_sec:.1f}s → {end_sec:.1f}s")

    @Slot()
    def _use_head_trim(self) -> None:
        self.slider_trim_start.setValue(0)
        self._apply_trim(auto=True)

    def _update_trim_ui_state(self) -> None:
        if self._source_duration_sec <= 0:
            self.slider_trim_start.setRange(0, 0)
            self.slider_trim_start.setEnabled(False)
            self.btn_apply_trim.setEnabled(False)
            self.btn_trim_head.setEnabled(False)
            self.lbl_trim.setText("0.0s → 0.0s")
            return

        max_start = max(0.0, self._source_duration_sec - 0.2)
        slider_max = int(max_start * 10)
        self.slider_trim_start.blockSignals(True)
        self.slider_trim_start.setRange(0, slider_max)
        self.slider_trim_start.setValue(int(self._trim_start_sec * 10))
        self.slider_trim_start.blockSignals(False)

        enabled = self._source_duration_sec > 10.0
        self.slider_trim_start.setEnabled(enabled)
        self.btn_apply_trim.setEnabled(enabled)
        self.btn_trim_head.setEnabled(enabled)

        end_sec = min(self._source_duration_sec, self._trim_start_sec + 10.0)
        self.lbl_trim.setText(f"{self._trim_start_sec:.1f}s → {end_sec:.1f}s")

    @Slot()
    def _apply_trim(self, auto: bool = False) -> None:
        if not self._source_audio_path:
            return

        if self._source_duration_sec <= 10.0:
            self._trimmed_audio_path = self._source_audio_path
            self.lbl_result.setText("Đầu ra: dùng file nguồn (<=10s)")
            self._load_preview(self._trimmed_audio_path)
            if not auto:
                self.status_message.emit("Audio nguồn đã <=10s, không cần cắt")
            return

        start_sec = max(0.0, self.slider_trim_start.value() / 10.0)
        end_sec = min(self._source_duration_sec, start_sec + 10.0)
        if end_sec - start_sec < 0.2:
            QMessageBox.warning(self, "Đoạn cắt quá ngắn", "Đoạn cắt phải dài tối thiểu 0.2 giây.")
            return

        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False, prefix="omnivoice_trim_tab_")
        tmp_path = tmp.name
        tmp.close()

        try:
            trimmed = audio_utils.trim_audio_segment(
                source_path=self._source_audio_path,
                output_path=tmp_path,
                start_sec=start_sec,
                max_duration_sec=10.0,
            )
        except Exception as e:
            Path(tmp_path).unlink(missing_ok=True)
            QMessageBox.warning(self, "Lỗi cắt audio", f"Không thể cắt audio:\n{e}")
            return

        self._trimmed_audio_path = trimmed
        self._temp_outputs.append(trimmed)
        self._trim_start_sec = start_sec
        self.lbl_result.setText(f"Đầu ra: {Path(trimmed).name} ({start_sec:.1f}s → {end_sec:.1f}s)")
        self._load_preview(trimmed)

        if not auto:
            self.status_message.emit(f"Đã cắt audio: {start_sec:.1f}s → {end_sec:.1f}s")

    @Slot()
    def _use_for_tts(self) -> None:
        if not self._source_audio_path:
            QMessageBox.information(self, "Thiếu file", "Vui lòng nạp file audio trước.")
            return

        if self._source_duration_sec > 10.0 and not self._trimmed_audio_path:
            self._apply_trim(auto=True)

        prompt_path = self._trimmed_audio_path or self._source_audio_path
        if not prompt_path or not Path(prompt_path).exists():
            QMessageBox.warning(self, "Thiếu audio", "Không tìm thấy file audio để gửi sang TTS.")
            return

        try:
            duration_sec = float(audio_utils.get_duration(prompt_path))
        except Exception:
            duration_sec = 0.0

        if duration_sec > 10.05:
            QMessageBox.warning(self, "Audio quá dài", "Audio dùng cho voice prompt phải <=10s.")
            return

        was_trimmed = prompt_path != self._source_audio_path
        payload = {
            "source_audio_path": self._source_audio_path,
            "prompt_audio_path": prompt_path,
            "start_sec": self._trim_start_sec if was_trimmed else 0.0,
            "duration_sec": duration_sec,
            "was_trimmed": was_trimmed,
        }
        self.trim_applied_to_tts.emit(payload)

        if was_trimmed:
            end_sec = payload["start_sec"] + duration_sec
            self.status_message.emit(f"Đã gửi đoạn đã cắt sang TTS: {payload['start_sec']:.1f}s → {end_sec:.1f}s")
        else:
            self.status_message.emit("Đã gửi audio nguồn sang TTS")

    # ==================================================================
    # Preview and cleanup
    # ==================================================================
    def _load_preview(self, path: str | None) -> None:
        if not path:
            return
        self.preview_player.load_file(path)
        try:
            envelope = audio_utils.audio_to_waveform_data(path)
            self.preview_waveform.set_data(envelope)
        except Exception as e:
            logger.warning("Failed to load waveform preview: %s", e)
            self.preview_waveform.clear()

    @Slot()
    def _clear(self) -> None:
        self._source_audio_path = None
        self._trimmed_audio_path = None
        self._source_duration_sec = 0.0
        self._trim_start_sec = 0.0

        self.drop_area.reset()
        self.preview_player.stop()
        self.preview_waveform.clear()
        self.lbl_source.setText("Nguồn: chưa nạp")
        self.lbl_result.setText("Đầu ra: dùng file nguồn")
        self.btn_use_for_tts.setEnabled(False)
        self._update_trim_ui_state()

    def stop_playback(self) -> None:
        self.preview_player.stop()

    def close(self) -> None:
        self.cleanup_temp_files()
        super().close()
