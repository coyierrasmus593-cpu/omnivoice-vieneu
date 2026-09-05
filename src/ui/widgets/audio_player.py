# -*- coding: utf-8 -*-
"""Audio player widget with play/stop, seek slider, and duration display."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal, Slot
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QWidget,
)


class AudioPlayerWidget(QWidget):
    """Compact audio player: play/stop + slider + time label."""

    playback_position_changed = Signal(float)  # 0.0–1.0 progress

    def __init__(self, parent=None):
        super().__init__(parent)
        self._file_path: str | None = None
        self._duration_ms: int = 0

        self._setup_ui()
        self._setup_player()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Play / Stop button
        self.btn_play = QPushButton("▶")
        self.btn_play.setObjectName("btn_play")
        self.btn_play.setFixedSize(32, 32)
        self.btn_play.setToolTip("Play / Pause")
        self.btn_play.clicked.connect(self._toggle_play)
        layout.addWidget(self.btn_play)

        # Filename label
        self.lbl_name = QLabel("No file")
        self.lbl_name.setObjectName("lbl_audio_name")
        self.lbl_name.setMinimumWidth(80)
        layout.addWidget(self.lbl_name)

        # Seek slider
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 1000)
        self.slider.setValue(0)
        self.slider.sliderMoved.connect(self._on_slider_moved)
        layout.addWidget(self.slider, stretch=1)

        # Time label
        self.lbl_time = QLabel("0:00 / 0:00")
        self.lbl_time.setObjectName("lbl_time")
        self.lbl_time.setFixedWidth(100)
        self.lbl_time.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.lbl_time)

    def _setup_player(self) -> None:
        self._audio_output = QAudioOutput(self)
        self._player = QMediaPlayer(self)
        self._player.setAudioOutput(self._audio_output)
        self._player.positionChanged.connect(self._on_position_changed)
        self._player.durationChanged.connect(self._on_duration_changed)
        self._player.playbackStateChanged.connect(self._on_state_changed)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def load_file(self, path: str) -> None:
        """Load an audio file for playback."""
        self._file_path = path
        self._player.setSource(QUrl.fromLocalFile(path))
        self.lbl_name.setText(Path(path).name)
        self.lbl_name.setToolTip(path)
        self.slider.setValue(0)
        self.btn_play.setText("▶")

    def stop(self) -> None:
        """Stop playback."""
        self._player.stop()
        self.slider.setValue(0)
        self.btn_play.setText("▶")

    def set_volume(self, volume: float) -> None:
        """Set volume (0.0–1.0)."""
        self._audio_output.setVolume(volume)

    @property
    def file_path(self) -> str | None:
        return self._file_path

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------
    @Slot()
    def _toggle_play(self) -> None:
        if self._file_path is None:
            return
        state = self._player.playbackState()
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
        else:
            self._player.play()

    @Slot(int)
    def _on_slider_moved(self, value: int) -> None:
        if self._duration_ms > 0:
            pos = int(value / 1000 * self._duration_ms)
            self._player.setPosition(pos)

    @Slot(int)
    def _on_position_changed(self, pos_ms: int) -> None:
        if self._duration_ms > 0:
            slider_val = int(pos_ms / self._duration_ms * 1000)
            self.slider.blockSignals(True)
            self.slider.setValue(slider_val)
            self.slider.blockSignals(False)
            self.playback_position_changed.emit(pos_ms / self._duration_ms)

        self.lbl_time.setText(
            f"{self._format_time(pos_ms)} / {self._format_time(self._duration_ms)}"
        )

    @Slot(int)
    def _on_duration_changed(self, dur_ms: int) -> None:
        self._duration_ms = dur_ms

    @Slot(QMediaPlayer.PlaybackState)
    def _on_state_changed(self, state: QMediaPlayer.PlaybackState) -> None:
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.btn_play.setText("⏸")
        else:
            self.btn_play.setText("▶")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _format_time(ms: int) -> str:
        total_s = ms // 1000
        m = total_s // 60
        s = total_s % 60
        return f"{m}:{s:02d}"
