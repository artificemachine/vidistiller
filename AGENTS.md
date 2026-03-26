# Repository Guidelines

## Project Structure & Module Organization
- `frontend/`: Next.js 14 + TypeScript app (`app/` routes, `components/`, `lib/`, `services/`, `__tests__/`).
- `backend/`: FastAPI app (`app/routes`, `app/services`, `app/db`, `app/core`) and Celery tasks.
- `tests/`: Backend/integration tests and shell security checks (`test_*.py`, `test_*.sh`).
- `migrations/`: Alembic migration scripts (`migrations/versions/`).
- `scripts/`: Local automation (startup, deploy, ship).
- `docs/`, `terraform/`, and root `docker-compose*.yml` for docs, infra, and environments.

## Build, Test, and Development Commands
- `bash scripts/start-app.sh --force`: start backend, Celery, and frontend with clean restart.
- `docker-compose up -d`: run full stack in Docker.
- `docker-compose -f docker-compose.test.yml up -d`: start only Postgres + Redis for host-side tests.
- `cd frontend && npm run dev`: run frontend locally.
- `cd frontend && npm run build && npm run start`: production build + serve frontend.
- `PYTHONPATH=backend .venv/bin/python -m pytest tests/ -v`: run backend test suite.
- `cd frontend && npm test`: run Vitest tests.
- `cd frontend && npm run lint && npm run type-check`: lint and TS checks.

## Coding Style & Naming Conventions
- Python: follow PEP 8, 4-space indentation, explicit type hints on public functions.
- TypeScript/React: functional components, PascalCase for components (`SnapshotsGallery.tsx`), camelCase for helpers/hooks.
- Tests: keep names descriptive and aligned to target module (e.g., `test_auth_routes.py`, `utils.test.ts`).
- Keep changes focused; avoid leaving dead code or commented-out blocks.

## Testing Guidelines
- Backend uses `pytest`; frontend uses `vitest` + Testing Library (`frontend/vitest.config.ts`).
- Add/update tests with every behavior change.
- For DB/Redis-dependent backend tests, start `docker-compose.test.yml` first.
- Validate both happy path and failure cases for API/service updates.

## Commit & Pull Request Guidelines
- Follow Conventional Commit style seen in history: `feat: ...`, `fix: ...`, `docs: ...`, `refactor: ...`.
- Use imperative, scoped summaries (example: `fix: handle empty transcript in llm service`).
- PRs should include: concise description, linked issue/PR number when applicable, test evidence, and screenshots/GIFs for UI changes.
- Call out migration, env var, or deployment-script impacts explicitly.

## Local Hooks Access
- To force an agent to read user-level hooks, request it explicitly: `Read $HOME/.githooks and summarize`.
- For direct output, ask for a concrete command: `ls -la $HOME/.githooks && sed -n '1,200p' $HOME/.githooks/pre-commit`.
- If sandbox permissions block access, the agent should request escalation and rerun the same command.

## Critical File Protection
- `CLAUDE.md` is protected and must not be modified in normal work.
- Agents/contributors may edit `CLAUDE.md` only when the user gives an explicit instruction that names `CLAUDE.md`.
- If a task appears to require changes near `CLAUDE.md`, stop and confirm scope instead of making implicit edits.

## Global Skills Integration
- Use global skill `repo-guardrails` from `$HOME/.codex/skills/repo-guardrails` for any edit/commit workflow; enforce protected-file checks before patching and before commit.
- Use global skill `githooks-inspector` from `$HOME/.codex/skills/githooks-inspector` when asked to read, validate, or troubleshoot hooks in `$HOME/.githooks`.
- Use global skill `security-pipeline` from `$HOME/.codex/skills/security-pipeline` for `pytest + reposec + report validation` before security-sensitive commits.
- If access to home-level paths is blocked by sandbox, request escalation and rerun the same read-only command.
