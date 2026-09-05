# -*- coding: utf-8 -*-
"""Background worker for TTS speech generation."""

from __future__ import annotations

import tempfile
import traceback

from PySide6.QtCore import QThread, Signal

from src.core.engine import VoiceEngine, GENERATION_CANCELLED
from src.core import audio_utils
from src.core.synthesis_pipeline import (
    synthesize_srt_timeline,
    synthesize_text_with_controls,
)
from src.ui.settings import AdvancedTtsSettings


class TTSWorker(QThread):
    """Generates speech on a background thread.

    Signals:
        progress(str): Status message updates.
        finished(bool, str, str): (success, output_wav_path, error_message).
    """

    progress = Signal(str)
    finished = Signal(bool, str, str)

    def __init__(
        self,
        engine: VoiceEngine,
        text: str,
        voice_prompt=None,
        output_path: str = None,
        speed: float = 1.0,
        num_step: int = 32,
        guidance_scale: float = 2.0,
        advanced_settings: AdvancedTtsSettings | None = None,
        srt_path: str | None = None,
    ):
        super().__init__()
        self.engine = engine
        self.text = text
        self.voice_prompt = voice_prompt
        self.output_path = output_path
        self.speed = speed
        self.num_step = num_step
        self.guidance_scale = guidance_scale
        self.advanced_settings = advanced_settings or AdvancedTtsSettings()
        self.srt_path = srt_path
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def _should_cancel(self) -> bool:
        return self._cancelled

    def run(self) -> None:
        try:
            self.progress.emit("Generating speech...")

            def _on_progress(msg: str) -> None:
                self.progress.emit(msg)

            if self.srt_path:
                audio_np, sr, warnings = synthesize_srt_timeline(
                    engine=self.engine,
                    srt_path=self.srt_path,
                    voice_prompt=self.voice_prompt,
                    base_speed=self.speed,
                    num_step=self.num_step,
                    guidance_scale=self.guidance_scale,
                    pause_comma_ms=self.advanced_settings.punctuation_pause_comma_ms,
                    pause_mid_ms=self.advanced_settings.punctuation_pause_mid_ms,
                    pause_end_ms=self.advanced_settings.punctuation_pause_end_ms,
                    overflow_policy=self.advanced_settings.srt_overflow_policy,
                    should_cancel=self._should_cancel,
                    on_progress=_on_progress,
                )
                for warn in warnings:
                    self.progress.emit(f"⚠ {warn}")
            else:
                audio_np, sr = synthesize_text_with_controls(
                    engine=self.engine,
                    text=self.text,
                    voice_prompt=self.voice_prompt,
                    base_speed=self.speed,
                    num_step=self.num_step,
                    guidance_scale=self.guidance_scale,
                    pause_comma_ms=self.advanced_settings.punctuation_pause_comma_ms,
                    pause_mid_ms=self.advanced_settings.punctuation_pause_mid_ms,
                    pause_end_ms=self.advanced_settings.punctuation_pause_end_ms,
                    should_cancel=self._should_cancel,
                    on_progress=_on_progress,
                )

            if self._should_cancel():
                self.finished.emit(False, "", GENERATION_CANCELLED)
                return

            # Determine output path
            if self.output_path:
                out = self.output_path
            else:
                tmp = tempfile.NamedTemporaryFile(
                    suffix=".wav", delete=False, prefix="omnivoice_"
                )
                out = tmp.name
                tmp.close()

            self.progress.emit("Saving audio...")
            audio_utils.save_wav(audio_np, out, sr)

            if self._should_cancel():
                self.finished.emit(False, "", GENERATION_CANCELLED)
                return

            self.progress.emit("Done!")
            self.finished.emit(True, out, "")

        except Exception as exc:
            if str(exc) == GENERATION_CANCELLED:
                self.finished.emit(False, "", GENERATION_CANCELLED)
                return
            tb = traceback.format_exc()
            self.finished.emit(False, "", f"{exc}\n\n{tb}")


class TranscribeWorker(QThread):
    """Transcribes reference audio on a background thread.

    Signals:
        finished(bool, str, str): (success, transcript, error_message).
    """

    finished = Signal(bool, str, str)

    def __init__(self, engine: VoiceEngine, audio_path: str):
        super().__init__()
        self.engine = engine
        self.audio_path = audio_path

    def run(self) -> None:
        try:
            text = self.engine.transcribe(self.audio_path)
            self.finished.emit(True, text, "")
        except Exception as exc:
            tb = traceback.format_exc()
            self.finished.emit(False, "", f"{exc}\n\n{tb}")


class VoicePromptWorker(QThread):
    """Creates VoiceClonePrompt on a background thread.

    Signals:
        progress(str): Status messages.
        finished(bool, object, str): (success, voice_prompt, error_message).
    """

    progress = Signal(str)
    finished = Signal(bool, object, str)

    def __init__(self, engine: VoiceEngine, audio_path: str, ref_text: str = None):
        super().__init__()
        self.engine = engine
        self.audio_path = audio_path
        self.ref_text = ref_text

    def run(self) -> None:
        try:
            self.progress.emit("Processing reference voice...")
            prompt = self.engine.create_voice_prompt(
                audio_path=self.audio_path,
                ref_text=self.ref_text,
            )
            self.progress.emit("Voice prompt ready!")
            self.finished.emit(True, prompt, "")
        except Exception as exc:
            tb = traceback.format_exc()
            self.finished.emit(False, None, f"{exc}\n\n{tb}")
