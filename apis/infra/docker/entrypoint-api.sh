#!/bin/sh
# ---------------------------------------------------------------------------
# APIS api-container entrypoint
#
# Runs Alembic migrations to head before starting the FastAPI app so schema
# drift cannot silently break `_load_persisted_state` on startup.  Added
# 2026-04-17 after a drift incident where 3 Deep-Dive Plan migrations had
# landed in code but were never applied to the running DB, causing
# portfolio/state/closed_trades restore to fail and /health to report
# `paper_cycle: no_data` on every restart.
#
# All migrations in this repo are additive (nullable column adds, new
# tables) so auto-apply is safe under paper mode.  If you go live, consider
# gating this on APIS_OPERATING_MODE and failing-fast instead of auto-
# applying.  The worker container does NOT run migrations â€” it depends on
# api health, so by the time it boots the schema is already up to date.
# ---------------------------------------------------------------------------
set -e

echo "[entrypoint-api] Running Alembic migrations (current -> head)..."
alembic upgrade head
echo "[entrypoint-api] Migrations complete. Starting uvicorn..."

exec uvicorn apps.api.main:app --host 0.0.0.0 --port 8000 --log-level info
