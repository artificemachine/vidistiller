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
