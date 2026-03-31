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
