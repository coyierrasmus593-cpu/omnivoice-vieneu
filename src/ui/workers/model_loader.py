# -*- coding: utf-8 -*-
"""Background worker for loading the OmniVoice model."""

from __future__ import annotations

import traceback

from PySide6.QtCore import QThread, Signal

from src.core.engine import VoiceEngine


class ModelLoaderWorker(QThread):
    """Loads VoiceEngine model on a background thread.

    Signals:
        progress(str): Status messages during loading.
        finished(bool, str, dict): (success, error_message, device_info).
    """

    progress = Signal(str)
    finished = Signal(bool, str, dict)

    def __init__(self, engine: VoiceEngine, model_id: str = None, device: str = None):
        super().__init__()
        self.engine = engine
        self.model_id = model_id or "k2-fsa/OmniVoice"
        self.device = device

    def run(self) -> None:
        try:
            dev_info = self.engine.load_model(
                model_id=self.model_id,
                device=self.device,
                on_progress=self._on_progress,
                load_asr=False,
            )
            self.finished.emit(True, "", dev_info)
        except Exception as exc:
            tb = traceback.format_exc()
            self.finished.emit(False, f"{exc}\n\n{tb}", {})

    def _on_progress(self, msg: str) -> None:
        self.progress.emit(msg)
