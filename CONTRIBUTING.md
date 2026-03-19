# Contributing to youtube-model-feeder

Thanks for your interest in contributing! Here's how to get started.

## Prerequisites

- Docker and Docker Compose
- Python 3.10+
- Node.js >= 18

## Setup

```bash
git clone https://github.com/celstnblacc/youtube-model-feeder.git
cd youtube-model-feeder
cp .env.example .env  # edit with your settings
docker compose up -d
```

## Development workflow

1. **Fork** the repo and create a branch from `main`.
2. Make your changes.
3. Test locally with `docker compose up`.
4. Open a Pull Request against `main`.

## What to contribute

- Bug fixes (check open issues)
- Improvements to transcription, snapshot extraction, or doc generation
- Frontend UI improvements
- Tests and documentation fixes

Issues labeled `good first issue` or `help wanted` are a great starting point.

## Architecture

- **api/** — FastAPI backend
- **web/** — Next.js frontend (React + TypeScript + Tailwind)
- **celery_worker** — Background tasks (YouTube download, Whisper transcription, FFmpeg snapshots, LLM doc generation)
- **postgres** — Data storage
- **redis** — Task queue broker
- **ollama** — Local LLM (Mistral 7B)

## Commit messages

Keep commits focused. Use a short summary line describing what changed and why.

## Reporting bugs

Open an issue with:
- What you expected to happen
- What actually happened
- Steps to reproduce
- Docker Compose logs if relevant

## License

By contributing, you agree that your contributions will be licensed under the [Apache License 2.0](LICENSE).
