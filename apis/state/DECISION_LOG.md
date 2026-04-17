# APIS — Decision Log
Format: timestamp | decision | alternatives considered | rationale | consequence

---

## [2026-04-16] Deep-Dive Review — Self-Improvement First Direction

### DEC-031: Defer walk-forward / OOS harness and survivorship-free data acquisition; prioritize self-improvement expansion + safe trade-count first
- **Decision:** Reordered the work queue so that internal self-improvement upgrades (Proposal Outcome Ledger, Shadow Portfolios, Strategy Bandit) and no-OOS-required trade-count levers (score-weighted rebalance, ATR stops, lowered buy threshold) come *before* the Apr-14 plan's Phase A (Norgate data) and Phase B (walk-forward harness).
- **Alternatives considered:**
  - (a) Execute Apr-14 plan A-F in order. Conservative, aligned with external review, but slow to deliver the operator's main ask.
  - (b) Parallel tracks. Broader but thins focus on each and stresses operator review bandwidth.
  - (c) Chosen: internal self-improvement + trade-count first, then OOS/data later.
- **Rationale:** Operator explicitly asked for more self-improvement capacity and more trades. Shadow-portfolio data (Rec 11) produces a large share of the evidence the walk-forward harness would otherwise need, and doing it first makes the eventual OOS work cheaper. The three-gate self-improvement promotion path is unchanged — none of the recommendations weakens a safety control.
- **Accepted P&L risk:** Survivorship bias continues to slightly inflate backtest Sharpe until Phase A eventually lands. Apr-14 review §3.2 estimates 50–150 bps/yr overstatement. Mitigated by: (a) no live capital flip planned before walk-forward eventually lands, (b) shadow portfolios build OOS-like evidence in the meantime.
- **Consequence:** 11-week sequence outlined in `APIS_DEEP_DIVE_REVIEW_2026-04-16.md` §10. Walk-forward harness re-enters the queue after Shadow Portfolios land.

### DEC-032: Phase 66 AI tilt treated as operator-level thesis, not self-improvement target
- **Decision:** The `_AI_THEME_BONUS`, `_AI_RANKING_BONUS`, and the raised `max_thematic_pct=0.75` are frozen relative to the self-improvement engine. The engine may propose changes to strategy weights, stops, thresholds, and sizing but not to these three AI-tilt knobs.
- **Alternatives considered:** Allow self-improvement to auto-rollback the tilt if shadow-P&L shows underperformance. Rejected — operator directive is explicit that this is a thesis-level bet, not a tunable parameter.
- **Consequence:** If the eventual shadow-portfolio scorer (Rec 11) shows a no-AI-tilt shadow outperforming live, it produces an *information* alert to the operator, not a proposal. The operator remains the sole decision-maker for this category.

### DEC-034: Shadow Portfolios — scope includes alternative rebalance weightings in parallel
- **Decision:** Rec 11 (Shadow-Portfolio Scorer) will track, in parallel: (a) REJECTED actions, (b) "watch"-tier borderline ranked opportunities, (c) stopped-out-continued-past-stop positions, AND (d) alternative rebalance weighting scenarios (equal vs score vs score_invvol) running as independent virtual portfolios on the same universe.
- **Alternatives considered:** Narrow scope (a+b only); defer (d) until walk-forward harness is built.
- **Rationale:** Operator directive 2026-04-16. (d) produces exactly the A/B evidence Rec 5.1 (score-weighted rebalance) needs to validate without walk-forward. Same codepath cost as (a+b+c) alone. Directly shortens the sequence from "wait for OOS harness" to "read the shadow dashboard."
- **Consequence:** Shadow portfolios table schema must accommodate a `scenario_key` column (default "live_mirror"). Weekly assessment job groups by `scenario_key` for performance comparison. Estimated effort stays ~3 weeks.

### DEC-035: Proposal Outcome Ledger — per-type measurement windows
- **Decision:** Rec 10 (Proposal Outcome Ledger) uses a per-proposal-type measurement window, not a global 30-day value. Default windows:
  - SOURCE_WEIGHT: 45 days
  - RANKING_THRESHOLD: 30 days
  - HOLDING_PERIOD_RULE: 14 days
  - CONFIDENCE_CALIBRATION: 60 days
  - PROMPT_TEMPLATE: 30 days
  - FEATURE_TRANSFORMATION: 45 days
  - SIZING_FORMULA: 30 days
  - REGIME_CLASSIFIER: 60 days
  - Unknown type fallback: 30 days
- **Alternatives considered:** Single 30-day global window (simpler, ~1 day less build). Rejected because HOLDING_PERIOD_RULE measurement at 30 days is ~2× its actual horizon (measures follow-on behavior, not the rule) and CONFIDENCE_CALIBRATION at 30 days is statistical noise.
- **Rationale:** Operator directive 2026-04-16. The whole point of the outcome ledger is verdict accuracy. Window mismatch systematically degrades that. ~1 extra day of build cost is trivial relative to the meta-learning benefit.
- **Consequence:** Store mapping in `config/settings.py` as `APIS_PROPOSAL_OUTCOME_WINDOWS` dict (env-overridable per type). Add `measurement_window_days` column to `proposal_outcomes` so historical records remain interpretable after any future tuning.

### DEC-033: Risk engine hard gates frozen during self-improvement work
- **Decision:** `max_positions`, `max_single_name_pct`, `max_sector_pct`, `max_thematic_pct`, `daily_loss_limit_pct`, `weekly_drawdown_limit_pct`, `monthly_drawdown_limit_pct`, `max_new_positions_per_day`, and the kill switch remain untouched during the 11-week sequence. PROTECTED_COMPONENTS list is not expanded or contracted.
- **Rationale:** These are what make Recommendations 6 (score-weighting), 7 (ATR stops), and 10 (lower buy threshold) safe. Loosening any of them would make the other recommendations load-bearing for safety, which is not what they were designed for.
- **Consequence:** If paper evidence suggests any of these are individually too restrictive after the 11-week batch lands, a separate DEC entry and explicit operator sign-off is required. Not implicit.

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

## [2026-03-31] Session — Securities Seed Fix

### DEC-016: Idempotent reference data seeding at worker startup
- **Decision:** Seed `securities`, `themes`, and `security_themes` tables automatically at worker startup via `_seed_reference_data()` in `main.py`, backed by `infra/db/seed_securities.py`.
- **Alternatives:** (a) Alembic data migration (one-shot, harder to maintain), (b) CLI management command (requires manual invocation), (c) init-db.sql (only runs on first postgres start, not on code-driven universe changes)
- **Rationale:** The seed must run every time the worker starts, be idempotent (safe to run repeatedly), and automatically adapt when universe tickers change in `config/universe.py`. Worker startup is the right hook because: it runs before any scheduled jobs fire, it has access to the DB, and it catches both fresh deploys and volume wipes.
- **Consequence:** Adding a ticker to `config/universe.py` automatically seeds it on next worker restart. No manual DB intervention needed.

### DEC-017: Worker source volume mount in Docker Compose
- **Decision:** Add `volumes: ../../../apis:/app/apis:ro` to the worker service in `docker-compose.yml`, matching the existing API service mount.
- **Alternatives:** Rebuild worker image on every code change (`docker compose up --build worker`)
- **Rationale:** During development, the API service already had this mount so code changes took effect immediately. The worker was missing it, requiring a full image rebuild for any code change — which was difficult due to Windows path quoting issues with `docker compose` commands.
- **Consequence:** Worker picks up code changes on container restart (`docker restart docker-worker-1`). No rebuild needed for development. Production deployments should still use baked-in images.

---

## [2026-04-08] Session — Phase 57 Scaffold (InsiderFlowStrategy)

### DEC-018: Phase 57 — add InsiderFlowStrategy as a new signal family, not a strategy swap
- **Decision:** Open Phase 57 to add a new `InsiderFlowStrategy` (congressional / 13F / unusual-options flow) as a 6th signal family feeding the existing composite ranking. Do NOT replace or dilute any existing strategy. Ship a scaffold first (no network calls, `NullInsiderFlowAdapter` default). Wire a concrete provider only after a multi-year walk-forward backtest via `BacktestEngine` and a `LiveModeGateService` readiness pass.
- **Trigger:** User asked whether to adopt the workflow in Samin Yasar's "Claude Just Changed the Stock Market Forever" tutorial (YouTube `lH5wrfNwL3k`) — trailing stop + copy-trading politicians + options wheel. Full transcript reviewed before deciding.
- **Alternatives considered:**
  (a) Adopt the full tutorial workflow. Rejected: the trailing-stop strategy is already a strict subset of Phase 25/26/42 risk-engine exits; "ladder-in on drawdown" contradicts Master Spec §9 "no averaging down without explicit rule support"; and the options wheel strategy directly violates Master Spec §4.2 (no options in MVP) and the Anti-Drift Rules in the Continuity Protocol §12.
  (b) Skip the video entirely. Rejected: the congressional / whale / unusual-options data source itself is legitimate, under-exploited by retail quant stacks, and maps cleanly onto APIS's existing enrichment pipeline alongside news / macro / theme / rumor overlays.
  (c) Bolt the new signal onto an existing strategy (e.g. fold into `SentimentStrategy`). Rejected: mixes signal families, breaks attribution and per-family weight auto-tuning (Phase 37), and blurs audit trails.
- **Rationale:** The video's real contribution is a data source, not a strategy. APIS already has a rigorous composite ranking, half-Kelly sizing, correlation / sector / liquidity / factor / VaR / stress-test risk stack, multi-cycle paper loop, and self-improvement framework — none of which should be torn out. Adding insider flow as an additional signal family is the minimum-disruption, highest-evidence way to test whether that data actually adds alpha after realistic frictions. Starting with a scaffold (`NullInsiderFlowAdapter` + neutral 0.5 signal) means zero production impact until the adapter is wired AND validated.
- **Guardrails enforced:** signal decays exponentially with filing age (half-life 14 days, hard cut at 60 days); reliability tier capped at `secondary_verified`; `contains_rumor=False` always (SEC filings are public record, not rumour); horizon classified as POSITIONAL (10–60 days); strategy is stateless and produces a neutral 0.5 signal with zero confidence until the overlay fields are populated. The options-wheel portion of the tutorial is **explicitly rejected** here as scope expansion under Master Spec §4.2 — any future consideration requires a logged spec revision, not a silent change.
- **Consequence:** New files: `services/signal_engine/strategies/insider_flow.py` (Strategy), `services/data_ingestion/adapters/insider_flow_adapter.py` (`InsiderFlowAdapter` ABC + `InsiderFlowEvent` + `InsiderFlowOverlay` + `NullInsiderFlowAdapter`), `tests/unit/test_phase57_insider_flow.py` (24 scaffold tests, all passing). `FeatureSet` gains three new overlay fields: `insider_flow_score`, `insider_flow_confidence`, `insider_flow_age_days`. `SignalType.INSIDER_FLOW` enum member added. Strategy not yet wired into `SignalEngineService.score_from_features()`, enrichment pipeline, or ranking composite — that wiring is Phase 57 Part 2 once a concrete provider (QuiverQuant / Finnhub / EDGAR) is chosen and ToS-reviewed.

---

## [2026-04-08] Session — Phase 58 Self-Improvement Auto-Execute Safety Gates

### DEC-020: Extend startup state restoration and add catch-up job runner (Phase 59)
- **Decision:** Expand `_load_persisted_state()` from 4 restored fields to 10+ by querying existing DB tables (PortfolioSnapshot, Position, WeightProfile, RegimeSnapshot, ReadinessSnapshot, PromotedVersion). Add a new `_run_startup_catchup()` function that re-runs missed morning pipeline jobs (correlation, liquidity, VaR, regime, stress, earnings, universe, rebalance, signals, ranking, weight optimization) when the API starts mid-day on a weekday and the corresponding app_state fields are still empty.
- **Alternatives:** (a) Add a Redis-backed cache layer that persists every app_state mutation. Rejected: adds infra complexity, cache-invalidation bugs, and a new dependency surface for MVP. (b) Persist all ephemeral computed state to new DB tables. Rejected: many fields (correlation matrix, VaR result, stress result) are recomputed every morning and don't need permanent storage — the existing scheduled jobs already handle freshness. (c) Do nothing and accept blank dashboards after restart. Rejected: violates spec §3.5 Continuity and makes the system appear broken.
- **Rationale:** The dashboard showed blank sections after every restart because ApiAppState defaults all ~60 fields to None/[]/{}. Only 4 fields were being restored from DB. The two-pronged approach (restore from DB what's already persisted + re-run jobs for ephemeral computed state) maximizes dashboard population with zero new tables or infra. The catch-up runner only fires on weekday starts, skips jobs whose data is already populated, and respects dependency ordering (e.g., signals before ranking).
- **Consequence:** Dashboard is immediately populated after restart. No new DB tables or Redis dependencies. 36 unit tests cover all restoration paths. Catch-up jobs add ~30-60s to startup on weekday mid-day restarts but are skipped entirely on weekends and when data is already fresh.

---

## [2026-04-16] Phase 66 — AI-Heavy Stock Selection Bias

### DEC-026: Apply heavy AI bias across regime weights, theme scoring, and ranking
- **Decision:** Make AI-related themes the dominant factor in stock selection via three reinforcing mechanisms: (1) theme_alignment_v1 is now the top-weighted strategy in most regimes, (2) AI theme scores get a 1.15–1.35× bonus multiplier, (3) AI tickers get a 0.03–0.08 additive ranking bonus. Thematic concentration cap raised from 50% to 75%.
- **Alternatives:** (a) Moderate bias (+10% theme weight only), (b) AI-only portfolio (exclude non-AI entirely), (c) No change (rely on organic theme scoring).
- **Rationale:** Operator directive — the portfolio thesis is centred on AI expansion. Non-AI stocks remain eligible as a diversification backstop but must meaningfully outperform on raw signals to rank above AI names. All hard risk controls (stop-loss, drawdown, position limits) remain unchanged.
- **Consequence:** Portfolio will naturally concentrate in AI infrastructure, semiconductors, power, cybersecurity, and cloud/software names. Sector concentration may approach 40% technology cap. Thematic concentration can reach 75% in a single AI theme. Must revert bias before transitioning to live trading if thesis changes.

---

## [2026-04-15] Phase A.2 — Point-in-Time Universe Source

### DEC-025: Introduce PointInTimeUniverseService as an alternate base-universe source (behind APIS_UNIVERSE_SOURCE flag)
- **Decision:** Add ``apis/services/universe_management/pointintime_source.py`` providing ``PointInTimeUniverseService.get_universe_as_of(date)`` — a survivorship-safe base-universe source backed by Norgate's ``S&P 500 Current & Past`` watchlist plus per-ticker ``index_constituent_timeseries`` membership lookups.  Gate behind new ``APIS_UNIVERSE_SOURCE`` flag (values: ``static`` default, ``pointintime``).  The existing ``UniverseManagementService.get_active_universe`` already accepts ``base_tickers`` as a parameter, so this is additive — operator ADD/REMOVE overrides and quality-based removal continue to work unchanged.
- **Context:** Phase A Part 2 of APIS_IMPLEMENTATION_PLAN_2026-04-14.md.  Independent review flagged the hand-curated 62-stock list in ``config/universe.py`` as survivorship-biased by construction: the operator included only names that seemed interesting *today*, so any backtest that iterates historical dates implicitly drops companies that were once in the S&P 500 but later delisted, merged, or were renamed.  The new service answers "what was the S&P 500 on YYYY-MM-DD?" and becomes the source of ``base_tickers`` when the flag is flipped.
- **Alternatives considered:**
  (a) Hard-code a larger "S&P 500 ever" list in ``config/universe.py``.  Rejected: stale the day a new constituent is added; re-creates the maintenance burden.
  (b) Delete the static universe entirely.  Rejected: yfinance users would have no way to run without Norgate/NDU, breaking the default-off Phase A Part 1 commitment.
  (c) Fold this into ``UniverseManagementService`` itself.  Rejected: ``UniverseManagementService`` is rightly stateless and focused on overrides/quality; adding Norgate calls there would entangle two responsibilities (source vs. transform).
- **Trial-tier limitation documented in the module docstring:** on the 21-day free trial, the watchlist name is exposed but the historical membership data is effectively current-only — ``get_candidate_pool()`` returned 541 names vs the 700+ expected for true survivorship safety (confirmed via ``norgate_vs_yfinance_compare.py`` on 2026-04-15).  The service still *runs* correctly against the trial — it just returns a smaller universe.  Full accuracy requires Platinum.
- **Rationale:** Landing the service behind a default-off flag means existing paper-trading cycles are untouched; when the operator purchases Platinum and sets ``APIS_UNIVERSE_SOURCE=pointintime``, every downstream consumer automatically begins iterating the survivorship-safe list with zero code changes elsewhere.  The instance-level cache (``_universe_cache`` keyed by (index, date)) makes walk-forward runs cheap: ~540 constituent calls on the first query for a date, free on every subsequent query for the same date.
- **Consequence:** New files: ``apis/services/universe_management/pointintime_source.py`` (~210 LOC), ``apis/tests/unit/test_pointintime_universe.py`` (11 tests — all pass with a patched ``sys.modules["norgatedata"]`` so CI doesn't need NDU).  Modified: ``apis/config/settings.py`` adds ``UniverseSource`` enum + three fields (``universe_source``, ``pointintime_index_name``, ``pointintime_watchlist_name``).  No existing behaviour changes — ``universe_source`` defaults to ``static``.  Combined suite (Phase A Part 1 + A.2) now 25/25 passing.

---

## [2026-04-15] Phase A — Survivorship-Free Market Data

### DEC-024: Adopt Norgate Data as point-in-time market-data provider (provisional, pending paid subscription)
- **Decision:** Add a second market-data adapter, `PointInTimeAdapter`, backed by the `norgatedata` Python package and the locally-running Norgate Data Updater (NDU).  Gate it behind a new `APIS_DATA_SOURCE` feature flag with values `yfinance` (default) and `pointintime`.  yfinance remains the fallback and the default so existing behaviour is unchanged until the operator opts in.
- **Context:** Independent review (APIS_INDEPENDENT_REVIEW_2026-04-14.md, top-10 item #1) identified survivorship bias as the single highest-impact integrity gap in the research stack.  yfinance only returns currently-listed tickers, so any historical backtest or self-improvement training set implicitly excludes delisted/failed companies — inflating measured edge and hiding tail-risk patterns.  APIS_IMPLEMENTATION_PLAN_2026-04-14.md Phase A committed to replacing yfinance for historical work with a point-in-time feed.
- **Alternatives considered:**
  (a) CRSP via academic partnership — rejected: no commercial licence, multi-week onboarding.
  (b) Polygon.io delisted add-on — rejected: history depth limited vs Norgate; adjusted-close methodology less transparent.
  (c) Sharadar SEP — viable but uses survivorship-handled files that require manual reconciliation; Norgate's integrated NDU model is lower-friction for a single-operator setup.
  (d) Stay on yfinance and rely on Phase B walk-forward to uncover bias — rejected: walk-forward on biased data just re-discovers the same bias on a sliding window.
- **Provisional status:** The 21-day Norgate free trial caps history at ~2 years, which is enough to wire the adapter, run smoke tests, and verify the universe-membership APIs — but *not* enough for a real walk-forward (bull-only 2024-2026).  Norgate support declined a trial extension on 2026-04-15.  The adapter lands now, behind the flag, so the code path exists and is tested; a real Phase B walk-forward is blocked until Aaron purchases a paid tier (recommended: Platinum at $630/yr for full Russell + S&P + delisted coverage).
- **Rationale:** Landing the adapter behind a default-off flag means yfinance users see zero behaviour change, but the moment the subscription is active, `APIS_DATA_SOURCE=pointintime` in `.env` flips the entire DataIngestionService onto survivorship-safe data with no code changes elsewhere.  Separately, the adapter exposes `list_delisted_symbols` / `watchlist_symbols` helpers so Phase A.2 (universe construction from `S&P 500 Current & Past`) can proceed independently of the bar-fetch path.
- **Consequence:** New files: `apis/services/data_ingestion/adapters/pointintime_adapter.py` (~230 LOC, 14 unit tests — all pass without NDU installed via patched `sys.modules["norgatedata"]`).  Modified: `apis/config/settings.py` (adds `DataSource` enum + `data_source: DataSource` field), `apis/services/data_ingestion/service.py` (adapter factory `_build_default_adapter()` picks by setting, falls back to yfinance on import error).  yfinance remains the default; no runtime change until operator flips the env var.  Phase B walk-forward still blocked pending paid subscription.

---

## [2026-04-09] Learning Acceleration — Paper Cycle + Threshold + Backtest Sweep

### DEC-023: Phase 57 Part 2 — Choose QuiverQuant (primary) + SEC EDGAR (supplementary) for insider/smart-money flow data
- **Decision:** Use QuiverQuant as the primary provider for congressional trading data, supplemented by SEC EDGAR (Form 4 / 13F) for insider transactions and institutional holdings. Finnhub rejected.
- **Alternatives:** (a) Finnhub `/stock/congressional-trading` — rejected: ToS unclear on programmatic trading bot use, response field structure (trade_date vs filing_date) undocumented, no 13F endpoint. (b) SEC EDGAR only — rejected alone: no congressional trading data, Form 13F lags 45+ days (too stale for swing signals), requires third-party wrapper (sec-api.io) for structured JSON access. (c) QuiverQuant only — viable but misses Form 4 insider transactions which SEC EDGAR provides for free.
- **Rationale:** QuiverQuant ToS explicitly states "Commercial purposes do not include personal securities trading activities" — clear permission for APIS. API has documented trade_date vs filing_date fields, dollar amounts, and a Python client. Cost ~$25/mo. SEC EDGAR Form 4 data is free public record with 2-day lag and clear field structure (`transactionDate` vs `filedAt`). Combined approach gives congressional + insider + institutional coverage.
- **Consequence:** `InsiderFlowAdapter` concrete implementation should fetch from QuiverQuant (daily) and SEC EDGAR Form 4 (daily). 13F data (quarterly) feeds longer-horizon strategies only. Provider choice logged before any code written per Phase 57 spec.

### DEC-022: Revert learning-acceleration overrides to production defaults
- **Decision:** Revert all DEC-021 paper-bake learning acceleration settings: cycles 12→7, composite score threshold 0.15→0.30, max new positions/day 8→3, max position age 5→20 days.
- **Alternatives:** (a) Keep learning acceleration active longer — rejected: sufficient paper trade data has accumulated (~10 days of active trading); marginal signal noise is no longer needed. (b) Partial revert (only threshold) — rejected: all four settings were part of the same learning package and should be reverted together for a clean live-trading baseline.
- **Rationale:** The learning acceleration period served its purpose — the self-improvement loop now has closed trades across multiple strategies. Continuing to admit low-confidence signals and run excessive cycles adds noise without further learning value. Reverting now establishes the production baseline that will carry into human_approved mode.
- **Consequence:** Worker runs 7 cycles/day instead of 12. Only opportunities scoring ≥0.30 composite enter the candidate list. Position limits return to conservative defaults. Docker services must be restarted for changes to take effect.

### DEC-021: Accelerate paper-bake learning via cycle frequency, threshold tuning, and backtest sweep
- **Decision:** (1) Increase paper trading cycles from 7 to 12 per day (~30-min cadence during market hours). (2) Add a configurable `ranking_min_composite_score` setting (default 0.30) and lower it to 0.15 during paper bake via `.env`. (3) Create a `scripts/run_backtest_sweep.py` that runs `BacktestComparisonService` across 6 historical market-regime windows (bull, bear, sideways, volatile, recovery, recent) to generate hundreds of simulated trades for the weight optimizer.
- **Alternatives:** (a) Only run more cycles — rejected alone because the position limits (max 10 positions, 8 new/day) still cap throughput; the self-improvement loop needs diversity of trade quality, not just quantity. (b) Only run backtests — rejected alone because backtests generate synthetic fills that may diverge from real-time paper execution behaviour. (c) Remove risk controls to increase throughput — rejected, violates spec §4.1; the learning system must learn under the same constraints it will face in live mode.
- **Rationale:** The self-improvement system requires at least 10 closed trades per strategy (`self_improvement_min_signal_quality_observations`) before auto-execute can fire. At 7 cycles/day with a 0.30 score floor, marginal signals are filtered out and the system only sees high-confidence trades — it never learns what a bad trade looks like. Lowering the threshold to 0.15 during paper bake is safe because the risk engine still enforces all hard limits (stop-loss, drawdown, VaR, sector concentration). The backtest sweep is the highest-leverage move: it can generate months of simulated data in hours, feeding the weight optimizer with Sharpe-optimal strategy weights before real-time paper data accumulates.
- **Consequence:** Worker schedules 12 cycles (was 7). More marginal signals admitted. `APIS_RANKING_MIN_COMPOSITE_SCORE` must be raised to 0.30+ before any live trading transition. Backtest sweep is manual (operator runs script); results persist to `backtest_runs` table for the 06:52 weight optimization job to consume automatically.

---

## [2026-04-08] Session — Phase 58 Self-Improvement Auto-Execute Safety Gates

### DEC-019: Gate the self-improvement auto-execute loop behind an explicit feature flag and a signal-quality observation floor
- **Decision:** Add three safety gates to `run_auto_execute_proposals` before any PROMOTED proposal can modify the running system:
  (1) `settings.self_improvement_auto_execute_enabled` — master switch, **default False**, operator must explicitly opt in;
  (2) `settings.self_improvement_min_signal_quality_observations` — default 10 — minimum `SignalQualityReport.total_outcomes_recorded` before the batch is allowed to run at all;
  (3) `settings.self_improvement_min_auto_execute_confidence` — default 0.70 — now actually passed through to `AutoExecutionService.auto_execute_promoted` (previously the argument was never passed, so the 0.70 default in `SelfImprovementConfig` was dead code in production).
- **Trigger:** Review of live-money readiness on 2026-04-08 surfaced that with only ~5 trading days of real signals (securities table was only seeded 2026-03-31), the `confidence_score` on any auto-generated proposal is statistically meaningless. Separately, reading `run_auto_execute_proposals` showed the worker never passed `min_confidence` to the service, so the documented 0.70 confidence gate wasn't being enforced at runtime.
- **Alternatives considered:**
  (a) Raise `min_auto_execute_confidence` to 0.90 and leave everything else as-is. Rejected: still leaves the observation-floor hole — a single noisy closed trade could fabricate a "high-confidence" proposal; and still depends on the caller actually passing the kwarg, which it wasn't.
  (b) Disable the scheduled `auto_execute_proposals` job outright until promotion to HUMAN_APPROVED. Rejected: loses coverage of the code path entirely, means the first time it runs in anger will be the first time it has ever run in paper, and hides the real bug (the missing `min_confidence` pass-through).
  (c) Delete `SelfImprovementConfig.min_auto_execute_confidence` and hardcode in the job. Rejected: config belongs in `Settings` so it can be flipped via env var without a code change.
- **Rationale:** The system should keep *generating* and *promoting* proposals during the paper-trading bake period (the signal_quality and self-improvement jobs remain valuable feedback loops), but applying them to runtime overrides without a human in the loop is premature when the underlying statistics are noise. A default-off flag plus an observation floor gives a clean, auditable "do nothing until the data supports it" posture, and the fixed confidence pass-through means that when the operator does flip the flag, the 0.70 gate actually works as documented. All three gates return a distinct `status` string (`skipped_disabled`, `skipped_insufficient_history`, `ok`) so operators and the dashboard can tell exactly why the job was a no-op on any given night.
- **Consequence:** Modified files: `config/settings.py` (+3 fields), `apps/worker/jobs/self_improvement.py` (`run_auto_execute_proposals` now reads settings, short-circuits, and passes `min_confidence` through), `tests/unit/test_phase35_auto_execution.py` (existing worker-job tests updated to pass an enabled `Settings`; helper `_make_app_state` now seeds a `SignalQualityReport` with 50 outcomes; `_make_promoted_proposal` defaults `confidence_score=0.80`; 6 new Phase 58 tests cover disabled default, enabled happy path, thin-history skip, missing-report skip, confidence-below-threshold skip, and high-confidence execute). All 13 `TestAutoExecuteWorkerJob` tests pass. Auto-execute is OFF by default — operator flips `APIS_SELF_IMPROVEMENT_AUTO_EXECUTE_ENABLED=true` only once closed-trade history and signal quality observations are stable (targeted for after the PAPER → HUMAN_APPROVED gate promotion).
