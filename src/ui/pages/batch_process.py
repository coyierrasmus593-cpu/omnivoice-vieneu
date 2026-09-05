# -*- coding: utf-8 -*-
"""Batch Processing page — import text list → generate all → export folder."""

from __future__ import annotations

import csv
import logging
from pathlib import Path

from PySide6.QtCore import Slot, Signal, QThread
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.core.engine import VoiceEngine
from src.core import audio_utils
from src.data.database import Database, BatchItem

logger = logging.getLogger(__name__)


class BatchGenerateWorker(QThread):
    """Process batch queue one item at a time."""

    item_started = Signal(int, str)     # (index, text_preview)
    item_finished = Signal(int, bool, str)  # (index, success, output_path_or_error)
    all_finished = Signal(int, int)     # (success_count, fail_count)

    def __init__(
        self,
        engine: VoiceEngine,
        items: list[BatchItem],
        voice_prompt,
        output_dir: str,
        output_format: str,
        speed: float,
        num_step: int,
    ):
        super().__init__()
        self.engine = engine
        self.items = items
        self.voice_prompt = voice_prompt
        self.output_dir = output_dir
        self.output_format = output_format
        self.speed = speed
        self.num_step = num_step
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)
        ok_count = 0
        fail_count = 0

        for i, item in enumerate(self.items):
            if self._cancelled:
                break

            preview = item.text[:50] + ("..." if len(item.text) > 50 else "")
            self.item_started.emit(i, preview)

            try:
                audio_np, sr = self.engine.generate(
                    text=item.text,
                    voice_prompt=self.voice_prompt,
                    speed=self.speed,
                    num_step=self.num_step,
                )

                # Save as WAV first
                wav_name = f"{i + 1:04d}_{self._safe_filename(item.text[:40])}.wav"
                wav_path = str(Path(self.output_dir) / wav_name)
                audio_utils.save_wav(audio_np, wav_path, sr)

                # Convert if needed
                if self.output_format != ".wav":
                    out_name = wav_name.replace(".wav", self.output_format)
                    out_path = str(Path(self.output_dir) / out_name)
                    audio_utils.export_audio(wav_path, out_path, self.output_format)
                    Path(wav_path).unlink(missing_ok=True)
                    item.output_path = out_path
                else:
                    item.output_path = wav_path

                item.status = "done"
                item.duration = audio_utils.get_duration(item.output_path)
                ok_count += 1
                self.item_finished.emit(i, True, item.output_path)

            except Exception as e:
                item.status = "error"
                item.error = str(e)
                fail_count += 1
                self.item_finished.emit(i, False, str(e))

        self.all_finished.emit(ok_count, fail_count)

    @staticmethod
    def _safe_filename(text: str) -> str:
        import re
        safe = re.sub(r'[^\w\s-]', '', text).strip()
        return re.sub(r'[\s]+', '_', safe)[:40]


class BatchProcessPage(QWidget):
    """Batch processing: import text list → generate all → export to folder."""

    status_message = Signal(str)
    show_progress = Signal(bool, str)
    join_audio_requested = Signal(list)

    def __init__(self, engine: VoiceEngine, db: Database, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.db = db

        self._items: list[BatchItem] = []
        self._voice_prompt = None
        self._worker: BatchGenerateWorker | None = None

        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(0, 0, 0, 0)

        # --- Import + Voice ---
        top_row = QHBoxLayout()

        # Import buttons
        self.btn_import_txt = QPushButton("Nhập file TXT")
        self.btn_import_txt.setObjectName("btn_secondary")
        self.btn_import_txt.clicked.connect(self._import_txt)
        top_row.addWidget(self.btn_import_txt)

        self.btn_import_csv = QPushButton("Nhập file CSV")
        self.btn_import_csv.setObjectName("btn_secondary")
        self.btn_import_csv.clicked.connect(self._import_csv)
        top_row.addWidget(self.btn_import_csv)

        self.btn_clear = QPushButton("Xoá tất cả")
        self.btn_clear.clicked.connect(self._clear_items)
        top_row.addWidget(self.btn_clear)

        self.btn_join_audio = QPushButton("Join Audio")
        self.btn_join_audio.setObjectName("btn_secondary")
        self.btn_join_audio.setToolTip("Nạp nhiều file audio vào tab Join Audio")
        self.btn_join_audio.clicked.connect(self._request_join_audio)
        top_row.addWidget(self.btn_join_audio)

        top_row.addStretch()

        # Voice selector
        top_row.addWidget(QLabel("Giọng:"))
        self.combo_voice = QComboBox()
        self.combo_voice.setMinimumWidth(200)
        self.combo_voice.addItem("— Không clone (giọng mặc định) —", "")
        self.combo_voice.currentIndexChanged.connect(self._on_voice_changed)
        top_row.addWidget(self.combo_voice)

        layout.addLayout(top_row)

        # --- Table ---
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["#", "Nội dung văn bản", "Trạng thái", "Thời lượng"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table)

        # --- Controls ---
        ctrl = QHBoxLayout()

        ctrl.addWidget(QLabel("Định dạng:"))
        self.combo_format = QComboBox()
        for ext, label in audio_utils.EXPORT_FORMATS.items():
            self.combo_format.addItem(label, ext)
        self.combo_format.setMinimumWidth(180)
        ctrl.addWidget(self.combo_format)

        ctrl.addWidget(QLabel("Tốc độ:"))
        self.combo_speed = QComboBox()
        self.combo_speed.addItems(["0.5x", "0.75x", "1.0x", "1.25x", "1.5x", "2.0x"])
        self.combo_speed.setCurrentIndex(2)
        self.combo_speed.setMinimumWidth(80)
        ctrl.addWidget(self.combo_speed)

        ctrl.addWidget(QLabel("Chất lượng:"))
        self.combo_steps = QComboBox()
        self.combo_steps.addItems(["8 (nhanh)", "16 (cân bằng)", "32 (chất lượng)"])
        self.combo_steps.setCurrentIndex(1)
        self.combo_steps.setMinimumWidth(150)
        ctrl.addWidget(self.combo_steps)

        ctrl.addStretch()
        layout.addLayout(ctrl)

        # --- Progress ---
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # --- Generate ---
        gen_row = QHBoxLayout()

        self.btn_generate = QPushButton("Tạo tất cả")
        self.btn_generate.setObjectName("btn_primary")
        self.btn_generate.setMinimumHeight(40)
        self.btn_generate.clicked.connect(self._start_batch)
        self.btn_generate.setEnabled(False)
        gen_row.addWidget(self.btn_generate)

        self.btn_cancel = QPushButton("Dừng")
        self.btn_cancel.setObjectName("btn_danger")
        self.btn_cancel.setMinimumWidth(80)
        self.btn_cancel.setVisible(False)
        self.btn_cancel.clicked.connect(self._cancel_batch)
        gen_row.addWidget(self.btn_cancel)

        self.lbl_summary = QLabel("")
        gen_row.addWidget(self.lbl_summary, stretch=1)

        layout.addLayout(gen_row)

    # ==================================================================
    # Voice list
    # ==================================================================
    def refresh_voice_list(self) -> None:
        self.combo_voice.blockSignals(True)
        current = self.combo_voice.currentData()
        self.combo_voice.clear()
        self.combo_voice.addItem("— Không clone (giọng mặc định) —", "")

        for v in self.db.list_voices(model_id=getattr(self.engine, "model_id", "k2-fsa/OmniVoice")):
            self.combo_voice.addItem(f"{v.name}  [{v.tags}]" if v.tags else v.name, v.id)

        if current:
            idx = self.combo_voice.findData(current)
            if idx >= 0:
                self.combo_voice.setCurrentIndex(idx)
        self.combo_voice.blockSignals(False)

    @Slot(int)
    def _on_voice_changed(self, index: int) -> None:
        voice_id = self.combo_voice.currentData()
        if not voice_id:
            self._voice_prompt = None
            return

        voice = self.db.get_voice(voice_id)
        if voice and Path(voice.audio_path).exists() and self.engine.is_loaded:
            # Create voice prompt in background to avoid blocking UI
            from src.ui.workers.tts_worker import VoicePromptWorker

            self._prompt_worker = VoicePromptWorker(
                self.engine, voice.audio_path, voice.ref_text or None
            )
            self._prompt_worker.finished.connect(
                lambda ok, prompt, err: self._on_batch_prompt_ready(ok, prompt, err, voice.name)
            )
            self.status_message.emit(f"Đang tạo voice prompt cho: {voice.name}...")
            self._prompt_worker.start()

    @Slot()
    def _on_batch_prompt_ready(self, ok: bool, prompt, err: str, voice_name: str) -> None:
        if ok:
            self._voice_prompt = prompt
            self.status_message.emit(f"Đã chọn giọng: {voice_name}")
        else:
            self._voice_prompt = None
            self.status_message.emit(f"Lỗi tạo voice prompt: {err}")

    # ==================================================================
    # Import
    # ==================================================================
    def _import_txt(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Nhập file TXT", "", "Text Files (*.txt);;All Files (*)",
        )
        if not path:
            return

        with open(path, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]

        for line in lines:
            self._items.append(BatchItem(text=line))

        self._refresh_table()
        self.status_message.emit(f"Đã nhập {len(lines)} dòng từ {Path(path).name}")

    def _import_csv(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Nhập file CSV", "", "CSV Files (*.csv);;All Files (*)",
        )
        if not path:
            return

        count = 0
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            for row in reader:
                if row:
                    text = row[0].strip()
                    if text:
                        self._items.append(BatchItem(text=text))
                        count += 1

        self._refresh_table()
        self.status_message.emit(f"Đã nhập {count} mục từ {Path(path).name}")

    def _clear_items(self) -> None:
        self._items.clear()
        self._refresh_table()

    @Slot()
    def _request_join_audio(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Chọn file để Join Audio",
            "",
            "Audio Files (*.wav *.mp3 *.flac *.ogg *.m4a *.aac *.wma);;All Files (*)",
        )
        if not files:
            return
        self.join_audio_requested.emit(files)
        self.status_message.emit(f"Đã chuyển {len(files)} file sang tab Join Audio")

    def _refresh_table(self) -> None:
        self.table.setRowCount(len(self._items))

        for i, item in enumerate(self._items):
            self.table.setItem(i, 0, QTableWidgetItem(str(i + 1)))
            self.table.setItem(i, 1, QTableWidgetItem(item.text))
            self.table.setItem(i, 2, QTableWidgetItem(self._status_label(item.status)))
            dur_str = f"{item.duration:.1f}s" if item.duration > 0 else "—"
            self.table.setItem(i, 3, QTableWidgetItem(dur_str))

        self.btn_generate.setEnabled(
            len(self._items) > 0 and self.engine.is_loaded
        )

    @staticmethod
    def _status_label(status: str) -> str:
        return {
            "pending": "Chờ",
            "processing": "Đang tạo...",
            "done": "✅ Xong",
            "error": "❌ Lỗi",
        }.get(status, status)

    # ==================================================================
    # Batch Generation
    # ==================================================================
    @Slot()
    def _start_batch(self) -> None:
        if not self._items:
            return

        output_dir = QFileDialog.getExistingDirectory(
            self, "Chọn thư mục lưu kết quả",
        )
        if not output_dir:
            return

        # Reset statuses
        for item in self._items:
            item.status = "pending"
            item.output_path = ""
            item.duration = 0
            item.error = ""

        self._refresh_table()

        speed_map = {"0.5x": 0.5, "0.75x": 0.75, "1.0x": 1.0,
                     "1.25x": 1.25, "1.5x": 1.5, "2.0x": 2.0}
        speed = speed_map.get(self.combo_speed.currentText(), 1.0)
        num_step = [8, 16, 32][self.combo_steps.currentIndex()]
        fmt = self.combo_format.currentData()

        self.btn_generate.setEnabled(False)
        self.btn_cancel.setVisible(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, len(self._items))
        self.progress_bar.setValue(0)

        self._worker = BatchGenerateWorker(
            engine=self.engine,
            items=self._items,
            voice_prompt=self._voice_prompt,
            output_dir=output_dir,
            output_format=fmt,
            speed=speed,
            num_step=num_step,
        )
        self._worker.item_started.connect(self._on_item_started)
        self._worker.item_finished.connect(self._on_item_finished)
        self._worker.all_finished.connect(self._on_all_finished)
        self._worker.start()

    @Slot()
    def _cancel_batch(self) -> None:
        if self._worker:
            self._worker.cancel()
            self.status_message.emit("Đang dừng...")

    @Slot(int, str)
    def _on_item_started(self, idx: int, preview: str) -> None:
        self._items[idx].status = "processing"
        self.table.setItem(idx, 2, QTableWidgetItem("Đang tạo..."))
        self.status_message.emit(f"[{idx + 1}/{len(self._items)}] {preview}")

    @Slot(int, bool, str)
    def _on_item_finished(self, idx: int, success: bool, result: str) -> None:
        item = self._items[idx]
        if success:
            self.table.setItem(idx, 2, QTableWidgetItem("✅ Xong"))
            dur_str = f"{item.duration:.1f}s" if item.duration > 0 else "—"
            self.table.setItem(idx, 3, QTableWidgetItem(dur_str))
        else:
            self.table.setItem(idx, 2, QTableWidgetItem("❌ Lỗi"))

        self.progress_bar.setValue(idx + 1)

    @Slot(int, int)
    def _on_all_finished(self, ok: int, fail: int) -> None:
        self.btn_generate.setEnabled(True)
        self.btn_cancel.setVisible(False)
        self.progress_bar.setVisible(False)

        self.lbl_summary.setText(f"Kết quả: {ok} thành công, {fail} lỗi")
        self.status_message.emit(f"Hoàn tất: {ok} thành công, {fail} lỗi")

    def stop_playback(self) -> None:
        pass
