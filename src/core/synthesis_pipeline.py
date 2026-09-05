# -*- coding: utf-8 -*-
"""Higher-level synthesis pipeline helpers for text and SRT workflows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Callable

import numpy as np

from src.core.engine import GENERATION_CANCELLED
from src.core.synthesis_text import build_synthesis_segments


@dataclass
class SrtCue:
    index: int
    start_ms: int
    end_ms: int
    text: str


def _clamp_speed(speed: float, min_speed: float = 0.5, max_speed: float = 2.5) -> float:
    return max(min_speed, min(max_speed, speed))


def _parse_srt_timestamp_ms(raw: str) -> int:
    m = re.match(r"^(\d{2}):(\d{2}):(\d{2})[,\.](\d{3})$", raw.strip())
    if not m:
        raise ValueError(f"Timestamp SRT không hợp lệ: {raw}")

    hh = int(m.group(1))
    mm = int(m.group(2))
    ss = int(m.group(3))
    ms = int(m.group(4))
    return ((hh * 60 + mm) * 60 + ss) * 1000 + ms


def parse_srt_file(path: str) -> list[SrtCue]:
    src = Path(path)
    if not src.exists():
        raise FileNotFoundError(f"Không tìm thấy file SRT: {src}")

    content = src.read_text(encoding="utf-8-sig", errors="ignore")
    blocks = re.split(r"\r?\n\r?\n+", content.strip())

    cues: list[SrtCue] = []
    for block in blocks:
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if len(lines) < 2:
            continue

        cue_idx = 0
        timing_line = lines[0]
        text_start = 1

        if re.match(r"^\d+$", lines[0]):
            cue_idx = int(lines[0])
            timing_line = lines[1]
            text_start = 2

        m = re.match(r"^(.+?)\s*-->\s*(.+?)(?:\s+.*)?$", timing_line)
        if not m:
            continue

        start_ms = _parse_srt_timestamp_ms(m.group(1))
        end_ms = _parse_srt_timestamp_ms(m.group(2))
        if end_ms <= start_ms:
            continue

        text = " ".join(lines[text_start:]).strip()
        if not text:
            continue

        if cue_idx <= 0:
            cue_idx = len(cues) + 1

        cues.append(SrtCue(index=cue_idx, start_ms=start_ms, end_ms=end_ms, text=text))

    if not cues:
        raise ValueError("File SRT không có cue hợp lệ")

    cues.sort(key=lambda c: c.start_ms)
    return cues


def synthesize_text_with_controls(
    engine,
    text: str,
    voice_prompt,
    base_speed: float,
    num_step: int,
    guidance_scale: float,
    pause_comma_ms: int,
    pause_mid_ms: int,
    pause_end_ms: int,
    should_cancel: Callable[[], bool] | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> tuple[np.ndarray, int]:
    segments = build_synthesis_segments(
        text=text,
        punctuation_pause_comma_ms=pause_comma_ms,
        punctuation_pause_mid_ms=pause_mid_ms,
        punctuation_pause_end_ms=pause_end_ms,
    )
    if not segments:
        raise ValueError("Không có nội dung để tạo giọng nói")

    chunks: list[np.ndarray] = []
    sample_rate = 24000

    text_count = sum(1 for s in segments if s.text)
    text_idx = 0

    for seg in segments:
        if should_cancel and should_cancel():
            raise RuntimeError(GENERATION_CANCELLED)

        if seg.text:
            text_idx += 1
            if on_progress:
                on_progress(f"Synthesizing segment {text_idx}/{text_count}...")

            speed = _clamp_speed(base_speed * seg.speed_multiplier)
            audio_np, sample_rate = engine.generate(
                text=seg.text,
                voice_prompt=voice_prompt,
                speed=speed,
                num_step=num_step,
                guidance_scale=guidance_scale,
                should_cancel=should_cancel,
            )
            chunks.append(audio_np.astype(np.float32))

        if seg.pause_after_ms > 0:
            pause_samples = int(sample_rate * (seg.pause_after_ms / 1000.0))
            if pause_samples > 0:
                chunks.append(np.zeros(pause_samples, dtype=np.float32))

    if not chunks:
        raise ValueError("Không tạo được audio từ nội dung đã nhập")

    if len(chunks) == 1:
        return chunks[0], sample_rate
    return np.concatenate(chunks, axis=0), sample_rate


def synthesize_srt_timeline(
    engine,
    srt_path: str,
    voice_prompt,
    base_speed: float,
    num_step: int,
    guidance_scale: float,
    pause_comma_ms: int,
    pause_mid_ms: int,
    pause_end_ms: int,
    overflow_policy: str,
    should_cancel: Callable[[], bool] | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> tuple[np.ndarray, int, list[str]]:
    cues = parse_srt_file(srt_path)
    warnings: list[str] = []
    pieces: list[np.ndarray] = []

    sample_rate = 24000
    cursor_ms = 0

    for i, cue in enumerate(cues, start=1):
        if should_cancel and should_cancel():
            raise RuntimeError(GENERATION_CANCELLED)

        if on_progress:
            on_progress(f"SRT cue {i}/{len(cues)}")

        # Respect timeline gap
        if cue.start_ms > cursor_ms:
            gap_ms = cue.start_ms - cursor_ms
            gap_samples = int(sample_rate * (gap_ms / 1000.0))
            if gap_samples > 0:
                pieces.append(np.zeros(gap_samples, dtype=np.float32))
            cursor_ms = cue.start_ms
        elif cue.start_ms < cursor_ms:
            warnings.append(
                f"Cue {cue.index} bị overlap timeline ({cue.start_ms}ms < {cursor_ms}ms)."
            )

        slot_ms = cue.end_ms - cue.start_ms

        audio_np, sample_rate = synthesize_text_with_controls(
            engine=engine,
            text=cue.text,
            voice_prompt=voice_prompt,
            base_speed=base_speed,
            num_step=num_step,
            guidance_scale=guidance_scale,
            pause_comma_ms=pause_comma_ms,
            pause_mid_ms=pause_mid_ms,
            pause_end_ms=pause_end_ms,
            should_cancel=should_cancel,
            on_progress=on_progress,
        )

        audio_ms = int(round(len(audio_np) * 1000.0 / sample_rate))

        if audio_ms > slot_ms and overflow_policy == "speed_up":
            speed_factor = audio_ms / max(1, slot_ms)
            boosted_speed = _clamp_speed(base_speed * speed_factor)
            if boosted_speed > base_speed + 1e-6:
                audio_np, sample_rate = synthesize_text_with_controls(
                    engine=engine,
                    text=cue.text,
                    voice_prompt=voice_prompt,
                    base_speed=boosted_speed,
                    num_step=num_step,
                    guidance_scale=guidance_scale,
                    pause_comma_ms=pause_comma_ms,
                    pause_mid_ms=pause_mid_ms,
                    pause_end_ms=pause_end_ms,
                    should_cancel=should_cancel,
                    on_progress=on_progress,
                )
                audio_ms = int(round(len(audio_np) * 1000.0 / sample_rate))

        if audio_ms > slot_ms:
            warnings.append(
                f"Cue {cue.index} dài hơn slot ({audio_ms}ms > {slot_ms}ms)."
            )

        pieces.append(audio_np.astype(np.float32))
        cursor_ms += audio_ms

        # Pad to end if shorter than slot
        if cursor_ms < cue.end_ms:
            pad_ms = cue.end_ms - cursor_ms
            pad_samples = int(sample_rate * (pad_ms / 1000.0))
            if pad_samples > 0:
                pieces.append(np.zeros(pad_samples, dtype=np.float32))
            cursor_ms = cue.end_ms

    if not pieces:
        raise ValueError("Không tạo được audio từ SRT")

    if len(pieces) == 1:
        return pieces[0], sample_rate, warnings
    return np.concatenate(pieces, axis=0), sample_rate, warnings
