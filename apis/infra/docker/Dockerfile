# APIS — Dockerfile
#
# Multi-stage build with two final targets:
#   api    — FastAPI app (uvicorn)
#   worker — APScheduler background worker
#
# Build from the workspace root (apis/ parent directory):
#   docker build -f apis/infra/docker/Dockerfile --target api -t apis-api .
#   docker build -f apis/infra/docker/Dockerfile --target worker -t apis-worker .

# ---------------------------------------------------------------------------
# Stage 1: base dependencies
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS base

WORKDIR /app

# System dependencies (psycopg3 needs libpq-dev; yfinance needs build tools)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies first (layer-caches requirements)
COPY apis/requirements.txt ./apis/requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r apis/requirements.txt

# Copy the full apis package
COPY apis/ ./apis/

# Set PYTHONPATH so all internal imports (config.*, services.*, etc.) work
ENV PYTHONPATH=/app/apis


# ---------------------------------------------------------------------------
# Stage 2: api target
# ---------------------------------------------------------------------------
FROM base AS api

WORKDIR /app/apis

EXPOSE 8000

CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "info"]


# ---------------------------------------------------------------------------
# Stage 3: worker target
# ---------------------------------------------------------------------------
FROM base AS worker

WORKDIR /app/apis

CMD ["python", "-m", "apps.worker.main"]
