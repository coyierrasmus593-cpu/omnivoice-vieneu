# -*- coding: utf-8 -*-
"""
Runtime Guard — background license re-verification + periodic anti-debug.
Periodically checks license validity and debugger presence during app runtime.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import time

logger = logging.getLogger(__name__)

_RE_VERIFY_INTERVAL = 3600  # 1 hour
_ANTI_DEBUG_INTERVAL = 30   # 30 seconds


# ==============================================================================
# ANTI-DEBUG — periodic check (mirrors main_secure.py logic)
# ==============================================================================
def _check_debugger() -> None:
    """Check for debugger presence using Windows native APIs. Exit if detected."""
    if not getattr(sys, "frozen", False):
        return
    try:
        import ctypes

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
                7,
                ctypes.byref(debug_port),
                ctypes.sizeof(debug_port),
                None,
            )
            if status == 0 and debug_port.value != 0:
                os._exit(1)
        except Exception:
            pass

        # Layer 3: Timing check
        t0 = time.perf_counter_ns()
        _ = sum(range(100000))
        elapsed_ms = (time.perf_counter_ns() - t0) / 1_000_000
        if elapsed_ms > 500:
            os._exit(1)

    except Exception:
        pass


class RuntimeGuard:
    """Background thread that periodically re-verifies license and checks for debuggers."""

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._verified = True

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="RuntimeGuard")
        self._thread.start()
        logger.debug("RuntimeGuard started")

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        logger.debug("RuntimeGuard stopped")

    @property
    def is_verified(self) -> bool:
        return self._verified

    def _run(self) -> None:
        elapsed = 0
        while not self._stop_event.wait(timeout=_ANTI_DEBUG_INTERVAL):
            # Anti-debug check every 30s
            _check_debugger()

            elapsed += _ANTI_DEBUG_INTERVAL
            if elapsed >= _RE_VERIFY_INTERVAL:
                # License re-verify every 1h
                try:
                    self._do_check()
                except Exception as e:
                    logger.warning(f"RuntimeGuard check error: {e}")
                elapsed = 0

    def _do_check(self) -> None:
        try:
            from src.core.license_client import get_license_manager
            mgr = get_license_manager()
            stored = mgr.load()
            if not stored:
                logger.warning("RuntimeGuard: no stored token")
                self._verified = False
                return

            result = mgr.verify(stored)
            if result.get("valid"):
                self._verified = True
                logger.debug("RuntimeGuard: license still valid")
            else:
                self._verified = False
                msg = result.get("message", "unknown")
                logger.warning(f"RuntimeGuard: license invalid — {msg}")
        except Exception as e:
            logger.warning(f"RuntimeGuard verify error: {e}")
            # Don't invalidate on network errors (offline grace)


_guard: RuntimeGuard | None = None


def get_runtime_guard() -> RuntimeGuard:
    global _guard
    if _guard is None:
        _guard = RuntimeGuard()
    return _guard
