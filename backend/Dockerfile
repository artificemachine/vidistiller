# syntax=docker/dockerfile:1
# Build context: repo root (context: .)

# ── Stage 1: dependency installer ────────────────────────────────────────────
FROM python:3.14-slim AS builder

WORKDIR /app

RUN pip install --upgrade pip --no-cache-dir

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt --target /app/deps

# ── Stage 2: runtime image ────────────────────────────────────────────────────
FROM python:3.14-slim AS runtime

WORKDIR /app

# Runtime deps: curl for healthcheck, libGL/libxcb for opencv (cv2),
# tesseract-ocr for slide OCR (presentation mode) — pytesseract in
# requirements.txt needs the system binary + English language data.
# unzip is needed to install the pinned Deno binary below.
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    unzip \
    libxcb1 \
    libx11-6 \
    libglib2.0-0 \
    libgl1 \
    libsm6 \
    libxext6 \
    libxrender1 \
    tesseract-ocr \
    tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

# Deno: yt-dlp's YouTube extractor needs a JS runtime to solve signature/n
# challenges (its "ejs:github" remote component). Pinned release binary,
# verified against the digest GitHub publishes for this asset — never piped
# through `deno install` / a remote shell script.
ARG DENO_VERSION=v2.9.5
ARG DENO_ZIP_SHA256=8b010a3b1a4a0188a67cdb8a7a27348b2a501af78aec7fc74f2ace167368d530
RUN curl -fsSL -o /tmp/deno.zip \
      "https://github.com/denoland/deno/releases/download/${DENO_VERSION}/deno-x86_64-unknown-linux-gnu.zip" \
    && echo "${DENO_ZIP_SHA256}  /tmp/deno.zip" | sha256sum -c - \
    && unzip -q /tmp/deno.zip -d /usr/local/bin \
    && chmod +x /usr/local/bin/deno \
    && rm /tmp/deno.zip

# Copy installed packages from builder
COPY --from=builder /app/deps /app/deps

ENV PYTHONPATH="/app/deps"
# pip --target installs console scripts (uvicorn, alembic, ...) into /app/deps/bin
ENV PATH="/app/deps/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Non-root user for runtime security
RUN groupadd --gid 1001 appgroup && \
    useradd --uid 1001 --gid appgroup --create-home --shell /usr/sbin/nologin appuser && \
    mkdir -p /data

# Copy application source
COPY backend/ ./

# Alembic config/migrations live at the repo root, not under backend/. Prod
# and staging bind-mount these over the top at runtime (see
# docker-compose.prod.yml), but that's compose-file-specific and fragile --
# baking them into the image means `alembic upgrade head` works in any
# context (e2e, a plain `docker run`, a compose file that forgets the
# bind mount) without depending on it.
COPY alembic.ini ./alembic.ini
COPY migrations/ ./migrations/

RUN chown -R appuser:appgroup /app /data

USER appuser

# Pre-download NLTK data so runtime has no home-dir write requirement
RUN python -c "import nltk; nltk.download('punkt', quiet=True); nltk.download('punkt_tab', quiet=True)"

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --retries=5 \
  CMD curl -sf http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
