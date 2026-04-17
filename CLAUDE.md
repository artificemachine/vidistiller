# Vidistiller — Video to Documentation Engine

## ⛔ DO NOT DELETE THIS DIRECTORY
This is an active source project. The `business_with_ai` contract has a task called
`cleanup-old-viddocs` — that task refers ONLY to the skill stub at
`business_with_ai/clawhub-skills/youtube-model-feeder/SKILL.md`, not this project.
Never `rm -rf` or delete `~/DevOpsSec/vidistiller/`.

Project-specific rules and conventions. For global rules, see `~/.claude/CLAUDE.md`.

---

## Quick Commands
- **Start app**: `bash scripts/start-app.sh --force`
- **Frontend dev**: `cd frontend && npm run dev`
- **Build**: `cd frontend && npm run build`
- **Test frontend**: `cd frontend && npm test`
- **Test backend**: `PYTHONPATH=backend .venv/bin/python -m pytest tests/ -v`
- **Test E2E**: `cd frontend && npx playwright test --config=../e2e/playwright.config.ts`
- **Lint**: `cd frontend && npm run lint`
- **Ship**: `bash scripts/ship.sh "commit message"`

---

## Project Structure
- `frontend/` — Next.js 14 + React 18 + TypeScript (App Router)
- `backend/` — FastAPI + SQLAlchemy + Celery
- `services/` — Reusable service modules (youtube, transcript, snapshot, llm)
- `scripts/` — Automation scripts (start-app, ship, deploy)
- `migrations/` — Alembic database migrations
- `e2e/` — Playwright E2E tests (89 tests across 13 suites)
- Frontend unit tests: 137 tests across 18 suites (Vitest + RTL)

---

---

## Frontend Conventions
- Functional components only, Tailwind CSS for styling
- State: Zustand for global, SWR for data fetching, React hooks for local
- Layout: VS Code-like resizable panels (react-resizable-panels)
- Tests: Vitest + React Testing Library
- Export: JSZip for Obsidian markdown bundles

---

## Backend Conventions
- Python 3.12, PEP 8, type hints on all signatures
- SQLAlchemy 2.0+ with DeclarativeBase
- Pydantic for API schemas, FastAPI Depends() for DI
- Celery + Redis for background job processing
- Structured JSON logging in production (python-json-logger), human-readable in dev
- RequestLoggingMiddleware adds X-Request-ID to every request
- Sentry error monitoring (opt-in via SENTRY_ENABLED=true + SENTRY_DSN)
- LLM provider abstraction (`llm_providers.py`) with support for Anthropic Claude, OpenAI, and Ollama
- Per-user LLM configuration with Fernet-encrypted API key storage (`crypto.py`)
- Settings API (`/settings/me`) for managing user LLM preferences

---

## LLM Provider Selection

Users can choose their LLM provider for summarization via `/app/settings`:

### Providers Supported
- **Ollama** (local, privacy-focused) — runs LLMs on user's machine, no API key required
- **OpenAI** — uses GPT-4o-mini by default, requires API key
- **Anthropic** — uses Claude Sonnet 4.6 by default, requires API key

### Configuration
- Settings page allows users to select provider, custom model name, API key, and Ollama base URL
- API keys are encrypted at rest using Fernet symmetric encryption (key stored in `FIELD_ENCRYPTION_KEY` env var)
- Never returned in API responses — only `has_api_key: bool` flag shown
- Settings endpoint: `GET/PATCH /settings/me`, `DELETE /settings/me/api-key`

### Integration
- Celery summarization tasks resolve the job owner's LLM settings at runtime
- Provider instance is built with user's credentials and passed to `LLMService`
- Backward compatible — existing jobs default to Ollama if user has no preference set

### Environment Variable
- `FIELD_ENCRYPTION_KEY` — Fernet key for encrypting sensitive fields. Generate with:
  ```python
  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  ```

---

## Project-Specific Rules

- Do not read `dist/`, `.next/`, or `node_modules/` folders
- Summarize logs > 20 lines; don't print full output
- Keep changes minimal; avoid over-engineering
- Delete unused code (no stub comments)
- Confirm before destructive git operations

---

## Global Rules

For security, secrets, paths, build/test/deploy safety, and documentation rules:
→ See `~/.claude/SECURITY_RULES.md`

For model selection (Haiku vs Sonnet vs Opus):
→ See `~/.claude/MODEL_SELECTION.md`

For available global commands:
→ See `~/.claude/commands/README.md`

---

---

## Cross-Agent Protocol (superreins)
This project uses superreins. Protocol files are in `.superreins/`.
- Read `contract.yaml` before starting any work.
- Read `failures.yaml` before implementing — search for past failures with this technology.
- Read `decisions.yaml` for architectural context.
- Read any handoffs in `handoffs/` addressed to `claude-code`.
- When you make a decision between alternatives: log it in the contract's decisions section.
- When something fails: log it in the contract's failures section.
- When you finish a task: update contract status, write a handoff, append to ledger.
- When reviewing Codex's work: use the review lenses assigned to the task in the contract.

## Review Lenses
When reviewing, check the `review_lenses` field on the task. Apply only the assigned lenses:
- security: auth, secrets, injection, data exposure
- architecture: patterns, coupling, dependency direction
- performance: N+1 queries, memory, scaling
- tests: coverage, edge cases, determinism
- error-handling: failure modes, logging, graceful degradation
- devops: config, CI/CD, observability
- api-contract: backwards compatibility, versioning

---

**Related:** `~/.claude/CLAUDE.md` (global rules index)
