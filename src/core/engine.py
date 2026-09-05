# -*- coding: utf-8 -*-
"""VoiceEngine — Wrapper around OmniVoice for desktop app integration.

Responsibilities:
- GPU/CPU auto-detection
- Model loading with progress callbacks
- Voice clone prompt creation
- Speech generation
- Resource cleanup
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import torch
import torchaudio

logger = logging.getLogger(__name__)

# Model identifier on HuggingFace Hub
DEFAULT_MODEL_ID = "k2-fsa/OmniVoice"
BUNDLED_MODEL_DIRNAME = "omnivoice_model"
BUNDLED_PROMPT_CACHE_DIRNAME = "omnivoice_prompt_cache"
APP_DATA_DIR = Path.home() / ".omnivoice-cloner"
PROMPT_CACHE_DIRNAME = "prompt_cache"
PROMPT_CACHE_SCHEMA_VERSION = 1
SAMPLE_RATE = 24000
GENERATION_CANCELLED = "__GENERATION_CANCELLED__"


def _is_truthy_env(name: str) -> bool:
    value = os.getenv(name, "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _model_dir_candidates() -> list[Path]:
    candidates: list[Path] = []

    if getattr(sys, "frozen", False):
        # Typical PyInstaller onedir layout
        exe_dir = Path(sys.executable).resolve().parent
        candidates.append(exe_dir / BUNDLED_MODEL_DIRNAME)

        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            meipass_path = Path(meipass)
            candidates.append(meipass_path / BUNDLED_MODEL_DIRNAME)
            candidates.append(meipass_path.parent / BUNDLED_MODEL_DIRNAME)

    # Dev/runtime local candidates
    repo_root = Path(__file__).resolve().parents[2]
    candidates.append(repo_root / BUNDLED_MODEL_DIRNAME)
    candidates.append(Path.cwd() / BUNDLED_MODEL_DIRNAME)

    # de-duplicate while preserving order
    unique: list[Path] = []
    seen: set[str] = set()
    for p in candidates:
        key = str(p)
        if key in seen:
            continue
        seen.add(key)
        unique.append(p)
    return unique


def _resolve_model_source(model_id: str) -> str:
    """Resolve model source path with offline-first behavior."""
    if model_id != DEFAULT_MODEL_ID:
        logger.info("Using custom model ID from HuggingFace Hub: %s", model_id)
        return model_id

    for candidate in _model_dir_candidates():
        if candidate.is_dir() and (candidate / "model.safetensors").exists():
            logger.info("Using local OmniVoice model: %s", candidate)
            return str(candidate)

    if getattr(sys, "frozen", False):
        raise RuntimeError(
            "Bundled OmniVoice model not found. "
            "Expected 'omnivoice_model/model.safetensors' next to the app binary."
        )

    if _is_truthy_env("OMNIVOICE_ALLOW_HUB_FALLBACK"):
        logger.warning(
            "Local OmniVoice model not found in dev; "
            "OMNIVOICE_ALLOW_HUB_FALLBACK=1 so fallback to Hub id: %s",
            model_id,
        )
        return model_id

    raise RuntimeError(
        "Local OmniVoice model not found in dev mode. "
        "Put model at './omnivoice_model/model.safetensors' "
        "or set OMNIVOICE_ALLOW_HUB_FALLBACK=1 to allow internet fallback."
    )


class VoiceEngine:
    """High-level wrapper around OmniVoice model."""

    def __init__(self, prompt_cache_dir: str | Path | None = None) -> None:
        self.model = None
        self.device: str = "cpu"
        self.dtype = torch.float32
        self.is_loaded: bool = False
        self._current_prompt = None  # cached VoiceClonePrompt
        if prompt_cache_dir is None:
            self._prompt_cache_dir = APP_DATA_DIR / PROMPT_CACHE_DIRNAME
        else:
            self._prompt_cache_dir = Path(prompt_cache_dir)
        self._prompt_cache_ready = False
        self._asr_enabled: bool = False
        self.model_id = DEFAULT_MODEL_ID

    # ------------------------------------------------------------------
    # Device detection
    # ------------------------------------------------------------------
    @property
    def asr_enabled(self) -> bool:
        return self._asr_enabled

    def detect_device(self) -> dict:
        """Detect available compute device.

        Returns dict with keys:
            device: str — 'cuda:0' or 'cpu'
            gpu_name: str | None
            vram_gb: float | None
            cpu_reason: str | None
        """
        info = {"device": "cpu", "gpu_name": None, "vram_gb": None, "cpu_reason": None}

        if torch.cuda.is_available():
            info["device"] = "cuda:0"
            info["gpu_name"] = torch.cuda.get_device_name(0)
            props = torch.cuda.get_device_properties(0)
            vram = getattr(props, "total_memory", None) or getattr(props, "total_mem", 0)
            info["vram_gb"] = round(vram / (1024**3), 1)
            logger.info("GPU detected: %s (%.1f GB)", info["gpu_name"], info["vram_gb"])
        else:
            reason = self._diagnose_no_cuda()
            info["cpu_reason"] = reason
            logger.info("No CUDA GPU detected — will use CPU (slower inference). Reason: %s", reason)

        return info

    @staticmethod
    def _diagnose_no_cuda() -> str:
        """Best-effort diagnosis for CPU fallback."""
        try:
            import subprocess

            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                gpu_names = result.stdout.strip()
                return (
                    f"Phát hiện GPU NVIDIA ({gpu_names}) nhưng PyTorch CUDA không khả dụng. "
                    "Có thể cần cài lại PyTorch bản hỗ trợ CUDA hoặc cập nhật driver NVIDIA."
                )
        except FileNotFoundError:
            pass
        except Exception:
            pass

        return (
            "Máy không có GPU NVIDIA hỗ trợ CUDA. GPU Intel/AMD hiện chưa được hỗ trợ. "
            "App sẽ chạy trên CPU (chậm hơn)."
        )

    # ------------------------------------------------------------------
    # Model loading
    # ------------------------------------------------------------------
    def load_model(
        self,
        model_id: str = DEFAULT_MODEL_ID,
        device: Optional[str] = None,
        on_progress: Optional[Callable[[str], None]] = None,
        load_asr: bool = True,
    ) -> dict:
        """Load OmniVoice model.

        Args:
            model_id: HuggingFace model identifier or local path.
            device: Force device ('cuda:0' or 'cpu'). Auto-detect if None.
            on_progress: Callback receiving status messages.

        Returns:
            Device info dict from detect_device().

        Raises:
            RuntimeError: If model fails to load.
        """
        def _emit(msg: str) -> None:
            logger.info(msg)
            if on_progress:
                on_progress(msg)

        self.model_id = model_id

        # Step 1: detect device
        _emit("Detecting hardware...")
        dev_info = self.detect_device()
        self.device = device or dev_info["device"]
        self.dtype = torch.float16 if "cuda" in self.device else torch.float32

        is_vieneu = "vieneu" in model_id.lower() or "pnnbao-ump" in model_id.lower()
        if is_vieneu:
            _emit("Importing VieNeu...")
            from vieneu import Vieneu
            _emit(f"Loading VieNeu model '{model_id}' on {self.device}...")
            self.model = Vieneu(mode="v3turbo")
            self._asr_enabled = False
            self.is_loaded = True
            _emit("Model loaded successfully!")
            return dev_info

        # Step 2: import OmniVoice (lazy — heavy import)
        _emit("Importing OmniVoice...")
        from omnivoice import OmniVoice  # noqa: F811

        resolved_model = _resolve_model_source(model_id)

        # Step 3: load model
        _emit(f"Loading model '{resolved_model}' on {self.device} ({self.dtype})...")
        try:
            self.model = OmniVoice.from_pretrained(
                resolved_model,
                device_map=self.device,
                dtype=self.dtype,
                load_asr=load_asr,  # enable auto-transcription
            )
            self._asr_enabled = load_asr
        except RuntimeError as exc:
            # GPU OOM → fallback to CPU
            if "CUDA" in str(exc) or "out of memory" in str(exc):
                _emit("GPU out of memory — falling back to CPU...")
                self.device = "cpu"
                self.dtype = torch.float32
                self.model = OmniVoice.from_pretrained(
                    resolved_model,
                    device_map="cpu",
                    dtype=torch.float32,
                    load_asr=load_asr,
                )
                self._asr_enabled = load_asr
            else:
                raise
        except Exception:
            if load_asr:
                _emit("ASR init failed — retry loading model without ASR...")
                self.model = OmniVoice.from_pretrained(
                    resolved_model,
                    device_map=self.device,
                    dtype=self.dtype,
                    load_asr=False,
                )
                self._asr_enabled = False
            else:
                raise

        self.is_loaded = True

        # Diagnostic: verify model is actually on the expected device
        try:
            first_param = next(self.model.parameters())
            actual_device = str(first_param.device)
            logger.info("Model device verification: expected=%s, actual=%s", self.device, actual_device)
            if self.device != "cpu" and "cuda" not in actual_device:
                logger.warning(
                    "Model is NOT on GPU despite device_map=%s! "
                    "Manually moving model to %s...",
                    self.device, self.device,
                )
                self.model = self.model.to(self.device)
                logger.info("Model moved to %s", self.device)
        except StopIteration:
            logger.warning("Model has no parameters — cannot verify device placement.")

        _emit("Model loaded successfully!")
        return dev_info

    # ------------------------------------------------------------------
    # Prompt cache
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_ref_text(ref_text: Optional[str]) -> str:
        return ref_text.strip() if ref_text and ref_text.strip() else ""

    def _resolve_bundled_prompt_cache_dir(self) -> Optional[Path]:
        candidates: list[Path] = []

        if getattr(sys, "frozen", False):
            exe_dir = Path(sys.executable).resolve().parent
            candidates.append(exe_dir / BUNDLED_PROMPT_CACHE_DIRNAME)

            meipass = getattr(sys, "_MEIPASS", None)
            if meipass:
                meipass_path = Path(meipass)
                candidates.append(meipass_path / BUNDLED_PROMPT_CACHE_DIRNAME)
                candidates.append(meipass_path.parent / BUNDLED_PROMPT_CACHE_DIRNAME)
        else:
            candidates.append(Path(__file__).parent.parent.parent / BUNDLED_PROMPT_CACHE_DIRNAME)

        for candidate in candidates:
            if candidate.exists() and candidate.is_dir():
                return candidate
        return None

    def _ensure_prompt_cache_ready(self) -> None:
        if self._prompt_cache_ready:
            return

        try:
            self._prompt_cache_dir.mkdir(parents=True, exist_ok=True)

            bundled_dir = self._resolve_bundled_prompt_cache_dir()
            if bundled_dir is not None:
                copied = 0
                for src in bundled_dir.rglob("*"):
                    if not src.is_file():
                        continue
                    rel = src.relative_to(bundled_dir)
                    dst = self._prompt_cache_dir / rel
                    if dst.exists():
                        continue
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
                    copied += 1

                if copied > 0:
                    logger.info("Copied %d seeded prompt cache file(s)", copied)
        except Exception as e:
            logger.warning("Prompt cache initialization failed: %s", e)
        finally:
            self._prompt_cache_ready = True

    @staticmethod
    def _sha256_file(path: Path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()

    def _build_prompt_cache_key(self, audio_path: str, ref_text: Optional[str]) -> tuple[str, dict]:
        audio_file = Path(audio_path).expanduser().resolve()
        stat = audio_file.stat()
        audio_sha256 = self._sha256_file(audio_file)

        payload = {
            "schema_version": PROMPT_CACHE_SCHEMA_VERSION,
            "model_id": DEFAULT_MODEL_ID,
            "audio_sha256": audio_sha256,
            "audio_size": stat.st_size,
            "ref_text": self._normalize_ref_text(ref_text),
        }
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        key = hashlib.sha256(raw).hexdigest()
        return key, payload

    def _prompt_cache_paths(self, key: str) -> tuple[Path, Path]:
        base = self._prompt_cache_dir / key
        return base.with_suffix(".pt"), base.with_suffix(".json")

    def _load_prompt_cache(self, key: str):
        self._ensure_prompt_cache_ready()
        prompt_path, meta_path = self._prompt_cache_paths(key)
        if not prompt_path.exists():
            return None

        try:
            try:
                prompt = torch.load(str(prompt_path), map_location=self.device, weights_only=False)
            except TypeError:
                prompt = torch.load(str(prompt_path), map_location=self.device)

            if meta_path.exists():
                try:
                    json.loads(meta_path.read_text(encoding="utf-8"))
                except Exception:
                    logger.warning("Prompt cache metadata is invalid: %s", meta_path)

            return prompt
        except Exception as e:
            logger.warning("Failed to load prompt cache %s: %s", prompt_path, e)
            prompt_path.unlink(missing_ok=True)
            meta_path.unlink(missing_ok=True)
            return None

    def _save_prompt_cache(self, key: str, cache_payload: dict, prompt) -> None:
        self._ensure_prompt_cache_ready()
        prompt_path, meta_path = self._prompt_cache_paths(key)
        tmp_prompt = prompt_path.with_suffix(".pt.tmp")
        tmp_meta = meta_path.with_suffix(".json.tmp")

        metadata = {
            **cache_payload,
            "saved_at": time.time(),
            "device": self.device,
            "dtype": str(self.dtype),
        }

        try:
            torch.save(prompt, str(tmp_prompt))
            tmp_meta.write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            tmp_prompt.replace(prompt_path)
            tmp_meta.replace(meta_path)
            logger.info("Saved voice prompt cache: %s", prompt_path.name)
        except Exception as e:
            logger.warning("Failed to save prompt cache %s: %s", prompt_path, e)
            tmp_prompt.unlink(missing_ok=True)
            tmp_meta.unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # Voice clone prompt
    # ------------------------------------------------------------------
    def create_voice_prompt(
        self,
        audio_path: str,
        ref_text: Optional[str] = None,
    ):
        """Create a reusable VoiceClonePrompt from reference audio.

        Bypasses omnivoice's internal audio loader (which depends on
        torchcodec/ffmpeg) by pre-loading with soundfile + torchaudio resample.

        Args:
            audio_path: Path to reference audio file.
            ref_text: Transcript of reference audio. If None, auto-transcribed.

        Returns:
            VoiceClonePrompt object (can be reused for multiple generations).
        """
        if not self.is_loaded:
            raise RuntimeError("Model not loaded. Call load_model() first.")

        import soundfile as sf

        cache_key, cache_payload = self._build_prompt_cache_key(audio_path, ref_text)
        cached_prompt = self._load_prompt_cache(cache_key)
        if cached_prompt is not None:
            logger.info(
                "Voice prompt cache hit: %s prompt_obj=%s source=%s ref_text=%s",
                cache_key[:12],
                hex(id(cached_prompt)),
                audio_path,
                "yes" if ref_text and ref_text.strip() else "no",
            )
            self._current_prompt = cached_prompt
            return cached_prompt

        logger.info("Voice prompt cache miss: %s", cache_key[:12])
        logger.info("Creating voice prompt from: %s", audio_path)

        # Pre-load audio with soundfile (reliable cross-platform, no ffmpeg needed)
        data, sr = sf.read(audio_path, dtype="float32", always_2d=True)
        if data.shape[1] > 1:
            data = data.mean(axis=1)
        else:
            data = data[:, 0]

        waveform = torch.from_numpy(data).unsqueeze(0)  # (1, T)

        # Resample to 16kHz if needed (OmniVoice expects 16kHz for prompt)
        if sr != 16000:
            waveform = torchaudio.functional.resample(waveform, sr, 16000)
            sr = 16000

        # Move tensor to model device for GPU inference
        if self.device != "cpu":
            waveform = waveform.to(self.device)

        prompt = self.model.create_voice_clone_prompt(
            ref_audio=(waveform, sr),
            ref_text=ref_text if ref_text and ref_text.strip() else None,
            preprocess_prompt=True,
        )
        logger.info(
            "Voice prompt created prompt_obj=%s source=%s ref_text=%s",
            hex(id(prompt)),
            audio_path,
            "yes" if ref_text and ref_text.strip() else "no",
        )
        self._save_prompt_cache(cache_key, cache_payload, prompt)
        self._current_prompt = prompt
        return prompt

    # ------------------------------------------------------------------
    # Text chunking for long inputs
    # ------------------------------------------------------------------
    MAX_CHUNK_CHARS = 200  # safe limit for diffusion TTS models

    @staticmethod
    def _split_text_into_chunks(text: str, max_chars: int = 200) -> list[str]:
        """Split text into chunks at sentence boundaries.

        Vietnamese text uses the same sentence-ending punctuation as
        Western languages (.!?;) plus common comma-separated clauses.
        We split at sentence boundaries first, then merge short
        sentences into chunks up to *max_chars*.
        """
        # Split at sentence boundaries (keep the delimiter)
        sentences = re.split(r'(?<=[.!?;…])\s+', text.strip())

        # Further split any sentence that's still too long at commas
        refined: list[str] = []
        for sent in sentences:
            if len(sent) <= max_chars:
                refined.append(sent)
            else:
                # Split at commas
                parts = re.split(r'(?<=,)\s+', sent)
                refined.extend(parts)

        # Merge small segments into chunks up to max_chars
        chunks: list[str] = []
        current = ""
        for seg in refined:
            candidate = (current + " " + seg).strip() if current else seg
            if len(candidate) <= max_chars:
                current = candidate
            else:
                if current:
                    chunks.append(current)
                current = seg
        if current:
            chunks.append(current)

        return chunks if chunks else [text]

    # ------------------------------------------------------------------
    # Speech generation
    # ------------------------------------------------------------------
    def generate(
        self,
        text: str,
        voice_prompt=None,
        speed: float = 1.0,
        num_step: int = 32,
        guidance_scale: float = 2.0,
        on_chunk_progress: Optional[Callable[[int, int], None]] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
    ) -> tuple[np.ndarray, int]:
        """Generate speech from text.

        Args:
            text: Text to synthesize.
            voice_prompt: VoiceClonePrompt (uses cached prompt if None).
            speed: Speaking speed factor (0.5–2.0).
            num_step: Diffusion steps (8/16/32). Higher = better quality.
            guidance_scale: Classifier-free guidance scale.
            on_chunk_progress: Optional callback(current_chunk, total_chunks).

        Returns:
            Tuple of (audio_numpy_array, sample_rate).

        Raises:
            RuntimeError: GENERATION_CANCELLED when user cancels generation.
        """
        if not self.is_loaded:
            raise RuntimeError("Model not loaded. Call load_model() first.")

        prompt = voice_prompt or self._current_prompt
        using_fallback_prompt = voice_prompt is None and self._current_prompt is not None

        # Split long text into manageable chunks
        chunks = self._split_text_into_chunks(text, self.MAX_CHUNK_CHARS)
        total = len(chunks)

        logger.info(
            "Generating speech: %d chars → %d chunk(s), speed=%.1f, steps=%d, prompt=%s, prompt_obj=%s, fallback_current_prompt=%s",
            len(text), total, speed, num_step,
            "yes" if prompt else "no",
            hex(id(prompt)) if prompt is not None else "None",
            using_fallback_prompt,
        )

        all_audio: list[np.ndarray] = []

        for i, chunk in enumerate(chunks):
            if should_cancel and should_cancel():
                raise RuntimeError(GENERATION_CANCELLED)
            logger.info("Chunk %d/%d: %d chars", i + 1, total, len(chunk))
            if on_chunk_progress:
                on_chunk_progress(i + 1, total)

            # Build generation config with correct API
            try:
                from omnivoice.models.omnivoice import OmniVoiceGenerationConfig
                gen_config = OmniVoiceGenerationConfig(
                    num_step=num_step,
                    guidance_scale=guidance_scale,
                )
                kwargs = {
                    "text": chunk,
                    "speed": speed,
                    "generation_config": gen_config,
                }
            except ImportError:
                # Fallback for older versions
                kwargs = {
                    "text": chunk,
                    "speed": speed,
                    "num_step": num_step,
                    "guidance_scale": guidance_scale,
                }
            if hasattr(self.model, "infer"):
                # VieNeu generation
                audio_np = self.model.infer(
                    text=chunk,
                    ref_audio=prompt.audio_path if prompt else None,
                )
                if isinstance(audio_np, torch.Tensor):
                    audio_np = audio_np.cpu().squeeze().numpy().astype(np.float32)
                all_audio.append(audio_np)
                continue

            if prompt is not None:
                kwargs["voice_clone_prompt"] = prompt

            audio_tensors = self.model.generate(**kwargs)

            # Convert first result to 1-D numpy array
            # OmniVoice returns list of tensors or numpy arrays
            audio_out = audio_tensors[0]
            if isinstance(audio_out, torch.Tensor):
                audio_np = audio_out.cpu().squeeze().numpy().astype(np.float32)
            else:
                import numpy as np
                audio_np = np.squeeze(audio_out).astype(np.float32)
            all_audio.append(audio_np)

        # Concatenate all chunks
        if len(all_audio) == 1:
            result = all_audio[0]
        else:
            result = np.concatenate(all_audio, axis=0)

        is_vieneu = hasattr(self.model, "infer")
        return result, 48000 if is_vieneu else SAMPLE_RATE

    # ------------------------------------------------------------------
    # Transcription
    # ------------------------------------------------------------------
    def transcribe(self, audio_path: str) -> str:
        """Transcribe audio file using built-in Whisper ASR.

        Pre-loads audio with soundfile to bypass torchcodec/ffmpeg issues.

        Args:
            audio_path: Path to audio file.

        Returns:
            Transcription text.
        """
        if not self.is_loaded:
            raise RuntimeError("Model not loaded. Call load_model() first.")
        if not self._asr_enabled:
            raise RuntimeError("ASR không khả dụng trong phiên tải model hiện tại.")

        import soundfile as sf

        # Pre-load to bypass omnivoice's internal loader
        data, sr = sf.read(audio_path, dtype="float32", always_2d=True)
        if data.shape[1] > 1:
            data = data.mean(axis=1)
        else:
            data = data[:, 0]

        waveform = torch.from_numpy(data).unsqueeze(0)
        if sr != 16000:
            waveform = torchaudio.functional.resample(waveform, sr, 16000)
            sr = 16000

        # Move tensor to model device for GPU inference
        if self.device != "cpu":
            waveform = waveform.to(self.device)

        return self.model.transcribe((waveform, sr))

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------
    def unload_model(self) -> None:
        """Unload model and free GPU memory."""
        if self.model is not None:
            del self.model
            self.model = None
            self.is_loaded = False
            self._current_prompt = None
            self._asr_enabled = False

            if torch.cuda.is_available():
                torch.cuda.empty_cache()

            logger.info("Model unloaded, GPU memory freed.")
