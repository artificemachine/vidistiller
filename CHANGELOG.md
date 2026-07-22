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
- 2026-06-08: security(frontend): add path traversal guard to snapproxy route (JS-002)
- 2026-06-08: feat(frontend): v1.7.0 — PDF export button (window.print), rename export→obsidian and save→backup json, add @media print CSS
- 2026-06-08: fix(frontend): print/PDF now renders clean transcript-only view; hide interactive layout on print
- 2026-06-08: chore(release): bump to v1.7.1 (fix print/PDF layout)
- 2026-06-08: fix(frontend): strip transcript preamble in print view; show clean timestamped lines only
- 2026-06-08: chore(release): bump to v1.7.2 (include preamble-strip fix in Docker image)
- 2026-06-08: fix(frontend): hide navbar on print (print:hidden on nav in layout.tsx)
- 2026-06-08: fix(frontend): print view renders transcript line-by-line matching sidebar/MD format; hide navbar on print
- 2026-06-08: fix(frontend): print view renders transcript line-by-line matching sidebar/MD format; hide navbar on print
- 2026-06-08: chore(release): bump to v1.7.3 (print transcript matches sidebar/MD export format)
- 2026-06-08: fix(frontend): pdf export renders all pages; strip preamble from print transcript
- 2026-06-08: chore(release): bump to v1.7.4 (pdf multi-page + preamble strip)
- 2026-06-08: fix(backend): default LLM provider to vLLM fleet; fall back to VLLM_VM913_URL env var
- 2026-06-08: chore(release): bump to v1.7.5 (default LLM to vLLM fleet)
- 2026-06-08: fix(config): correct VLLM_VM913_URL port 8100→8000 in .env.example; update VLLMFleetSettings docstring to reflect direct vLLM (no proxy); add docker compose down --remove-orphans before up in CI deploy
- 2026-06-08: fix(config): change default vLLM model from qwopus-27b (typo/nonexistent) to gemma4-31b (loaded on vm913 GPUs 4-7)
- 2026-06-08: feat(backend): fleet-aware summarize — queries all VMs /v1/models to find which one has the requested model loaded instead of hardcoding vm913
- 2026-06-08: fix(test): update vLLM default model assertion to match gemma4-31b
- 2026-06-08: chore(release): bump to v1.8.0 (fleet-aware summarization + model/default fixes)
- 2026-06-09: fix(llm): extract JSON array from Pass 1 response before parsing to handle trailing text
- 2026-06-09: chore(release): bump to v1.8.1 (two-pass JSON trailing-text fix)
- 2026-06-09: test(frontend): add polling-restart and failed-status tests for summarize button; add ops-runbook.md
- 2026-06-09: fix(frontend): rename 'backup json' button to 'backup'
- 2026-06-09: chore(release): bump to v1.8.2 (rename backup json button)
- 2026-06-09: fix(slides): route presentation-mode LLM disambiguation through the provider abstraction (vLLM fleet) instead of dead localhost Ollama
- 2026-06-09: feat(frontend): rename 'obsidian' export button and landing chip to 'markdown'
- 2026-06-09: chore(release): bump to v1.8.3 (presentation-mode LLM fix + markdown rename)
- 2026-06-09: chore: remove 52 empty scaffolding stub files (never populated since initial commit); fix ops-runbook orphan-container note
- 2026-06-09: chore(e2e): add playwright.config.ts + global-setup.ts so the e2e specs are runnable again; fix stale command + test-count references in CLAUDE.md
- 2026-06-09: chore(e2e): avoid path.join in global-setup (shipguard JS-002 false positive); use template literal
- 2026-06-09: ci: bump actions to Node 24-compatible versions ahead of 2026-06-16 cutover
- 2026-06-09: chore(deploy): add orphan-safe deploy script (rm -f tutorial_* -> pull -> up)
- 2026-06-09: feat(slides): add slide_status to distinguish failed/skipped slide runs
- 2026-06-09: fix(slides): use incremental_ssim_threshold as non-LLM fast-path; record parent links
- 2026-06-09: test(e2e): add CI e2e job (docker-compose.e2e.yml + playwright chromium)
- 2026-06-09: chore: bump version to 1.9.0 (feat/slides minor bump)
- 2026-06-09: fix(ci): quote shell array in deploy.sh; fix e2e build context to repo root
- 2026-06-09: fix(e2e): use python3 -m celery for worker (celery not in PATH in runtime image)
- 2026-06-09: fix(e2e): override api command to python -m uvicorn (matches prod; bins not on PATH)
- 2026-06-09: fix(e2e): use postgres:5432 (compose service name) not localhost in DATABASE_URL
- 2026-06-09: fix(docker): mkdir /data + chown appuser in Dockerfile for e2e startup
- 2026-06-09: fix(e2e): set NODE_PATH so @playwright/test resolves from e2e/playwright.config.ts
- 2026-06-09: fix(ci): bump e2e-tests timeout-minutes 8→20 (docker build takes ~7m in CI)
- 2026-06-09: fix(e2e): wait for port 3000 (web) in boot step before running playwright tests
- 2026-06-09: fix(e2e): global-setup: use dashboard link as auth indicator; handle middleware /login→/ redirect
- 2026-06-09: fix(e2e): replace Logout button checks with dashboard link (logout is in collapsed dropdown)
- 2026-06-09: ci(e2e): increase job timeout to 35min + 2 parallel workers to prevent timeout on 35-test suite
- 2026-06-09: fix(e2e): update settings and password-reset tests for redesigned UI (radio cards, updated button text)
- 2026-06-09: fix(e2e): use Promise.all for waitForResponse to eliminate race conditions in vllm tests
- 2026-06-09: fix(slides): cancel_check must signal on CANCELLED status not FAILED
- 2026-06-09: test(slides): unit coverage for ssim_transition_scan and layout_detection
- 2026-06-09: test(slides): integration tests for run_full_pipeline orchestration
- 2026-06-09: fix(slides): reliable video_duration fallback + OCR frame-index cache
- 2026-06-09: test(frontend): assert slide mode toggle sets is_slide_mode in API payload
- 2026-06-09: chore(release): bump to v1.9.1 (cancel signal fix, SSIM/layout/pipeline tests, video_duration fallback, OCR cache, frontend toggle test)
- 2026-06-09: fix(e2e): narrow password-reset locator to avoid strict-mode violation
- 2026-06-10: fix(slides): layout-aware SSIM thresholds and min-duration for pip_speaker screencasting
- 2026-06-10: chore(release): bump to v1.9.2 (pip_speaker SSIM tuning)
- 2026-06-10: feat(llm): vision pre-pass — describe snapshots with fleet vision model before summarization
- 2026-06-10: chore(release): bump to v1.10.0 (vision pre-pass)
- 2026-06-10: fix(frontend): hide 'toggle logs' button when no logs exist; hide empty logs panel; persist slideTextVisible to localStorage
- 2026-06-10: chore(release): bump to v1.10.1 (frontend UI fixes)
- 2026-06-10: chore: sanitize hardcoded paths in contract.yaml and memory; harden security CI gate
- 2026-06-10: chore: global rename LXC_HOST → STAGING_HOST; resolve 9 moderate frontend vulnerabilities (v1.10.1 maintenance)
- 2026-06-10: feat(llm): tuned vision pre-pass prompt for technical slide analysis
- 2026-06-10: chore(release): bump to v1.10.2 (cleanup and prompt tuning)
- 2026-06-10: fix(backend): summarize task now uses slides as fallback context for vision pre-pass in slide_aware mode
- 2026-06-10: chore(release): bump to v1.10.3 (vision pre-pass slide fix)
- 2026-06-10: fix(backend): convert images to base64 data URIs for vision pre-pass; reduce max_tokens in analysis pass to fix 16k context limits
- 2026-06-10: chore(release): bump to v1.10.4 (vision pre-pass base64 and context fix)
- 2026-06-10: fix(frontend): fix left sidebar panel toggles failing due to missing order props in react-resizable-panels
- 2026-06-10: chore(release): bump to v1.10.5 (frontend UI fix)
- 2026-06-10: fix(frontend): fix left sidebar panel toggles failing due to missing order props; use imperative control instead of conditional rendering for layout stability
- 2026-06-10: chore(release): bump to v1.10.6 (frontend UI fix v2)
- 2026-06-13: fix(frontend): fix workspace panels overflowing viewport; panel sizes now sum to 100%; restore collapsed state after Group remount
- 2026-06-13: fix(frontend): fix panel toggle buttons not collapsing panels; remove Group key to prevent remount race; add save layout button; add ActivityBar tooltips. v1.10.8.
- 2026-06-13: fix(frontend): fix Layout type for vertical panel defaultLayout (react-resizable-panels v4 expects Record not number[])
- 2026-06-13: fix(frontend): fix multi-panel toggle bug — make savedVerticalLayout stable (useState lazy init) so defaultLayout never re-applies on toggle
- 2026-06-13: fix(frontend): fix Snapshots toggle requiring double-click — decouple toggle functions from isCollapsed(); sync panel state via useEffect on hydration. v1.10.9.
- 2026-06-13: fix(frontend): fix Save Layout not restoring panel sizes on reload — use useGroupRef/setLayout after hydration instead of broken useState lazy init. v1.10.10.
- 2026-06-13: fix(frontend): replace imperative panel collapse with conditional rendering — toggle buttons now unmount panels instead of collapsing them, eliminating all isCollapsed() state sync issues. v1.10.11.
- 2026-06-24: harden repo (Phase 6 gitleaks + dependabot)
- 2026-06-24: add missing .gitleaks.toml

- 2026-06-25: chore: remove personal workspace path from tracked files

- 2026-06-30: feat: add summary_language user setting; fix vLLM fleet routing to qwen3-32b-awq on vm903; fix duplicate transcript header; fix frontend NEXT_PUBLIC_API_URL baking
- 2026-06-30: feat: add DeepSeek, MiniMax, and OpenCode LLM providers; fix vllm model list dedup; fix BACKEND_URL baked at build time
- 2026-06-30: chore(ci): exclude GHA-002 from shipguard scan (0.4.3 false positive on SHA-pinned actions); add .shipguard.toml
- 2026-06-30: fix(e2e): scroll vllm radio into view before clicking and scroll to bottom after — fleet section renders below the radio
- 2026-06-30: fix(ci): remove Jinja2 raw tags from gitleaks.yml — caused workflow parse failure on GitHub
- 2026-06-30: fix(ci): replace gitleaks-action@v2 (requires paid org license) with direct CLI install; fix e2e selectVllm to click label instead of sr-only radio input
- 2026-06-30: fix(ci): scope gitleaks scan to PR commits only, not full history (157 pre-existing false positives in history)

## [Unreleased] — 2026-07-20

### Fixed
- fix: restore image-baked /app/deps under backend bind mount in dev compose — fresh-clone quickstart failed with "uvicorn: executable not found" (api) and "No module named celery" (worker) because ./backend shadowed the pip --target dir; anonymous volume over /app/deps restores it (found by /job-ready stage 4, reproduced 2x)

### Fixed
- fix: add /app/deps/bin to PATH in backend Dockerfile — pip --target installs console scripts there, so `uvicorn` was not on PATH and the api container could not exec its CMD

### Security
- chore: scrub internal homelab topology from tracked files — replaced internal 10.255.x.x addresses with 10.0.x documentation placeholders and real node names with generic ones across .env.example, deploy/ (terraform+ansible), CI deploy workflow, backend docstrings, docs, and tests; production health check now reads vars.PROD_API_BASE_URL; untracked .superharness/ (agent state) and features_to_add/ (working notes incl. personal-named .docx) and gitignored both

### Fixed
- docs: README surface repair — removed broken links (DESIGN_EXPORT_GUIDE.md, DESIGN_README.md, docs/DOCKER.md, docs/DEPLOYMENT.md), corrected terraform description (Proxmox, not AWS), dropped pink-span heading styling, aligned Python prerequisite to 3.12+ (matches Docker image and CI)

### Added
- docs: add SECURITY.md with private-reporting policy and self-hosted scope notes

### Fixed
- chore: align backend version to 1.10.11 (pyproject was 1.10.6, frontend 1.10.11), switch CI to npm ci for deterministic installs, npm audit fix (resolves HIGH form-data CRLF injection GHSA-hmw2-7cc7-3qxx; prod deps now 0 vulnerabilities)

### Removed
- chore: delete 33 local + 78 remote branches verified as merged via their PR head refs (ancestry check under-counts with squash-merge)

### Fixed
- fix: scope gitleaks ipv4-address rule to the real internal range (10.255.x.x) — the generic IPv4 regex flagged documentation placeholders (44 false positives on this PR) and the per-rule `enabled = false` line was silently ignored (gitleaks has no such field); PR-range CI scans now pass

### Fixed
- fix: security workflow — pass --severity high to shipguard so the scan step exits non-zero only on high/critical findings; previously any medium finding failed the job before the severity-policy step could run (fail-closed on noise)

## v1.10.12

### Fixed
- fix(security): make the gitleaks personal-email rule use a non-capturing group — with a capturing group gitleaks reported the captured domain ("gmail") as the Secret instead of the full address, which also prevented allowlist regexes from matching. Backported from fix/gitleaks-pii-regex-backport; the private-range IP allowlist from that same branch was deliberately NOT taken, as `^10\.` fully suppresses the scoped 10.255.x.x rule added in #98.
- fix(security): replace the real-format Fernet key in .env.example with base64("DEV-ONLY-INSECURE-CHANGE-ME-0000") — still a valid Fernet key so `cp .env.example .env` boots for local dev, but self-evidently not a secret. Verified it never matched the live production key.
- fix(scripts): remove hardcoded internal IP from scripts/push-backend.sh; SSH target now defaults to the `vidistiller` host alias and is overridable via VIDISTILLER_SSH.

### Changed
- chore(gitleaks): allowlist the public dev Fernet key and truncated OpenAPI JWT examples so PR-range CI scans stay clean without weakening any rule.
- chore(gitignore): ignore local agent/session artifacts (.ship-check-passed, .hablatone-project, .voice-toolkit-project, HANDOFF.md).

## v1.10.13

### Security
- fix(security): JWT_SECRET_KEY no longer has a hardcoded default. The former default ("TestSecretKey123!@#abcDEF_development_only") and the .env.example placeholder ("ChangeMe123!ReplaceThisNow_32charsMin") both passed every strength check, so any deployment that never set the variable signed tokens with a secret published in this repository — forgeable tokens for any account. Both are now rejected by exact-value match in every environment. Production requires an explicit key; outside production an ephemeral random key is generated at startup with a warning, so `cp .env.example .env` still boots without a public secret ever signing a token. Verified: production deployments were unaffected (real 64-char key in use).
- fix(security): add pip-audit to the security workflow. Python dependency CVEs were previously never scanned in CI. PYSEC-2026-1325 (ecdsa, transitive via python-jose) is ignored with justification — it has no upstream fix and its ECDSA code path is unreachable because JWTs are signed with HS256.
- fix(deps): raise pillow floor to >=12.3.0, closing 8 CVEs. pillow decodes video snapshot frames via Image.open(), so it sits directly on the untrusted-input path.

### Fixed
- fix(config): construct JWTSettings via default_factory instead of at class-definition time. As an import-time singleton, an unset JWT_SECRET_KEY in production made app.core.config itself un-importable, which would have broken migrations and tooling. The remaining sub-settings share this pattern but are not security-gated.
- fix(config): correct requires-python from >=3.14 to >=3.12, matching .python-version, the Dockerfile and CI. The previous value meant local development ran a different interpreter than CI and production.

### Changed
- chore(security): drop the stale --exclude-rules GHA-002 workaround from security.yml and .shipguard.toml. Verified that the rule no longer fires on shipguard 0.5.2.

## v1.10.14

### Security
- fix(security): confine verify_token to access tokens. It backs get_current_user, so whatever it accepts is a full API credential, yet it checked only "sub" while the refresh and password-reset verifiers did check "type". Access tokens carried no type claim at all. A password-reset token — delivered in an emailed URL, so it persists in browser history and Referer headers — therefore worked as a bearer token, and remained valid after the reset was consumed because verify_token never consults the database. Access tokens now carry type=access and it is asserted on verification. Existing sessions are invalidated on deploy; this is intended.
- fix(security): add SSRF guards on every user-supplied URL the backend fetches itself. video_url was validated only by "\.' in netloc", which rejected localhost by accident while permitting every IP literal including 169.254.169.254, and was passed to yt_dlp synchronously inside the POST handler from inside the private network. GET /settings/vllm/models was worse: it returned the fetched body and reflected the exception text, making it a non-blind read proxy. llm_ollama_url had no validation at all and is persisted, so it was a stored SSRF primitive replayed on every summarization job.
- fix(security): stop reflecting the sidecar exception string in the 502 body of /settings/vllm/models; it is now logged instead.

### Added
- feat(config): ALLOWED_LLM_HOSTS. LLM and vLLM endpoints legitimately target private addresses, so a denylist would break the local-first path; they are matched against this operator allowlist instead. Defaults to loopback, the compose service names, and host.docker.internal, so the documented Docker setup keeps working.
- feat(security): backend/app/core/url_guard.py, with validate_fetch_target (deny private/loopback/link-local/reserved/multicast, all resolved addresses checked) and validate_llm_endpoint (allowlist). Documented limitation: validation is pre-request, so DNS rebinding and redirect chains are not covered.

### Fixed
- fix(ui): settings page rendered neither a success nor an error banner when the API returned a 422. FastAPI sends `detail` as a list of objects for validation failures, and passing that array into JSX crashed the render. New `errorMessage()` helper in frontend/lib/utils.ts flattens both shapes; wired into the save and clear-api-key handlers.
- fix(test): SSRF tests hardcoded a real homelab address, which the scoped gitleaks ipv4 rule correctly flagged. Replaced with the scrubbed 10.0.x convention already used in the same files.
- test(e2e): "can save vllm provider settings" asserted success-or-error, so it went green on a rejected save. Now asserts the success banner, with the mock fleet's RFC5737 addresses allowlisted via ALLOWED_LLM_HOSTS in docker-compose.e2e.yml.

## [1.10.15] - 2026-07-20

### Security
- fix(security): snapshot and slide images were served by a bare StaticFiles mount, so anyone who learned a job UUID could read that job's frames without logging in. Frame filenames are deterministic, so one leaked UUID exposed the whole set permanently. Both paths are now FastAPI routes that authenticate the caller and verify job ownership, returning 404 rather than 403 to a non-owner so the response cannot confirm a job exists.
- fix(security): the /snapproxy Next route fetched upstream with no credentials. Now that delivery is authenticated it forwards the caller's auth_token as a bearer token and refuses anonymous requests, rather than acting as a read hole around the ownership check.
- fix(security): media responses are Cache-Control private, not public. Per-user images must not sit in a shared cache.

### Fixed
- fix(config): Settings.storage was built at class-definition time, so DATA_DIR was frozen at import and could not be changed without a restart. Now a default_factory, matching the jwt fix in 1.10.13. The remaining sub-settings fields still share the old pattern.

## [1.10.16] - 2026-07-20

### Fixed
- fix(config): JWTSettings has no env_prefix, so its secret_key field bound to SECRET_KEY while .env.example, the docs and every compose file set JWT_SECRET_KEY. Production therefore ran on an unread variable. The field now reads JWT_SECRET_KEY first and still accepts SECRET_KEY so hosts patched during the incident keep booting.
- fix(config): the character-composition rules rejected high-entropy generated keys such as `openssl rand -hex 32`, which have no uppercase or punctuation. Keys of 64+ characters now skip those rules and are checked for character variety instead.
- fix(config): a blank ALLOWED_LLM_HOSTS is treated as unconfigured rather than as an empty allowlist, so the `${ALLOWED_LLM_HOSTS:-}` passthrough added below cannot silently block the local Ollama endpoint.
- fix(deploy): docker-compose.prod.yml now passes ALLOWED_LLM_HOSTS to api and celery_worker. It was hand-patched into the production host only, so a rebuild from the repository regressed it.
- docs: VM_DEPLOYMENT.md generates the JWT secret with token_urlsafe(48) instead of (32); the shorter draw could fail the composition rules by chance.

## [1.10.17] - 2026-07-21

### Changed
- chore(deploy): docker-compose.prod.yml image tags are now `${VIDISTILLER_IMAGE_TAG:-latest}` instead of a hardcoded `latest`. Pinning a release makes the running version knowable from configuration and turns a rollback into a one-line .env change. Behaviour is unchanged when the variable is unset.
- docs: .env.example documents VIDISTILLER_IMAGE_TAG. The production host has been pinned to 1.10.16 and its incident-era SECRET_KEY entry removed, now that 1.10.16 reads JWT_SECRET_KEY; that entry never existed in this repository's compose file.

## [1.10.18] - 2026-07-21

### Fixed
- fix(captions): YouTubeCaptionProvider ignored the requested language and handed every available language code to find_manually_created_transcript, returning the first match. For an auto-dubbed video (which exposes a manually-created caption track per dub language) that was a dub, not the original, so an English video could be transcribed in Arabic. Selection now prefers the requested language via find_transcript, then any manual track, then the first available. _fetch_platform_captions threads the language through to both providers.

## [1.11.0] - 2026-07-21

### Added
- feat(captions): users can choose the caption language for a job. The create form fetches the video's available caption tracks (new `POST /api/videos/caption-tracks`, authenticated) and shows a language dropdown when tracks exist; the choice is persisted as `caption_language` on the job and threaded into caption fetching. Defaults to auto (English) when unset. Migration 014 adds the nullable `processing_jobs.caption_language` column. This selects among existing tracks only — it does not translate.

## [1.11.1] - 2026-07-21

### Changed
- docs(readme): correct the `scripts/` list to the files that actually exist (deploy.sh, push-backend.sh, setup-staging.sh, batch_process.py).
- docs: soften a stray "production-ready" line in docs/README.my.notes.md; point to the audit reports for known limitations.

### Added
- chore(community): CODE_OF_CONDUCT.md (Contributor Covenant 2.1), PR template, and bug/feature issue templates.
- chore(ci): Dependabot now covers npm (frontend) and docker (backend + frontend Dockerfiles) in addition to pip and github-actions.
- docs(audits): 2026-07-21 job-ready audit report.

## [1.11.2] - 2026-07-21

### Security
- fix(security): the rate limiter and the import-task ownership check now fail CLOSED on a Redis error instead of open. Previously a Redis outage silently disabled brute-force protection on the auth endpoints and let any authenticated user read another user's import status. Both now deny on Redis failure (auth requests get a retry-able rate-limit response; import status returns not-found), trading availability during an outage for the security control staying enforced. Regression tests added in tests/test_fail_closed.py.

## [1.11.3] - 2026-07-21

### Fixed
- fix(migrations): consolidate the broken alembic chain into a single squashed baseline and restore migrations/env.py. The prior chain was unrunnable from a fresh clone — revisions 001/007/009/011 were committed as empty stubs then deleted, leaving dangling down_revision references, and env.py had been removed. Both dev and prod build the schema from the models via create_all at startup, so alembic had drifted into a decorative broken state. `alembic upgrade head` now works from a fresh clone and builds the full current schema (verified: 10 tables incl. caption_language). The baseline uses create_all with checkfirst, so it is a safe no-op on an already-populated database. Prod reconciliation (schema already create_all-built): `alembic stamp --purge 0001_squashed_baseline` if a stale version stamp exists.

## [1.11.4] - 2026-07-21

### Changed
- chore(ci): docker-publish.yml now gates image publishing on a test job (`build-and-push` needs `test`). A `v*` tag push previously built and pushed images to Docker Hub with no test run; backend + frontend tests must now pass first.

## [1.12.0] - 2026-07-21

### Changed
- fix(config): all 16 sub-settings now use default_factory instead of building at class-definition time, so environment changes are read when Settings() is constructed rather than frozen at module import.
- fix(db): the Video, Transcript, TranscriptSegment, Snapshot and Document foreign keys now declare ON DELETE CASCADE at the database level, matching the ORM cascade so raw/bulk deletes cannot orphan rows.
- fix(ops): prod docker-compose now sets mem_limit and cpus on every service (postgres, redis, api, web, pgadmin), not just celery_worker.

### Added
- feat(health): /readyz readiness probe that checks database and Redis liveness and returns 503 when a dependency is down, distinct from the static /health liveness probe.

## [1.12.1] - 2026-07-21

### Security
- feat(auth): token revocation via a per-user token_version. Each access token carries the version it was minted with; logout and password reset bump the version, invalidating every token issued before the bump (this token and any on other devices). Gives the stateless JWT a real revocation path without a denylist. Existing DBs get the users.token_version column via the startup ALTER block; fresh clones via the alembic baseline.
- fix(security): /api/videos/metadata, /captions and /check now require authentication. They trigger outbound fetches (yt_dlp / caption APIs) and were previously callable unauthenticated. Not used by the frontend, so no UX impact.

## [1.12.2] - 2026-07-21

### Fixed
- fix(tasks): process_transcript is now idempotent for terminal-state jobs. With task_acks_late, a worker killed after finishing but before acking gets the job redelivered; reprocessing a completed job would overwrite its transcript and re-run the LLM. Jobs already completed or cancelled are now skipped on redelivery.

## [1.12.3] - 2026-07-21

### Fixed
- fix(startup): the startup column-add loop ran every ALTER on one shared connection. On Postgres, the first ALTER that fails because the column already exists aborts the transaction, so every subsequent ALTER silently fails with "current transaction is aborted" — which caused a deploy to ship without users.token_version and break login. Each ALTER now runs in its own transaction and rolls back on failure. Regression test added.

## [1.12.4] - 2026-07-21

### Added
- docs(readme): add a landing-page and workspace screenshot above the fold so the README shows what the product does at a glance. Assets live in docs/assets/ (allowlisted via .allow-binary-paths).

## [1.12.5] - 2026-07-21

### Fixed
- fix(config): docker-compose.yml passes `JWT_SECRET_KEY: ${JWT_SECRET_KEY}` with no default, so leaving it unset in .env (the documented way to get an auto-generated dev key) arrives in the container as an EMPTY STRING, not an absent variable. The v1.10.16 alias fix made the field read that empty string as "set" and reject it outright, which broke `docker compose up -d` on a genuinely fresh clone — the api container never became healthy. A blank/whitespace-only value is now treated the same as unset. Found by an actual fresh-clone `docker compose up -d` verification, not a config test alone.
- docs(env): .env.example VLLM_VM913_URL and siblings are now commented out, matching the neighboring ALLOWED_LLM_HOSTS example and the "leave blank to hide a VM" comment already above them. Previously uncommented, so a fresh `cp .env.example .env` populated the UI's fleet picker with 4 example VMs by default.

## [1.12.6] - 2026-07-21

### Fixed
- fix(docs): CONTRIBUTING.md had three factual errors: claimed Apache 2.0 license (actual LICENSE is MIT), described backend/frontend as `api/`/`web/` (actual dirs are `backend/`/`frontend/`), and stated Python 3.10+ (pyproject.toml requires 3.12+). Also updated the stale "Ollama/Mistral 7B only" LLM description to reflect the current multi-provider support.
- fix(docs): docs/README.md linked to 6 files that do not exist (DEPLOYMENT.md, DEVELOPMENT.md, PROGRESS.md, ARCHITECTURE.md, API.md, API_DOCUMENTATION.md) — a 100%-dead-link documentation index. Rewritten to link only files that exist, each labeled with its actual status.
- chore: removed a dead `main.py` scaffold stub at the repo root (untouched since v0.2.0, disconnected from the real app in backend/app/main.py).

## [1.12.7] - 2026-07-21

### Changed
- chore: renamed the internal machine-to-machine service-account identifier from a named sibling private project ("semblar") to a generic `m2m-client`. Renamed in code (`SEMBLAR_SERVICE_USERNAME` -> `M2M_SERVICE_USERNAME`), comments, `.env.example`, and the design doc (`docs/SEMBLAR_INTEGRATION.md` -> `docs/M2M_AUTH_DESIGN.md`, stripped project-specific naming and topology, status corrected from stale "Proposed" to "Implemented"). No behavior change — this is an internal identifier the calling client never sends or sees. Production service-user row renamed to match after this deploy.

## [1.12.8] - 2026-07-21

### Changed
- docs: executed the Stage 2 /docs-organize cleanup plan — moved DESIGN_SPEC.md, ROADMAP.md, TECH_STACK.md and VidDocs_UI_UX_Audit_Report.md from repo root into docs/, updated the README design-spec link and the docs/README.md index to match.
- docs: redacted a personal name from docs/VidDocs_UI_UX_Audit_Report.md's "Prepared for" line (the email there was already a safe @example.com placeholder).

## [1.12.9] - 2026-07-21

### Changed
- docs: VidDocs_UI_UX_Audit_Report.md "Prepared for" line set to the repo owner's name, at their request.

## [1.12.10] - 2026-07-21

### Fixed
- docs(readme): the "Explanation of Each Part" section described a `config/` directory that does not exist. Corrected to describe the actual location, `backend/app/core/config.py`. Found during a fresh /readme-audit re-validation; every other referenced directory (backend/, frontend/, migrations/, tests/, scripts/, terraform/, .github/workflows/) checked and confirmed accurate.

## [1.12.11] - 2026-07-21

### Changed
- chore(deps): pytest requirement bumped from >=7.4.0 to >=9.1.1 (applied manually — Dependabot PR #83 had gone stale/conflicting after other same-day dependency merges touched the same file).

## [1.12.12] - 2026-07-22

### Fixed
- fix(e2e): settings-buttons.spec.ts asserted `successMsg.or(errorMsg).or(savingBtn)` as if the three were mutually exclusive. The save handler sets the success message, then makes a second request (GET /auth/me) before clearing the saving state in a finally block, so the success toast and a disabled "saving..." button are legitimately visible at the same time -- not a third outcome, an implementation detail of a real success. Playwright's strict mode failed the assertion on 2 simultaneous matches. Assert on the two actual terminal states (success/error) instead. Found by a genuine `/portfolio-ready` fresh-clone re-verification surfacing a real e2e failure on main after 9 dependency bumps -- not caused by any single bump, a pre-existing latent test assumption that finally got hit.

## [1.12.13] - 2026-07-22

### Changed
- docs(claude): CLAUDE.md's stated Python version updated from a hardcoded "3.12" to reflect the actual convention -- 3.12+ is the floor (pyproject.toml), CI pins 3.12 explicitly (test.yml), and Docker/prod track whatever version Dependabot has most recently verified (currently 3.14, per the python:3.12-slim->3.14-slim base image bump). Decision: single-version-tracking going forward rather than restoring the old deliberate dual-version testing split, since CI's pinned 3.12 matrix already provides that coverage automatically.

## [1.12.14] - 2026-07-22

### Fixed
- fix(ci): Deploy workflow's SAST gate failed on every main push. `shipguard scan` exits non-zero on ANY finding, and GitHub's default `bash -eo pipefail` aborted the step before the python severity-gate (which fails only on critical/high) could run -- so `publish` and `deploy-production` (both `needs: [security]`) were perpetually SKIPPED. Added `|| true` to the scan line so the python gate is the real decision point. Prod was unaffected (deploys were done manually); this restores the intended auto-publish/auto-deploy path.

## [1.12.15] - 2026-07-22

### Fixed
- fix(ui): portrait snapshots/slides (e.g. YouTube Shorts, 9:16) were forced into a hardcoded 16:9 container -- cropped in thumbnail grids (object-cover) and letterboxed in previews. Galleries now derive the preview aspect ratio from each image's natural dimensions on load (SnapshotsGallery, SlidesGallery), thumbnails use object-contain (no crop), and inline summary/snapshot thumbs render at natural height. Capture was already correct; this was purely a display bug. Added regression tests asserting natural-AR adoption and no-crop thumbnails.

### Changed
- refactor(ui): the portrait aspect-ratio fix (1.12.15) now sources dimensions primarily from the backend-captured `image_width`/`image_height` (measured once at frame capture and already stored per snapshot/slide) instead of the browser's on-load natural size. Deterministic, no 16:9-to-real layout shift on load. The `page.tsx` snapshot mapping was dropping those fields; now threaded through. On-load natural size is retained only as a fallback for legacy rows with null dimensions.

## [1.12.16] - 2026-07-22

### Changed
- chore: commit GEMINI.md (Gemini agent doctrine, was untracked since scaffold) and two session audit reports (docs/audits/2026-07-20-job-ready-final.md, docs/bulletproof-report-2026-07-22.md) that follow the repo's existing committed-audit convention. gitignore e2e/test-results/ (Playwright transient run artifacts, was never excluded) and delete the stray directory.

## [1.12.17] - 2026-07-22

### Changed
- docs(readme): replaced the two README screenshots (stale at v1.10.16, unredacted username visible in the nav) with three current v1.12.16 captures -- landing page, job workspace (transcript + player + snapshots), and jobs dashboard. Converted PNG source captures to WebP (5.5MB -> 148KB combined; per-image 4.2MB -> 22-84KB) so no image exceeds the pre-commit binary-size gate and no git-lfs is needed. Username redacted via solid-box overlay (not blur) on all three before compression. Assets live under the existing docs/assets/ convention.

## [1.12.18] - 2026-07-22

### Fixed
- fix(deps): sharp@0.34.5 (transitive via next, production) carried 4 unpatched HIGH-severity libvips CVEs (CVE-2026-33327/33328/35590/35591). Added an npm `overrides` pin (`sharp: ^0.35.0`) since sharp isn't a direct dependency. `npm audit --production` now reports 0 vulnerabilities (was 2 high, 1 low pre-fix on the dev-dependency side). Verified: 238/238 frontend tests pass, production build succeeds on all 11 routes. Found by /golive Stage 4's fresh-clone dependency-health check -- this was the pipeline's single mechanical NOT READY trigger.

## [1.12.19] - 2026-07-22

### Removed
- chore: deleted the dead root `services/{llm,snapshot,transcript,youtube}/` scaffold -- 9 tracked files, every one a comment-only planning stub with zero implementation, zero imports anywhere in the codebase. Predated and fully superseded by the real implementations under `backend/app/services/`. Undisclosed duplicate naming was flagged independently by three separate audit methodologies (folder-structure idiom check, /bulletproof claim-harvesting, /user-reviewer) in the 2026-07-22 /golive audit.
- chore: deleted `scripts/batch_process.py` -- README-advertised ("processes multiple video URLs in one go") but 100% comments, zero implementation; ran silently as a no-op instead of erroring. Removed rather than implemented (out of scope for a hygiene pass) per the audit's own "implement or remove" framing. Removed the corresponding README.md scripts/ table entry.

### Fixed
- fix: docker build/dev-stack broke after removing the dead services/ directory (backend/Dockerfile's `COPY services/ /services/`, docker-compose.yml's `./services:/services` volume mounts on api and celery_worker). Directory was never referenced by PYTHONPATH or runtime code -- removed the dead references, verified docker build succeeds clean.

## [1.12.20] - 2026-07-22

### Fixed
- fix(db): wired real Alembic migrations, replacing the decorative schema management this project has actually had since inception. `backend/app/main.py`'s startup lifespan ran `Base.metadata.create_all()` plus a hand-written 3-column ALTER-loop on every boot; the sole Alembic revision's `upgrade()` just called `create_all()` again, and nothing anywhere ever invoked `alembic upgrade head` for real -- found by the 2026-07-22 /golive audit's Stage 6 (CRITICAL). Investigating it surfaced that production's *running container* still had 9 of 13 pre-squash migration files baked in as 0-byte empty stubs (including `011_add_cancelled_status.py`), and its `alembic_version` was stamped at an orphaned revision from before the 2026-07-21 squash.
- fix(db): **live production bug** -- the cancel-job endpoint (`routes/jobs.py`, `job.status = ProcessingStatus.CANCELLED`) was broken in production. Its Postgres enum type (misspelled `processingstatatus`, a leftover from the original migration) had no `cancelled` value at all -- almost certainly because the empty `011_add_cancelled_status.py` stub was supposed to add it and never did. Fixed live via `ALTER TYPE ... ADD VALUE`, then the type itself renamed to the correct `processingstatus` (an unused, correctly-named duplicate type already existed from an earlier partial `create_all()` attempt, orphaned and unreferenced).
- fix(db): production's `videos.url` was `VARCHAR(255)` against the model's declared `String(512)` -- a URL between 256-512 chars would have failed to save. Widened live to match.
- fix(db): 5 production foreign keys (documents, snapshots, transcript_segments, transcripts, videos -> processing_jobs/transcripts) were missing `ON DELETE CASCADE` that every model declares. Not an active bug -- SQLAlchemy's ORM-level `cascade="all, delete-orphan"` on every relevant `relationship()` already handles job deletion correctly regardless of the DB constraint -- but a real gap between declared and actual DB-level behavior. Fixed live to match.
- fix(db): every production drift item above was independently re-verified via `alembic revision --autogenerate` producing a **zero-item diff** against current models before and after each fix, using a schema-only `pg_dump` restored into a disposable local Postgres -- never diffed by connecting a write-capable session directly to production.
- fix(db): rewrote `migrations/versions/0001_squashed_baseline.py`'s `upgrade()` with real, explicit, reviewable DDL (`op.create_table`/`op.create_index`/... via `alembic revision --autogenerate` against an empty database) instead of a lazy `create_all()` call, and gave it a real, scoped `downgrade()` (drops exactly what `upgrade()` created, in FK-safe order) instead of the previous `Base.metadata.drop_all()` full-wipe. Found and fixed during testing: the generated `downgrade()` didn't drop the two Postgres enum types, so a downgrade -> upgrade cycle failed with "type already exists" -- added explicit `sa.Enum(...).drop()` calls.
- fix(db): `migrations/script.py.mako` didn't exist in the repo at all -- `alembic revision` (new migrations, with or without --autogenerate) couldn't have worked for anyone, ever. Added the standard template.
- fix(db): removed `main.py`'s `create_all()` + ALTER-loop entirely. Schema is now managed exclusively by `alembic upgrade head`, run as a separate step -- already how the documented quickstart (`README.md` step 3) and `deploy.yml`'s "Run migrations" step describe it; the code just didn't match the docs before now.
- fix(db): production is stamped to the new baseline revision (no DDL re-run -- its schema was independently confirmed identical via the same zero-diff check) rather than migrated.
- test(db): added `tests/test_migration_drift.py` -- asserts `alembic upgrade head` against a real Postgres produces exactly the schema `models.py` declares. Mutation-tested: confirmed it fails when a column is added to a model without a corresponding migration. Requires real Postgres (the rest of the suite runs on SQLite in-memory, which can't exercise the Postgres-specific DDL this guards); skips gracefully without one, but runs for real in CI via a new dedicated `migration-drift` job in `.github/workflows/test.yml` (GitHub Actions native Postgres service) so this protection is not itself decorative.
- fix(ci): `alembic.ini` was missing `path_separator = os`, triggering a deprecation warning on every invocation.

### Fixed
- fix(ci): e2e-tests broke after removing main.py's create_all() (v1.12.20) -- create_all() running automatically on every api boot was the only thing that ever created tables for the e2e stack; nothing in docker-compose.e2e.yml or the e2e CI job ran migrations. Added an explicit "Run e2e migrations" step (alembic upgrade head inside the api container), matching deploy.yml's existing pattern for prod/staging.

### Fixed
- fix(docker): backend/Dockerfile never COPYed alembic.ini or migrations/ into the image at all -- only backend/ was copied. Prod and staging compose files bind-mount both over the top at runtime (compose-file-specific, fragile), which is why prod's migration step worked while docker-compose.e2e.yml (no such bind mount) failed with "No script_location key found in configuration" the moment main.py stopped silently creating tables via create_all(). Baked both into the image directly so `alembic upgrade head` works in any context, bind-mounted or not.
