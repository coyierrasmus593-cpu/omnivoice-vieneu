# -*- coding: utf-8 -*-
"""SQLite database layer for voice library and project data."""

from __future__ import annotations

import json
import logging
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Default DB location
DEFAULT_DB_DIR = Path.home() / ".omnivoice-cloner"
DEFAULT_DB_PATH = DEFAULT_DB_DIR / "voices.db"


@dataclass
class VoiceProfile:
    """A saved voice profile with reference audio + metadata."""
    id: str = ""
    name: str = ""
    audio_path: str = ""
    ref_text: str = ""
    tags: str = ""  # comma-separated
    language: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0
    notes: str = ""
    model_id: str = "k2-fsa/OmniVoice"

    def __post_init__(self):
        if not self.id:
            self.id = uuid.uuid4().hex[:12]
        if not self.created_at:
            self.created_at = time.time()
        if not self.updated_at:
            self.updated_at = self.created_at

    @property
    def tag_list(self) -> list[str]:
        return [t.strip() for t in self.tags.split(",") if t.strip()]


@dataclass
class BatchItem:
    """A single item in a batch processing queue."""
    id: str = ""
    text: str = ""
    voice_id: str = ""
    output_path: str = ""
    status: str = "pending"  # pending, processing, done, error
    error: str = ""
    duration: float = 0.0

    def __post_init__(self):
        if not self.id:
            self.id = uuid.uuid4().hex[:8]


class Database:
    """SQLite database manager for voice profiles."""

    def __init__(self, db_path: str | Path = None):
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        self._init_db()
        self._repair_bundled_voice_paths()
        self._auto_import_bundled_voices()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def _init_db(self) -> None:
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS voices (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                audio_path TEXT NOT NULL,
                ref_text TEXT DEFAULT '',
                tags TEXT DEFAULT '',
                language TEXT DEFAULT '',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                notes TEXT DEFAULT '',
                model_id TEXT DEFAULT 'k2-fsa/OmniVoice'
            );

            CREATE TABLE IF NOT EXISTS generation_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                voice_id TEXT,
                text TEXT NOT NULL,
                output_path TEXT,
                speed REAL DEFAULT 1.0,
                num_step INTEGER DEFAULT 32,
                created_at REAL NOT NULL,
                duration REAL DEFAULT 0.0,
                FOREIGN KEY (voice_id) REFERENCES voices(id)
            );
        """)
        conn.commit()
        
        # Migration: Add model_id to voices if it doesn't exist
        try:
            conn.execute("ALTER TABLE voices ADD COLUMN model_id TEXT DEFAULT 'k2-fsa/OmniVoice'")
            conn.commit()
            logger.info("Migrated database: added model_id to voices table")
        except sqlite3.OperationalError:
            pass # Column already exists
            
        logger.info("Database initialized: %s", self.db_path)

    def _get_bundled_voices_json_path(self) -> Path | None:
        import sys

        if getattr(sys, "frozen", False):
            base = Path(sys._MEIPASS)
        else:
            base = Path(__file__).parent.parent.parent

        voices_json = base / "omnivoice_voice_library" / "voices.json"
        if voices_json.exists():
            return voices_json
        return None

    def _repair_bundled_voice_paths(self) -> None:
        """Repair stale absolute paths for bundled voices after app moves."""
        voices_json = self._get_bundled_voices_json_path()
        if voices_json is None:
            return

        try:
            with open(voices_json, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.warning("Failed to read bundled voices manifest for repair: %s", e)
            return

        voices = data.get("voices", [])
        if not voices:
            return

        base_dir = voices_json.parent
        conn = self._get_conn()
        repaired = 0

        for entry in voices:
            voice_id = str(entry.get("id") or "").strip()
            audio_file = str(entry.get("audio_file") or "").strip()
            if not voice_id or not audio_file:
                continue

            target_path = (base_dir / audio_file).resolve()
            if not target_path.exists():
                continue

            row = conn.execute(
                "SELECT audio_path FROM voices WHERE id = ?",
                (voice_id,),
            ).fetchone()
            if row is None:
                continue

            current_path = str(row[0] or "").strip()
            if current_path == str(target_path):
                continue
            if current_path and Path(current_path).exists():
                continue

            conn.execute(
                "UPDATE voices SET audio_path = ?, updated_at = ? WHERE id = ?",
                (str(target_path), time.time(), voice_id),
            )
            repaired += 1

        if repaired:
            conn.commit()
            logger.info("Repaired %d bundled voice path(s) using %s", repaired, voices_json)

    def _auto_import_bundled_voices(self) -> None:
        """Auto-import bundled voice library on first launch."""
        voices_json = self._get_bundled_voices_json_path()
        if voices_json is None:
            return

        # Check if voices already imported (skip if DB has any voices)
        conn = self._get_conn()
        count = conn.execute("SELECT COUNT(*) FROM voices").fetchone()[0]
        if count > 0:
            return

        try:
            imported = self.import_voices_json(voices_json)
            if imported > 0:
                logger.info("Auto-imported %d bundled voices from %s", imported, voices_json)
        except Exception as e:
            logger.warning("Failed to auto-import bundled voices: %s", e)

    # ------------------------------------------------------------------
    # Voice CRUD
    # ------------------------------------------------------------------
    def save_voice(self, voice: VoiceProfile) -> VoiceProfile:
        voice.updated_at = time.time()
        conn = self._get_conn()
        conn.execute("""
            INSERT OR REPLACE INTO voices
            (id, name, audio_path, ref_text, tags, language, created_at, updated_at, notes, model_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (voice.id, voice.name, voice.audio_path, voice.ref_text,
              voice.tags, voice.language, voice.created_at, voice.updated_at, voice.notes, voice.model_id))
        conn.commit()
        logger.info("Saved voice: %s (%s)", voice.name, voice.id)
        return voice

    def get_voice(self, voice_id: str) -> Optional[VoiceProfile]:
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM voices WHERE id = ?", (voice_id,)).fetchone()
        if row:
            return VoiceProfile(**dict(row))
        return None

    def list_voices(self, search: str = "", tag: str = "", model_id: str = "") -> list[VoiceProfile]:
        conn = self._get_conn()
        query = "SELECT * FROM voices WHERE 1=1"
        params = []
        
        if model_id:
            query += " AND model_id = ?"
            params.append(model_id)

        if search:
            query += " AND (name LIKE ? OR tags LIKE ? OR notes LIKE ?)"
            s = f"%{search}%"
            params.extend([s, s, s])

        if tag:
            query += " AND tags LIKE ?"
            params.append(f"%{tag}%")

        query += " ORDER BY updated_at DESC"
        rows = conn.execute(query, params).fetchall()
        return [VoiceProfile(**dict(r)) for r in rows]

    def delete_voice(self, voice_id: str) -> bool:
        conn = self._get_conn()
        cursor = conn.execute("DELETE FROM voices WHERE id = ?", (voice_id,))
        conn.commit()
        return cursor.rowcount > 0

    def get_all_tags(self) -> list[str]:
        voices = self.list_voices()
        tags = set()
        for v in voices:
            tags.update(v.tag_list)
        return sorted(tags)

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------
    def add_history(self, voice_id: str, text: str, output_path: str,
                    speed: float, num_step: int, duration: float) -> None:
        conn = self._get_conn()
        conn.execute("""
            INSERT INTO generation_history
            (voice_id, text, output_path, speed, num_step, created_at, duration)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (voice_id, text, output_path, speed, num_step, time.time(), duration))
        conn.commit()

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------
    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # Import from voices.json
    # ------------------------------------------------------------------
    def import_voices_json(self, json_path: str | Path, model_id: str = "k2-fsa/OmniVoice") -> int:
        """Import voices from an OmniVoice voices.json file.

        Args:
            json_path: Path to voices.json file.

        Returns:
            Number of voices imported.
        """
        json_path = Path(json_path)
        if not json_path.exists():
            raise FileNotFoundError(f"File not found: {json_path}")

        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        voices = data.get("voices", [])
        base_dir = json_path.parent
        imported = 0

        for entry in voices:
            voice_id = entry.get("id", "")
            name = entry.get("name", "")
            audio_file = entry.get("audio_file", "")
            ref_text = entry.get("ref_text", "")

            if not voice_id or not audio_file:
                continue

            # Resolve relative audio path
            audio_path = base_dir / audio_file
            if not audio_path.exists():
                logger.warning("Skipping voice '%s': audio file not found: %s", name, audio_path)
                continue

            # Check if already imported
            existing = self.get_voice(voice_id)
            if existing:
                logger.debug("Voice '%s' already exists, skipping.", name)
                continue

            # Parse created_at from ISO string
            created_str = entry.get("created_at", "")
            try:
                import datetime
                dt = datetime.datetime.fromisoformat(created_str)
                created_at = dt.timestamp()
            except (ValueError, TypeError):
                created_at = time.time()

            voice = VoiceProfile(
                id=voice_id,
                name=name,
                audio_path=str(audio_path.resolve()),
                ref_text=ref_text,
                created_at=created_at,
                updated_at=created_at,
                model_id=model_id,
            )
            self.save_voice(voice)
            imported += 1
            logger.info("Imported voice: %s (%s)", name, voice_id)

        return imported
