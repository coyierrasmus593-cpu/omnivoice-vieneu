# -*- coding: utf-8 -*-
"""Audio utility functions for loading, saving, and processing audio."""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import soundfile as sf

logger = logging.getLogger(__name__)

SUPPORTED_FORMATS = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac", ".wma"}


def is_supported_audio(path: str) -> bool:
    """Check if file extension is a supported audio format."""
    return Path(path).suffix.lower() in SUPPORTED_FORMATS


def load_audio(path: str) -> tuple[np.ndarray, int]:
    """Load audio file and return (samples, sample_rate).

    Returns mono audio as 1-D numpy array (float32).
    """
    data, sr = sf.read(path, dtype="float32", always_2d=True)
    # Mix to mono if stereo
    if data.shape[1] > 1:
        data = data.mean(axis=1)
    else:
        data = data[:, 0]
    return data, sr


def save_wav(audio: np.ndarray, path: str, sample_rate: int = 24000) -> str:
    """Save numpy audio array as WAV file.

    Args:
        audio: Audio data. Shape (channels, samples) or (samples,).
        path: Output file path.
        sample_rate: Sample rate in Hz.

    Returns:
        Absolute path of saved file.
    """
    # Ensure 1-D for soundfile
    if audio.ndim == 2:
        audio = audio[0] if audio.shape[0] <= audio.shape[1] else audio[:, 0]

    out = Path(path).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(out), audio, sample_rate, subtype="PCM_16")
    logger.info("Saved WAV: %s (%.1fs)", out, len(audio) / sample_rate)
    return str(out)


def get_duration(path: str) -> float:
    """Get audio file duration in seconds."""
    info = sf.info(path)
    return info.duration


def get_duration_formatted(path: str) -> str:
    """Get audio duration as formatted string 'M:SS.s'."""
    dur = get_duration(path)
    mins = int(dur // 60)
    secs = dur % 60
    return f"{mins}:{secs:04.1f}"


def audio_to_waveform_data(
    path: str,
    num_points: int = 200,
) -> np.ndarray:
    """Load audio and downsample to fixed number of points for waveform display.

    Returns array of shape (num_points,) with values in [0, 1].
    """
    data, _sr = load_audio(path)
    data = np.abs(data)

    if len(data) == 0:
        return np.zeros(num_points)

    # Downsample by chunking
    chunk_size = max(1, len(data) // num_points)
    chunks = len(data) // chunk_size
    trimmed = data[: chunks * chunk_size].reshape(chunks, chunk_size)
    envelope = trimmed.max(axis=1)

    # Normalize to [0, 1]
    peak = envelope.max()
    if peak > 0:
        envelope = envelope / peak

    # Pad or trim to exact num_points
    if len(envelope) < num_points:
        envelope = np.pad(envelope, (0, num_points - len(envelope)))
    else:
        envelope = envelope[:num_points]

    return envelope


# ------------------------------------------------------------------
# Multi-format export
# ------------------------------------------------------------------
EXPORT_FORMATS = {
    ".wav": "WAV (Lossless)",
    ".mp3": "MP3 (Compressed)",
    ".flac": "FLAC (Lossless Compressed)",
    ".ogg": "OGG Vorbis",
}


def export_audio(
    source_path: str,
    output_path: str,
    output_format: str = ".wav",
    sample_rate: int = 24000,
    bitrate: str = "192k",
) -> str:
    """Export audio to various formats using pydub/ffmpeg.

    Args:
        source_path: Path to source WAV file.
        output_path: Path for output file.
        output_format: Target format extension (.wav, .mp3, .flac, .ogg).
        sample_rate: Output sample rate.
        bitrate: Bitrate for lossy formats (mp3, ogg).

    Returns:
        Absolute path of exported file.
    """
    from pydub import AudioSegment

    out = Path(output_path).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    audio = AudioSegment.from_file(source_path)
    audio = audio.set_frame_rate(sample_rate)

    fmt = output_format.lstrip(".").lower()
    export_kwargs = {}
    if fmt in ("mp3", "ogg"):
        export_kwargs["bitrate"] = bitrate
    if fmt == "ogg":
        export_kwargs["codec"] = "libvorbis"

    audio.export(str(out), format=fmt, **export_kwargs)
    logger.info("Exported %s: %s", fmt.upper(), out)
    return str(out)


def trim_audio_segment(
    source_path: str,
    output_path: str,
    start_sec: float,
    max_duration_sec: float = 10.0,
) -> str:
    """Trim an audio segment and export to WAV.

    Args:
        source_path: Input audio path.
        output_path: Trimmed output file path.
        start_sec: Start offset in seconds.
        max_duration_sec: Maximum segment duration in seconds.

    Returns:
        Absolute output path.
    """
    from pydub import AudioSegment

    if start_sec < 0:
        raise ValueError("start_sec phải >= 0")
    if max_duration_sec <= 0:
        raise ValueError("max_duration_sec phải > 0")

    audio = AudioSegment.from_file(source_path)
    if len(audio) <= 0:
        raise ValueError("Audio rỗng hoặc không hợp lệ")

    start_ms = int(start_sec * 1000)
    if start_ms >= len(audio):
        raise ValueError("Điểm bắt đầu vượt quá thời lượng audio")

    end_ms = min(len(audio), start_ms + int(max_duration_sec * 1000))
    if end_ms <= start_ms:
        raise ValueError("Khoảng cắt không hợp lệ")

    segment = audio[start_ms:end_ms]

    out = Path(output_path).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    segment.export(str(out), format="wav")
    logger.info("Trimmed audio: %s (start=%.2fs, duration=%.2fs)", out, start_sec, (end_ms - start_ms) / 1000.0)
    return str(out)


def join_audio_files(
    input_paths: list[str],
    output_path: str,
    output_format: str = ".wav",
    sample_rate: int = 24000,
    bitrate: str = "192k",
) -> str:
    """Join multiple audio files into one output file.

    Args:
        input_paths: Ordered list of audio file paths.
        output_path: Output file path.
        output_format: Target format extension.

    Returns:
        Absolute output path.
    """
    from pydub import AudioSegment

    if not input_paths:
        raise ValueError("Danh sách file audio trống")

    merged: AudioSegment | None = None
    for p in input_paths:
        audio = AudioSegment.from_file(p)
        audio = audio.set_frame_rate(sample_rate).set_channels(1)
        if merged is None:
            merged = audio
        else:
            merged = merged.append(audio, crossfade=0)

    if merged is None:
        raise ValueError("Không thể merge audio")

    fmt = output_format.lstrip(".").lower()
    out = Path(output_path).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    export_kwargs = {}
    if fmt in ("mp3", "ogg"):
        export_kwargs["bitrate"] = bitrate
    if fmt == "ogg":
        export_kwargs["codec"] = "libvorbis"

    merged.export(str(out), format=fmt, **export_kwargs)
    logger.info("Joined %d audio files -> %s", len(input_paths), out)
    return str(out)
