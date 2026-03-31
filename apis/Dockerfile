# ─────────────────────────────────────────────────────────────────────────────
# APIS — Single image for both API server and Worker
#
# Usage:
#   docker build -t apis:latest .
#
# Run API server:
#   docker run --env-file .env apis:latest api
#
# Run Worker:
#   docker run --env-file .env apis:latest worker
# ─────────────────────────────────────────────────────────────────────────────

# ── Stage 1: dependency builder ───────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

# System deps needed to compile psycopg binary + numpy
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy only dependency files first (layer cache: only re-runs when these change)
COPY requirements.txt pyproject.toml ./

# Install into an isolated prefix so we can copy cleanly to the final image
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ── Stage 2: runtime image ────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

# Runtime system deps (libpq for psycopg at runtime)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Non-root user for security (matches K8s securityContext runAsUser: 1000)
RUN groupadd -g 1000 apis && useradd -u 1000 -g apis -s /bin/bash -m apis

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application source
COPY --chown=apis:apis . .

USER apis

# Expose API port
EXPOSE 8000

# Entrypoint script selects api or worker based on CMD argument
ENTRYPOINT ["python", "-m"]

# Default: run the API server
# Override with "apps.worker.main" to run the worker
CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
