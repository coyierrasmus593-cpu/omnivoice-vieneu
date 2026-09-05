# -*- coding: utf-8 -*-
"""UI runtime settings shared across pages."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QSettings


@dataclass
class AdvancedTtsSettings:
    """Advanced generation controls."""

    # Additive pauses after punctuation; 0 means rely on model-native rhythm.
    punctuation_pause_comma_ms: int = 0
    punctuation_pause_mid_ms: int = 0
    punctuation_pause_end_ms: int = 0
    srt_overflow_policy: str = "warn"  # warn | speed_up


class SettingsStore:
    """Thin wrapper around QSettings for this app."""

    def __init__(self) -> None:
        self._qs = QSettings()

    def load_advanced_tts(self) -> AdvancedTtsSettings:
        get = self._qs.value

        def _int(name: str, default: int) -> int:
            try:
                return int(get(name, default))
            except Exception:
                return default

        def _clamp_ms(value: int) -> int:
            return max(0, min(2000, int(value)))

        policy = str(get("tts/srt_overflow_policy", "warn") or "warn").strip().lower()
        if policy not in {"warn", "speed_up"}:
            policy = "warn"

        comma = _clamp_ms(_int("tts/pause_comma_ms", 0))
        mid = _clamp_ms(_int("tts/pause_mid_ms", 0))
        end = _clamp_ms(_int("tts/pause_end_ms", 0))

        # One-time migration: old unchanged defaults (120/180/260) -> model-native (0/0/0)
        migrated = bool(int(get("tts/pause_defaults_migrated_v2", 0) or 0))
        if not migrated:
            if (comma, mid, end) == (120, 180, 260):
                comma, mid, end = 0, 0, 0
                self._qs.setValue("tts/pause_comma_ms", comma)
                self._qs.setValue("tts/pause_mid_ms", mid)
                self._qs.setValue("tts/pause_end_ms", end)
            self._qs.setValue("tts/pause_defaults_migrated_v2", 1)

        return AdvancedTtsSettings(
            punctuation_pause_comma_ms=comma,
            punctuation_pause_mid_ms=mid,
            punctuation_pause_end_ms=end,
            srt_overflow_policy=policy,
        )

    def save_advanced_tts(self, settings: AdvancedTtsSettings) -> None:
        self._qs.setValue("tts/pause_comma_ms", int(settings.punctuation_pause_comma_ms))
        self._qs.setValue("tts/pause_mid_ms", int(settings.punctuation_pause_mid_ms))
        self._qs.setValue("tts/pause_end_ms", int(settings.punctuation_pause_end_ms))
        self._qs.setValue("tts/srt_overflow_policy", settings.srt_overflow_policy)

    @staticmethod
    def default_advanced_tts() -> AdvancedTtsSettings:
        return AdvancedTtsSettings()
