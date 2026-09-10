#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OmniVoice Cloner — Secure Entry Point.
This file wraps main.py with anti-debug, integrity checks, and license gate.
Used by PyInstaller as the actual entry point for distribution builds.
"""
from __future__ import annotations

import hashlib
import io
import logging
import os
import sys
import time

def _setup_utf8_streams() -> None:
    """Ensure sys.stdout and sys.stderr use UTF-8 encoding with character replacement to prevent UnicodeEncodeError in GUI executables."""
    os.environ["PYTHONIOENCODING"] = "utf-8"
    os.environ["PYTHONUTF8"] = "1"

    class NullStream(io.TextIOBase):
        def write(self, s: str) -> int:
            return len(s) if s else 0
        def flush(self) -> None:
            pass

    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is None:
            setattr(sys, stream_name, NullStream())
        else:
            try:
                if hasattr(stream, "reconfigure"):
                    stream.reconfigure(encoding="utf-8", errors="replace")
                elif hasattr(stream, "buffer"):
                    setattr(sys, stream_name, io.TextIOWrapper(stream.buffer, encoding="utf-8", errors="replace"))
            except Exception:
                setattr(sys, stream_name, NullStream())

    # Protect logging.StreamHandler against UnicodeEncodeError & AttributeError (NoneType write)
    try:
        _orig_emit = logging.StreamHandler.emit
        def _safe_emit(self, record):
            if getattr(self, "stream", None) is None:
                self.stream = sys.stderr or NullStream()
            try:
                _orig_emit(self, record)
            except Exception:
                try:
                    msg = self.format(record)
                    safe_msg = msg.encode("ascii", errors="replace").decode("ascii")
                    if self.stream and hasattr(self.stream, "write"):
                        self.stream.write(safe_msg + "\n")
                except Exception:
                    pass
        logging.StreamHandler.emit = _safe_emit
    except Exception:
        pass

_setup_utf8_streams()


# ==============================================================================
# ANTI-DEBUG — multi-layer checks (runs before anything else)
# ==============================================================================
def _native_anti_debug() -> None:
    """Check for debugger presence using Windows native APIs."""
    if not getattr(sys, "frozen", False):
        return  # Skip in dev mode
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        ntdll = ctypes.windll.ntdll

        # Layer 1: IsDebuggerPresent
        if kernel32.IsDebuggerPresent():
            os._exit(1)

        # Layer 2: NtQueryInformationProcess (ProcessDebugPort = 7)
        try:
            debug_port = ctypes.c_ulong(0)
            status = ntdll.NtQueryInformationProcess(
                kernel32.GetCurrentProcess(),
                7,  # ProcessDebugPort
                ctypes.byref(debug_port),
                ctypes.sizeof(debug_port),
                None,
            )
            if status == 0 and debug_port.value != 0:
                os._exit(1)
        except Exception:
            pass

        # Layer 3: Timing check (debugger slows execution)
        t0 = time.perf_counter_ns()
        _ = sum(range(100000))
        elapsed_ms = (time.perf_counter_ns() - t0) / 1_000_000
        if elapsed_ms > 500:  # Should take < 10ms normally
            os._exit(1)

    except Exception:
        pass


_native_anti_debug()


# ==============================================================================
# INTEGRITY CHECK — verify critical files in _internal/ haven't been tampered
# ==============================================================================
def _verify_internal_integrity() -> bool:
    """Check SHA-256 of critical files inside _internal/ against known hashes."""
    if not getattr(sys, "frozen", False):
        return True  # Skip in dev mode

    try:
        from src.core._internal_hashes import HASHES
    except ImportError:
        return False

    if not HASHES:
        return False

    base = getattr(sys, "_MEIPASS", None)
    if not base:
        return False

    from pathlib import Path
    base_path = Path(base)

    for rel_path, expected_hash in HASHES.items():
        full_path = base_path / rel_path
        if not full_path.exists():
            return False
        actual_hash = hashlib.sha256(full_path.read_bytes()).hexdigest()
        if actual_hash != expected_hash:
            return False

    return True


if not _verify_internal_integrity():
    os._exit(1)


# ==============================================================================
# MAIN — delegate to the real main.py
# ==============================================================================
if __name__ == "__main__":
    if "--smoke-test" in sys.argv:
        print("SMOKE_TEST_OK")
        sys.exit(0)

    # Ensure ffmpeg is available (bundled via imageio-ffmpeg)
    try:
        import imageio_ffmpeg
        _ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        _ffmpeg_dir = os.path.dirname(_ffmpeg_exe)
        if _ffmpeg_dir not in os.environ.get("PATH", ""):
            os.environ["PATH"] = _ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")
        try:
            from pydub.utils import which as _which
            if not _which("ffmpeg"):
                import pydub
                pydub.AudioSegment.converter = _ffmpeg_exe
                _ffprobe = _ffmpeg_exe.replace("ffmpeg", "ffprobe")
                if os.path.exists(_ffprobe):
                    pydub.AudioSegment.ffprobe = _ffprobe
        except Exception:
            pass
    except ImportError:
        pass

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logger = logging.getLogger("omnivoice-cloner")

    from src.ui.app import create_app
    from src.ui.main_window import MainWindow

    app = create_app(sys.argv)
    logger.info("Starting %s %s", app.applicationName(), app.applicationVersion())

    # --- License Gate ---
    license_info = None
    try:
        from src.ui.dialogs.license_dialog import LicenseDialog

        dialog = LicenseDialog()

        if dialog.try_auto_verify():
            license_info = dialog.get_license_info()
            logger.info("License auto-verified from stored token")
        else:
            from PySide6.QtWidgets import QDialog
            result = dialog.exec()
            if result != QDialog.DialogCode.Accepted:
                logger.info("License dialog cancelled — exiting")
                sys.exit(0)
            license_info = dialog.get_license_info()
    except ImportError as e:
        logger.warning(f"License module not available: {e}")
    except Exception as e:
        logger.warning(f"License check error: {e}")

    # --- Start Runtime Guard ---
    try:
        from src.core.runtime_guard import get_runtime_guard
        guard = get_runtime_guard()
        guard.start()
    except Exception as e:
        logger.warning(f"RuntimeGuard start error: {e}")

    # --- Main Window ---
    window = MainWindow(license_info=license_info)
    window.show()

    logger.info("Application window shown — entering event loop")
    exit_code = app.exec()

    # Stop runtime guard
    try:
        guard.stop()
    except Exception:
        pass

    sys.exit(exit_code)
