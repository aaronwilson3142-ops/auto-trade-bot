# APIS — Decision Log
Format: timestamp | decision | alternatives considered | rationale | consequence

---

## [2026-03-17 00:00 UTC] Session 1 — Foundation Architecture Decisions

### DEC-001: Python 3.11 as minimum version
- **Decision:** Require Python 3.11+
- **Alternatives:** 3.10 (still supported), 3.12 (latest)
- **Rationale:** 3.11 provides significant performance improvements, `tomllib` stdlib, improved error messages. Widely available. 3.12 has some library compatibility lag. 3.10 is approaching EOL.
- **Consequence:** All code may use 3.11+ type syntax (e.g. `X | Y` union types, `match` statements).

### DEC-002: FastAPI as API framework
- **Decision:** Use FastAPI for the `apps/api` layer
- **Alternatives:** Flask (simpler), Django REST (heavier), Litestar
- **Rationale:** FastAPI is async-native, Pydantic v2 integrated, automatic OpenAPI docs, strong typing support. Excellent fit for a structured data API with schema documentation requirements.
- **Consequence:** All API schemas must be Pydantic models. Dependency injection via FastAPI's DI system.

### DEC-003: SQLAlchemy 2.0 + Alembic for database layer
- **Decision:** SQLAlchemy 2.0 ORM + Alembic migrations against PostgreSQL
- **Alternatives:** Tortoise ORM (async), Peewee (simpler but limited), raw psycopg
- **Rationale:** SQLAlchemy 2.0 is the industry standard, has full async support, mature migration tooling via Alembic, excellent typing support. Required for the audit/traceability requirements in the spec.
- **Consequence:** All models use SQLAlchemy declarative base. Migrations track schema evolution.

### DEC-004: pydantic-settings for config management
- **Decision:** All config loaded via pydantic-settings from environment variables + .env file
- **Alternatives:** python-decouple, dynaconf, raw os.environ
- **Rationale:** Pydantic-settings integrates natively with Pydantic v2, provides type validation, nested config, and env prefix support. Catches misconfiguration at startup.
- **Consequence:** All services receive config via the central `Settings` object. No `os.getenv()` calls scattered in service code.

### DEC-005: structlog for logging
- **Decision:** structlog for structured JSON logging
- **Alternatives:** loguru (simpler), stdlib logging (less structured)
- **Rationale:** Structured logging is required for auditability. structlog integrates with stdlib logging and produces machine-readable JSON events. Critical for observability in a trading system.
- **Consequence:** All log statements use structlog. No raw `print()` debugging in service code.

### DEC-006: Paper broker first, Alpaca second
- **Decision:** Build paper broker adapter before Alpaca adapter
- **Alternatives:** Build Alpaca paper mode directly (no internal paper broker)
- **Rationale:** Spec explicitly requires paper broker first. An internal paper broker allows full testing without API keys, network calls, or rate limits. Alpaca paper is the next step after internal paper validates the flow.
- **Consequence:** All paper trading tests use internal paper broker. Alpaca paper mode adds real data later.

### DEC-007: BrokerAdapter abstract base class pattern
- **Decision:** Use Python ABC (Abstract Base Class) for BrokerAdapter interface
- **Alternatives:** Protocol class (structural typing), duck typing
- **Rationale:** ABC enforces that all adapters implement required methods at class definition time, providing clear contract enforcement aligned with the spec's requirement of a broker abstraction interface.
- **Consequence:** All broker adapters must inherit from `BaseBrokerAdapter` and implement abstract methods.

### DEC-008: alpaca-py as Alpaca SDK
- **Decision:** Use `alpaca-py` (official Alpaca Python SDK v2+)
- **Alternatives:** `alpaca-trade-api` (deprecated older SDK)
- **Rationale:** `alpaca-py` is the current official maintained SDK. `alpaca-trade-api` is deprecated.
- **Consequence:** Alpaca adapter will use `alpaca.trading.client.TradingClient` and `alpaca.data` namespaces.

### DEC-009: APScheduler for background jobs
- **Decision:** APScheduler 3.x for scheduled worker jobs
- **Alternatives:** Celery (complexity), RQ (Redis Queue), cron-based scripts
- **Rationale:** APScheduler is lightweight, in-process, does not require a broker/message-queue infrastructure for MVP. Can be swapped for Celery later if distributed execution is needed.
- **Consequence:** All scheduled jobs defined in `apps/worker/schedulers/`. Can be run as a standalone worker process.

### DEC-010: yfinance as dev-mode market data provider
- **Decision:** Use `yfinance` for development/backtest data; replace with paid feed for paper/live
- **Alternatives:** polygon.io, Alpha Vantage, Interactive Brokers data, Alpaca market data
- **Rationale:** yfinance is free, fast for prototyping, and covers daily OHLCV. Not suitable for real-time paper/live use due to reliability and terms. Alpaca market data (via alpaca-py) is the natural step up.
- **Consequence:** Market data service abstracted behind interface so provider can be swapped. Dev and paper modes use different providers.

---

## [2026-03-26] Session — Hardening Sprint (Items #8–#15)

### DEC-011: ruff as blocking CI lint gate
- **Decision:** ruff lint check is blocking in CI (non-zero exit fails the pipeline); mypy type-check is informational with `|| true`
- **Alternatives:** Keep ruff as `--exit-zero` advisory; make mypy blocking
- **Rationale:** ruff covers style, imports, and common bugs. Blocking on ruff catches real issues immediately. mypy strict mode on a large codebase would generate too many annotation gaps to be usable as a gate today; informational keeps it visible without blocking merges.
- **Consequence:** All PRs must pass `ruff check .` to merge. mypy errors tracked but not blocking until annotation coverage improves.

### DEC-012: PEP 604 union types (`X | None`) as project standard
- **Decision:** All type annotations use `X | None` syntax (PEP 604) rather than `Optional[X]`
- **Alternatives:** Keep `Optional[X]`; suppress UP007/UP045 ruff rules
- **Rationale:** Python 3.11+ is the project minimum. PEP 604 syntax is more readable and concise. `from __future__ import annotations` makes it safe everywhere.
- **Consequence:** 721 `Optional[X]` instances across 140 files converted. Future code should use `X | None` natively.

### DEC-013: Worker Redis heartbeat for health observability
- **Decision:** Worker writes a `worker:heartbeat` key to Redis every 60s with 180s TTL; Docker Compose healthcheck reads that key
- **Alternatives:** File-based heartbeat; HTTP endpoint on worker; no worker healthcheck
- **Rationale:** Redis is already a dependency for the worker. Writing a heartbeat key is zero-overhead. The 3× TTL multiplier ensures one missed write does not kill the container. The healthcheck makes the worker a first-class observable service alongside postgres/redis/api.
- **Consequence:** `docker ps` will show `(healthy)` for the worker after next restart. Ops can detect a stuck/dead worker without log inspection.

### DEC-014: GRAFANA_ADMIN_PASSWORD as required env var (no fallback)
- **Decision:** Grafana admin password uses `:?` Docker Compose syntax — startup fails if the var is not set
- **Alternatives:** Keep a default `change_me` value; use a secrets manager
- **Rationale:** A default weak password is a security vulnerability that is easy to ship to production accidentally. Hard-failing at `docker compose up` time forces operators to set a real password before the stack starts.
- **Consequence:** `.env` must contain `GRAFANA_ADMIN_PASSWORD` before next `docker compose up`. `.env.example` documents this requirement.

### DEC-015: Coverage enforcement via fail_under in CI
- **Decision:** CI enforces 60% minimum coverage on every run (via `fail_under = 60` in pyproject.toml, with `--cov` enabled in CI)
- **Alternatives:** Advisory-only coverage reporting; higher or lower floor
- **Rationale:** 60% is a realistic floor that catches regressions without blocking incremental development. The value is already in pyproject.toml; CI was incorrectly overriding it with `--no-cov`.
- **Consequence:** PRs that delete tests or add uncovered code without tests will fail CI coverage gating.

---

## [2026-03-30] Session — Infrastructure Health Dashboard

### DEC-016: In-process infrastructure health probes on dashboard
- **Decision:** Add an Infrastructure Health panel to the operator dashboard that probes Postgres (SELECT 1), Redis (PING), and infers worker status from `last_paper_cycle_at` freshness — all from within the API process.
- **Alternatives:** (a) Query Kubernetes API for pod status directly (requires RBAC service account); (b) Separate health-check microservice; (c) Rely on `/health` JSON endpoint only (no visual dashboard)
- **Rationale:** The worker pod was scaled to 0 for 8 days without anyone noticing because no dashboard indicator existed. The API process already has DB and Redis connections, and the worker's last-cycle timestamp is in shared app state. Probing from within the API is zero-dependency and immediately deployable. K8s API access would require RBAC changes and is fragile across cluster rebuilds.
- **Consequence:** Operators see green/yellow/red status for all 6 critical components on every dashboard page load. Worker outages are visible within minutes (page auto-refreshes every 60s). No new dependencies or service accounts required.
