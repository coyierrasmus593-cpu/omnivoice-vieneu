# -*- coding: utf-8 -*-
"""Help dialog — basic usage guide."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.ui.app import APP_DISPLAY_NAME


def build_help_html() -> str:
    app = QApplication.instance()
    version = app.applicationVersion().strip() if app else "N/A"

    return f"""
<h2 style="color: #89b4fa;">Hướng dẫn sử dụng</h2>

<h3 style="color: #cdd6f4;">1. Tạo giọng nói (TTS Studio)</h3>
<ul style="color: #bac2de;">
  <li><b>Bước 1:</b> Chọn giọng từ thư viện hoặc kéo thả file audio mẫu (WAV/MP3/FLAC/OGG/M4A)</li>
  <li><b>Bước 2:</b> Kiểm tra/chỉnh <b>Lời giọng mẫu</b> (có thể bấm ASR để nhận dạng tự động)</li>
  <li><b>Bước 3:</b> Nhập văn bản cần tạo giọng ở ô nội dung</li>
  <li><b>Bước 4:</b> Chọn <b>thư mục output</b> và định dạng file (WAV/MP3)</li>
  <li><b>Bước 5:</b> Bấm <b>"Tạo giọng nói"</b> (nút sẽ đổi thành <b>"Dừng"</b> trong lúc chạy)</li>
  <li><b>Bước 6:</b> Nghe lại kết quả, file sẽ <b>tự động lưu</b> vào thư mục output đã chọn</li>
</ul>

<h3 style="color: #cdd6f4;">2. Thư viện giọng</h3>
<ul style="color: #bac2de;">
  <li>Quản lý các giọng đã lưu từ TTS Studio</li>
  <li>Bấm <b>"Dùng"</b> để nạp nhanh giọng vào trang TTS Studio</li>
  <li>Bấm <b>"Sửa"</b> để đổi tên, <b>"Xoá"</b> để gỡ giọng khỏi thư viện</li>
</ul>

<h3 style="color: #cdd6f4;">3. Xử lý hàng loạt (Batch)</h3>
<ul style="color: #bac2de;">
  <li>Tạo nhiều file audio trong một lần chạy</li>
  <li>Chọn 1 giọng từ thư viện và nhập danh sách văn bản</li>
  <li>Xuất đồng loạt theo định dạng WAV/MP3</li>
</ul>

<hr style="border-color: #313244;">

<h3 style="color: #cdd6f4;">Lưu ý quan trọng</h3>
<ul style="color: #bac2de;">
  <li><b>Nên chọn giọng mẫu trùng ngôn ngữ với văn bản input</b> để phát âm ổn định hơn</li>
  <li><b>Nên chuẩn hoá văn bản input:</b> xoá ký tự thừa, ký tự lạ, khoảng trắng dư để tránh AI đọc sai</li>
  <li>Giọng mẫu tốt nhất: 5–15 giây, rõ ràng, ít tạp âm</li>
  <li>GPU NVIDIA giúp tạo giọng nhanh hơn đáng kể so với CPU</li>
</ul>

<hr style="border-color: #313244;">

<p style="color: #585b70; font-size: 11px;">
  <b>Ứng dụng:</b> {APP_DISPLAY_NAME}<br>
  <b>Liên hệ hỗ trợ:</b> Telegram: @nobitabx<br>
  <b>Phiên bản:</b> {version}<br>
  <b>Website:</b> ai86.pro
</p>
"""


class HelpDialog(QDialog):
    """Popup with basic usage instructions."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Hướng dẫn sử dụng")
        self.setMinimumSize(500, 500)
        self.resize(520, 560)
        self._build_ui()
        self._apply_style()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        # Scrollable content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(12, 8, 12, 8)

        help_label = QLabel(build_help_html())
        help_label.setWordWrap(True)
        help_label.setTextFormat(Qt.TextFormat.RichText)
        help_label.setStyleSheet("background: transparent; color: #cdd6f4;")
        help_label.setOpenExternalLinks(True)
        content_layout.addWidget(help_label)
        content_layout.addStretch()

        scroll.setWidget(content)
        layout.addWidget(scroll, stretch=1)

        # Close button
        btn_close = QPushButton("Đóng")
        btn_close.setObjectName("btn_primary")
        btn_close.setMinimumHeight(36)
        btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close)

    def _apply_style(self) -> None:
        self.setStyleSheet("""
            QDialog {
                background-color: #1e1e2e;
            }
            QPushButton#btn_primary {
                background-color: #89b4fa;
                color: #1e1e2e;
                font-weight: bold;
                font-size: 13px;
                border: none;
                border-radius: 6px;
                padding: 8px 22px;
            }
            QPushButton#btn_primary:hover {
                background-color: #74c7ec;
            }
        """)
