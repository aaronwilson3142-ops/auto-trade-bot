# APIS — Decision Log
Format: timestamp | decision | alternatives considered | rationale | consequence

---

## [2026-04-26] Phase 67 — Worker RED Fix

### DEC-049: Anti-churn cap — cap OPEN target_notional to rebalance target weight × equity
- **Decision:** After rebalance merge step, iterate OPEN actions and cap `target_notional` to the rebalance target weight for that ticker × current equity. Recalculate `target_quantity` accordingly.
- **Alternatives considered:** (a) Reduce half-Kelly factor from 0.5 to a lower value — too blunt, affects all sizing not just rebalance conflicts. (b) Skip OPEN entirely when rebalance target exists — too aggressive, prevents any new position entry. (c) Use rebalance target as max instead of half-Kelly — chosen approach, surgically fixes the mismatch.
- **Rationale:** Half-Kelly sized ODFL at ~14.6% ($14.6k) while rebalance target was 6.67% ($6.7k). The 2x overshoot triggered immediate TRIM, then next cycle re-bought at full size. Capping to rebalance target eliminates the sizing mismatch that drives the churn loop.
- **Consequence:** OPEN positions will be right-sized from the start, eliminating the OPEN→TRIM→OPEN churn cycle. Cash freed up (~$8k per position saved). Sharpe should recover over 1-2 weeks.

### DEC-050: Signal quality — bulk upsert with ON CONFLICT DO NOTHING
- **Decision:** Replace per-row `session.add()` + batch `session.commit()` with PostgreSQL `pg_insert().on_conflict_do_nothing(constraint="uq_signal_outcome_trade")`.
- **Alternatives considered:** (a) Check existence before insert — N+1 query pattern, slower. (b) Try/except per row — masks other errors. (c) Bulk upsert with ON CONFLICT — chosen, idempotent and efficient.
- **Rationale:** Duplicate (ticker, strategy_name, trade_opened_at) tuples from prior runs caused IntegrityError. The constraint `uq_signal_outcome_trade` already existed; the code just needed to use it.
- **Consequence:** Signal quality updates will complete cleanly on re-runs. `signal_outcomes` table will accumulate data for quality reporting.

### DEC-051: Sector rebalance trims — active sector weight correction
- **Decision:** Add `generate_sector_trim_actions()` to SectorExposureService. When a sector exceeds `max_sector_pct` (40%), generate pre-approved TRIM actions for the largest positions in that sector until projected weight drops to or below the limit.
- **Alternatives considered:** (a) Only block new OPENs (existing behavior) — insufficient, doesn't reduce existing overweight. (b) Close entire positions — too aggressive, loses position thesis. (c) Trim largest first to reduce excess — chosen, preserves positions while reducing concentration.
- **Rationale:** Sector filter only prevented new breaches but never corrected existing ones. Tech at 39.7% could easily cross 40% with a single price move and would stay overweight indefinitely.
- **Consequence:** Sectors will be actively managed back under limits. Trim actions are pre-approved (same as overconcentration trims). Currently tech at 39.7% won't trigger, but provides forward protection.

---

## [2026-04-23] Phase 65b — Intra-Cycle Churn Fix

### DEC-048: Phase 65b — suppress non-critical exit CLOSEs for rebalance-protected tickers + add intra-cycle OPEN+CLOSE dedup guard
- **Decision:** Two-layer fix: (1) extend the exit-action merge in `run_paper_trading_cycle` to suppress non-critical exit CLOSEs (score_decay_exit, max_position_age, etc.) for rebalance-protected tickers while letting critical risk exits (stop_loss, trailing_stop, atr_stop, max_drawdown) fire unconditionally; (2) add a final intra-cycle dedup pass after ALL action sources complete, dropping CLOSEs for any ticker that also has an OPEN in the same batch. Also fixed NULL origin_strategy with fallback chain.
- **Alternatives considered:**
  - (a) Modify `apply_ranked_opportunities` in `portfolio_engine/service.py` to accept a "just_opened" set. Rejected — `apply_ranked_opportunities` already correctly partitions opens and closes by ticker; the churn comes from the interaction between MULTIPLE subsystems (portfolio engine CLOSEs vs rebalance OPENs, exit evaluation CLOSEs vs rebalance OPENs), not from within a single subsystem.
  - (b) Move all CLOSEs to run BEFORE all OPENs in separate execution batches. Rejected — would require splitting the execution engine call and the broker sync, adding complexity to the cycle flow. The dedup guard achieves the same effect with zero refactoring.
  - (c) Make rebalance targets suppress ALL CLOSEs regardless of reason. Rejected — critical risk exits (stop-loss, trailing-stop) must always fire; rebalance targets should not override safety mechanisms.
- **Rationale:** DEC-037 (TTL 3600→43200) fixed the stale-target path but didn't address exit evaluation generating CLOSEs with reasons that bypass Phase 65 suppression (which only checked for reason == "not_in_buy_set"). Exit evaluation fires after Phase 65 suppression and adds CLOSEs to the same `proposed_actions` list that rebalance later adds OPENs to — creating cross-cycle and potentially intra-cycle conflicts. The `_critical_exit_reasons` whitelist is the minimal change that preserves safety while eliminating waste. The dedup guard is a safety net for any future subsystem interaction that produces same-ticker OPEN+CLOSE pairs.
- **Consequence:** Rebalance-protected positions can no longer be closed by non-critical exit evaluation. This means positions held by rebalance targets will stay open longer (until rebalance targets change or a critical stop fires). This is the correct behaviour — if the rebalance engine wants a position, non-critical exits shouldn't fight it. Validation: next paper cycles should show zero intra-cycle churn, stable cash, and clearing broker_health_position_drift warnings.

---

## [2026-04-22] Five-Concern Operator Sprint

### DEC-037: Phase 65 Alternating Churn — fix via `rebalance_target_ttl_seconds` 3600 → 43200, not by modifying the suppression logic
- **Decision:** Raise the TTL for cached rebalance targets from 1h to 12h (12 × 3600 = 43200 s). Leave the Phase 65 PaperBrokerAdapter persistence and the rebalance-close suppression branch in `paper_trading.py` untouched.
- **Alternatives considered:**
  - (a) Add a second persistence layer on top of the 2026-04-16 fixes. Rejected — the original fixes were still intact; dupes were NOT from the persistence path regressing.
  - (b) Shorten the rebalance_check → first-paper-cycle gap by moving the cron. Rejected — the 06:26 ET cadence is shared with other jobs; moving it risks cascading schedule drift.
  - (c) Tie rebalance target lifetime to a session boundary (expire at next 06:26 ET). Rejected as overengineered — a 12h TTL falls naturally before the next 06:26 ET rebalance overwrites the cache anyway.
- **Rationale:** Root cause analysis showed the 2026-04-22 re-emergence of +1 dupe CLOSED row per ticker per cycle was driven by targets aging out between the 06:26 ET rebalance_check and the 09:35 ET first paper cycle (3h9m gap > 1h TTL). Once a target is `None`, the rebalance-close suppression branch correctly returns early — but so does the rebalance logic itself, which then re-enters via the default CLOSE path. Fixing the TTL preserves the original Phase 65 fix invariants and introduces no new branches.
- **Consequence:** Targets persist through the full trading day (06:26 ET → 18:26 ET) and expire before the next daily rebalance_check overwrites them. Validation: first Thu 2026-04-23 09:35 ET paper cycle should emit zero new duplicate CLOSED rows. If that assertion holds through a 2-day observation window, the churn regression is closed.

### DEC-038: Phantom-equity mark-to-market — add `_fetch_price_strict` helper, preserve prior-close on yfinance failure, emit WARN
- **Decision:** Introduce `_fetch_price_strict(ticker, market_data_svc) -> Decimal | None` as a new helper in `paper_trading.py` and call it from the MTM loop. On `None` result, preserve the prior-close price from the open Position row and log `mark_to_market_stale_price_preserved` at WARN. Separately log `phantom_equity_guard_active` at WARN when the guard runs.
- **Alternatives considered:**
  - (a) Modify `_fetch_price` in-place to return `None` on failure instead of defaulting to `$1000/qty`. Rejected — `_fetch_price` is also used by sizing paths where the `$1000/qty` nominal fallback is intentional (OPEN sizing needs a shape even with stale data); changing that behaviour risks a second-order regression elsewhere.
  - (b) Skip the MTM snapshot entirely on any failure. Rejected — blanking the equity curve is worse for observability than preserving the last-good value plus a WARN.
- **Rationale:** Root cause was `_fetch_price` returning `$1000/qty` on yfinance DNS failure, overwriting real prior prices in the mark-to-market loop and collapsing gross exposure to ~$5K. Strict variant separates "sizing default" vs. "valuation truth" semantics. Prior-close preservation keeps the equity curve monotonic across transient network failures.
- **Consequence:** Any future yfinance outage produces a flat-equity snapshot rather than a phantom-zero snapshot. The WARN pair (`mark_to_market_stale_price_preserved`, `phantom_equity_guard_active`) is a new observability signal — deep-dive §2 should grep worker logs for these going forward.

### DEC-039: Orders + Fills ledger writer — land `_persist_orders_and_fills` with `{cycle_id}:{ticker}:{side}` idempotency key
- **Decision:** Add `_persist_orders_and_fills(approved_requests, execution_results, run_at, cycle_id)` helper in `paper_trading.py`, wired immediately after `_execution_svc.execute_approved_actions()`. One `Order` row per `ExecutionRequest` (success OR failure), one `Fill` row per FILLED result. Idempotency key: `{cycle_id}:{ticker}:{side}`. Fire-and-forget: logs `persist_orders_fills_failed` at WARN on any exception, never raises.
- **Alternatives considered:**
  - (a) Key by `execution_request.id` alone. Rejected — request IDs are not guaranteed stable across a replay, but `cycle_id` + ticker + side is.
  - (b) Key by `cycle_id` + `request.id`. Rejected — too verbose, and tracks an internal detail (request.id) that deep-dive reconciliation shouldn't need.
  - (c) Only persist FILLED rows (skip REJECTED/BLOCKED). Rejected — the whole point is a per-order audit trail; REJECTED/BLOCKED rows are the most valuable ones for the self-improvement engine.
  - (d) Raise on failure instead of WARN-and-continue. Rejected — every other persistence path in paper_trading.py is fire-and-forget (see `_persist_positions`), and paper cycles must not crash on ledger write failures.
- **Rationale:** `orders` and `fills` tables had zero rows ever despite hundreds of executions — no production writer existed. Mirror the Phase 64 Position persistence pattern exactly. The `{cycle_id}:{ticker}:{side}` key allows UPSERT on cycle replay without duplicating rows.
- **Consequence:** First Thu 2026-04-23 09:35 ET paper cycle should produce non-zero `orders` and `fills` rows. Deep-dive §2 gains a new cross-check: `orders`/`fills`/`closed_trades`/`positions` should reconcile. Idempotency test: re-running a cycle with the same `cycle_id` must not duplicate rows.

### DEC-040: universe_overrides — land Alembic migration even though the table was never missed in production
- **Decision:** Add `p6q7r8s9t0u1_add_universe_overrides.py` migration matching the `UniverseOverride` ORM exactly. down_revision = `o5p6q7r8s9t0` (Deep-Dive Step 8 strategy_bandit_state). Apply immediately via `docker exec docker-api-1 alembic upgrade head`.
- **Alternatives considered:**
  - (a) Keep the gap — the ORM exists but no production code path depends on the table today (the `UniverseManagementService` DB load path silently skips when the table is absent). Rejected — deep-dive §3 flags it every run as alembic-drift, and POST/DELETE on `/api/v1/universe/overrides` routes return 500 on any write attempt.
  - (b) Delete the ORM model instead. Rejected — the service + route code would also need ripping out, and operator intent for Phase 48 was to have this override path available.
- **Rationale:** A table that exists in the ORM but not in any migration is always drift; the question is only when it bites. Closing the gap now costs one migration file + one index trio, and aligns the Alembic head with the ORM model set.
- **Consequence:** Alembic head advances to `p6q7r8s9t0u1`. Deep-dive §3 should now see a clean head state. Universe override routes no longer 503; they still 401 in unit tests due to operator-auth env drift — that is a separate pre-existing issue unrelated to this migration. Rollback path if needed: `alembic downgrade o5p6q7r8s9t0`.

### DEC-041: Phantom-equity snapshot 2026-04-22 13:35:00.075017 — DB-side DELETE now, do not wait for self-heal
- **Decision:** DELETE the one phantom row (`id = '4e6421e1-27c6-4dc4-851b-2cca0ed57274'`) from `portfolio_snapshots` via direct psql. Scope the delete with a belt-and-braces `AND equity_value < 30000` so only the phantom row can match.
- **Alternatives considered:**
  - (a) Let the next cycle self-heal the equity curve and leave the phantom row in place as a historical artifact. Rejected — the deep-dive daily report aggregates over `portfolio_snapshots` for the equity curve; leaving a $0-ish row in would skew every chart that spans 2026-04-22.
  - (b) Archive the row to a `portfolio_snapshots_quarantine` table. Rejected — we already have the phantom-equity post-mortem documented in `project_phantom_equity_writer_2026-04-22.md` and `HEALTH_LOG.md`; a DB-side copy adds no value.
- **Rationale:** One-off data hygiene op with a narrow predicate. The fix in DEC-038 prevents future phantom rows; this cleanup removes the single bad row already on disk.
- **Consequence:** 1 row deleted; verification SELECT confirmed 0 remaining. Equity curve across 2026-04-22 is now monotonic. If a similar event recurs before DEC-038's fix has fully propagated (shouldn't happen — the code is already deployed), the same narrow DELETE pattern is repeatable.

---

## [2026-04-18] Phase 57 Part 2 — Insider Flow Providers Land Default-OFF

### DEC-036: Land Phase 57 Part 2 (QuiverQuant + SEC EDGAR adapters + enrichment wiring) straight to `main` behind default-OFF credential gates
- **Decision:** Commit the two concrete `InsiderFlowAdapter` implementations (`QuiverQuantAdapter`, `SECEdgarFormFourAdapter`), the `build_insider_flow_adapter` factory, and the `FeatureEnrichmentService` hook directly to `main` without a feature branch. The entire codepath is gated by `APIS_INSIDER_FLOW_PROVIDER=null` (default) plus the Part-1 `APIS_ENABLE_INSIDER_FLOW_STRATEGY=false` flag, so production behaviour is byte-for-byte identical until the operator opts in and supplies a credential.
- **Alternatives considered:**
  - (a) Land on `feat/phase57-part2` branch, open a PR against `main`. Rejected — operator directive 2026-04-18 ("commit the concrete adapter straight to `main`; default-OFF flag means behaviour-neutral, consistent with how the Deep-Dive steps landed"). The Deep-Dive Step 1–8 commits used the same straight-to-`main` pattern.
  - (b) Crash-on-missing-credential. Rejected — "a missing signal is preferable to a crashed paper cycle." The factory logs a WARNING and degrades to `NullInsiderFlowAdapter`. Explicit `_fire_ks()`-triad lesson from the 2026-04-17 crash-triad (see `project_paper_cycle_crashtriad_2026-04-18.md`): adapters in the hot path must fail open.
  - (c) Use HTTP retries that raise on exhaustion. Rejected for the same reason; retry exhaustion returns `[]`.
- **Rationale:** Default-OFF behind two flags + credential presence = zero risk of unintended signal injection before ToS review. The paid QuiverQuant account requires operator review of programmatic-ingestion terms before a key can be provisioned. SEC EDGAR requires a real User-Agent before any traffic is sent. Both gates are explicit in the factory's fallback matrix (see docstring of `insider_flow_factory.py`).
- **Consequence:** Adapter code is on `main` and live in the image, but the signal stays absent from `InsiderFlowOverlay` until the operator:
  1. Reviews QuiverQuant ToS for the APIS use-case.
  2. Sets `APIS_INSIDER_FLOW_PROVIDER=quiverquant` (or `sec_edgar`/`composite`) in `apis/.env`.
  3. Sets the matching credential (`APIS_QUIVERQUANT_API_KEY` and/or `APIS_SEC_EDGAR_USER_AGENT=<real contact>`).
  4. For EDGAR: threads a `ticker_to_cik` map into the factory call from the enrichment wire (currently passes `None` → tickers without CIK silently skip).
  5. Flips `APIS_ENABLE_INSIDER_FLOW_STRATEGY=true` so the `InsiderFlowStrategy` reads the now-populated overlay.
- **Not covered by this decision:** the signal's weight inside the regime-weighted blend. That stays at its Part-1 scaffold value until after shadow-portfolio evidence accumulates (see DEC-034). Any raise is a separate proposal through the self-improvement engine (subject to DEC-033's frozen-gates list).

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
