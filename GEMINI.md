# Vidistiller — Gemini Context

Vidistiller is a video-to-documentation engine that distills YouTube content into structured markdown notes.

## 🎯 Project Overview
- **Purpose:** Automated video summarization and documentation generation.
- **Stack:** 
    - **Frontend:** Next.js 14, React, TS, Zustand.
    - **Backend:** FastAPI, SQLAlchemy, Celery, Redis.
    - **Services:** YouTube API, Whisper/Edge-TTS.

## 🛠 Building and Running

### Core Commands
- **Start App:** `bash scripts/start-app.sh --force`
- **Frontend Dev:** `cd frontend && npm run dev`
- **Test Backend:** `PYTHONPATH=backend .venv/bin/python -m pytest tests/`
- **Test E2E:** `cd frontend && npx playwright test`

## 📏 Operational Rules
- **Privacy:** User LLM keys are Fernet-encrypted at rest.
- **Architecture:** Uses `superreins` protocol (mapped to `shux` conventions).
- **Decoupling:** Binary must not depend on local repo path once installed.

## External Client Access

To call this app's API from a script or agent, load credentials from `~/.vidistiller` (chmod 600).
Variables: `VIDISTILLER_URL`, `VIDISTILLER_USER`, `VIDISTILLER_PASSWORD`.
Full reference: `docs/VM_DEPLOYMENT.md` and vault `notes/1_infrastructure/vidistiller-api.md`.

## 🤝 Workspace Conventions
- **CHANGELOG.md:** Append-only, required per commit.
- **Task Lifecycle:** todo → plan_proposed → plan_approved → in_progress → report_ready → review_requested → review_passed → done.
- **Task Management:** Use `shux` for all task coordination.
- **Handoffs:** Write via `shux handoff-write`.
