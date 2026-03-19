# Technology Stack — youtube-model-feeder

## Overview
This project uses a modern microservices architecture with containerized services orchestrated via Docker Compose.

---

## Frontend Technologies

### Core Framework
- **Next.js 14.0.0** - React framework with App Router for server-side rendering and routing
- **React 18.2.0** - UI library for building component-based interfaces
- **TypeScript 5.0.0** - Type-safe JavaScript superset

### UI & Styling
- **Tailwind CSS 3.3.0** - Utility-first CSS framework
- **PostCSS 8.4.0** - CSS transformation and autoprefixer
- **react-resizable-panels 4.6.2** - Resizable layout components

### State Management & Data Fetching
- **Zustand 4.4.0** - Lightweight state management
- **SWR 2.2.0** - React hooks for data fetching with caching
- **Axios 1.6.0** - HTTP client for API requests
- **JSZip** - ZIP file generation for Obsidian export bundles

### Testing
- **Vitest 4.0.18** - Fast unit test framework
- **@testing-library/react 16.3.2** - React component testing utilities
- **@testing-library/jest-dom 6.9.1** - Custom Jest matchers for DOM
- **@testing-library/user-event 14.6.1** - User interaction simulation
- **jsdom 28.0.0** - DOM implementation for Node.js

### Build Tools
- **@vitejs/plugin-react 5.1.3** - Vite plugin for React Fast Refresh
- **Node.js 18** - JavaScript runtime (Alpine Linux variant)

---

## Backend Technologies

### Core Framework
- **FastAPI 0.104.0+** - Modern Python web framework for building APIs
- **Uvicorn 0.24.0+** - ASGI server for FastAPI
- **Python 3.12** - Programming language (slim variant)

### Data Validation & Settings
- **Pydantic 2.0.0+** - Data validation using Python type annotations
- **pydantic-settings 2.0.0+** - Settings management from environment
- **pydantic[email] 2.0.0+** - Email validation support
- **email-validator 2.0.0+** - Email address validation

### Database & ORM
- **PostgreSQL 15** - Relational database (Alpine Linux variant)
- **SQLAlchemy 2.0.23+** - SQL toolkit and ORM
- **Alembic 1.13.0+** - Database migration tool
- **psycopg2-binary 2.9.9+** - PostgreSQL adapter for Python

### Task Queue & Caching
- **Celery 5.3.0+** - Distributed task queue
- **Redis 7** - In-memory data store (Alpine Linux variant)
- **redis 5.0.0+** - Python Redis client

### External APIs & Services
- **google-api-python-client 2.100.0+** - Google APIs client library
- **OpenAI 1.0.0+** - OpenAI API client
- **anthropic** - Anthropic Claude API client
- **yt-dlp 2024.0.0+** - YouTube video downloader
- **youtube-transcript-api 0.6.0+** - YouTube transcript extraction
- **requests 2.31.0+** - HTTP library
- **httpx 0.25.0+** - Async HTTP client

### Video & Media Processing
- **opencv-python 4.8.0+** - Computer vision and image processing
- **moviepy 1.0.3+** - Video editing library
- **Pillow 10.0.0+** - Image processing library
- **ffmpeg-python 0.2.0+** - FFmpeg wrapper
- **pydub 0.25.1+** - Audio manipulation

### Natural Language Processing
- **nltk 3.8+** - Natural Language Toolkit
- **langdetect 1.0.9+** - Language detection library

### Security & Authentication
- **python-jose 3.3.0+** - JOSE (JWT) implementation
- **passlib 1.7.4** - Password hashing library
- **argon2-cffi 21.3.0+** - Argon2 password hasher
- **cryptography (Fernet)** - Symmetric encryption for per-user API key storage

### Utilities
- **python-dotenv 1.0.0+** - Environment variable management
- **pytz 2023.3+** - Timezone definitions

### Monitoring & Logging
- **python-json-logger 2.0.7+** - JSON log formatter
- **sentry-sdk 1.38.0+** - Error tracking and monitoring

### Testing
- **pytest 7.4.0+** - Testing framework
- **pytest-asyncio 0.21.0+** - Async test support
- **pytest-cov 4.1.0+** - Code coverage plugin

### Code Quality
- **black 23.10.0+** - Python code formatter
- **ruff 0.1.0+** - Fast Python linter
- **mypy 1.6.0+** - Static type checker
- **isort 5.12.0+** - Import statement organizer

---

## Infrastructure & DevOps

### Containerization
- **Docker** - Container platform
- **Docker Compose** - Multi-container orchestration
- **Docker Compose Plugin** - Modern Compose V2

### Infrastructure as Code
- **Terraform 1.0.0+** - Infrastructure provisioning
- **Telmate/proxmox Provider 3.0** - Proxmox provider for Terraform

### Virtualization
- **Proxmox VE** - Virtualization platform
- **LXC Containers** - Linux container technology
  - **Nesting enabled** - For Docker-in-LXC support
  - **Keyctl enabled** - For advanced Docker operations

### Database Administration
- **pgAdmin 4** - PostgreSQL web interface (latest)

### Networking
- **Docker Bridge Network** - Container networking
- **CORS** - Cross-Origin Resource Sharing support

---

## Development Tools & Workflows

### Version Control
- **Git** - Version control system
- **GitHub** - Code hosting and collaboration

### Package Managers
- **npm** - Node.js package manager
- **pip** - Python package installer
- **uv** - Fast Python package installer and resolver

### Environment Management
- **python-dotenv** - Environment variable management
- **.env files** - Configuration management

### Health Checks
- **curl** - HTTP health check tool
- **pg_isready** - PostgreSQL readiness check
- **redis-cli** - Redis health check

---

## Architecture Patterns

### Design Patterns
- **Microservices Architecture** - Separated services (API, Worker, Frontend)
- **Task Queue Pattern** - Async job processing with Celery
- **Repository Pattern** - Database access abstraction
- **Dependency Injection** - FastAPI dependency system
- **Factory Pattern** - Session and service factories

### Communication
- **REST API** - HTTP/JSON API design
- **Message Queue** - Redis-backed Celery tasks
- **Server-Sent Events** - Real-time updates (via SWR polling)

### Data Management
- **ORM** - SQLAlchemy for database abstraction
- **Migrations** - Alembic for schema versioning
- **Caching** - Redis for session and rate-limit storage
- **Named Volumes** - Docker volumes for data persistence

---

## External Services Integration

### AI/ML Services
- **Ollama** - Local LLM inference (configurable base URL)
- **OpenAI API** - Cloud-based AI services

### Video Services
- **YouTube API** - Video metadata and information
- **YouTube Transcript API** - Subtitle extraction
- **yt-dlp** - Video download and processing

---

## Operating Systems & Base Images

### Docker Base Images
- **python:3.12-slim** - Backend/worker containers
- **node:18-alpine** - Frontend container (multi-stage build)
- **postgres:15-alpine** - Database container
- **redis:7-alpine** - Cache/broker container
- **dpage/pgadmin4:latest** - Database admin container

### LXC Container
- **Ubuntu 22.04** - Base OS for Proxmox LXC container
- **Alpine Linux** - Base for most Docker images (smaller footprint)

---

## Deployment Configuration

### Container Orchestration
- **6 Services in Production**:
  1. PostgreSQL (database)
  2. Redis (cache/broker)
  3. FastAPI (REST API)
  4. Celery Worker (background tasks)
  5. Next.js (frontend)
  6. pgAdmin (database admin - dev only)

### Resource Management
- Configurable CPU cores and memory allocation
- Swap memory configuration
- Storage volumes (postgres_data, redis_data, shared_data)

### Network Configuration
- Bridge network driver
- Port mapping for external access
- Service discovery via DNS (container names)
- Configurable CORS origins

---

## Development Workflow Tools

### Hot Reload
- **Next.js dev server** - Frontend auto-reload
- **Uvicorn reload** - Backend auto-reload (via volume mounts)

### Testing Infrastructure
- **docker-compose.test.yml** - Isolated test stack
- **Hardcoded test credentials** - Reproducible test environment
- **Health check dependencies** - Service startup ordering

### Code Quality Pipeline
- **Type checking** - TypeScript & mypy
- **Linting** - ESLint (Next.js) & ruff
- **Formatting** - Prettier (implicit via Next.js) & black
- **Import sorting** - isort

---

## Summary by Category

### Languages
- Python 3.12
- TypeScript 5.0
- JavaScript (ES6+)
- HCL (Terraform)
- YAML (Docker Compose)
- SQL (PostgreSQL)

### Frameworks
- FastAPI (Python backend)
- Next.js 14 (React frontend)
- Celery (task queue)
- SQLAlchemy (ORM)
- Tailwind CSS (styling)

### Databases
- PostgreSQL 15
- Redis 7

### Infrastructure
- Docker & Docker Compose
- Terraform
- Proxmox VE & LXC

### AI/ML
- OpenAI API
- Ollama (local LLM)
- NLTK (NLP)

### Media Processing
- FFmpeg
- OpenCV
- MoviePy
- Pillow
- pydub

### Testing
- Vitest (frontend)
- pytest (backend)
- React Testing Library
- Playwright (E2E)

### Monitoring
- Sentry
- JSON logging
- Health check endpoints
