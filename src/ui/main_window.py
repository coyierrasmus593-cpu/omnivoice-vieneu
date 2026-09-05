# -*- coding: utf-8 -*-
"""Main window — sidebar navigation + multi-page layout (Vietnamese UI)."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from src.core.engine import VoiceEngine
from src.core.license_models import LicenseInfo
from src.data.database import Database
from src.ui.app import APP_DISPLAY_NAME
from src.ui.dialogs.help_dialog import HelpDialog
from src.ui.dialogs.license_info_dialog import LicenseInfoDialog
from src.ui.pages.tts_studio import TTSStudioPage
from src.ui.pages.voice_library import VoiceLibraryPage
from src.ui.pages.batch_process import BatchProcessPage
from src.ui.pages.join_audio import JoinAudioPage
from src.ui.pages.trim_audio import TrimAudioPage
from src.ui.workers.model_loader import ModelLoaderWorker
from src.ui.widgets.log_panel import LogPanel

logger = logging.getLogger(__name__)


class SidebarButton(QPushButton):
    """A navigation button for the sidebar."""

    def __init__(self, text: str, icon_char: str = "", parent=None):
        label = f"{icon_char}  {text}" if icon_char else text
        super().__init__(label, parent)
        self.setObjectName("sidebar_btn")
        self.setCheckable(True)
        self.setMinimumHeight(44)
        self.setCursor(Qt.CursorShape.PointingHandCursor)


class MainWindow(QMainWindow):
    """OmniVoice Cloner — cua so chinh voi thanh dieu huong ben trai."""

    def __init__(self, license_info: dict | None = None) -> None:
        super().__init__()

        self.engine = VoiceEngine()
        self.db = Database()
        self._license_info = self._build_license_info(license_info)

        self._model_worker: ModelLoaderWorker | None = None

        self._setup_window()
        self._build_ui()
        self._start_model_loading()

    def _build_license_info(self, raw: dict | None) -> LicenseInfo:
        if raw is None:
            return LicenseInfo()
        return LicenseInfo.from_verify_result(raw)

    def _get_app_version(self) -> str:
        app = QApplication.instance()
        if app is None:
            return ""
        return app.applicationVersion().strip()

    # ==================================================================
    # Window Setup
    # ==================================================================
    def _setup_window(self) -> None:
        version = self._get_app_version()
        title = APP_DISPLAY_NAME if not version else f"{APP_DISPLAY_NAME} {version}"
        self.setWindowTitle(title)
        self.setMinimumSize(1100, 750)
        self.resize(1250, 850)

    # ==================================================================
    # Build UI
    # ==================================================================
    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # --- Sidebar ---
        root.addWidget(self._build_sidebar())

        # --- Content Area ---
        content = QVBoxLayout()
        content.setContentsMargins(16, 12, 16, 8)
        content.setSpacing(8)

        # Model status bar
        content.addWidget(self._build_model_bar())

        # Stacked pages
        self.stack = QStackedWidget()
        self._page_tts = TTSStudioPage(self.engine, self.db)
        self._page_library = VoiceLibraryPage(self.engine, self.db)
        self._page_batch = BatchProcessPage(self.engine, self.db)
        self._page_join = JoinAudioPage()
        self._page_trim = TrimAudioPage()

        self.stack.addWidget(self._page_tts)        # index 0
        self.stack.addWidget(self._page_library)    # index 1
        self.stack.addWidget(self._page_batch)      # index 2
        self.stack.addWidget(self._page_join)       # index 3
        self.stack.addWidget(self._page_trim)       # index 4

        content.addWidget(self.stack, stretch=1)

        # Progress bar
        content.addWidget(self._build_progress_bar())

        root.addLayout(content, stretch=7)

        # --- Log Panel (right column) ---
        self.log_panel = LogPanel()
        root.addWidget(self.log_panel, stretch=2)

        # --- Connect page signals ---
        self._page_tts.status_message.connect(self._show_status)
        self._page_tts.status_message.connect(lambda msg: self.log_panel.append_log(msg, "INFO"))
        self._page_tts.show_progress.connect(self._show_progress)
        self._page_library.status_message.connect(self._show_status)
        self._page_library.status_message.connect(lambda msg: self.log_panel.append_log(msg, "INFO"))
        self._page_library.voice_selected_for_tts.connect(self._use_voice_from_library)
        self._page_batch.status_message.connect(self._show_status)
        self._page_batch.status_message.connect(lambda msg: self.log_panel.append_log(msg, "INFO"))
        self._page_batch.show_progress.connect(self._show_progress)
        self._page_batch.join_audio_requested.connect(self._open_join_audio_with_files)
        self._page_join.status_message.connect(self._show_status)
        self._page_join.status_message.connect(lambda msg: self.log_panel.append_log(msg, "INFO"))
        self._page_tts.trim_audio_requested.connect(self._open_trim_audio_with_context)
        self._page_trim.status_message.connect(self._show_status)
        self._page_trim.status_message.connect(lambda msg: self.log_panel.append_log(msg, "INFO"))
        self._page_trim.trim_applied_to_tts.connect(self._apply_trimmed_audio_to_tts)

        # --- Pipe Python logging into log panel ---
        import logging as _logging
        root_logger = _logging.getLogger()
        log_handler = self.log_panel.create_logging_handler(level=_logging.INFO)
        root_logger.addHandler(log_handler)

        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Đang khởi động...")

    # ------------------------------------------------------------------
    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(200)

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(8, 16, 8, 16)
        layout.setSpacing(4)

        # App logo
        icon_path = Path(__file__).parent.parent.parent / "Applogo.png"
        if icon_path.exists():
            logo = QLabel()
            logo.setObjectName("sidebar_logo")
            pixmap = QPixmap(str(icon_path)).scaled(
                48, 48, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            logo.setPixmap(pixmap)
            logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(logo)

        # App title
        title = QLabel(APP_DISPLAY_NAME.replace("-", "\n", 1))
        title.setObjectName("sidebar_title")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        layout.addSpacing(20)

        # Nav buttons
        self.nav_buttons: list[SidebarButton] = []

        self.btn_nav_tts = SidebarButton("Tạo giọng nói", "🎙")
        self.btn_nav_library = SidebarButton("Thư viện giọng", "📚")
        self.btn_nav_batch = SidebarButton("Xử lý hàng loạt", "📋")
        self.btn_nav_join = SidebarButton("Join Audio", "🎚")
        self.btn_nav_trim = SidebarButton("Trim Audio", "✂")

        for i, btn in enumerate([
            self.btn_nav_tts,
            self.btn_nav_library,
            self.btn_nav_batch,
            self.btn_nav_join,
            self.btn_nav_trim,
        ]):
            btn.clicked.connect(lambda checked, idx=i: self._switch_page(idx))
            layout.addWidget(btn)
            self.nav_buttons.append(btn)

        self.btn_nav_tts.setChecked(True)

        layout.addStretch()

        # Utility buttons (non-nav)
        self.btn_license = SidebarButton("Bản quyền", "🔑")
        self.btn_license.setCheckable(False)
        self.btn_license.clicked.connect(self._show_license_info)
        layout.addWidget(self.btn_license)

        self.btn_help = SidebarButton("Hỗ trợ", "❓")
        self.btn_help.setCheckable(False)
        self.btn_help.clicked.connect(self._show_help)
        layout.addWidget(self.btn_help)

        layout.addSpacing(8)

        # Version
        version = self._get_app_version() or "N/A"
        ver_label = QLabel(version)
        ver_label.setObjectName("sidebar_version")
        ver_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(ver_label)

        return sidebar

    # ------------------------------------------------------------------
    def _build_model_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("model_bar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 6, 12, 6)

        self.combo_model = QComboBox()
        self.combo_model.addItem("OmniVoice (k2-fsa/OmniVoice)", "k2-fsa/OmniVoice")
        self.combo_model.addItem("VieNeu-TTS (pnnbao-ump/VieNeu-TTS-v3-Turbo)", "pnnbao-ump/VieNeu-TTS-v3-Turbo")
        self.combo_model.currentIndexChanged.connect(self._start_model_loading)
        layout.addWidget(self.combo_model)

        self.lbl_model_status = QLabel("⏳ Đang tải mô hình...")
        self.lbl_model_status.setObjectName("lbl_model_status")
        layout.addWidget(self.lbl_model_status, stretch=1)

        self.btn_reload = QPushButton("Tải lại")
        self.btn_reload.setObjectName("btn_secondary")
        self.btn_reload.setMinimumWidth(80)
        self.btn_reload.clicked.connect(self._start_model_loading)
        self.btn_reload.setEnabled(False)
        layout.addWidget(self.btn_reload)

        return bar

    # ------------------------------------------------------------------
    def _build_progress_bar(self) -> QWidget:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(False)
        self.progress_bar.setFixedHeight(18)
        layout.addWidget(self.progress_bar, stretch=1)

        self.lbl_progress = QLabel("")
        self.lbl_progress.setObjectName("lbl_progress")
        layout.addWidget(self.lbl_progress)

        return container

    # ==================================================================
    # Navigation
    # ==================================================================
    @Slot()
    def _switch_page(self, index: int) -> None:
        # Stop playback on current page
        current = self.stack.currentWidget()
        if hasattr(current, "stop_playback"):
            current.stop_playback()

        self.stack.setCurrentIndex(index)

        for i, btn in enumerate(self.nav_buttons):
            btn.setChecked(i == index)

        # Refresh data on page switch
        if index == 1:  # Voice Library
            self._page_library.refresh()
        elif index == 0:  # TTS Studio
            self._page_tts.refresh_voice_list()
        elif index == 2:  # Batch
            self._page_batch.refresh_voice_list()

    def _use_voice_from_library(self, voice_id: str) -> None:
        """Switch to TTS page and select a voice from library."""
        self._page_tts.refresh_voice_list()
        # Find voice in combo
        idx = self._page_tts.combo_voice.findData(voice_id)
        if idx >= 0:
            self._page_tts.combo_voice.setCurrentIndex(idx)
        self._switch_page(0)

    @Slot(list)
    def _open_join_audio_with_files(self, files: list[str]) -> None:
        self._page_join.load_files(files)
        self._switch_page(3)

    @Slot(dict)
    def _open_trim_audio_with_context(self, context: dict) -> None:
        source_path = str(context.get("source_audio_path") or "").strip()
        ref_text = str(context.get("ref_text") or "")
        if not source_path:
            self._show_status("Chưa có file tham chiếu để trim")
            return

        self._page_trim.load_source_audio(source_path, ref_text=ref_text)
        self._switch_page(4)

    @Slot(dict)
    def _apply_trimmed_audio_to_tts(self, payload: dict) -> None:
        self._page_tts.apply_trimmed_reference(payload)
        self._switch_page(0)

    # ==================================================================
    # Model Loading
    # ==================================================================
    def _start_model_loading(self) -> None:
        self.btn_reload.setEnabled(False)
        self.lbl_model_status.setText("⏳ Đang tải mô hình...")
        self._show_progress(True, "Đang tải mô hình AI...")
        
        # Get model_id from combo box if available, otherwise default
        model_id = getattr(self, "combo_model", None) and self.combo_model.currentData() or "k2-fsa/OmniVoice"

        self._model_worker = ModelLoaderWorker(self.engine, model_id=model_id)
        self._model_worker.progress.connect(self._on_model_progress)
        self._model_worker.finished.connect(self._on_model_loaded)
        self._model_worker.start()

    @Slot(str)
    def _on_model_progress(self, msg: str) -> None:
        self.lbl_model_status.setText(f"⏳ {msg}")
        self.lbl_progress.setText(msg)
        self.status_bar.showMessage(msg)

    @Slot(bool, str, dict)
    def _on_model_loaded(self, success: bool, error: str, dev_info: dict) -> None:
        self._show_progress(False)
        self.btn_reload.setEnabled(True)

        if success:
            device = dev_info.get("device", "cpu")
            gpu_name = dev_info.get("gpu_name", "")
            cpu_reason = str(dev_info.get("cpu_reason") or "").strip()
            if "cuda" in device and gpu_name:
                vram = dev_info.get("vram_gb", "?")
                status = f"✅ Mô hình đã tải — GPU: {gpu_name} ({vram} GB)"
                ready_msg = "Sẵn sàng"
            else:
                status = "✅ Mô hình đã tải — Chế độ CPU (chậm hơn)"
                ready_msg = cpu_reason or "Sẵn sàng ở chế độ CPU"
            self.lbl_model_status.setText(status)
            self.status_bar.showMessage(ready_msg)

            # Notify pages
            self._page_tts.on_model_loaded()
            self._page_tts.refresh_voice_list()
            self._page_library.refresh()
            self._page_batch.refresh_voice_list()
        else:
            self.lbl_model_status.setText("❌ Tải mô hình thất bại")
            self.status_bar.showMessage("Lỗi tải mô hình")
            QMessageBox.critical(
                self, "Lỗi Mô hình",
                f"Không thể tải mô hình OmniVoice:\n\n{error}",
            )

    # ==================================================================
    # Status helpers
    # ==================================================================
    @Slot(str)
    def _show_status(self, msg: str) -> None:
        self.status_bar.showMessage(msg)

    @Slot(bool, str)
    def _show_progress(self, visible: bool, text: str = "") -> None:
        self.progress_bar.setVisible(visible)
        self.lbl_progress.setText(text)

    # ==================================================================
    # License & Help dialogs
    # ==================================================================
    @Slot()
    def _show_license_info(self) -> None:
        dialog = LicenseInfoDialog(self._license_info, parent=self)
        dialog.license_deactivated.connect(self._on_license_deactivated)
        dialog.exec()

    @Slot()
    def _on_license_deactivated(self) -> None:
        """Handle license deactivation — close app to restart with new key."""
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(
            self, "Đã huỷ kích hoạt",
            "Bản quyền đã được huỷ.\nApp sẽ đóng lại, vui lòng mở lại để nhập key mới.",
        )
        self.close()

    @Slot()
    def _show_help(self) -> None:
        dialog = HelpDialog(parent=self)
        dialog.exec()

    # ==================================================================
    # Cleanup
    # ==================================================================
    def closeEvent(self, event) -> None:
        self._page_tts.stop_playback()
        self._page_library.stop_playback()
        self._page_batch.stop_playback()
        self._page_join.stop_playback()
        self._page_trim.stop_playback()
        self._page_trim.cleanup_temp_files()
        self.engine.unload_model()
        self.db.close()
        super().closeEvent(event)
