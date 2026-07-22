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

# Runtime deps: curl for healthcheck, libGL/libxcb for opencv (cv2)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libxcb1 \
    libx11-6 \
    libglib2.0-0 \
    libgl1 \
    libsm6 \
    libxext6 \
    libxrender1 \
    && rm -rf /var/lib/apt/lists/*

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

RUN chown -R appuser:appgroup /app /data

USER appuser

# Pre-download NLTK data so runtime has no home-dir write requirement
RUN python -c "import nltk; nltk.download('punkt', quiet=True); nltk.download('punkt_tab', quiet=True)"

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --retries=5 \
  CMD curl -sf http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
