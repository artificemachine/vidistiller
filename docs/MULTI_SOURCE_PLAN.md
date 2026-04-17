# Multi-Source Video Support Plan

**Goal:** Accept video URLs from any major platform, not just YouTube.
**Date:** 2026-04-17
**Status:** Planning

---

## Realistic Sources to Support, Grouped by Priority

### Tier 1 — High value, works reliably with yt-dlp (v1 scope)

| Source | Notes |
|--------|-------|
| **YouTube** | Already supported |
| **Vimeo** | Pro, On Demand, private with password |
| **Twitch** | VODs, clips, live streams |
| **Twitter / X.com** | Same yt-dlp extractor, both domains work |
| **TikTok** | Videos, user pages |
| **Reddit** | Video posts (v.redd.it) |
| **Rumble** | YouTube alternative, growing user base |
| **Direct MP4/video URL** | Any `.mp4`, `.webm`, `.mov` link — yt-dlp handles natively |

### Tier 2 — Supported but with friction (auth, geo, rate limits)

| Source | Notes |
|--------|-------|
| **Instagram** | Requires login for most content |
| **Facebook** | Often requires login/cookies |
| **Dailymotion** | Works well, smaller user base |
| **Bilibili** | Works, mostly Chinese content |
| **Odysee / LBRY** | Works |
| **Streamable** | Short clips, works fine |

### Tier 3 — Not in scope for v1

| Source | Notes |
|--------|-------|
| **LinkedIn** | Learning videos only, heavy auth |
| **Kick** | Live streaming, VODs still limited |
| **PeerTube** | Federated, dozens of instances |
| **TikTok Live** | Ephemeral, no transcript value |

**v1 scope: Tier 1 + direct MP4 URLs only.**
Instagram and Facebook require cookie/session management that adds significant complexity.

---

## Blast Radius Summary

| Component | File | Severity |
|-----------|------|----------|
| URL validation | `schemas.py` | CRITICAL |
| Video ID extraction | `youtube.py` | CRITICAL |
| Video player component | `YouTubePlayer.tsx` | CRITICAL |
| Database schema | `models.py` | HIGH |
| Field naming (`youtube_url`) | All files | HIGH |
| Caption fetching strategy | `tasks.py` | HIGH |
| Metadata response shape | `videos.py` | MEDIUM |
| Export/import format | `jobs.py` | MEDIUM |
| LLM summarization context | `tasks.py` | LOW |

---

## Implementation Phases

---

### Phase 1 — Backend Type System (no migrations, no breakage)

**Goal:** Remove the YouTube gatekeepers without touching the DB or API contract.

#### 1.1 — Add `SourceType` enum

Create `backend/app/core/source_type.py`:

```python
class SourceType(str, Enum):
    YOUTUBE = "youtube"
    VIMEO = "vimeo"
    TWITCH = "twitch"
    TWITTER = "twitter"
    TIKTOK = "tiktok"
    REDDIT = "reddit"
    RUMBLE = "rumble"
    DIRECT = "direct"
    UNKNOWN = "unknown"
```

#### 1.2 — Create `VideoSourceResolver`

New file: `backend/app/services/source_resolver.py`

- `resolve(url: str) -> tuple[SourceType, str]` — detects platform and extracts a source-specific ID
- Uses yt-dlp's `extract_info(url, download=False)` to detect extractor name when regex is insufficient
- Replaces `YouTubeService.extract_video_id()` as the single entry point for URL parsing
- YouTube ID stays 11 chars; Vimeo is numeric; Twitter/X is numeric; TikTok is numeric; direct URLs use a hash of the URL

#### 1.3 — Refactor `YouTubeService` into `VideoService`

Rename `backend/app/services/youtube.py` → `backend/app/services/video.py`:

- `get_video_metadata(url)` — already uses yt-dlp internally, remove the `extract_video_id()` guard
- `download_audio(url)` — replace `{video_id}.mp3` filename with `{source_type}_{source_id}.mp3`
- `get_captions(url)` — delegate to `CaptionProvider` based on `SourceType`

#### 1.4 — Create `CaptionProvider` interface

New file: `backend/app/services/caption_providers.py`:

- Abstract base: `CaptionProvider.fetch(url, source_id, language) -> Optional[str]`
- `YouTubeCaptionProvider` — wraps existing `YouTubeTranscriptApi` logic
- `YtdlpCaptionProvider` — wraps existing yt-dlp subtitle extraction (works for Vimeo, Twitch, etc.)
- `WhisperCaptionProvider` — fallback, wraps existing Ollama Whisper logic

Fallback chain in `tasks.py`:
```
Platform-native captions → yt-dlp subtitles → Whisper transcription
```

#### 1.5 — Update `tasks.py`

- `_fetch_youtube_captions()` → `_fetch_captions(url, source_type)` dispatching to the right provider
- Remove hard dependency on `YouTubeService`; inject `VideoService` + `VideoSourceResolver`

**Tests (RED first):**
- `test_source_resolver.py` — assert correct `SourceType` and ID for YouTube, Vimeo, Twitter/X, TikTok, Reddit, Rumble, direct MP4 URLs
- `test_caption_providers.py` — mock each provider, assert fallback chain order

---

### Phase 2 — Database + API (one migration, breaking rename)

**Goal:** Clean up the data layer and expose a source-agnostic API.

#### 2.1 — Alembic migration

New migration: `migrations/versions/XXX_multi_source_support.py`

Changes:
- Rename `processing_jobs.youtube_url` → `processing_jobs.video_url`
- Expand `videos.video_id` from `String(20)` to `String(100)`
- Add `processing_jobs.source_type` column (`String(20)`, nullable, default `"youtube"`)
- Add `videos.source_type` column (`String(20)`, nullable, default `"youtube"`)

Existing rows: backfill `source_type = "youtube"` for all existing records.

#### 2.2 — Update `models.py`

- `ProcessingJob.youtube_url` → `ProcessingJob.video_url`
- `ProcessingJob.source_type: Mapped[str]`
- `Video.video_id: String(100)`
- `Video.source_type: Mapped[str]`

#### 2.3 — Update `schemas.py`

- `JobCreate.youtube_url` → `JobCreate.video_url`
- Replace `validate_youtube_url()` with `validate_video_url()` — accept any URL that yt-dlp can handle (strategy: attempt `ydl.extract_info` with `download=False`; if it raises `DownloadError`, reject)
- Add `source_type: SourceType` to `JobCreate`, `JobResponse`, `VideoResponse`

#### 2.4 — Update routes

- `routes/jobs.py`: rename field references, add `source_type` to responses
- `routes/videos.py`: remove `YouTubeURLRequest`; accept generic URL; return `source_type` in metadata response
- Update OpenAPI doc strings

**Tests (RED first):**
- `test_schemas.py` — assert Vimeo, Twitch, Twitter, TikTok, Rumble, direct MP4 URLs all pass `validate_video_url()`
- `test_migration.py` — assert existing YouTube rows get `source_type = "youtube"` after migration

---

### Phase 3 — Frontend

**Goal:** Accept non-YouTube URLs and play non-YouTube videos.

#### 3.1 — Replace `YouTubePlayer.tsx` with `VideoPlayer`

Install: `npm install react-player`

- New component: `frontend/components/VideoPlayer.tsx` wrapping `react-player`
- `react-player` natively handles YouTube, Vimeo, Twitch, Twitter/X, TikTok, Facebook, Dailymotion, direct MP4
- Drop `YouTubePlayer.tsx` entirely
- Props interface: `{ url: string; sourceType: SourceType }` — `react-player` uses `url` directly

#### 3.2 — Update `page.tsx` (submission form)

- Field name: `youtube_url` → `video_url`
- Label: `"YouTube URL"` → `"Video URL"`
- Placeholder: `"https://www.youtube.com/watch?v=..."` → `"YouTube, Vimeo, Twitch, X.com, TikTok, Reddit, Rumble or direct .mp4 link"`
- Copy: `"works with any YouTube video"` → `"works with any video from supported platforms"`

#### 3.3 — Update `jobs/[id]/page.tsx`

- Rename `job.youtube_url` → `job.video_url`
- Pass `source_type` to `VideoPlayer`
- Update conditional render: `showPlayer = job.status === 'completed' && job.video_url`

#### 3.4 — Update `types/index.ts`

- `ProcessingJob.youtube_url` → `ProcessingJob.video_url`
- Add `source_type: SourceType` to `ProcessingJob`, `Transcript`, `VideoMetadata`

**Tests (RED first):**
- Update existing Vitest + RTL tests for renamed props
- Add snapshot test for `VideoPlayer` rendering Vimeo URL

---

### Phase 4 — Export/Import + Polish

**Goal:** Preserve source context across export/import and clean up remaining references.

#### 4.1 — Update export format in `jobs.py`

- Include `source_type` in exported JSON
- Update import logic to read and restore `source_type`

#### 4.2 — Update LLM prompts in `tasks.py`

- Pass `source_type` to summarization context
- Header line: `Source: {video_url} ({source_type})` instead of just the URL

#### 4.3 — Search and replace remaining `youtube_url` references

Files to audit: all routes, tasks, schemas, test files, frontend components, E2E tests.

#### 4.4 — Update E2E tests

- `e2e/` — update any Playwright tests that submit a YouTube URL to also test a Vimeo or direct MP4 URL

---

## File Changelog

| File | Change |
|------|--------|
| `backend/app/core/source_type.py` | NEW — `SourceType` enum |
| `backend/app/services/source_resolver.py` | NEW — `VideoSourceResolver` |
| `backend/app/services/caption_providers.py` | NEW — `CaptionProvider` interface + implementations |
| `backend/app/services/youtube.py` | REFACTOR → `video.py`, remove YouTube guards |
| `backend/app/services/transcript.py` | UPDATE — use `CaptionProvider` |
| `backend/app/tasks.py` | UPDATE — dispatch by source type |
| `backend/app/schemas.py` | UPDATE — `video_url`, generic validator |
| `backend/app/db/models.py` | UPDATE — rename column, expand `video_id`, add `source_type` |
| `migrations/versions/XXX_multi_source.py` | NEW — Alembic migration |
| `backend/app/routes/videos.py` | UPDATE — generic URL input/output |
| `backend/app/routes/jobs.py` | UPDATE — `video_url`, `source_type` |
| `frontend/components/YouTubePlayer.tsx` | DELETE |
| `frontend/components/VideoPlayer.tsx` | NEW — react-player wrapper |
| `frontend/app/page.tsx` | UPDATE — label, placeholder, field name |
| `frontend/app/jobs/[id]/page.tsx` | UPDATE — `video_url`, `source_type` |
| `frontend/types/index.ts` | UPDATE — add `source_type`, rename field |

---

### Phase 5 — Rename to Vidistiller

**Goal:** Rebrand the project from `youtube-model-feeder` to **Vidistiller** across the entire stack.

**Rationale:** `vid` + `stiller` — "the thing that distills video." Source-agnostic name that fits the expanded Tier 1 source list. Matches the agent-noun naming family: Phraser, Ozarys, Nocture, Vidistiller.

#### 5.1 — Repository

- Rename GitHub repo: `youtube-model-feeder` → `vidistiller`
- Update local remote URL after rename

#### 5.2 — Package manifests

- `frontend/package.json`: `"name": "youtube-model-feeder"` → `"name": "vidistiller"`
- `backend/pyproject.toml` (if present): update `name` field

#### 5.3 — Frontend internals

- `localStorage` key: `youtube-model-feeder-theme` → `vidistiller-theme` (search all `lib/themes.ts`, `localStorage` calls)
- Update `<title>` / `<meta name="description">` in `layout.tsx` or `_document.tsx`
- Update any hardcoded copy referencing "youtube-model-feeder"

#### 5.4 — Docker + Compose

- `docker-compose.yml` service/image names: `viddocs-*` → `vidistiller-*`
- Docker image tags in build/push scripts
- Any `COMPOSE_PROJECT_NAME` env var or `.env` reference

#### 5.5 — Design files

- `.pen` design file: `new_youtube-model-feeder_ui.pen` → `new_vidistiller_ui.pen`
- `DESIGN_SPEC.md`, `DESIGN_EXPORT_GUIDE.md`, `DESIGN_README.md` — update project name references

#### 5.6 — CI/CD

- `.github/workflows/` — update workflow names, job names, and any artifact paths that reference `youtube-model-feeder`
- Terraform resource names (if applicable)

#### 5.7 — Documentation + README

- Replace `youtube-model-feeder` in all `docs/`, `README.md`, `CHANGELOG.md` headers with Vidistiller
- Use the README draft from vault `1_ai/youtube_converter/vidistiller_readme_description.md` as the new `README.md` body

#### 5.8 — Database + migrations

- Verify no project name is stored in the schema or seed data
- If `COMPOSE_PROJECT_NAME` affects Postgres volume names, document the migration path for existing deployments

#### 5.9 — LXC deployment

- After rename, re-run `rsync` with new paths; update any systemd units or cron jobs on `yt-model-feeder-lxc` that reference the old directory name
- Update `~/.ssh/config` Host alias if desired (`yt-model-feeder-lxc` → `vidistiller-lxc`)

---

## Dependencies

| Package | Where | Purpose |
|---------|-------|---------|
| `react-player` | frontend | Multi-source video player abstraction |
| `yt-dlp` | backend (already installed) | Metadata + audio extraction for all sources |
| `youtube-transcript-api` | backend (already installed) | YouTube-only captions, kept as one provider |

No new backend Python dependencies required for Tier 1 sources.

---

## Risks

| Risk | Mitigation |
|------|------------|
| Alembic migration on existing production data | Backfill `source_type = "youtube"` for all rows; test with a copy of prod DB first |
| `react-player` adds bundle size | It is lazy-loadable; only the YouTube iframe loads by default unless another provider is triggered |
| TikTok / Twitter rate limiting | These sources are lower reliability; Whisper fallback catches failures |
| Renaming `youtube_url` breaks existing API consumers | API version bump; old field kept as deprecated alias for one release |
