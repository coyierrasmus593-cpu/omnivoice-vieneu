# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

CapCut Mate API — an open-source FastAPI service that programmatically creates and manipulates JianYing/CapCut draft projects. It exposes a REST API for adding videos, audio, images, captions, effects, filters, masks, keyframes, and stickers to drafts, and can trigger cloud rendering to produce final videos.

## Commands

```bash
# Install dependencies (requires uv — https://astral.sh/uv)
uv sync
# On Windows, also install Windows-specific deps:
uv pip install -e .[windows]

# Start the API server (port 30000)
uv run main.py

# Docker
docker-compose pull && docker-compose up -d
```

API docs available at `http://localhost:30000/docs` after startup.

### Desktop Client (Electron + React)

```bash
cd desktop-client
npm install
npm run web:dev    # Start Vite dev server for the web UI
npm start          # Launch Electron app
npm run web:build  # Build web UI for production
```

## Architecture

### Backend (Python, FastAPI)

Three-layer structure — all layers follow the same naming convention per feature:

- **Router** (`src/router/v1.py`): Single file defining all `/openapi/capcut-mate/v1/*` endpoints. Receives Pydantic request models, calls service functions, returns Pydantic response models.
- **Service** (`src/service/`): Business logic. One file per feature (e.g., `add_videos.py`, `add_captions.py`). Draft-mutating operations use async lock protection (`*_async` variants) to prevent concurrent writes to the same draft.
- **Schemas** (`src/schemas/`): Pydantic request/response models. One file per feature, mirroring service names.

### Draft Engine (`src/pyJianYingDraft/`)

Core library that reads/writes JianYing draft JSON files (`draft_content.json`). Key components:

- `ScriptFile` / `DraftFolder` — create and manage draft project structure
- Segment classes (`VideoSegment`, `AudioSegment`, `TextSegment`, `EffectSegment`, `FilterSegment`, `StickerSegment`) — represent timeline elements
- `metadata/` — enums and constants for fonts, masks, filters, transitions, effects, animations
- `JianyingController` — Windows-only; automates JianYing desktop app via UI automation (pyautogui, uiautomation)

### Middleware (`src/middlewares/`)

- `PrepareMiddleware` — request preparation (e.g., draft downloading)
- `ResponseMiddleware` — wraps all responses in a unified `{code, message, data}` envelope

### Configuration

- `config.py` — project constants (paths, URLs, COS credentials, feature flags). Uses env vars with defaults.
- `exceptions.py` — `CustomError` enum with bilingual (zh/en) error codes + `CustomException` class.

### Desktop Client (`desktop-client/`)

Electron app with a Vite+React frontend (`desktop-client/web/`). Provides a GUI for draft management and downloading. Pages: ConfigCenter, Download, History. Communicates with the backend API via `electronService.js`.

## Key Patterns

- **Draft URL flow**: `create_draft` returns a `draft_url` that subsequent endpoints accept to identify and modify the draft. Drafts are stored under `output/draft/`.
- **Concurrency**: Draft-mutating endpoints acquire an async lock per draft ID with a 30s timeout to prevent file corruption.
- **Time units**: JianYing uses microseconds internally. The `time_util.py` module provides `SEC` (1,000,000), `tim()`, and `trange()` helpers.
- **Bilingual errors**: `CustomError` enum carries both Chinese and English messages; language is selected at response time.
- **Backward compatibility**: `pyJianYingDraft/__init__.py` maintains deprecated snake_case aliases (e.g., `Script_file` -> `ScriptFile`) with deprecation warnings.

## Behavioral Guidelines

1. **Think before coding** — State assumptions. If multiple interpretations exist, present them. Push back if a simpler approach exists.
2. **Simplicity first** — No features beyond what was asked. No abstractions for single-use code.
3. **Surgical changes** — Don't "improve" adjacent code. Match existing style. Only remove code that YOUR changes made unused.
4. **Goal-driven execution** — Define success criteria, verify after each step.
