# -*- coding: utf-8 -*-
"""QApplication factory — sets up the app instance, theme, and font."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont, QIcon


APP_DISPLAY_NAME = "89Media TTS Pro"
APP_DEFAULT_VERSION = "V1.1.1-13042026"
APP_ORGANIZATION = "AI86.PRO"
MANIFEST_FILENAME = "RELEASE_MANIFEST.json"
RESOURCES_DIR = Path(__file__).parent.parent / "resources"


def _version_manifest_candidates() -> list[Path]:
    candidates: list[Path] = []

    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        candidates.extend([
            exe_dir / MANIFEST_FILENAME,
            exe_dir.parent / MANIFEST_FILENAME,
        ])

        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            meipass_dir = Path(meipass).resolve()
            candidates.extend([
                meipass_dir / MANIFEST_FILENAME,
                meipass_dir.parent / MANIFEST_FILENAME,
            ])
    else:
        repo_root = Path(__file__).parent.parent.parent
        candidates.append(repo_root / MANIFEST_FILENAME)

        dist_manifests = sorted(
            repo_root.glob("dist*/RELEASE_MANIFEST.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        candidates.extend(dist_manifests)

    unique: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def resolve_app_version() -> str:
    for manifest_path in _version_manifest_candidates():
        if not manifest_path.exists():
            continue
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            build_tag = str(data.get("build_tag", "") or "").strip()
            if build_tag:
                return build_tag
        except Exception:
            continue

    return APP_DEFAULT_VERSION


def create_app(argv: list[str] | None = None) -> QApplication:
    """Create and configure the QApplication instance."""
    app = QApplication(argv or sys.argv)

    app.setApplicationName(APP_DISPLAY_NAME)
    app.setApplicationVersion(resolve_app_version())
    app.setOrganizationName(APP_ORGANIZATION)

    # App icon
    icon_path = Path(__file__).parent.parent.parent / "Applogo.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    # Font
    font = QFont("Segoe UI", 10)
    app.setFont(font)

    # Load stylesheet
    qss_path = RESOURCES_DIR / "style.qss"
    if qss_path.exists():
        app.setStyleSheet(qss_path.read_text(encoding="utf-8"))

    return app
