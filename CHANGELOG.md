# Changelog

All notable changes to this project will be documented in this file.

> **Strict rule:** This file is **append-only**.
> Never edit, reorder, or delete existing entries.
> Add new entries at the bottom only.
> For corrections, append a new correction entry — never rewrite history.

---

## [Unreleased] — 2026-03-26

### Added
- Retroactive CHANGELOG scaffold added to bring project into compliance


## [0.1.1] — 2026-03-26

### Added
- CLAUDE.md: ⛔ DO NOT DELETE protection note — clarifies cleanup-old-viddocs scope
- .project-hooks/pre-commit: resilient hook (skips gracefully when .venv/node_modules absent)
- .gitignore: removed incorrect CLAUDE.md/AGENTS.md exclusion — these files should be tracked

### Chore
- Bump version to 0.1.1

## [Unreleased] — 2026-03-26 (security patch)

### Security
- .gitignore: add *.key, *.pem, *.p12, *.pfx, *.crt, *.cer (fixes SC-004 shipguard finding)

## [0.2.0] — 2026-04-17 (multi-source + rename)

### Added
- Multi-source video support (Phases 1-4): SourceType enum, VideoSourceResolver, CaptionProvider abstraction, VideoService (replaces YouTubeService), Alembic migration 012 (youtube_url → video_url, source_type columns), react-player v3 VideoPlayer component
- source_type threaded through LLM summarization header (Source: <url> (<type>))

### Renamed
- Project renamed from youtube-model-feeder to Vidistiller (Phase 5)
- localStorage keys: youtube-model-feeder-* → vidistiller-*
- package.json name, pyproject.toml name, FastAPI title, Docker Compose project names, CI/CD runner labels, Docker image name updated
- 2026-04-17: deploy Phase 5 Vidistiller rename to LXC (viddocs web rebuild + restart); fix VidDocs_UI_UX_Audit_Report.md header and inline references to Vidistiller
- 2026-04-17: update CLAUDE.md header from youtube-model-feeder to Vidistiller (rename cleanup)
- 2026-04-17: update README.md — multi-source video support, multi-provider LLM, VideoService rename, v1.1.0 version string
- 2026-04-17: chore: replace Apache 2.0 LICENSE with MIT (copyright celstnblacc)
- 2026-04-17: feat: add deploy/ — Terraform + Ansible for LXC→VM migration to node-antares (10.255.181.20)
- 2026-04-17: fix: ansible provisioning fixes — python -m commands, alembic.ini template, migrations copy, image tag format, qemu-guest-agent ignore_errors
- 2026-04-17: feat: update hero copy, add register password validation, fix migrate-db.yml, fix pgadmin email in vault
- 2026-04-18: fix: add secret-protection entries to deploy/terraform and deploy/ansible .gitignore (shipguard SC-004)
- 2026-04-18: fix: Next.js rewrites proxy — default NEXT_PUBLIC_API_URL to /api and proxy via BACKEND_URL so browser never needs direct access to port 8000
- 2026-04-19: fix: pass BACKEND_URL build arg in Dockerfile so Next.js rewrites bake http://backend:8000 not localhost:8000; bump frontend image to 0.2.2
- 2026-04-19: chore: rename Docker Hub org celestinmax → newblacc across Ansible defaults, CI workflow, and live docker-compose
- 2026-04-19: chore: migrate repo to github.com/artificemachine/vidistiller
- 2026-04-19: security: bind Redis and pgAdmin ports to 127.0.0.1 in dev docker-compose (threat model hardening)
- 2026-04-19: chore: update README docker-compose commands to Docker Compose v2 syntax; add Prerequisites section; remove embedded npm vulnerability output
- 2026-04-19: security: npm audit fix — upgrade axios 1.15.0, rollup 4.60.2, picomatch 2.3.2, brace-expansion 2.1.0, follow-redirects 1.16.0, remove serialize-javascript; 3 HIGH CVEs (Next.js, Sentry) tracked in chore/upgrade-nextjs-v16
- 2026-04-19: fix: add --retry=2 to pre-commit vitest run to handle load-sensitive async timeouts
- 2026-04-19: chore: bump version 0.2.0 → 0.2.1 (patch: fix/security commits in PRs #10 and #11)
- 2026-04-19: security: upgrade Next.js 14→15.5.15, React 18→19, @sentry/nextjs 8→10.49.0 — resolves 5 HIGH CVEs (GHSA-ggv3-7p47-pfv8, GHSA-9g9p-9gw9-jx7f, GHSA-h25m-26qc-wcjf, GHSA-3x4c-7xq6-9pq8, GHSA-q4gf-8mx6-v5v3) and 1 rollup HIGH (GHSA-mw96-cpmx-2vgc); remove swcMinify (Next.js 15 default); fix React 19 useRef explicit undefined
- 2026-04-19: chore: bump version 0.2.1 → 0.2.2, frontend 1.1.0 → 1.2.0 (security: Next.js/React/Sentry upgrade)
- 2026-04-19: chore: replace alert() with in-page flash banner in dashboard; migrate Pydantic V2 class Config → model_config/ConfigDict across config.py, models.py; replace from_orm with model_validate in snapshots.py; migrate FastAPI on_event("startup") → lifespan handler
- 2026-04-19: fix: deploy workflow — replace git-pull with docker compose pull (server is not a git repo); fix migration command (service: backend, not api); fix health check endpoint to 10.255.181.20:8000; update production image tags to :latest; fix postgres-data uid from 999 → 70 (postgres:15-alpine uses uid=70)
- 2026-04-28: feat: add API key auth for machine-to-machine clients — ApiKeySettings with VIDISTILLER_API_KEY env var, api_key_auth.py dependency (X-API-Key header support with JWT fallback), auto-create semblar service user on first API key call, wire into all /api/jobs routes for Semblar integration
- 2026-04-29: chore: bump version 0.3.1 → 0.3.2
- 2026-04-29: fix: docker-compose.prod.yml use bind mounts for postgres and redis to preserve data across deploys
- 2026-04-29: fix: deploy workflow syncs docker-compose.prod.yml from repo before deploying; migrations run by default with opt-out input
- 2026-04-29: fix: set BACKEND_URL=http://api:8000 in web service so Next.js rewrites proxy correctly to API container
- 2026-04-29: fix: Dockerfile BACKEND_URL default http://backend:8000 → http://api:8000 so Next.js rewrites proxy to correct container; add version badge to dashboard
- 2026-04-29: fix: absorb Docker Hub publish into deploy.yml as prerequisite job; deploy-production now always pulls fresh image before deploying
- 2026-05-07: fix: pass VIDISTILLER_API_KEY env var into api container in docker-compose.prod.yml
- 2026-05-09: fix: deploy workflow chowns app-data to 1001:1001 before compose up so non-root container can write videos/snapshots/slides
- 2026-05-09: feat: wire vLLM fleet config (VLLMFleetSettings); /settings/vllm/fleet now returns VM913/VM903/VM901/VM2900 nodes from VLLM_VM*_URL env vars
- 2026-05-09: feat(frontend): YouTubePlayer remembers last playback position (localStorage, keyed by videoId, 90-day TTL); resumes within READY handler
- 2026-05-09: chore(security): disable PY-007 (53 audited FPs from buggy shipguard 0.4.0 rule); add *.p12 + secrets.json to .gitignore; mark md5 url-cache hash usedforsecurity=False; npm audit fix (axios + fast-uri highs)
- 2026-05-09: docs: rename LXC_DEPLOYMENT.md → VM_DEPLOYMENT.md and update infra references; prod migrated from Proxmox LXC to Proxmox VM 900

## v0.4.0 — 2026-05-09

- feat(player): video playback resume (localStorage, keyed by videoId, 90-day TTL)
- feat(config): wire vLLM fleet settings (`VLLM_VM*_URL`); `/settings/vllm/fleet` now returns four GPU sidecar nodes
- fix(deploy): chown `app-data` to 1001:1001 before compose up — fixes Permission denied for non-root backend (uid 1001) on bind-mounted host dir
- fix(api): pass `VIDISTILLER_API_KEY` env var into api container in docker-compose.prod.yml
- chore(security): disable PY-007 (53 audited shipguard 0.4.0 false positives), npm audit fix (axios + fast-uri), add `*.p12`/`secrets.json` to gitignore, mark md5 url-cache hash `usedforsecurity=False`
- docs: rename LXC_DEPLOYMENT → VM_DEPLOYMENT; update infra references after prod migrated to a Proxmox VM
- 2026-05-09: fix(frontend): add Next.js rewrite for /static/:path* → backend; snapshot and slide images now load through the frontend origin (was 404 because only /api was rewritten)

## v0.4.1 — 2026-05-09

- fix(frontend): add Next.js rewrite for `/static/:path*` so snapshot and slide thumbnails load through the frontend origin (was 404 because only `/api` was rewritten)
- 2026-05-09: chore(ansible): weekly docker-image-prune systemd timer (Sun 03:30 UTC, until=168h) — prevents prod VM disk from filling with old image layers
- 2026-05-10: fix(frontend): extend playback resume to generic VideoPlayer — saves every 5 s, restores on ready, mirrors YouTubePlayer behavior

## v0.4.2 — 2026-05-10

- fix(frontend): extend playback resume to generic VideoPlayer — saves every 5 s to localStorage, restores on ready, mirrors YouTubePlayer behavior (PR #37)
- 2026-05-10: fix(frontend): guard VideoPlayer resume restore with hasRestoredRef — prevents onReady loop when ReactPlayer re-fires on seek

## v0.4.3 — 2026-05-10

- fix(frontend): prevent resume seek loop in VideoPlayer — hasRestoredRef ensures position is restored only once per mount (PR #39)
- 2026-05-10: feat(frontend): show app version below title in navbar (v{pkg.version} from package.json)

## v0.5.0 — 2026-05-10

- feat(frontend): show app version below title in navbar on every page (PR #41)

## Unreleased

- security(backend): bump pillow constraint to >=12.2.0 to cover GHSA-pwv6-vv43-88gr (OOB write via invalid PSD tile extents)
- feat(backend): vision pre-pass — VLLMProvider.describe_image() describes snapshot images using fleet vision model (VLLM_VISION_MODEL); descriptions injected into transcript context before summarization; parallel via ThreadPoolExecutor; gracefully skipped if no snapshots or vision model not configured
- feat(backend): add vision_model field to VLLMFleetSettings (VLLM_VISION_MODEL env var)
- fix(backend): set broker_transport_options visibility_timeout=86400 to prevent Celery re-queuing long-running summarization tasks
- fix(backend): LLM_TIMEOUT now passed through docker-compose.prod.yml to api and celery_worker containers
- fix(backend): vLLM provider auto-detection in summarize task — defaults to fleet when VLLM_VM*_URL configured
- fix(backend): correct default vLLM model ID (qwopus3.6-27b) in DEFAULT_MODELS
- fix(backend): vLLM URL fallback in LLMService uses fleet settings instead of Ollama base URL
- 2026-06-07: refactor(vision): use single multimodal model (self._model) for vision pre-pass; remove VLLM_VISION_MODEL env var; update tests
- 2026-06-08: fix(vllm): clear stale torch compile cache to fix 'NoneType.size' crash when loading gemma4-31b with image:1; update default vllm model to gemma4-31b
- 2026-06-08: feat(frontend): v1.6.0 — Obsidian export includes snapshot images (snapproxy route), summarize polling restart + progress bar, logout cookie-clear fix
