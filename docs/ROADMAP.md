# Vidistiller Roadmap

## Auth
- [ ] Email verification on register
- [ ] OAuth login (Google/GitHub)
- [ ] Rate limiting on login endpoint

## UX
- [ ] Progress bar for video processing
- [ ] Drag-and-drop URL input
- [ ] Batch video processing

## Export
- [ ] PDF export
- [ ] Notion export
- [ ] Improve Obsidian export formatting

## Infra
- [ ] HTTPS/TLS via Caddy reverse proxy
- [x] CI/CD pipeline (GitHub Actions) — `.github/workflows/{test,security,deploy,docker-publish,gitleaks}.yml` all run on every push/PR; the 2026-04-26 incident (green CI didn't catch a broken release) was a fix to the run-on-push posture, so the pipeline blocks a release on broken tests
- [ ] Backup strategy (PostgreSQL + data) — backup scripts drafted at `docs/VM_DEPLOYMENT.md` ~line 840; automated-restore drill not yet run, leaving this `[ ]` until that drill confirms end-to-end recoverability

## Quality
- [x] E2E tests with Playwright
- [x] Error monitoring with Sentry
- [x] Structured logging

## Features
- [ ] YouTube playlist support
- [ ] Video chapter detection
- [ ] Custom prompt templates for summarization
