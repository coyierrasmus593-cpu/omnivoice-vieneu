#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OmniVoice Cloner — Desktop Voice Cloning & TTS Application.

Entry point: python main.py
"""

import io
import logging
import os
import sys

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

# Ensure ffmpeg is available (bundled via imageio-ffmpeg)
try:
    import imageio_ffmpeg
    _ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    _ffmpeg_dir = os.path.dirname(_ffmpeg_exe)
    if _ffmpeg_dir not in os.environ.get("PATH", ""):
        os.environ["PATH"] = _ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")
    # Also configure pydub to use this ffmpeg
    try:
        from pydub.utils import which as _which
        if not _which("ffmpeg"):
            import pydub
            pydub.AudioSegment.converter = _ffmpeg_exe
            # ffprobe might have a different name/path
            _ffprobe = _ffmpeg_exe.replace("ffmpeg", "ffprobe")
            if os.path.exists(_ffprobe):
                pydub.AudioSegment.ffprobe = _ffprobe
    except Exception:
        pass
except ImportError:
    pass  # ffmpeg must be in system PATH

# Configure logging before any imports
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("omnivoice-cloner")


def main() -> int:
    """Application entry point."""
    from src.ui.app import create_app
    from src.ui.main_window import MainWindow

    app = create_app(sys.argv)
    logger.info("Starting %s %s", app.applicationName(), app.applicationVersion())

    # --- License Gate ---
    license_info = None
    try:
        from src.ui.dialogs.license_dialog import LicenseDialog

        dialog = LicenseDialog()

        # Try auto-verify stored token first
        if dialog.try_auto_verify():
            license_info = dialog.get_license_info()
            logger.info("License auto-verified from stored token")
        else:
            # Show license dialog (blocking)
            from PySide6.QtWidgets import QDialog
            result = dialog.exec()
            if result != QDialog.DialogCode.Accepted:
                logger.info("License dialog cancelled — exiting")
                return 0
            license_info = dialog.get_license_info()
    except ImportError as e:
        logger.warning(f"License module not available: {e} — running without license")
    except Exception as e:
        logger.warning(f"License check error: {e} — running without license")

    # --- Main Window ---
    window = MainWindow(license_info=license_info)
    window.show()

    logger.info("Application window shown — entering event loop")
    return app.exec()


if __name__ == "__main__":
    if "--smoke-test" in sys.argv:
        print("SMOKE_TEST_OK")
        sys.exit(0)
    sys.exit(main())
