# Vidistiller

**Turn any video into structured documentation.**

Vidistiller is a local-first, source-agnostic video-to-documentation engine. Paste a URL from YouTube, Vimeo, Twitch, X, Reddit, Rumble, or any direct MP4 link — Vidistiller distills the video down to what matters: the spoken words, the slides, the structure. Hours of watching become minutes of reading.

---

## <span style="color: pink;">Architecture Diagram</span>

The diagram below shows how every component connects at runtime.

```
                          ┌──────────────────────────────────────────────────┐
                          │                   User / Browser                 │
                          └──────────────────────┬───────────────────────────┘
                                                 │  HTTP (port 3000)
                                                 ▼
                          ┌──────────────────────────────────────────────────┐
                          │             web  (Next.js Frontend)              │
                          │  React + TypeScript · Tailwind CSS               │
                          │  Submits video URLs, displays generated docs     │
                          └──────────────────────┬───────────────────────────┘
                                                 │  HTTP REST (port 8000)
                                                 ▼
                          ┌──────────────────────────────────────────────────┐
                          │             api  (FastAPI Backend)               │
                          │  Receives requests · Validates input             │
                          │  Queues background jobs · Returns results        │
                          └───┬──────────┬──────────┬───────────────────────┘
                              │          │          │
               ┌──────────────┘          │          └──────────────┐
               │                         │                         │
               ▼                         ▼                         ▼
  ┌────────────────────┐   ┌────────────────────┐   ┌────────────────────────┐
  │  postgres (DB)     │   │  redis (Cache +    │   │  LLM (multi-provider)  │
  │  PostgreSQL 15     │   │  Message Broker)   │   │  Ollama/OpenAI/Claude  │
  │  Stores all data:  │   │  Redis 7           │   │  Generates structured  │
  │  jobs, videos,     │   │  Caches results,   │   │  documentation from    │
  │  transcripts,      │   │  rate limits,      │   │  transcripts           │
  │  snapshots, docs   │   │  delivers tasks    │   └────────────────────────┘
  └────────────────────┘   │  to Celery         │
                           └─────────┬──────────┘
                                     │  task queue (Redis as broker)
                                     ▼
                          ┌──────────────────────────────────────────────────┐
                          │         celery_worker  (Background Tasks)        │
                          │  Same codebase as api, different startup command  │
                          │                                                  │
                          │  ┌─────────────┐  ┌──────────────┐              │
                          │  │  Video       │  │  Transcript  │              │
                          │  │  Service     │  │  Service     │              │
                          │  │  (download)  │  │  (Whisper)   │              │
                          │  └─────────────┘  └──────────────┘              │
                          │  ┌─────────────┐  ┌──────────────┐              │
                          │  │  Snapshot    │  │  LLM         │              │
                          │  │  Service     │  │  Service     │              │
                          │  │  (FFmpeg)    │  │  (Ollama)    │              │
                          │  └─────────────┘  └──────────────┘              │
                          │  ┌─────────────────────────────┐               │
                          │  │  Slide Detection Service    │               │
                          │  │  (SSIM + Tesseract OCR)     │               │
                          │  └─────────────────────────────┘               │
                          └──────────────────────────────────────────────────┘

  ┌──────────────────────────────────────────────────────────────────────────┐
  │  pgadmin — Web UI for database administration (development only)        │
  │  Accessible at http://localhost:${PGADMIN_PORT}                         │
  └──────────────────────────────────────────────────────────────────────────┘
```

### Data Flow (step by step)

```
1. User pastes a video URL in the frontend
2. Frontend sends POST request to the API
3. API validates the URL, creates a ProcessingJob in PostgreSQL, and pushes a task to Redis
4. Celery worker picks up the task from Redis and runs the pipeline:
   a. Video Service    → downloads the video and extracts metadata
   b. Transcript Service → converts audio to text (via Ollama Whisper)
   c. Snapshot Service  → extracts key frames with FFmpeg
   d. LLM Service       → generates structured markdown/HTML documentation
5. Results are saved back to PostgreSQL
6. Frontend polls the API and displays the finished documentation
```

---

## <span style="color: pink;">Presentation Mode (Slide Detection)</span>

For **presentation-style videos** (tech talks, lectures, tutorials with slides), enable **Presentation Mode** to automatically detect and extract slides.

### How it works

When Presentation Mode is toggled on before submitting a URL, the pipeline adds a slide detection phase after transcription:

1. **Layout Detection** — Classifies the video as `full_frame`, `pip_speaker` (picture-in-picture), or `split_panel`
2. **SSIM Transition Scan** — Compares consecutive frames using Structural Similarity Index to find slide changes
3. **LLM Ambiguity Classification** — For borderline transitions (SSIM 0.85–0.93), the LLM classifies them as real transitions or incremental builds
4. **Slide Grouping** — Merges transitions into distinct slides with enforced minimum duration (3s)
5. **Final State Capture** — Extracts the last frame of each slide and saves it as a JPEG
6. **OCR** — Runs Tesseract on each slide image to extract on-screen text
7. **Transcript Alignment** — Maps spoken words to each slide by matching timestamp ranges

### What you get

Each detected slide includes:
- **Slide image** — The final-state frame captured from the video
- **OCR text** — Text detected in the slide image (requires `tesseract`)
- **Transcript text** — What the speaker said during that slide's time window
- **Timestamp range** — When the slide appeared in the video

### Example video

A good test case is a **conference talk with slides**, such as:

```
https://www.youtube.com/watch?v=aolI_Rz0ZqY
```

> *"So You Think You Know Git?" — Scott Chacon at FOSDEM 2024*
> Clean slide transitions, English captions, standard presentation layout.

This type of video typically produces 20–40 well-defined slides with OCR text and aligned transcript. Sports videos or vlogs are **not** good candidates — they have no actual slides, so every scene change gets flagged as a transition.

### Requirements

- **Tesseract** must be installed for OCR (`brew install tesseract` on macOS, `apk add tesseract-ocr` in Docker)
- **Ollama** is needed for LLM ambiguity classification (optional — only used for borderline transitions)

---

## <span style="color: pink;">🎨 Design System — Multi-Theme</span>

The Vidistiller UI supports three palettes switchable at runtime: **Monokai** (default, dark), **Lunaris**, and **Nord**. The active palette is persisted to `localStorage` as `vidistiller-theme`.

### Design Files & Documentation

- **Design File:** [`new_vidistiller_ui.pen`](./new_vidistiller_ui.pen) — Complete Pencil design with all screens and Monokai colors
- **Design Specification:** [`DESIGN_SPEC.md`](./DESIGN_SPEC.md) — Full design system details, colors, typography, and spacing
- **Implementation Guide:** [`DESIGN_EXPORT_GUIDE.md`](./DESIGN_EXPORT_GUIDE.md) — Code implementation patterns for React/Tailwind
- **Quick Reference:** [`DESIGN_README.md`](./DESIGN_README.md) — 5-minute overview of the design system

### Key Design Tokens

**Palettes:**

| Token | Monokai (default) | Lunaris | Nord |
|---|---|---|---|
| Primary | `#BFFF3F` (lime) | `#FF8400` (orange) | `#88C0D0` (blue) |
| bg-dark | `#272822` | `#111111` | `#243353` |
| bg-light | `#FDF6E3` | `#F2F3F0` | `#ECF0F4` |

**Status colors (theme-independent):**
- Success: `#22C55E` | Warning: `#FFB547` | Destructive: `#FF5C33`

**Typography:**
- Sans: Arial, Helvetica
- Mono: Fira Code

### Open in Pencil

To view or edit the design:
```bash
open new_vidistiller_ui.pen
```

The design includes:
- 8 main screens (Home, Job Detail, Settings, Login, Register, Forgot Password, Reset Password, Dashboard)
- Component library with buttons, inputs, badges, cards
- Mobile views (iPhone 14)
- State variations (Loading, Error, Success)

---

## <span style="color: pink;">Explanation of Each Part</span>

### `backend/` — FastAPI Backend

The Python server that powers the entire application. Built with [FastAPI](https://fastapi.tiangolo.com/), it:

- **Receives HTTP requests** from the frontend (submit URL, check job status, fetch results).
- **Validates input** using Pydantic schemas (`schemas.py`, `models.py`).
- **Persists data** via SQLAlchemy ORM models in `db/models.py`, connected through the session factory in `db/session.py`.
- **Queues background work** by dispatching Celery tasks (defined in `tasks.py`) through Redis.
- **Exposes interactive docs** automatically at `/docs` (Swagger UI).

Configuration is centralized in `core/config.py` and loaded from the `.env` file.

### `frontend/` — Next.js Frontend

The user-facing web application. Built with [Next.js](https://nextjs.org/) (App Router), React, TypeScript, and Tailwind CSS.

- **`app/`** uses file-based routing: each folder becomes a URL path. `[id]` is a dynamic segment (e.g., `/jobs/abc-123`).
- **`components/`** contains the UI building blocks — a form to submit URLs, progress bars, transcript viewers, image galleries, and document renderers.
- **`services/api.ts`** and **`lib/api.ts`** handle all HTTP communication with the backend.
- **`hooks/`** provides custom React hooks for data fetching and polling job status.

### `backend/app/services/` — Core Service Modules

Self-contained Python modules that encapsulate the core processing logic, all located in `backend/app/services/`.

| Service | What it does |
|---|---|
| `video.py` | Downloads the video, extracts metadata (title, channel, duration, thumbnail), resolves source type |
| `transcript.py` | Sends audio to Whisper, returns timestamped text segments |
| `snapshot.py` | Uses FFmpeg to extract key frames at configurable intervals |
| `llm.py` | Sends transcript + snapshots to LLM (Ollama, OpenAI, or Anthropic), returns structured documentation |

### `migrations/` — Database Migrations (Alembic)

[Alembic](https://alembic.sqlalchemy.org/) manages database schema changes. Each file in `versions/` is a migration script with `upgrade()` and `downgrade()` functions, ensuring every environment (local, CI, production) has an identical database schema.

### `tests/` — Backend Test Suite

[Pytest](https://docs.pytest.org/) test files. `conftest.py` provides shared fixtures (test database sessions, mocked services). Run the full suite with `pytest tests/`.

### `frontend/__tests__/` — Frontend Test Suite

[Vitest](https://vitest.dev/) + [React Testing Library](https://testing-library.com/docs/react-testing-library/intro/) tests for React components and utilities. Run with `cd frontend && npm test`.

### `config/` — Configuration Templates

Python modules for database, logging, and general settings. These provide defaults and helpers used during app initialization.

### `scripts/` — Utility Scripts

Automation helpers for common tasks:
- `init-docker.sh` — first-time Docker environment bootstrap
- `init_db.py` — seeds the database with initial data
- `health-check.sh` — verifies all services are running
- `batch_process.py` — processes multiple YouTube URLs in one go

### `terraform/` — Infrastructure as Code

[Terraform](https://www.terraform.io/) definitions for deploying the application to AWS. Defines cloud resources (VPC, ECS, RDS, ElastiCache, etc.) and outputs connection details after `terraform apply`.

### `.github/workflows/` — CI/CD

A GitHub Actions pipeline template for automated testing and deployment on push/PR.

---

## <span style="color: pink;">Docker Compose Files</span>

The project includes three Compose files, each serving a different purpose:

### `docker-compose.yml` — Full Development Stack

The main file. Starts **all 6 services** needed for local development:

| Service | Role |
|---|---|
| `postgres` | PostgreSQL 15 database |
| `redis` | Cache + Celery message broker |
| `api` | FastAPI backend (port 8000) |
| `celery_worker` | Background task processor |
| `web` | Next.js frontend (port 3000) |
| `pgadmin` | Database admin UI |

```bash
docker-compose up -d          # start everything
docker-compose logs -f api    # follow API logs
docker-compose down           # stop everything
```

### `docker-compose.test.yml` — Test Infrastructure Only

A **lightweight** file that spins up **only postgres and redis** with hardcoded credentials. It exists so you can run `pytest` on your host machine (or in CI) against real database and cache instances, without starting the full stack.

Key differences from the main file:
- **2 services** instead of 6 (no api, celery, web, or pgadmin)
- **Hardcoded credentials** (`tutorial_user` / `tutorial_password`) so tests are reproducible without a `.env` file
- **Faster health checks** (5s interval vs 10s) for quicker test startup

```bash
docker-compose -f docker-compose.test.yml up -d   # start test infra
pytest tests/                                       # run tests against real postgres + redis
docker-compose -f docker-compose.test.yml down      # tear down
```

### `docker-compose.override.yml` — Local Overrides

Automatically merged with `docker-compose.yml` by Docker Compose. Use this for personal developer customizations (extra port mappings, debug flags, volume overrides) without touching the shared main file.

---

## <span style="color: pink;">Getting Started</span>

1. **Clone the repository** and copy the environment template:
   ```bash
   cp .env.example .env
   # Edit .env with your local values
   ```

2. **Start all services:**
   ```bash
   # Optional: remove all containers and images first
   docker-compose down --rmi all

   # Start all services
   docker-compose down && 
   docker-compose up -d && 
   sleep 60 && 
   docker-compose ps

   ```

3. **Run database migrations:**
   ```bash
   docker-compose exec api alembic upgrade head
   ```

4. **Open the app:**
   - Frontend: `http://localhost:3000`
   - API docs: `http://localhost:8000/docs`
   - pgAdmin: `http://localhost:5050`

See [DOCKER.md](docs/DOCKER.md) for troubleshooting and [DEPLOYMENT.md](docs/DEPLOYMENT.md) for production setup.

---

## <span style="color: pink;">Running the Frontend Alone</span>

If you just want to preview the UI in your browser without starting the full stack:

### Option 1 — Directly on your host (no Docker)

```bash
cd frontend && npm install && npm run dev
```

Output
```bash
added 130 packages, and audited 131 packages in 21s

29 packages are looking for funding
  run `npm fund` for details

1 high severity vulnerability

To address all issues (including breaking changes), run:
  npm audit fix --force

Run `npm audit` for details.

> vidistiller@1.1.0 dev
> next dev

  ▲ Next.js 14.2.35
  - Local:        http://localhost:3000

 ✓ Starting...
Attention: Next.js now collects completely anonymous telemetry regarding usage.
This information is used to shape Next.js' roadmap and prioritize features.
You can learn more, including how to opt-out if you'd not like to participate in this anonymous program, by visiting the following URL:
https://nextjs.org/telemetry


   We detected TypeScript in your project and reconfigured your tsconfig.json file for you. Strict-mode is set to false by default.
   The following suggested values were added to your tsconfig.json. These values can be changed to fit your project's needs:

   	- allowJs was set to true
   	- incremental was set to true
   	- include was updated to add '.next/types/**/*.ts'
   	- plugins was updated to add { name: 'next' }

   The following mandatory changes were made to your tsconfig.json:

   	- moduleResolution was set to node (to match webpack resolution)
   	- jsx was set to preserve (next.js implements its own optimized jsx transform)
...
```

This starts the Next.js dev server at `http://localhost:3000`. The UI will load and render, but any API calls to the backend will fail since the API isn't running.

### Option 2 — Only the web container (skip dependencies)

```bash
docker-compose up -d --no-deps web
```

The `--no-deps` flag tells Compose to start **only** the `web` container and ignore its `depends_on` chain (`api` -> `postgres` + `redis`). The UI will render but API requests will fail without the backend.

> **Note:** Running `docker-compose up -d web` (without `--no-deps`) will also start `api`, `postgres`, and `redis` automatically because of the dependency chain defined in `docker-compose.yml`.

---

## <span style="color: pink;">Running the Backend Alone</span>

If you want to work on the API without starting the frontend, Celery worker, or pgAdmin:

### Option 1 — Directly on your host (no Docker)

You still need PostgreSQL and Redis running (either locally installed or via the test compose file):

```bash
# Start only the database and cache
docker-compose -f docker-compose.test.yml up -d

# Install Python dependencies
cd backend && pip install -r requirements.txt

# Run database migrations
alembic upgrade head

# Start the FastAPI dev server with auto-reload
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at `http://localhost:8000` with interactive docs at `http://localhost:8000/docs`.

### Option 2 — Only the API container (with its dependencies)

```bash
docker-compose up -d api
```

This starts `api`, `postgres`, and `redis` (because `api` depends on both being healthy), but **does not** start `web`, `celery_worker`, or `pgadmin`.

### Option 3 — API + Celery worker (for background job processing)

```bash
docker-compose up -d api celery_worker
```

This starts `api`, `celery_worker`, `postgres`, and `redis` — everything needed for the full backend pipeline without the frontend or pgAdmin.

> **Note:** Without the `celery_worker`, the API can still receive requests and create jobs, but no background processing (video downloads, transcription, document generation) will happen.
