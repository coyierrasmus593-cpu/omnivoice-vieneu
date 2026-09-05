# -*- coding: utf-8 -*-
"""TTS Studio page — the core voice cloning + speech generation interface."""

from __future__ import annotations

import logging
import shutil
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Slot, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from src.core.engine import VoiceEngine, GENERATION_CANCELLED
from src.core import audio_utils
from src.data.database import Database, VoiceProfile
from src.ui.dialogs.advanced_settings_dialog import AdvancedSettingsDialog
from src.ui.settings import SettingsStore
from src.ui.widgets.audio_player import AudioPlayerWidget
from src.ui.widgets.waveform_widget import WaveformWidget
from src.ui.widgets.drop_area import DropArea
from src.ui.workers.tts_worker import TTSWorker, VoicePromptWorker, TranscribeWorker

logger = logging.getLogger(__name__)


class TTSStudioPage(QWidget):
    """Main TTS page: select voice → enter text → generate → export."""

    status_message = Signal(str)
    show_progress = Signal(bool, str)
    trim_audio_requested = Signal(dict)

    def __init__(self, engine: VoiceEngine, db: Database, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.db = db

        self._voice_prompt = None
        self._ref_audio_path: str | None = None
        self._prompt_audio_path: str | None = None
        self._trim_temp_path: str | None = None
        self._ref_duration_sec: float = 0.0
        self._srt_path: str | None = None
        self._output_path: str | None = None
        self._output_dir: str | None = None
        self._selected_voice: VoiceProfile | None = None
        self._is_generating = False
        self._settings_store = SettingsStore()

        # Worker refs
        self._tts_worker: TTSWorker | None = None
        self._prompt_worker: VoicePromptWorker | None = None
        self._transcribe_worker: TranscribeWorker | None = None
        self._prompt_request_id: int = 0
        self._pending_prompt_request: tuple[int, str, str | None] | None = None

        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(0, 0, 0, 0)

        # Keep page usable on smaller windows: sections can scroll instead of overlapping
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setSpacing(14)
        content_layout.setContentsMargins(0, 0, 4, 0)

        # --- Voice Selection (from library OR browse) ---
        content_layout.addWidget(self._build_voice_section())

        # --- Text Input ---
        content_layout.addWidget(self._build_text_section())

        # --- Output ---
        content_layout.addWidget(self._build_output_section())

        content_layout.addStretch()

        self._scroll.setWidget(content)
        layout.addWidget(self._scroll)

    # ------------------------------------------------------------------
    # Voice Section
    # ------------------------------------------------------------------
    def _build_voice_section(self) -> QGroupBox:
        group = QGroupBox("Giọng mẫu tham chiếu")
        main_layout = QVBoxLayout(group)
        main_layout.setSpacing(10)

        # ── Row 1: Voice library selector (full width) ──
        lib_row = QHBoxLayout()
        lib_row.setSpacing(8)
        lib_row.addWidget(QLabel("Giọng:"))

        self.combo_voice = QComboBox()
        self.combo_voice.setMinimumWidth(220)
        self.combo_voice.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.combo_voice.addItem("— Chọn file mới —", "")
        self.combo_voice.currentIndexChanged.connect(self._on_voice_selected)
        lib_row.addWidget(self.combo_voice, stretch=1)

        self.btn_refresh_voices = QPushButton("↻ Làm mới")
        self.btn_refresh_voices.setObjectName("btn_secondary")
        self.btn_refresh_voices.setMinimumHeight(32)
        self.btn_refresh_voices.setToolTip("Làm mới danh sách giọng")
        self.btn_refresh_voices.clicked.connect(self.refresh_voice_list)
        lib_row.addWidget(self.btn_refresh_voices)

        main_layout.addLayout(lib_row)

        # ── Row 2: Reference audio controls (single-column to avoid overlap) ──
        self.drop_area = DropArea()
        self.drop_area.file_dropped.connect(self._on_ref_audio_dropped)
        main_layout.addWidget(self.drop_area)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.btn_browse_ref = QPushButton("Duyệt...")
        self.btn_browse_ref.setObjectName("btn_secondary")
        self.btn_browse_ref.setMinimumHeight(34)
        self.btn_browse_ref.clicked.connect(self._browse_ref_audio)
        btn_row.addWidget(self.btn_browse_ref)

        self.btn_save_voice = QPushButton("Lưu giọng")
        self.btn_save_voice.setObjectName("btn_secondary")
        self.btn_save_voice.setMinimumHeight(34)
        self.btn_save_voice.setToolTip("Lưu vào thư viện giọng")
        self.btn_save_voice.clicked.connect(self._save_voice_to_library)
        self.btn_save_voice.setEnabled(False)
        btn_row.addWidget(self.btn_save_voice)

        self.btn_asr = QPushButton("ASR")
        self.btn_asr.setObjectName("btn_secondary")
        self.btn_asr.setMinimumHeight(34)
        self.btn_asr.setToolTip("Tự động nhận dạng lời nói")
        self.btn_asr.clicked.connect(self._transcribe_ref)
        self.btn_asr.setEnabled(False)
        btn_row.addWidget(self.btn_asr)
        btn_row.addStretch()

        main_layout.addLayout(btn_row)

        # Ref text
        ref_text_row = QHBoxLayout()
        ref_text_row.setSpacing(8)
        ref_text_row.addWidget(QLabel("Lời:"))
        self.txt_ref_text = QLineEdit()
        self.txt_ref_text.setPlaceholderText("Tự động nhận dạng hoặc nhập thủ công")
        ref_text_row.addWidget(self.txt_ref_text, stretch=1)
        main_layout.addLayout(ref_text_row)

        # Prompt source status
        prompt_row = QHBoxLayout()
        prompt_row.setSpacing(8)
        self.lbl_prompt_source = QLabel("Prompt: dùng file nguồn")
        self.lbl_prompt_source.setObjectName("lbl_progress")
        prompt_row.addWidget(self.lbl_prompt_source, stretch=1)
        main_layout.addLayout(prompt_row)

        # Player + Waveform
        self.ref_player = AudioPlayerWidget()
        main_layout.addWidget(self.ref_player)

        self.ref_waveform = WaveformWidget()
        self.ref_waveform.setMinimumHeight(72)
        self.ref_waveform.setMaximumHeight(96)
        self.ref_player.playback_position_changed.connect(self.ref_waveform.set_progress)
        main_layout.addWidget(self.ref_waveform)

        # ── Clone status ──
        self.lbl_clone_status = QLabel("")
        self.lbl_clone_status.setObjectName("lbl_progress")
        main_layout.addWidget(self.lbl_clone_status)

        return group

    # ------------------------------------------------------------------
    # Text Section
    # ------------------------------------------------------------------
    def _build_text_section(self) -> QGroupBox:
        group = QGroupBox("Nhập văn bản")
        layout = QVBoxLayout(group)
        layout.setSpacing(10)

        layout.addWidget(QLabel("Nhập văn bản cần chuyển thành giọng nói:"))

        self.txt_input = QPlainTextEdit()
        self.txt_input.setPlaceholderText("Nhập hoặc dán văn bản tại đây...")
        self.txt_input.setMinimumHeight(100)
        self.txt_input.setMaximumHeight(200)
        self.txt_input.textChanged.connect(self._on_text_changed)
        layout.addWidget(self.txt_input)

        stats_row = QHBoxLayout()
        stats_row.setSpacing(8)
        self.lbl_text_stats = QLabel("Ký tự: 0 | Từ: 0")
        self.lbl_text_stats.setObjectName("lbl_progress")
        stats_row.addWidget(self.lbl_text_stats)
        stats_row.addStretch()
        layout.addLayout(stats_row)

        speed_row = QHBoxLayout()
        speed_row.setSpacing(8)

        speed_row.addWidget(QLabel("Tốc độ:"))
        self.slider_speed = QSlider(Qt.Orientation.Horizontal)
        self.slider_speed.setRange(50, 200)
        self.slider_speed.setValue(100)
        self.slider_speed.setTickInterval(25)
        self.slider_speed.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.slider_speed.valueChanged.connect(self._on_speed_changed)
        speed_row.addWidget(self.slider_speed)

        self.lbl_speed = QLabel("1.0x")
        self.lbl_speed.setFixedWidth(40)
        speed_row.addWidget(self.lbl_speed)
        speed_row.addStretch()
        layout.addLayout(speed_row)

        quality_row = QHBoxLayout()
        quality_row.setSpacing(8)
        quality_row.addWidget(QLabel("Chất lượng:"))
        self.combo_steps = QComboBox()
        self.combo_steps.addItems(["8 (nhanh)", "16 (cân bằng)", "32 (chất lượng)"])
        self.combo_steps.setCurrentIndex(2)
        self.combo_steps.setMaximumWidth(220)
        quality_row.addWidget(self.combo_steps)
        quality_row.addStretch()
        layout.addLayout(quality_row)

        # Advanced settings + SRT mode
        advanced_btn_row = QHBoxLayout()
        advanced_btn_row.setSpacing(8)
        self.btn_advanced = QPushButton("Cấu hình nâng cao")
        self.btn_advanced.setObjectName("btn_secondary")
        self.btn_advanced.clicked.connect(self._open_advanced_settings)
        advanced_btn_row.addWidget(self.btn_advanced)

        self.btn_load_srt = QPushButton("Nạp file SRT")
        self.btn_load_srt.setObjectName("btn_secondary")
        self.btn_load_srt.clicked.connect(self._choose_srt_file)
        advanced_btn_row.addWidget(self.btn_load_srt)

        self.btn_clear_srt = QPushButton("Bỏ SRT")
        self.btn_clear_srt.setObjectName("btn_secondary")
        self.btn_clear_srt.clicked.connect(self._clear_srt_file)
        self.btn_clear_srt.setEnabled(False)
        advanced_btn_row.addWidget(self.btn_clear_srt)
        advanced_btn_row.addStretch()
        layout.addLayout(advanced_btn_row)

        srt_row = QHBoxLayout()
        srt_row.setSpacing(8)
        self.lbl_srt = QLabel("SRT: chưa nạp")
        self.lbl_srt.setObjectName("lbl_progress")
        self.lbl_srt.setWordWrap(True)
        srt_row.addWidget(self.lbl_srt, stretch=1)
        layout.addLayout(srt_row)
        return group

    # ------------------------------------------------------------------
    # Output Section
    # ------------------------------------------------------------------
    def _build_output_section(self) -> QGroupBox:
        group = QGroupBox("Kết quả")
        layout = QVBoxLayout(group)
        layout.setSpacing(10)

        # Generate button row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.btn_generate = QPushButton("Tạo giọng nói")
        self.btn_generate.setObjectName("btn_primary")
        self.btn_generate.setMinimumHeight(40)
        self.btn_generate.clicked.connect(self._on_generate_clicked)
        self.btn_generate.setEnabled(False)
        btn_row.addWidget(self.btn_generate)
        layout.addLayout(btn_row)

        # Output player + waveform
        self.out_player = AudioPlayerWidget()
        self.out_waveform = WaveformWidget()
        self.out_player.playback_position_changed.connect(self.out_waveform.set_progress)
        layout.addWidget(self.out_player)
        layout.addWidget(self.out_waveform)

        # Output settings row
        output_btn_row = QHBoxLayout()
        output_btn_row.setSpacing(8)

        self.combo_format = QComboBox()
        self.combo_format.addItem("WAV (Lossless)", ".wav")
        self.combo_format.addItem("MP3 (Compressed)", ".mp3")
        self.combo_format.setMaximumWidth(240)
        output_btn_row.addWidget(self.combo_format)

        self.btn_choose_output_dir = QPushButton("Chọn thư mục output")
        self.btn_choose_output_dir.setObjectName("btn_secondary")
        self.btn_choose_output_dir.clicked.connect(self._choose_output_dir)
        output_btn_row.addWidget(self.btn_choose_output_dir)
        output_btn_row.addStretch()

        layout.addLayout(output_btn_row)

        output_path_row = QHBoxLayout()
        output_path_row.setSpacing(8)
        self.lbl_output_dir = QLabel("Chưa chọn thư mục output")
        self.lbl_output_dir.setObjectName("lbl_progress")
        self.lbl_output_dir.setWordWrap(True)
        output_path_row.addWidget(self.lbl_output_dir, stretch=1)
        layout.addLayout(output_path_row)

        return group

    # ==================================================================
    # Voice Library Integration
    # ==================================================================
    def refresh_voice_list(self) -> None:
        """Reload voice dropdown from database."""
        self.combo_voice.blockSignals(True)
        current_id = self.combo_voice.currentData()

        self.combo_voice.clear()
        self.combo_voice.addItem("— Chọn file mới —", "")

        voices = self.db.list_voices(model_id=getattr(self.engine, "model_id", "k2-fsa/OmniVoice"))
        for v in voices:
            label = f"{v.name}"
            if v.tags:
                label += f"  [{v.tags}]"
            self.combo_voice.addItem(label, v.id)

        # Restore selection
        if current_id:
            idx = self.combo_voice.findData(current_id)
            if idx >= 0:
                self.combo_voice.setCurrentIndex(idx)

        self.combo_voice.blockSignals(False)

    @Slot(int)
    def _on_voice_selected(self, index: int) -> None:
        voice_id = self.combo_voice.currentData()
        if not voice_id:
            # "Chọn file mới" selected
            self._selected_voice = None
            self.drop_area.reset()
            self.drop_area.setVisible(True)
            self.btn_browse_ref.setVisible(True)
            return

        voice = self.db.get_voice(voice_id)
        if voice and Path(voice.audio_path).exists():
            self._selected_voice = voice
            self.txt_ref_text.setText(voice.ref_text or "")
            self._load_ref_audio(voice.audio_path)

    def _save_voice_to_library(self) -> None:
        source_for_save = self._prompt_audio_path or self._ref_audio_path
        if not source_for_save:
            return

        from PySide6.QtWidgets import QInputDialog

        name, ok = QInputDialog.getText(
            self, "Lưu giọng", "Tên giọng:",
            text=Path(source_for_save).stem,
        )
        if not ok or not name.strip():
            return

        tags, _ = QInputDialog.getText(
            self, "Lưu giọng", "Nhãn (phân tách bởi dấu phẩy):",
            text="",
        )

        # Copy audio to voice library folder
        voice_dir = Path.home() / ".omnivoice-cloner" / "voices"
        voice_dir.mkdir(parents=True, exist_ok=True)

        import uuid
        voice_id = uuid.uuid4().hex[:12]
        ext = Path(source_for_save).suffix or ".wav"
        dest = voice_dir / f"{voice_id}{ext}"
        shutil.copy2(source_for_save, dest)

        voice = VoiceProfile(
            id=voice_id,
            name=name.strip(),
            audio_path=str(dest),
            ref_text=self.txt_ref_text.text().strip(),
            tags=tags.strip(),
            model_id=getattr(self.engine, "model_id", "k2-fsa/OmniVoice"),
        )
        self.db.save_voice(voice)
        self._selected_voice = voice

        self.refresh_voice_list()
        # Select newly saved voice
        idx = self.combo_voice.findData(voice_id)
        if idx >= 0:
            self.combo_voice.setCurrentIndex(idx)

        self.status_message.emit(f"Đã lưu giọng '{name}' vào thư viện!")

    # ==================================================================
    # Reference Audio
    # ==================================================================
    @Slot()
    def _browse_ref_audio(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Chọn file âm thanh tham chiếu", "",
            "File âm thanh (*.wav *.mp3 *.flac *.ogg *.m4a);;Tất cả (*)",
        )
        if path:
            self._load_ref_audio(path)

    @Slot(str)
    def _on_ref_audio_dropped(self, path: str) -> None:
        self._load_ref_audio(path)

    def _load_ref_audio(self, path: str) -> None:
        self._cleanup_trim_temp()
        self._ref_audio_path = path
        self._prompt_audio_path = path
        filename = Path(path).name

        try:
            self._ref_duration_sec = float(audio_utils.get_duration(path))
            duration_fmt = audio_utils.get_duration_formatted(path)
            self.drop_area.set_file_info(filename, duration_fmt)
        except Exception:
            self._ref_duration_sec = 0.0
            self.drop_area.set_file_info(filename, "?")

        self._update_prompt_source_label()
        self.btn_asr.setEnabled(self.engine.is_loaded and self.engine.asr_enabled)
        self.btn_save_voice.setEnabled(True)

        # Reset voice prompt → will recreate
        self._voice_prompt = None
        self.lbl_clone_status.setText("⏳ Đang tạo voice prompt...")

        self._load_ref_preview(self._prompt_audio_path)
        if self.engine.is_loaded:
            self._create_voice_prompt()

        self._update_generate_button()
        if self._ref_duration_sec > 10.0:
            self.status_message.emit(
                f"Đã tải giọng mẫu: {filename}. File >10s, vào tab 'Trim Audio' để cắt đoạn prompt."
            )
        else:
            self.status_message.emit(f"Đã tải giọng mẫu: {filename}")

    # ==================================================================
    # Transcription
    # ==================================================================
    @Slot()
    def _transcribe_ref(self) -> None:
        source = self._prompt_audio_path or self._ref_audio_path
        if not source or not self.engine.is_loaded:
            return

        self.btn_asr.setEnabled(False)
        self.btn_asr.setText("...")
        self.show_progress.emit(True, "Đang nhận dạng giọng nói...")

        self._transcribe_worker = TranscribeWorker(self.engine, source)
        self._transcribe_worker.finished.connect(self._on_transcribed)
        self._transcribe_worker.start()

    @Slot(bool, str, str)
    def _on_transcribed(self, success: bool, text: str, error: str) -> None:
        self.show_progress.emit(False, "")
        self.btn_asr.setEnabled(self.engine.asr_enabled)
        self.btn_asr.setText("ASR")

        if success:
            self.txt_ref_text.setText(text)
            self.status_message.emit("Nhận dạng hoàn tất")
            # Recreate voice prompt with new transcript
            self._create_voice_prompt()
        else:
            self.status_message.emit("Nhận dạng thất bại")
            logger.error("Transcription failed: %s", error)

    # ==================================================================
    # Voice Prompt
    # ==================================================================
    def _create_voice_prompt(self) -> None:
        source = self._prompt_audio_path or self._ref_audio_path
        if not source or not self.engine.is_loaded:
            return

        ref_text = self.txt_ref_text.text().strip() or None
        self.lbl_clone_status.setText("⏳ Đang xử lý giọng mẫu...")
        self.show_progress.emit(True, "Đang xử lý giọng mẫu...")

        self._prompt_request_id += 1
        request_id = self._prompt_request_id
        self._pending_prompt_request = (request_id, source, ref_text)
        logger.info(
            "Queue voice prompt request id=%s source=%s ref_text=%s",
            request_id,
            source,
            "yes" if ref_text else "no",
        )

        # Stop any previous running prompt worker
        if hasattr(self, '_prompt_worker') and self._prompt_worker is not None:
            if self._prompt_worker.isRunning():
                logger.info("Prompt worker busy; skip stale request and keep latest id=%s", request_id)
                return

        self._start_pending_prompt_worker()

    def _start_pending_prompt_worker(self) -> None:
        pending = self._pending_prompt_request
        if pending is None:
            return

        request_id, source, ref_text = pending
        logger.info(
            "Start voice prompt worker id=%s source=%s ref_text=%s",
            request_id,
            source,
            "yes" if ref_text else "no",
        )
        self._prompt_worker = VoicePromptWorker(self.engine, source, ref_text)
        self._prompt_worker.progress.connect(
            lambda msg, rid=request_id: self._on_prompt_progress(rid, msg)
        )
        self._prompt_worker.finished.connect(
            lambda success, prompt, error, rid=request_id, src=source, txt=ref_text: self._on_prompt_created(
                rid, src, txt, success, prompt, error
            )
        )
        self._prompt_worker.start()

    def _on_prompt_progress(self, request_id: int, msg: str) -> None:
        if request_id != self._prompt_request_id:
            logger.info("Ignore stale prompt progress id=%s latest=%s", request_id, self._prompt_request_id)
            return
        self.status_message.emit(msg)

    def _has_reference_voice(self) -> bool:
        return bool(self._prompt_audio_path or self._ref_audio_path)

    def _is_prompt_pending(self) -> bool:
        return self._pending_prompt_request is not None or bool(
            self._prompt_worker and self._prompt_worker.isRunning()
        )

    def _on_prompt_created(
        self,
        request_id: int,
        source: str,
        ref_text: str | None,
        success: bool,
        prompt,
        error: str,
    ) -> None:
        latest_request = self._pending_prompt_request
        if self._prompt_worker and not self._prompt_worker.isRunning():
            self._prompt_worker = None

        if latest_request is not None and latest_request[0] != request_id:
            logger.info(
                "Drop stale prompt result id=%s latest=%s source=%s",
                request_id,
                latest_request[0],
                source,
            )
            if self._prompt_worker is None:
                self._start_pending_prompt_worker()
            return

        self.show_progress.emit(False, "")
        self._pending_prompt_request = None

        if success:
            self._voice_prompt = prompt
            logger.info(
                "Voice prompt ready id=%s prompt_obj=%s source=%s ref_text=%s",
                request_id,
                hex(id(prompt)),
                source,
                "yes" if ref_text else "no",
            )
            self.lbl_clone_status.setText("✅ Voice prompt sẵn sàng — chế độ clone giọng")
            self.status_message.emit("Voice prompt đã sẵn sàng!")
        else:
            self._voice_prompt = None
            self.lbl_clone_status.setText("❌ Tạo voice prompt thất bại — sẽ dùng giọng mặc định")
            self.status_message.emit("Tạo voice prompt thất bại")
            logger.error("Voice prompt failed id=%s source=%s: %s", request_id, source, error)

        self._update_generate_button()

    # ==================================================================
    # Generation
    # ==================================================================
    def _get_num_steps(self) -> int:
        return [8, 16, 32][self.combo_steps.currentIndex()]

    def _get_speed(self) -> float:
        return self.slider_speed.value() / 100.0

    @Slot(int)
    def _on_speed_changed(self, value: int) -> None:
        self.lbl_speed.setText(f"{value / 100.0:.1f}x")

    @Slot()
    def _on_text_changed(self) -> None:
        text = self.txt_input.toPlainText()
        char_count = len(text)
        word_count = len([w for w in text.split() if w])
        self.lbl_text_stats.setText(f"Ký tự: {char_count} | Từ: {word_count}")
        self._update_generate_button()

    @Slot()
    def _on_generate_clicked(self) -> None:
        if self._is_generating:
            self._confirm_stop_generation()
            return
        self._start_generation()

    def _set_generating_state(self, generating: bool) -> None:
        self._is_generating = generating
        if generating:
            self.btn_generate.setText("Dừng")
            self.btn_generate.setObjectName("btn_danger")
            self.btn_generate.setEnabled(True)
        else:
            self.btn_generate.setText("Tạo giọng nói")
            self.btn_generate.setObjectName("btn_primary")
            self._update_generate_button()

        # Re-polish style after objectName change
        self.btn_generate.style().unpolish(self.btn_generate)
        self.btn_generate.style().polish(self.btn_generate)
        self.btn_generate.update()

    def _confirm_stop_generation(self) -> None:
        if not self._tts_worker or not self._tts_worker.isRunning():
            return

        confirm = QMessageBox.question(
            self,
            "Xác nhận dừng",
            "Bạn có chắc muốn dừng quá trình tạo giọng nói?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        self._tts_worker.cancel()
        self.show_progress.emit(True, "Đang dừng tạo giọng nói...")
        self.status_message.emit("Đang dừng tạo giọng nói...")

    @Slot()
    def _start_generation(self) -> None:
        if not self.engine.is_loaded:
            QMessageBox.warning(
                self,
                "Mô hình chưa sẵn sàng",
                "Mô hình AI đang tải. Vui lòng chờ đến khi trạng thái báo Sẵn sàng.",
            )
            return

        text = self.txt_input.toPlainText().strip()
        if not self._srt_path and not text:
            QMessageBox.warning(self, "Thiếu văn bản", "Vui lòng nhập văn bản hoặc nạp file SRT trước khi tạo giọng nói.")
            return
        if not self._output_dir or not Path(self._output_dir).exists():
            QMessageBox.warning(self, "Thiếu thư mục output", "Vui lòng chọn thư mục output trước khi tạo giọng nói.")
            return
        if self._is_prompt_pending():
            QMessageBox.information(
                self,
                "Đang xử lý giọng mẫu",
                "Voice prompt đang được cập nhật. Vui lòng chờ vài giây rồi tạo lại.",
            )
            logger.warning("Blocked generation while prompt request is still pending")
            return
        if self._has_reference_voice() and self._voice_prompt is None:
            QMessageBox.warning(
                self,
                "Giọng mẫu chưa sẵn sàng",
                "Chưa có voice prompt hợp lệ cho giọng đã chọn. Vui lòng tạo lại giọng mẫu trước khi tạo audio.",
            )
            logger.warning("Blocked generation because reference voice exists but prompt is None")
            return

        prompt_for_run = self._voice_prompt
        logger.info(
            "Start generation selected_voice=%s prompt_obj=%s text_chars=%s srt=%s",
            self._selected_voice.id if self._selected_voice else "",
            hex(id(prompt_for_run)) if prompt_for_run is not None else "None",
            len(text),
            "yes" if self._srt_path else "no",
        )

        self._set_generating_state(True)
        self.show_progress.emit(True, "Đang tạo giọng nói...")

        # Stop any previous running worker
        if hasattr(self, '_tts_worker') and self._tts_worker is not None:
            if self._tts_worker.isRunning():
                self._tts_worker.wait(2000)

        self._tts_worker = TTSWorker(
            engine=self.engine,
            text=text,
            voice_prompt=prompt_for_run,
            speed=self._get_speed(),
            num_step=self._get_num_steps(),
            advanced_settings=self._settings_store.load_advanced_tts(),
            srt_path=self._srt_path,
        )
        self._tts_worker.progress.connect(
            lambda msg: self.status_message.emit(msg)
        )
        self._tts_worker.finished.connect(self._on_tts_finished)
        self._tts_worker.start()

    def _build_output_filename(self, ext: str) -> str:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"voice-cloner_{ts}{ext}"

    def _resolve_unique_path(self, base_path: Path) -> Path:
        if not base_path.exists():
            return base_path
        stem = base_path.stem
        suffix = base_path.suffix
        parent = base_path.parent
        i = 1
        while True:
            candidate = parent / f"{stem}_{i:02d}{suffix}"
            if not candidate.exists():
                return candidate
            i += 1

    @Slot()
    def _choose_output_dir(self) -> None:
        start_dir = self._output_dir or str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, "Chọn thư mục output", start_dir)
        if not folder:
            return
        self._output_dir = folder
        self.lbl_output_dir.setText(folder)
        self._update_generate_button()

    @Slot()
    def _open_advanced_settings(self) -> None:
        dialog = AdvancedSettingsDialog(self._settings_store, parent=self)
        if dialog.exec():
            self.status_message.emit("Đã cập nhật cấu hình nâng cao")

    @Slot()
    def _choose_srt_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Chọn file SRT",
            "",
            "Subtitle Files (*.srt);;All Files (*)",
        )
        if not path:
            return

        self._srt_path = path
        self.btn_clear_srt.setEnabled(True)
        self.lbl_srt.setText(f"SRT: {Path(path).name}")
        self.status_message.emit(f"Đã nạp SRT: {Path(path).name}")

    @Slot()
    def _clear_srt_file(self) -> None:
        self._srt_path = None
        self.btn_clear_srt.setEnabled(False)
        self.lbl_srt.setText("SRT: chưa nạp")
        self.status_message.emit("Đã bỏ chế độ SRT")

    @Slot()
    def _request_trim_tab(self) -> None:
        if not self._ref_audio_path:
            QMessageBox.information(self, "Thiếu file", "Vui lòng nạp file audio mẫu trước.")
            return

        payload = {
            "source_audio_path": self._ref_audio_path,
            "ref_text": self.txt_ref_text.text().strip(),
        }
        self.trim_audio_requested.emit(payload)

    @Slot(dict)
    def apply_trimmed_reference(self, payload: dict) -> None:
        source_path = str(payload.get("source_audio_path") or "").strip()
        prompt_path = str(payload.get("prompt_audio_path") or "").strip()
        was_trimmed = bool(payload.get("was_trimmed"))
        start_sec = float(payload.get("start_sec") or 0.0)
        duration_sec = float(payload.get("duration_sec") or 0.0)

        if not prompt_path or not Path(prompt_path).exists():
            self.status_message.emit("Không nhận được audio đã cắt hợp lệ từ tab Trim")
            return

        self._cleanup_trim_temp()
        self._ref_audio_path = source_path or self._ref_audio_path
        if was_trimmed:
            self._trim_temp_path = prompt_path
            self._prompt_audio_path = prompt_path
        else:
            self._trim_temp_path = None
            self._prompt_audio_path = prompt_path

        self._update_prompt_source_label(start_sec=start_sec, duration_sec=duration_sec, was_trimmed=was_trimmed)
        self.btn_save_voice.setEnabled(True)
        self.btn_asr.setEnabled(self.engine.is_loaded)

        self._voice_prompt = None
        self.lbl_clone_status.setText("⏳ Đang tạo voice prompt từ audio đã chọn...")
        self._load_ref_preview(self._prompt_audio_path)
        if self.engine.is_loaded:
            self._create_voice_prompt()

        if was_trimmed:
            end_sec = start_sec + max(0.0, duration_sec)
            self.status_message.emit(f"Đã nhận audio đã cắt: {start_sec:.1f}s → {end_sec:.1f}s")
        else:
            self.status_message.emit("Đã nhận audio nguồn từ tab Trim")

    def _update_prompt_source_label(
        self,
        start_sec: float = 0.0,
        duration_sec: float = 0.0,
        was_trimmed: bool | None = None,
    ) -> None:
        if was_trimmed is None:
            was_trimmed = bool(self._prompt_audio_path and self._ref_audio_path and self._prompt_audio_path != self._ref_audio_path)

        if was_trimmed:
            end_sec = start_sec + max(0.0, duration_sec)
            self.lbl_prompt_source.setText(f"Prompt: đoạn cắt {start_sec:.1f}s → {end_sec:.1f}s")
        else:
            self.lbl_prompt_source.setText("Prompt: dùng file nguồn")

    def _load_ref_preview(self, path: str | None) -> None:
        if not path:
            return
        self.ref_player.load_file(path)
        try:
            envelope = audio_utils.audio_to_waveform_data(path)
            self.ref_waveform.set_data(envelope)
        except Exception as e:
            logger.warning("Failed to load waveform: %s", e)

    def _cleanup_trim_temp(self) -> None:
        if self._trim_temp_path:
            try:
                Path(self._trim_temp_path).unlink(missing_ok=True)
            except Exception:
                pass
            self._trim_temp_path = None

    @Slot(bool, str, str)
    def _on_tts_finished(self, success: bool, output_path: str, error: str) -> None:
        self.show_progress.emit(False, "")
        self._set_generating_state(False)

        if not success and error == GENERATION_CANCELLED:
            self.status_message.emit("Đã dừng tạo giọng nói.")
            return

        if success:
            final_path = output_path
            fmt_ext = self.combo_format.currentData() or ".wav"

            try:
                if self._output_dir and Path(self._output_dir).exists():
                    out_dir = Path(self._output_dir)
                    final_name = self._build_output_filename(fmt_ext)
                    target = self._resolve_unique_path(out_dir / final_name)

                    if fmt_ext == ".wav":
                        shutil.copy2(output_path, target)
                    else:
                        audio_utils.export_audio(output_path, str(target), output_format=fmt_ext)

                    final_path = str(target)
                    self.status_message.emit(f"Đã tự động lưu: {final_path}")
                else:
                    self.status_message.emit("Tạo giọng nói hoàn tất (chưa chọn output dir, dùng file tạm).")
            except Exception as e:
                logger.error("Auto-save failed: %s", e)
                QMessageBox.warning(self, "Lỗi lưu file", f"Tạo giọng nói thành công nhưng lưu tự động thất bại:\n{e}")
                self.status_message.emit("Tạo giọng nói thành công nhưng lưu tự động thất bại.")

            self._output_path = final_path
            self.out_player.load_file(final_path)
            try:
                envelope = audio_utils.audio_to_waveform_data(final_path)
                self.out_waveform.set_data(envelope)
            except Exception as e:
                logger.warning("Failed to load output waveform: %s", e)

            # Record history
            voice_id = self._selected_voice.id if self._selected_voice else ""
            try:
                dur = audio_utils.get_duration(final_path)
                self.db.add_history(
                    voice_id=voice_id,
                    text=self.txt_input.toPlainText().strip(),
                    output_path=final_path,
                    speed=self._get_speed(),
                    num_step=self._get_num_steps(),
                    duration=dur,
                )
            except Exception:
                pass

            if self._output_dir and Path(self._output_dir).exists():
                self.status_message.emit(f"Tạo giọng nói hoàn tất! Đã lưu tại: {final_path}")
        else:
            self.status_message.emit("Tạo giọng nói thất bại")
            QMessageBox.warning(self, "Lỗi tạo giọng nói", f"Thất bại:\n\n{error}")

    # ==================================================================
    # State
    # ==================================================================
    def _update_generate_button(self) -> None:
        if self._is_generating:
            self.btn_generate.setEnabled(True)
            return

        # Keep button clickable once model is ready.
        # Detailed validation (text/output folder) is handled in _start_generation
        # so users always get a clear warning instead of a "dead" button.
        self.btn_generate.setEnabled(self.engine.is_loaded)

    def on_model_loaded(self) -> None:
        """Called by MainWindow when model finishes loading."""
        self.btn_asr.setEnabled(bool(self._ref_audio_path))
        if self._ref_audio_path and not self._voice_prompt:
            self._create_voice_prompt()
        self._update_generate_button()

    def stop_playback(self) -> None:
        self.ref_player.stop()
        self.out_player.stop()

    def close(self) -> None:
        self._cleanup_trim_temp()
        super().close()
