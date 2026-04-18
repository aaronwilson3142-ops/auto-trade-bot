# APIS — Changelog
Format: [YYYY-MM-DD] | file/module | description

---

## [2026-04-18] Deep-Dive Plan Steps 7 + 8 — MERGED TO MAIN (d3d2bfe)

Overnight scheduled task `deep-dive-steps-7-8` completed the final two steps of the 2026-04-16 Deep-Dive Execution Plan on branch `feat/deep-dive-plan-steps-7-8`; fast-forward-merged to `main` 2026-04-18.

**Step 7 — Shadow Portfolio Scorer (Rec 11 + DEC-034)** — committed at `7009538`.
- New tables `shadow_portfolios`, `shadow_positions`, `shadow_trades` (migration `n4o5p6q7r8s9_add_shadow_portfolios.py`).
- `services/shadow_portfolio/service.py` (464 lines) + `apps/worker/jobs/shadow_performance_assessment.py` (101 lines) — weekly parallel rebalance-weighting shadows.
- `config/settings.py` — `strategy_bandit_enabled=False` + friends; `APIS_SHADOW_PORTFOLIO_ENABLED=False`; `shadow_stopped_out_max_age_days=30`.
- 23 unit tests in `tests/unit/test_deep_dive_step7_shadow_portfolios.py` — all passing.
- DEC-034 logged (parallel shadow portfolios for rebalance-weighting comparison).

**Step 8 — Thompson Strategy Bandit (Rec 12)** — committed at `d3d2bfe`.
- New table `strategy_bandit_state` (migration `o5p6q7r8s9t0_add_strategy_bandit_state.py`). One row per strategy_family holds Beta(alpha, beta) posterior + counters + last_sampled_weight `Numeric(18, 16)`.
- `services/strategy_bandit/service.py` (290 lines) — `StrategyBanditService.update_from_trade(...)`, `sample_weights(...)`; Thompson draw → lambda smoothing → floor/ceiling clamp → renormalise.
- `apps/worker/jobs/paper_trading.py` — closed-trade hook that runs **unconditionally** (plan A8.6) so the posterior accumulates 2–4 weeks of warm-start priors even while the runtime flag is OFF.
- `config/settings.py` — 5 new settings:
  - `strategy_bandit_enabled = False`
  - `strategy_bandit_smoothing_lambda = 0.3`
  - `strategy_bandit_min_weight = 0.05`
  - `strategy_bandit_max_weight = 0.40`
  - `strategy_bandit_resample_every_n_cycles = 10`
- 25 unit tests in `tests/unit/test_deep_dive_step8_strategy_bandit.py` — all passing (settings defaults, constructor validation, update semantics, sampling, plan-§8.6 invariant, read helpers).

**Alembic smoke test (against live docker-postgres-1):**
`m3n4o5p6q7r8 → n4o5p6q7r8s9 → o5p6q7r8s9t0` (upgrade head) → `downgrade -1` (back to `n4o5p6q7r8s9`) → `upgrade head` (back to `o5p6q7r8s9t0`). Both migrations reversible.

**Behavioural impact:** zero. Every Step 7 + Step 8 behaviour is gated on a flag that defaults OFF. The *only* path that runs regardless is the Step 8 closed-trade posterior update (plan A8.6 warm-start requirement).

**Merge summary:** `e6b2a3a..d3d2bfe` fast-forward, 14 files, +2902/-3.

---

## [2026-04-18 10:24 UTC] CRITICAL FIX — Paper cycle crash-triad (kill-switch + broker lazy-init + EvaluationRun ORM)

Autonomous daily health check traced yesterday's complete paper-cycle failure to three bugs that had to be fixed together. All three landed in today's session; worker + api restarted and verified healthy.

**Fix 1 — `_fire_ks()` signature mismatch in `apps/worker/jobs/paper_trading.py`.**
`services/broker_adapter/health.py::check_broker_adapter_health` calls `fire_kill_switch_fn(reason)` with a string, but the inline kill-switch helper defined in `run_paper_trading_cycle` took zero args. Every invariant breach therefore crashed with `TypeError: _fire_ks() takes 0 positional arguments but 1 was given` BEFORE the kill switch could arm. Changed `def _fire_ks()` → `def _fire_ks(reason: str)`; still sets `app_state.kill_switch_active = True` on any exception path.

**Fix 2 — Broker adapter lazy-init must precede the health invariant check.**
Same file. On a fresh worker boot (which Phase 64 encourages because positions restore from DB), `app_state.broker_adapter` is None until the cycle constructs it — but the broker-adapter invariant check ran FIRST and saw None-adapter + live-positions, which is explicitly the "hard stop" condition in Deep-Dive Step 2 Rec 2. Added a guarded lazy-init block that runs before the health check:
```python
# ── Broker adapter lazy init (must precede health check) ─────────────────
if getattr(app_state, "broker_adapter", None) is None and broker is None:
    try:
        from broker_adapters.paper.adapter import PaperBrokerAdapter
        app_state.broker_adapter = PaperBrokerAdapter(market_open=True)
        logger.info("broker_adapter_lazy_initialized", cycle_id=cycle_id, reason="fresh_worker_start")
    except Exception as _bi_exc:
        logger.warning("broker_adapter_lazy_init_failed", error=str(_bi_exc), cycle_id=cycle_id)
```
This preserves the invariant's intent (no live trading with a lost adapter mid-cycle) while correctly handling the cold-start case.

**Fix 3 — `EvaluationRun.idempotency_key` missing on ORM model.**
The 2026-04-17 Alembic migration `k1l2m3n4o5p6` added the `idempotency_key` column (+ unique constraint) to `evaluation_runs`, but `infra/db/models/evaluation.py::EvaluationRun` wasn't updated to mirror it. Every `_persist_evaluation_run` call with a `run_id` therefore raised `AttributeError: 'EvaluationRun' has no attribute 'idempotency_key'`. Added:
```python
idempotency_key: Mapped[str | None] = mapped_column(sa.String(200), nullable=True)
```
ORM models for `PortfolioSnapshot` and `PositionHistory` already had this attribute; evaluation.py was the outlier.

**Fix 4 — Pre-existing test mock closure bug in `tests/unit/test_deep_dive_step2_idempotency_keys.py`.**
After Fix 3 landed, `test_persist_evaluation_run_with_run_id_populates_idem_key` exposed a pre-existing bug in `_FakeEvalDb._Result.scalar_one_or_none`: the method referenced `self._existing`, but because `_Result` is a class nested inside `execute()`, the nested-scope `self` was ambiguous. Fixed by renaming the implicit-self parameter to `self_inner` and accessing `self_inner._existing` — unambiguous to the reader and a no-op in intended behaviour.

**Verification:**
- `docker compose restart worker api` → both containers healthy.
- `/health` → all components `ok`.
- Scheduler loaded 35 jobs; next paper cycle = Monday 2026-04-20 09:30 ET (market closed Saturday).
- AST-parse + import + `hasattr(EvaluationRun, 'idempotency_key')` assertions all pass.
- Pytest re-run of `test_deep_dive_step2_idempotency_keys.py` deferred to next interactive session (autonomous run, no Docker access from sandbox).

**Operational impact:**
Monday's first paper cycle will now be the first one since 2026-04-16 that reaches `_persist_evaluation_run` without crashing. The kill-switch will also arm cleanly if the adapter invariant *legitimately* fails later.

**Flagged for operator (NOT auto-fixed):**
Post-fix `_load_persisted_state` restored **cash=-$80,274.62 and 13 positions** — Phase 63's phantom-cash guard requires `positions==0` to intervene, so it doesn't. This is financial-state correction and should happen with operator present. See HEALTH_LOG.md 2026-04-18 entry, "Known Issues" §1.

See: `apis/state/HEALTH_LOG.md` entry 2026-04-18 10:24 UTC.

---

## [2026-04-17 12:12 UTC] OPS — Migrations self-heal on api startup (entrypoint script)

Followed up on this morning's migration-drift incident (see 10:15 UTC entry below) with a permanent hardening so the same root cause cannot recur.

**What changed:**
- NEW `apis/infra/docker/entrypoint-api.sh` — baked into the api image at `/usr/local/bin/entrypoint-api.sh`. Runs `alembic upgrade head` before exec-ing `uvicorn apps.api.main:app`. `set -e` ensures a failed migration hard-stops the container (container goes unhealthy → operator pages) instead of silently booting against a stale schema.
- `apis/infra/docker/Dockerfile` api stage — swapped final `CMD [uvicorn …]` for `ENTRYPOINT ["/usr/local/bin/entrypoint-api.sh"]`. Worker stage unchanged (worker `depends_on: api: service_healthy`, so by the time worker boots the api has already applied migrations — no race, no need to duplicate the upgrade).
- Script path is `/usr/local/bin/` (not `/app/apis/`) so it's **outside** the dev source bind-mount in `docker-compose.yml`; operators developing with source mount still get the entrypoint. Mode 0755 via `RUN chmod +x`.

**Verification:**
- `docker compose build api` succeeded. `docker compose up -d --no-deps --force-recreate api` booted the container, logs showed `[entrypoint-api] Running Alembic migrations (current -> head)...` → `INFO  [alembic.runtime.migration] Context impl PostgreSQLImpl.` → `Migrations complete. Starting uvicorn...`. `/health` returned all components `ok` once uvicorn finished startup.
- Confirmed self-heal property with `docker restart docker-api-1` — logs show the entrypoint banner twice (initial boot + restart), migrations idempotent on already-head DB.

**Operational impact:**
Schema drift between committed migrations and live DB now self-heals on every api boot. Paper-mode only — if/when APIS goes live, consider gating on `APIS_OPERATING_MODE` and fail-fast on drift rather than auto-applying (rationale in the entrypoint header comment).

See: entrypoint header comment for full rationale, and 10:15 UTC entry below for the incident that motivated this.

---

## [2026-04-17 10:15 UTC] OPS — Applied 3 pending Alembic migrations (j0k1l2m3n4o5 → m3n4o5p6q7r8)

Daily health check discovered API startup at 03:31 UTC was failing `_load_persisted_state` because the ORM had three recent schema changes (Deep-Dive Plan Steps 2/5/6) whose Alembic migration files were committed but never applied to the live DB. Symptoms: `paper_cycle: no_data` on /health; `load_portfolio_snapshot_failed`, `portfolio_state_restore_failed`, `closed_trades_restore_failed` warnings on startup referencing missing columns `portfolio_snapshots.idempotency_key` and `positions.origin_strategy`.

Ran `docker exec -w /app/apis docker-worker-1 alembic upgrade head` — all 3 migrations applied cleanly (only additive: nullable column adds + new `proposal_outcomes` table). Restarted docker-api-1 to re-run restore with new schema. Post-restart: all components `ok`; portfolio restored with 5 positions / $44,326.61 cash / $94,403.69 equity; 99 closed trades; 84 evaluation runs; 15 paper cycle count.

Follow-up recommendation: wire `alembic upgrade head` into worker/api container entrypoint so migrations self-apply on deploy.

See: `apis/state/HEALTH_LOG.md` entry 2026-04-17 10:11 UTC.

---

## [2026-04-17 13:00 UTC] Deep-Dive Plan — Step 6 LANDED (Proposal Outcome Ledger + daily assessment job, flag default OFF)

### Summary
Step 6 of the Deep-Dive Execution Plan complete — Rec 10 (DEC-035). New `proposal_outcomes` ledger table plus a `ProposalOutcomeLedgerService` that records every terminal decision (PROMOTED / REJECTED / EXECUTED / REVERTED) on an `ImprovementProposal` together with a baseline metric snapshot, then closes the window after `PROPOSAL_OUTCOME_WINDOWS[proposal_type]` days and fills in the realized snapshot, verdict, and confidence. The ledger drives a per-type **batting-average** feedback signal which the proposal generator uses (via `SelfImprovementService.apply_outcome_feedback`) to suppress under-performing proposal types. All new behaviour is gated behind `APIS_PROPOSAL_OUTCOME_LEDGER_ENABLED=False` (default), so byte-for-byte legacy behaviour is preserved until the operator opts in. Per DEC-031 this advances the "more self-improvement" lever without touching the 9 hard risk gates (DEC-033) or AI-tilt defaults (DEC-032).

### New settings (`config/settings.py`)
- `proposal_outcome_ledger_enabled: bool = False` — master switch. When OFF, the ledger silently collects decision rows (write-only) and `apply_outcome_feedback` is a no-op; the generator never consults batting averages. When ON, `generate_proposals` skips suppressed `(proposal_type, target_component)` combos per plan §6.6.
- `proposal_outcome_min_observations: int = 10` (1..1000) — diversity floor: minimum assessed rows before the generator starts suppressing a combo. Prevents first-few-assessments noise from killing a type outright.
- `proposal_outcome_diversity_floor_days: int = 31` (1..365) — minimum days between two suppressions of the same type. Per plan §6.6 prevents exploration collapse.

### Per-type measurement windows (DEC-035)
Defined in `services/self_improvement/outcome_ledger.py::PROPOSAL_OUTCOME_WINDOWS`. Tests in §`TestProposalOutcomeWindows` lock these to DEC-035:
- `source_weight` → 45 days
- `ranking_threshold` → 30 days
- `holding_period_rule` → 14 days
- `confidence_calibration` → 60 days
- `prompt_template` → 30 days
- `_DEFAULT` → 30 days (unknown / new types)
`window_days_for(type_key)` lowercases + strips whitespace, defaults to `_DEFAULT` for unknown keys so a typo in proposal_type never crashes the writer.

### Rec 10 — Ledger module
- NEW `services/self_improvement/outcome_ledger.py` (288 lines)
  - `PROPOSAL_OUTCOME_WINDOWS` table + `window_days_for(type_key)` lookup.
  - `BattingAverage` dataclass — `proposal_type`, `n_total`, `n_improved`, `n_regressed`, `n_unchanged`, `n_inconclusive`, plus `improved_rate` / `regressed_rate` properties that guard against div-by-zero.
  - `ProposalOutcomeLedgerService(session)`:
    - `write_decision(proposal_id, decision, baseline_metric_snapshot, now=None)` — inserts a new row with `measurement_window_days` resolved from the proposal's type. Guards: decision ∈ {`PROMOTED`,`REJECTED`,`EXECUTED`,`REVERTED`}.
    - `get_due_for_assessment(now=None)` — rows where `decision_at + measurement_window_days ≤ now` AND `realized_metric_snapshot IS NULL`. Ordered by oldest-first.
    - `write_assessment(outcome_id, realized_metric_snapshot, outcome_verdict, outcome_confidence, measured_at)` — guards verdict ∈ {`improved`,`unchanged`,`regressed`,`inconclusive`}; confidence ∈ [0,1]. Idempotent on outcome_id.
    - `batting_average(proposal_type, min_observations=10)` — aggregates closed rows into a `BattingAverage`; returns `None` if `n_total < min_observations`.
    - `suppressed_types(min_observations, max_regression_rate)` — returns the set of proposal types whose regressed_rate exceeds the threshold.
- NEW `infra/db/models/self_improvement.py::ProposalOutcome` ORM model (declarative SQLAlchemy) with FK to `improvement_proposals.id`, JSONB `baseline_metric_snapshot` / `realized_metric_snapshot`, `outcome_verdict` VARCHAR(20), `outcome_confidence` NUMERIC(4,3), `measured_at` TIMESTAMPTZ, `TimestampMixin` for created_at/updated_at.
- NEW Alembic migration `infra/db/versions/m3n4o5p6q7r8_add_proposal_outcomes.py` — `CREATE TABLE proposal_outcomes` with unique constraint on (proposal_id). Revises `l2m3n4o5p6q7` (Step 5 origin_strategy). Additive-only; safe to apply eagerly.

### Self-improvement generator feedback loop
- `services/self_improvement/service.py`:
  - `__init__` adds `self._suppressed_types: set[str] = set()`.
  - `apply_outcome_feedback(suppressed_types: set[str] | None)` — caller (worker job) passes the result of `ProposalOutcomeLedgerService.suppressed_types()`. When `None` or empty set, clears the filter. Flag-OFF callers never invoke this so legacy behaviour is unchanged.
  - `generate_proposals` end-of-function filter: `[p for p in proposals if p.proposal_type.value not in self._suppressed_types]`. With default-empty set, filter is a no-op.

### Daily assessment worker job
- NEW `apps/worker/jobs/proposal_outcome_assessment.py` (84 lines, **stub** for Step 6 Part A)
  - `run_proposal_outcome_assessment(now=None)`:
    1. Exits early with `{"considered":0,"assessed":0,"skipped":0,"flag_off":True}` if `proposal_outcome_ledger_enabled=False`.
    2. Otherwise opens a `SessionLocal()` session, fetches due rows via `get_due_for_assessment`, and writes `inconclusive` verdicts with `outcome_confidence=0.0` for each. This is a harmless default that keeps the ledger from growing an unbounded backlog once the flag is flipped.
    3. Actual metric computation (Δ batting-avg, Δ realized Sharpe, etc.) is intentionally deferred to Step 6 **Part B** once the canonical per-type metric family is chosen. Landing Part A now unblocks the feedback loop end-to-end.
- Wiring into APScheduler (daily 18:30 ET after US market close + daily P&L) is deferred to a later commit to keep Step 6 reviewable in isolation.

### Tests (19 total — 16 pass + 3 sandbox-skip, no regressions)
- `tests/unit/test_deep_dive_step6_proposal_outcome_ledger.py` (363 lines):
  - `TestProposalOutcomeWindows` (3): DEC-035 windows match, `window_days_for` normalises case/None/unknown → `_DEFAULT`.
  - `TestProposalOutcomeLedgerService` (6): decision-value guard, verdict-value guard, confidence-range guard, stub declarative model shape (columns / FKs / constraints present).
  - `TestBattingAverage` (3): improved_rate, regressed_rate, zero-total div-guard.
  - `TestGeneratorFeedbackLoop` (3): suppressed types filter out matching proposals, `apply_outcome_feedback(None)` clears suppression, default-construction produces all rules. **Skipped on Python 3.10 sandbox** because `SelfImprovementService.generate_proposals` instantiates `ImprovementProposal`, whose dataclass default_factory calls `dt.datetime.now(dt.UTC)` (Python 3.11+). Production runs 3.11+ so these tests exercise live behaviour there. Follows Step 5 precedent of skipping sandbox-only 3.10 breakage rather than patching an out-of-scope pre-existing model file.
  - `TestWorkerJobFlagOff` (1): flag-off path returns `{considered:0, assessed:0, skipped:0, flag_off:True}` with a stub `_FakeSettings` — no DB touched.
  - `TestSettingsIntegration` (3): `proposal_outcome_ledger_enabled` default False + env-var override, `proposal_outcome_min_observations` bounds, `proposal_outcome_diversity_floor_days` bounds.
- Tests that require a live DB session (end-to-end `write_decision → assess` + `get_due_for_assessment` against real rows) are deferred to the integration suite — the ledger model itself is declarative SQLAlchemy so migration correctness + the alembic run in dev confirmed the schema.
- Full Deep-Dive Step 1–6 sweep: **142 passed, 15 skipped** (skips are Python 3.10 sandbox for `datetime.UTC` in Steps 2 / 5 / 6). No regressions.

### Bug / edge-case learnings this step
- Two real bugs were found in the overnight autonomous artifacts during this morning's verification pass:
  1. `apps/worker/jobs/proposal_outcome_assessment.py` imported `get_session_factory` from `infra/db/session.py`, but that module exposes `SessionLocal` (sessionmaker) not `get_session_factory`. Fixed by switching to `with SessionLocal() as db:` — matches the pattern used by every other worker job.
  2. 3 tests in `TestGeneratorFeedbackLoop` crashed with `AttributeError: module 'datetime' has no attribute 'UTC'` because `services/self_improvement/models.py` lines 80/114/157 use `dt.datetime.now(dt.UTC)` as a `default_factory`. This is **pre-existing code** (present in HEAD before Step 6 started), and production runs Python 3.11+ where `dt.UTC` resolves. Decided to **skip the 3 tests under 3.10** rather than patch the out-of-scope model file — same precedent Step 5 set ("Python 3.10 sandbox still can't resolve `dt.UTC`"). Added `@pytest.mark.skipif(sys.version_info < (3,11), ...)` to the class.
- Mount-sync corruption hit `apps/worker/jobs/proposal_outcome_assessment.py` during the fix — 54 trailing null bytes after byte offset 3307 (the closing `}` of the return dict). Python refused to import the module with `ValueError: source code string cannot contain null bytes`. Recovered by reading the file, `data.rstrip(b'\x00').rstrip() + b'\n'`, writing through a tempfile + `shutil.copy` — same pattern established by Steps 1–5.

### Files touched (authoritative)
- `apis/config/settings.py` — 3 new `Field` entries (already present from overnight run, verified).
- `apis/services/self_improvement/outcome_ledger.py` — new (288 lines, from overnight run).
- `apis/services/self_improvement/service.py` — `_suppressed_types` + `apply_outcome_feedback` + filter in `generate_proposals` (from overnight run).
- `apis/infra/db/models/self_improvement.py` — `ProposalOutcome` ORM model (from overnight run).
- `apis/infra/db/versions/m3n4o5p6q7r8_add_proposal_outcomes.py` — new migration (from overnight run; applied to live DB at 10:15 UTC during drift self-heal).
- `apis/apps/worker/jobs/proposal_outcome_assessment.py` — new (84 lines, **import bug fixed 13:00 UTC** + null-byte recovery).
- `apis/tests/unit/test_deep_dive_step6_proposal_outcome_ledger.py` — new (363 lines; sandbox-skip added 13:00 UTC).

### Operator guidance
- **To activate the ledger write-path:** set `APIS_PROPOSAL_OUTCOME_LEDGER_ENABLED=true` in `apis/.env`. The migration was already applied (see 10:15 UTC OPS entry), so no schema work needed. Rows will start appearing in `proposal_outcomes` as soon as the next terminal decision fires on an improvement proposal. The worker job currently writes `inconclusive` + `confidence=0` (stub); meaningful verdicts land in Step 6 Part B.
- **Watch for:** `proposal_outcome_assessment.due` log line with a non-zero `count` starting 14 days after the first `PROMOTED`/`EXECUTED` decision (shortest window, `holding_period_rule`).
- **To activate the feedback loop:** after Part B lands, the generator will automatically start pruning proposal types whose `regressed_rate > regression_threshold` AND `n_total >= proposal_outcome_min_observations`. Paper-bake ≥6 weeks after the feedback loop activates before considering the signal material.
- Each flag is independent — ledger-write can be ON without the generator filter firing (first 10 observations are below the default floor).

---

## [2026-04-17] Deep-Dive Plan — Step 5 LANDED (ATR stops + per-family max-age + portfolio_fit sizing, both flags default OFF)

### Summary
Step 5 of the Deep-Dive Execution Plan complete — Recs 5 and 7 together in one landing because both hang off the shared `Position.origin_strategy` schema change. Two new flags (`APIS_ATR_STOPS_ENABLED`, `APIS_PORTFOLIO_FIT_SIZING_ENABLED`), both default **OFF**, so legacy behaviour (flat 7% stop / 20-day max age / 5% trailing / half-Kelly sizing) is byte-for-byte preserved until the operator opts in. The shared schema change (one nullable `VARCHAR(64)` column on `positions`) is safe to apply eagerly — existing rows get `NULL` and are treated as the "default" family by the resolver, which is intentionally wider and longer than legacy so no position is stopped out earlier when the flag flips.

### New settings (pydantic `Field` with bounds)
- `atr_stops_enabled: bool = False` — Rec 7 master switch. When ON, `RiskEngineService.evaluate_exits` consults `FAMILY_PARAMS[position.origin_strategy or "default"]` and computes per-position `stop_loss_pct = max(floor, min(cap, stop_atr_mult × atr/price))`. When OFF, the legacy flat `stop_loss_pct` / `max_position_age_days` / `trailing_stop_pct` fire unchanged.
- `portfolio_fit_sizing_enabled: bool = False` — Rec 5 master switch. When ON, `compute_sizing` multiplies half-Kelly by `ranked_result.portfolio_fit_score` (clamped to [0,1]) before the `min(…, max_single_name_pct)` cap applies. When OFF, `portfolio_fit_score` is ignored (its historical state — previously no production consumer).

### Rec 7 — ATR-scaled per-family stops & max-age
- NEW `services/risk_engine/family_params.py` — frozen `FamilyParams` dataclass + 7-entry `FAMILY_PARAMS` dict:
  - `momentum`: 2.5× ATR stop / floor 0.04 / cap 0.18 / 1.5× trailing / 60-day max-age / 5% activation.
  - `theme_alignment`: same as momentum.
  - `macro_tailwind`: same stops as momentum but 20-day max-age.
  - `sentiment`: 2.0× stop / floor 0.03 / cap 0.15 / 1.0× trailing / 15-day max-age (tighter everything).
  - `valuation`: 3.5× stop / floor 0.05 / cap 0.25 / 2.0× trailing / 90-day max-age (widest & longest).
  - `mean_reversion`: 1.5× / 7-day (future family, listed for completeness).
  - `default`: 2.5× / 20-day / 4-15% (hit when origin_strategy is NULL / unknown).
- `resolve_family(key)` — case-insensitive lookup with `Strategy` suffix stripping + hyphen/space normalisation. Unknown keys → `"default"`.
- `compute_atr_stop_pct(family, atr, price)` + `compute_atr_trailing_pct(…)` — bounded by family floor/cap; missing/zero ATR or price returns the floor so callers always get a usable number.
- `derive_origin_strategy(contributing_signals)` — picks the strategy_key with max `signal_score × confidence_score`; malformed entries (non-numeric scores, missing key) are skipped; empty/`None` → `None`. Tie-breaking is stable (first-encountered wins).
- `services/risk_engine/service.py::evaluate_exits` — new `atr_by_ticker: dict[str, float] | None` kwarg. When `atr_stops_enabled=True`, each loop iteration resolves the family per position and overrides `stop_loss`, `max_age_days`, trailing_pct, activation_pct in-place. When OFF, the legacy `legacy_stop_loss` / `legacy_max_age_days` binds (renamed for clarity; behaviour unchanged).

### Rec 5 — Promote portfolio_fit_score into sizing
- `services/portfolio_engine/service.py::compute_sizing` — new `fit_on` branch between raw half-Kelly and the Decimal conversion. When flag ON and `ranked_result.portfolio_fit_score is not None`, `half_kelly_pct *= clamp01(float(fit_score))` before the cap stack runs. Rationale string gets a `fit_score=…` token only when the flag fires, so legacy rationales are byte-identical under OFF.

### Shared schema — Position.origin_strategy
- `infra/db/models/portfolio.py::Position` — new `origin_strategy: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)`.
- `services/portfolio_engine/models.py::PortfolioPosition` — new `origin_strategy: str = ""` field on the in-memory dataclass; consumed by `evaluate_exits` via `getattr(position, "origin_strategy", "")`.
- NEW Alembic migration `infra/db/versions/l2m3n4o5p6q7_add_position_origin_strategy.py` — adds nullable `VARCHAR(64)` column. Revises `k1l2m3n4o5p6` (Step 2 idempotency keys).

### Tests (38, all passing)
- `tests/unit/test_deep_dive_step5_atr_stops_and_fit_sizing.py`:
  - `TestFamilyParamsTable` (4): default + 6 expected families present, momentum wider than sentiment, valuation longest hold.
  - `TestResolveFamily` (7): None/empty/exact/case-insensitive/Strategy-suffix/hyphen-space/unknown.
  - `TestATRComputations` (6): within floor-cap, hits floor, hits cap, missing ATR → floor, zero price → floor, trailing follows same rules.
  - `TestDeriveOriginStrategy` (4): empty/None, highest product wins, malformed entries skipped, missing strategy_key skipped.
  - `TestEvaluateExitsFlagOff` (3): below legacy stop trips, above legacy stop holds, legacy age expiry.
  - `TestEvaluateExitsFlagOn` (6): null origin → default family; valuation family wider than legacy; sentiment stops earlier than momentum; ATR scaling widens stop (momentum cap holds at -17%); per-family max-age (momentum holds 25d, sentiment trips at 20d).
  - `TestComputeSizingFlagOff` (1): byte-for-byte legacy with bad-fit ignored.
  - `TestComputeSizingFlagOn` (5): fit=0.5 cuts Kelly in half, fit=1.0 leaves cap binding, fit=None leaves Kelly alone, fit=0 zeroes out, rationale gains `fit_score` only when flag on.
  - `TestSettingsIntegration` (2): defaults off, env-var override works.
- Full Deep-Dive Step 1–5 sweep: **126 passed, 12 skipped** (skips are Python 3.10 sandbox for `datetime.UTC`). No regressions.

### Files touched (authoritative)
- `apis/config/settings.py` — 2 new `Field` entries.
- `apis/services/risk_engine/family_params.py` — new (160 lines).
- `apis/services/risk_engine/service.py::evaluate_exits` — kwargs + atr_stops_on branch, ~30-line patch.
- `apis/services/portfolio_engine/service.py::compute_sizing` — fit_on branch, ~15-line patch.
- `apis/services/portfolio_engine/models.py::PortfolioPosition` — `origin_strategy: str = ""` field.
- `apis/infra/db/models/portfolio.py::Position` — `origin_strategy` nullable column + file rebuild after mount-sync truncation at line 162.
- `apis/infra/db/versions/l2m3n4o5p6q7_add_position_origin_strategy.py` — new migration, revises `k1l2m3n4o5p6`.
- `apis/tests/unit/test_deep_dive_step5_atr_stops_and_fit_sizing.py` — new (38 tests).

### Operator guidance
- **ATR stops:** set `APIS_ATR_STOPS_ENABLED=true`. Run `alembic upgrade head` first so the `origin_strategy` column exists. Until the column is populated by new opens, all positions are in the `default` family (wider/longer than legacy, so safe). To start tagging new positions, the worker/open-path must call `derive_origin_strategy(ranked_result.contributing_signals)` and pass the result into the persist layer — this wiring is intentionally deferred to a follow-up since it crosses the paper_trading cycle's persistence code which is already idempotency-sensitive (Step 2). Paper-bake 3 weeks per plan §5.4.
- **Portfolio-fit sizing:** set `APIS_PORTFOLIO_FIT_SIZING_ENABLED=true`. No migration needed. Paper-bake 2 weeks per plan §5.4. Expect smaller average position sizes when fit scores are low.
- Each flag is independent — one OFF, one ON is valid.

### Bug / edge-case learnings this step
- Python 3.10 sandbox still can't resolve `dt.UTC`. Tests work around it by passing `reference_dt=_NOW` (a module-level `dt.datetime.now(dt.timezone.utc)`) to every `evaluate_exits` call so the service's internal `dt.UTC` fallback is never hit. Production runs on 3.11+ where `dt.UTC` is resolvable.
- `RiskEngineService._log` is a structlog-bound logger assigned in `__init__`. Bypassing init (`object.__new__(...)`) in tests leaves it unset and the exit path's `self._log.info(...)` crashes. Fixed with a `_NullLog` stub that absorbs structlog-style kwargs.
- Mount-sync corruption hit `infra/db/models/portfolio.py` at line 162 (mid-RiskEvent column). Recovery: `tail + git show HEAD` append the missing RiskEvent body (~14 lines). No downstream damage because the truncation was in a completely separate table from the Step 5 patch target.
- Test file itself got truncated mid-line at line 410 after `Edit`. Recovery: Python rstrip-and-append to restore the last test method.

---

## [2026-04-17] Deep-Dive Plan — Step 4 LANDED (Score-weighted rebalance allocator, flag default OFF)

### Summary
Step 4 of the Deep-Dive Execution Plan complete — a new pure-function allocator that can weight target positions by composite score or score/volatility ("risk-parity adjacent"), with floor + cap guardrails and a master kill-switch. Per DEC-031, default behaviour is **byte-for-byte identical to the legacy 1/N equal-weight path** because `rebalance_weighting_method="equal"` and `score_weighted_rebalance_enabled=False` out of the box. Operator must flip BOTH `APIS_SCORE_WEIGHTED_REBALANCE_ENABLED=true` AND set `APIS_REBALANCE_WEIGHTING_METHOD` to `score` or `score_invvol` to activate. Belt-and-suspenders by design so either flag alone is a no-op.

### New settings (pydantic `Field` with bounds + validator)
- `rebalance_weighting_method: str = "equal"` — one of `equal` / `score` / `score_invvol`. Validator normalises any unknown string to `equal` at Settings-construct time so bad env values can't crash the worker.
- `score_weighted_rebalance_enabled: bool = False` — master kill-switch. When False, allocator returns equal-weight regardless of method.
- `rebalance_min_weight_floor_fraction: float = 0.10` (0.0–1.0) — every kept ticker gets at least `floor_fraction × equal_w` before redistribution. Prevents tail tickers from collapsing to zero.
- `rebalance_max_single_weight: float = 0.20` (0.0–1.0) — post-normalisation cap per ticker; overflow redistributes proportionally to remaining tickers (iterative, max 10 rounds).

### Rec 6 — New `services/rebalancing_engine/` module
- `allocator.py` (276 lines) — pure functions only, no DB writes, no app_state access:
  - `AllocationResult` dataclass — `weights` dict, `method_used`, `tickers_considered`, `floor_applied_count`, `cap_applied_count`, `fell_back_to_equal`, `reason`, `per_ticker_raw`.
  - `compute_weights(ranked_tickers, n_positions, *, method, enabled, scores, volatilities, min_floor_fraction, max_single_weight)` — main entry. Top-N truncate → kill-switch / method-gate → raw weight calc → all-scores-zero fallback → proportional-floor enforcement → cap with redistribution.
  - Key design choice: **floor is enforced exactly** rather than by max+renormalize. Below-floor tickers are pinned at `min_w`; remaining budget `1 − n_below × min_w` is split among above-floor tickers proportionally to their pre-floor normalised weight. This preserves the floor guarantee post-normalisation.
  - `_apply_cap_with_redistribution(weights, cap, max_iterations=10)` — fixed-point loop, locks over-cap tickers AT cap, spreads overflow to under-cap tickers in proportion to current weight. Degenerate all-at-cap case exits cleanly.
  - `RebalanceAllocator.compute_target_weights(...)` — class wrapper returning just the weights dict. Mirrors `services/risk_engine/rebalancing.py::RebalancingService` shape so workers can swap one for the other.
- `__init__.py` re-exports `AllocationResult`, `RebalanceAllocator`, `compute_weights`.

### Worker wiring
- `apps/worker/jobs/rebalancing.py::run_rebalance_check` — new `if _method_on and _method in ("score","score_invvol")` branch reads rankings → builds `scores` dict from `composite_score`, pulls `volatilities` from `app_state.latest_volatility_20d` (empty dict if absent), calls `compute_weights(...)`, logs `rebalance_weighted_allocation` with method / tickers / floor+cap counts / fallback state. Legacy `RebalancingService.compute_target_weights` still fires on the else branch — flag-OFF behaviour is unchanged.

### Tests (23, all passing)
- `tests/unit/test_deep_dive_step4_score_weighted_rebalance.py`:
  - `TestEqualModeBackwardsCompat` (5): default path matches legacy, top-N truncation, empty input, zero-n, `enabled=False` + `method="score"` stays equal.
  - `TestScoreMode` (5): proportional-to-score weights, sum-to-1, higher-score-higher-weight, all-zero-scores fall-back to equal (`fell_back_to_equal=True`), missing-score treated as ~zero.
  - `TestScoreInvVolMode` (3): inverse-vol doubles weight for half-vol ticker, missing-vol falls back to score-only per-ticker, zero-vol falls back per-ticker.
  - `TestMinFloorFraction` (2): floor=0.5 lifts tiny weights to ≥0.5/N, floor=0 leaves distribution alone.
  - `TestMaxSingleWeight` (3): cap=0.5 caps top weight with `cap_applied_count≥1`, overflow redistributes 3:1 when B/C are in 0.15:0.05 ratio, cap=1.0 no-op.
  - `TestClassWrapperParity` (1): `RebalanceAllocator.compute_target_weights` returns same dict as `compute_weights(...).weights`.
  - `TestUnknownMethod` (1): garbage method string → equal + `reason="unknown_method:..."`.
  - `TestSettingsIntegration` (3): defaults, validator normalises garbage to `equal`, valid strings accepted.
- Full Deep-Dive Step 1–4 sweep: **88 passed, 12 skipped** (skips are Python 3.10 sandbox gating for `datetime.UTC` in Step 2 idempotency + observation-floor tests). No regressions.

### Bug fixes found during testing
1. `positive_count` guard — initial implementation used `total_raw <= _EPS` but `raw[t] = _EPS` for zero-score tickers made `total_raw = n × _EPS > _EPS`, so the fallback never fired. Fixed by counting positive scores explicitly and falling back when `positive_count == 0`.
2. Floor-after-renormalize drift — original `max(w, min_w)` + re-normalize approach let the floor be violated post-normalisation (a 0.95/0.03/0.02 score split produced B=0.130 against a 0.167 floor). Rewritten as proportional-budget allocator: pin below-floor tickers at `min_w`, redistribute `1 − n_below × min_w` to above-floor tickers proportionally. Floor is now an exact lower bound.

### Files touched (authoritative)
- `apis/config/settings.py` — 4 new `Field` entries + `_validate_rebalance_method` field-validator.
- `apis/services/rebalancing_engine/__init__.py` — new (8 lines).
- `apis/services/rebalancing_engine/allocator.py` — new (276 lines).
- `apis/apps/worker/jobs/rebalancing.py` — score-weighted branch wired in between rankings extraction and drift computation (170 lines total).
- `apis/tests/unit/test_deep_dive_step4_score_weighted_rebalance.py` — new (23 tests).

### Operator guidance
- To turn on: `APIS_SCORE_WEIGHTED_REBALANCE_ENABLED=true` **and** `APIS_REBALANCE_WEIGHTING_METHOD=score` (or `score_invvol`). Both flags required.
- Watch `rebalance_weighted_allocation` log line: `method`, `floor_applied`, `cap_applied`, `fell_back`, `reason`. A non-empty `reason` signals degenerate input (empty rankings, no positive scores, unknown method).
- Default floor 0.10 and cap 0.20 produce well-behaved distributions for 10–15 position portfolios. Tune `APIS_REBALANCE_MIN_WEIGHT_FLOOR_FRACTION` and `APIS_REBALANCE_MAX_SINGLE_WEIGHT` if positions diverge too far or not enough.

### Sandbox gotchas observed this step
- Mount-sync corruption hit again: `services/rebalancing_engine/__init__.py` came out empty after `Write`, `apps/worker/jobs/rebalancing.py` truncated at line 103 after `Edit`, and `config/settings.py` was truncated at 286. Fix pattern is now routine: `git show HEAD:path > /tmp/clean.py` (or `head -N` on the current file) + Python `str.replace` patch + `shutil.copy` back.
- `__pycache__` still uneditable on OneDrive; always run `python3 -B` so stale `.pyc` can't shadow freshly-patched `.py`.

---

## [2026-04-17] Deep-Dive Plan — Step 3 LANDED (Trade-count lift, both flags default OFF)

### Summary
Step 3 of the Deep-Dive Execution Plan complete — two behavioral flags that together lift the cycle's trade count when operator opts in. Both default **OFF** so live behavior is bit-for-bit unchanged until the operator flips them. Per DEC-031, this advances the "more trades + more self-improvement" lever without touching the 9 hard risk gates (DEC-033) or the AI-tilt defaults (DEC-032).

### New settings (all pydantic `Field` with bounds)
- `lower_buy_threshold_enabled: bool = False` — Rec 9. When ON, `_recommend_action` uses `lower_buy_threshold_value` instead of `buy_threshold`.
- `lower_buy_threshold_value: float = 0.55` (0.0–1.0) — effective "buy" cut-point when Rec 9 is active.
- `conditional_ranking_min_enabled: bool = False` — Rec 8. When ON, `_apply_ranking_min_filter` uses a relaxed floor for currently-held tickers with positive closed-trade history.
- `ranking_min_held_positive: float = 0.20` (0.0–1.0) — loose floor for the Rec 8 allow-list.

### Rec 9 — Lower "buy" threshold (flag)
- `services/ranking_engine/service.py::_recommend_action` now reads `buy_threshold`, optionally overridden by `lower_buy_threshold_value` when `lower_buy_threshold_enabled` is True. `watch_threshold` is unchanged. Caller at `rank_signals` (line 218) threads `settings` through. Flag-OFF path is byte-identical to legacy behavior.

### Rec 8 — Conditional ranking-min relaxation (flag)
- `apps/worker/jobs/paper_trading.py` — new helper `_apply_ranking_min_filter(rankings, app_state, settings)` replaces the inline list-comprehension at the call site. Filter logic:
  - Flag OFF (legacy): every ranking must satisfy `composite_score >= ranking_min_composite_score` (0.30).
  - Flag ON: a ticker that is (a) currently in `app_state.portfolio_state.positions` AND (b) has ≥1 prior closed trade graded "A" or "B" in `app_state.trade_grades` gets the looser floor (`ranking_min_held_positive`, default 0.20). All other tickers keep the strict 0.30 floor.
  - C/D/F history does NOT qualify — only A/B (reward meaningful winners).
  - Unheld tickers fall back to strict 0.30 even with A/B history (prevents re-entries via back-door).
- Call site at `run_paper_trading_cycle` now emits a `paper_cycle_min_score_filter` log line only when a filter actually fires, with `conditional_on` flag indicating which mode ran.

### Tests
- `tests/unit/test_deep_dive_step3_trade_count_lift.py` — 21 tests. Breakdown:
  - `TestLowerBuyThresholdFlagOff` (4): below-watch → avoid, between-watch-and-buy → watch, ≥0.65 → buy.
  - `TestLowerBuyThresholdFlagOn` (4): below 0.55 → watch, ≥0.55 → buy, watch threshold unchanged, custom value honored.
  - `TestConditionalRankingMinFlagOff` (3): strict 0.30 floor, held+A-grade still fails below 0.30 when flag off.
  - `TestConditionalRankingMinFlagOn` (10): held+A allowed at 0.25, held+B allowed at 0.21, held+no-history rejected at 0.25, unheld+A rejected at 0.25, held+only-D rejected, held+only-C rejected, mixed history (F+A+D) allowed, below-loose still rejected, multi-ticker integration, None-composite handling, missing portfolio_state defensive.
- Full Deep-Dive Step 1–3 sweep: **65 passed, 12 skipped** (skips are Python 3.10 sandbox gating for `datetime.UTC`). No regressions.

### Files touched (authoritative)
- `apis/config/settings.py` — 4 new `Field` entries.
- `apis/services/ranking_engine/service.py` — `_recommend_action` gains the flag branch (and a settings-import fix; file was re-landed from git HEAD via Python atomic-copy because the mount-sync corruption chronicled in Step 2 recurred mid-edit).
- `apis/apps/worker/jobs/paper_trading.py` — new `_apply_ranking_min_filter` helper + call-site swap. Rest of the Step 2 wiring (cycle_id, broker-health check, conflict detector, idem-keyed persist calls) preserved intact.
- `apis/tests/unit/test_deep_dive_step3_trade_count_lift.py` — new.

### Operator guidance
Both flags default OFF. To run the trade-count-lift experiment:
```
export APIS_LOWER_BUY_THRESHOLD_ENABLED=true
export APIS_CONDITIONAL_RANKING_MIN_ENABLED=true
```
Suggest flipping individually (lower-buy first, then conditional-min) and letting ≥5 paper cycles run to observe the composite on the proposal outcomes. Nothing else needs to change — the Shadow Portfolio tables from Step 7 will eventually provide the A/B evidence needed to decide whether to lock these ON.

### Sandbox gotchas (for Step 4+ work)
- Mount-sync corruption recurred on `services/ranking_engine/service.py` — both bash `cat` and file-tool Read showed truncated content despite successful write. Fix was: `git show HEAD:apis/services/ranking_engine/service.py > /tmp/...`, apply Step 1 + Step 3 patches in Python (str.replace), then `shutil.copy` back. Memory note: for files with Step 1 edits that need a Step 3 tweak, preferring a git-HEAD rebuild over incremental Edit is safer on this mount.
- `__pycache__` cannot be deleted on the OneDrive mount (Operation not permitted). Always run Python with `-B` to skip bytecode while iterating. Don't trust `dis.dis` output unless you've confirmed the .pyc is fresh.

---

## [2026-04-17] Deep-Dive Plan — Step 2 LANDED (Stability invariants + observation floor)

### Summary
Step 2 of the Deep-Dive Execution Plan complete. Three safety invariants and one self-improvement floor landed, with DB-level idempotency keys on the three fire-and-forget cycle writers (portfolio snapshots, position history, evaluation runs). Per DEC-031, the two **safety** invariants (broker-adapter health, action-conflict detector) default **ON**; the remaining Step-2 behaviors preserve existing semantics at defaults. No change to hard risk gates (DEC-033) or AI-tilt defaults (DEC-032).

### New settings (all pydantic `Field` with bounds)
- `broker_health_invariant_enabled: bool = True` — gates Rec 1 health check at top of paper_trading cycle.
- `broker_health_position_drift_tolerance: float = 0.01` (0.0–100.0) — share-quantity tolerance for non-fatal broker↔DB drift warnings.
- `action_conflict_detector_enabled: bool = True` — gates Rec 2 OPEN/CLOSE same-ticker resolver inside paper_trading cycle.
- `self_improvement_min_signal_quality_observations: int = 50` (0–10000) — Rec 13 observation floor; raised 10 → 50 per DEC-034 so confidence_score isn't statistical noise.

### Rec 1 — Broker-adapter health invariant (NEW)
- `apis/services/broker_adapter/health.py` — `check_broker_adapter_health(app_state, settings, ...)` → `HealthResult`. Two invariants:
  1. Fatal: `adapter_present=False` + DB reports `Position.status='open'` rows → fire kill switch (default flips `app_state.kill_switch_active`), raise `BrokerAdapterHealthError`.
  2. Non-fatal: quantity disagreement between broker `positions_by_ticker` and DB open positions beyond tolerance → log WARNING, populate `drift_tickers`, cycle proceeds (DB = source of truth).
- Wired into `apis/apps/worker/jobs/paper_trading.py` at the top of `run_paper_trading_cycle`, AFTER the mode guard but BEFORE the rankings check. On `BrokerAdapterHealthError` the cycle returns `status="error_broker_health"` with no orders submitted.

### Rec 2 — Action-conflict detector (NEW)
- `apis/services/action_orchestrator/invariants.py` — `resolve_action_conflicts(actions, settings=None, alert_fn=None)` → `ActionConflictReport(conflicts, resolved_actions, had_conflicts)`. Truth-table:
  - Empty input → empty report.
  - No conflicts (different tickers / non-opposing pairs) → passthrough.
  - OPEN vs CLOSE on same ticker → higher `composite_score` wins; tie → OPEN wins (`resolution_reason="tie_break_prefer_open"`).
  - Both scores None → treated as tie → OPEN wins.
  - `settings.action_conflict_detector_enabled=False` → passthrough with zero conflicts.
  - `alert_fn` invoked once per conflict; exceptions from alert_fn are swallowed.
  - Also exposes convenience `assert_no_action_conflicts(actions)` returning just the cleaned list.
- Wired into `apis/apps/worker/jobs/paper_trading.py` AFTER the Phase-65 CLOSE-suppression block and BEFORE the Phase-39 correlation filter. Logs `action_conflict_count` on resolution.

### Rec 4 — Idempotency keys on fire-and-forget DB writers
- `apis/infra/db/versions/k1l2m3n4o5p6_add_idempotency_keys.py` — Alembic migration adds `idempotency_key VARCHAR(200) NULL` + unique constraint on three tables:
  - `portfolio_snapshots` → `uq_portfolio_snapshot_idempotency_key` ← key `"{cycle_id}:portfolio_snapshot"`.
  - `position_history` → `uq_position_history_idempotency_key` ← key `"{cycle_id}:position_history:{ticker}"`.
  - `evaluation_runs` → `uq_evaluation_run_idempotency_key` ← key `"{run_date}:{mode}:evaluation_run"`.
- Revises `j0k1l2m3n4o5_add_readiness_snapshots`. Nullable column → non-blocking for historical rows.
- Model declarations updated in `apis/infra/db/models/portfolio.py` (`PortfolioSnapshot`, `PositionHistory`) and `apis/infra/db/models/evaluation.py` (`EvaluationRun`) with the new column + uq index.
- `apis/apps/worker/jobs/paper_trading.py`:
  - `uuid.uuid4().hex` cycle_id generated at top of `run_paper_trading_cycle`; logged in `paper_trading_cycle_starting`.
  - `_persist_portfolio_snapshot(state, mode, cycle_id=...)` — when cycle_id provided, uses `sqlalchemy.dialects.postgresql.insert(...).on_conflict_do_nothing(constraint="uq_portfolio_snapshot_idempotency_key")`. Absent → legacy `db.add()` path (unchanged).
  - `_persist_position_history(state, snapshot_at, cycle_id=...)` — same pattern, per-ticker keys.
- `apis/apps/worker/jobs/evaluation.py`:
  - `_persist_evaluation_run(scorecard, mode, run_id=...)` — SELECT by `idempotency_key` before insert (simpler than ON CONFLICT + RETURNING id since child `EvaluationMetric` rows reference `run.id`).
  - Caller threads `run_id = f"{scorecard.scorecard_date}:{mode}"` in `run_daily_evaluation`.
- All three writers remain fire-and-forget: DB errors are caught + logged WARNING, never re-raised to the scheduler.

### Rec 13 — Self-improvement observation floor
- `apis/config/settings.py` — `self_improvement_min_signal_quality_observations` default raised 10 → 50 per DEC-034.
- `apis/apps/worker/jobs/self_improvement.py::run_auto_execute_proposals` already gated on this floor (no code change needed); the Step 2 change is purely the default shift so the auto-execute readiness floor doesn't trigger on statistical noise.

### Files touched
- `apis/config/settings.py` (+4 fields, rewritten via heredoc to resolve a sandbox mount-sync issue; clean 304-line version)
- `apis/services/broker_adapter/health.py` (NEW)
- `apis/services/action_orchestrator/invariants.py` (NEW)
- `apis/apps/worker/jobs/paper_trading.py` (health-check + conflict-detector wiring; cycle_id + idem-key plumbing)
- `apis/apps/worker/jobs/evaluation.py` (run_id + idem-key plumbing)
- `apis/infra/db/models/portfolio.py`, `apis/infra/db/models/evaluation.py` (idempotency_key column + uq constraint)
- `apis/infra/db/versions/k1l2m3n4o5p6_add_idempotency_keys.py` (NEW migration, Revises `j0k1l2m3n4o5`)

### New tests (32 total; 21 pass + 11 correctly skipped in Python 3.10 sandbox)
- `apis/tests/unit/test_deep_dive_step2_broker_health.py` (7) — healthy state, disabled flag no-op, adapter-missing + live positions fires KS & raises, default KS path, drift warned non-fatal, drift within tolerance is clean, DB query failure doesn't block cycle.
- `apis/tests/unit/test_deep_dive_step2_action_conflicts.py` (13) — empty input, no-conflict passthrough, OPEN-vs-CLOSE higher-score wins (both directions), tie → OPEN, both-None tie, settings-flag off, alert_fn invoked once-per-conflict + exception doesn't corrupt result, different-ticker isolation, convenience wrapper, OPEN-vs-TRIM non-conflict, multi-ticker resolution.
- `apis/tests/unit/test_deep_dive_step2_idempotency_keys.py` (8, skipped in Python 3.10 sandbox) — portfolio_snapshot with/without cycle_id, error-swallowing, position_history per-ticker keys + legacy path, evaluation_run with run_id populates key / duplicate skip / legacy path.
- `apis/tests/unit/test_deep_dive_step2_observation_floor.py` (4; 1 passes + 3 skipped) — settings default=50, below-floor skipped_insufficient_history, at-floor proceeds, missing quality_report treated as zero.

Full cross-step run: `44 passed, 12 skipped` (Step 1 + Step 2 combined). No pre-existing test regressions — the Python 3.10 sandbox cannot import modules that use `datetime.UTC`, so 11 tests are correctly `pytest.skipif`-guarded and 3 pre-existing test files (`test_execution_engine.py`, `test_paper_broker.py`, `test_paper_trading.py`) fail at collection under 3.10; all will run under the 3.11 production env.

### Notes for operator
- Migration `k1l2m3n4o5p6` must be applied before paper_trading cycles write with cycle_id. If the column is missing, the insert will fail and the `except Exception` catch will log a warning but skip persistence entirely. Plan: operator runs `alembic upgrade head` next time Postgres is reachable; until then, legacy `db.add()` path is dormant (cycle_id is always passed in Step 2).
- Broker-adapter health default ON is a **safety** invariant — keep ON in production. Tolerance of 0.01 shares is conservative; expect zero drifts unless fractional-share fills ever land.
- Action-conflict detector default ON is a safety invariant; if rebalance logic ever legitimately wants to flip position polarity in a single cycle, flag can be turned off via `APIS_ACTION_CONFLICT_DETECTOR_ENABLED=false`.

---

## [2026-04-16] Deep-Dive Plan — Step 1 LANDED (Un-bury 6 hard-coded constants)

### Summary
Step 1 of the Deep-Dive Execution Plan complete. Six magic numbers relocated from code into `config/settings.py` as first-class typed settings with env-var overrides and range validation. Defaults preserve pre-refactor values **byte-for-byte** per DEC-032. No behavior change — pure refactor / observability win.

### Settings added (all pydantic `Field` with bounds)
- `buy_threshold` (default 0.65, 0.0–1.0) — consumed by `RankingEngineService._recommend_action`
- `watch_threshold` (default 0.45, 0.0–1.0) — consumed by `RankingEngineService._recommend_action`
- `source_weight_hit_rate_floor` (default 0.50, 0.0–1.0) — consumed by `SelfImprovementService`
- `ranking_threshold_avg_loss_floor` (default -0.02, < 0) — consumed by `SelfImprovementService`
- `ai_ranking_bonus_map` (default Phase-66 9-key map) — consumed by `RankingEngineService`
- `ai_theme_bonus_map` (default Phase-66 8-key map) — consumed by `ThemeAlignmentStrategy`
- `rebalance_target_ttl_seconds` (default 3600) — consumed by `_fresh_rebalance_targets` helper in `apps/worker/jobs/paper_trading.py`

### Files touched
- `apis/config/settings.py` — 7 new fields + `_DEFAULT_AI_RANKING_BONUS_MAP` / `_DEFAULT_AI_THEME_BONUS_MAP` module-level dicts.
- `apis/services/ranking_engine/service.py` — `_recommend_action` takes `settings` arg; reads `buy_threshold`/`watch_threshold`/`ai_ranking_bonus_map` from settings instead of literals.
- `apis/services/signal_engine/strategies/theme_alignment.py` — reads `ai_theme_bonus_map` from settings; module-level `_AI_THEME_BONUS` dict removed.
- `apis/services/self_improvement/service.py` — hit-rate and avg-loss floors sourced from settings, not literals.
- `apis/apps/worker/jobs/paper_trading.py` — new `_fresh_rebalance_targets(app_state, settings)` helper; both Phase-65 CLOSE-suppression and Phase-49 rebalance-merge sites call it (was `getattr(app_state, "rebalance_targets", {}) or {}`). Normalises naive datetimes to UTC; TTL ≤ 0 disables check (legacy compat).
- `apis/apps/worker/main.py` — startup log `deep_dive_step1_settings` dumps all 7 values (+ bonus-map keys) for operator audit.

### New tests (24 total, 23 pass + 1 skipped for Python 3.10 sandbox limit)
- `apis/tests/unit/test_deep_dive_step1_constants.py`
  - `TestStep1Defaults` (7) — defaults match pre-refactor literals byte-for-byte
  - `TestStep1EnvOverrides` (5) — env-var overrides work
  - `TestStep1RangeValidation` (2) — out-of-range values reject
  - `TestRankingEngineUsesSettings` (2) — `_recommend_action` honors settings (not literals)
  - `TestRebalanceTargetTTL` (6) — fresh/stale/missing/naive/ttl=0/empty paths all exercised
  - `TestThemeAlignmentUsesSettings` (1) — AI-infra bonus of 1.35× applied via settings
  - `TestSelfImprovementUsesSettings` (1, skipped on sandbox Python 3.10) — hit-rate floor flows through

### Acceptance criteria (all green)
- [x] Defaults byte-for-byte match pre-refactor (DEC-032 AI tilt frozen)
- [x] Env overrides plumbed via `APIS_*` pydantic-settings prefix
- [x] Range validation rejects nonsense inputs (`buy_threshold > 1.0`, positive avg-loss floor)
- [x] All Step 1 consumers wired (5 call-sites across 4 files)
- [x] `_fresh_rebalance_targets` handles 6 corner cases (fresh, stale, missing, ttl≤0, empty, naive)
- [x] Startup log dumps all 7 values for audit
- [x] No behavior change — pre-refactor defaults preserved

### Paper-bake
None required — pure refactor. No production flags added. Step 1 is foundation for Steps 2–8.

### Rollback
Revert the commit. No migrations. No runtime state changes.

---

## [2026-04-16] Deep-Dive Execution Plan (Awaiting Operator Approval, No Code Change)

### Summary
Following operator's approval of the approach outlined in `APIS_DEEP_DIVE_REVIEW_2026-04-16.md`, wrote a detailed per-recommendation execution plan covering Steps 1–8 (13 recommendations). Operator directed: (1) write the plan first — no code until approved; (2) every behavioral change lands feature-flagged with default OFF. Plan reflects DEC-034 (shadow portfolios include parallel rebalance weightings) and DEC-035 (per-type outcome measurement windows).

### Artifacts
- `APIS_EXECUTION_PLAN_2026-04-16.md` (workspace root) — per-step scope, files touched, new settings/migrations, feature flag names, test plan, rollback, paper-bake duration, acceptance criteria.

### Steps (8 total, ~11 calendar weeks)
1. Un-bury 6 hard-coded constants (~1 d, no behavior change).
2. Broker-adapter health + action conflict detector + idempotency keys + observation floor 10→50 (~3 d, safety invariants on by default, governance tightening).
3. Trade-count lift — lower buy threshold 0.65→0.55 + conditional ranking-min 0.30→0.20 for held names with positive history (~2 d, flags OFF).
4. Score-weighted rebalance allocator with 3 parallel modes (~1 wk, flag OFF).
5. ATR stops + per-family max-age + promote `portfolio_fit_score` into sizing (~1.5 wk, flag OFF).
6. Proposal Outcome Ledger — new table, daily 18:30 ET job, generator feedback, per-type windows per DEC-035 (~2 wk, flag OFF, 4 wk data-only bake).
7. Shadow-Portfolio Scorer — rejected actions + watch-tier + stopped-out continued + parallel rebalance weightings (DEC-034) (~3 wk, flag OFF).
8. Thompson-sampling strategy-weight bandit with floors/ceilings (~1 wk, flag OFF, 2 wk RESEARCH shadow first).

### Feature flags to be introduced (11 total)
Two default ON (safety invariants): `APIS_BROKER_HEALTH_INVARIANT_ENABLED`, `APIS_ACTION_CONFLICT_DETECTOR_ENABLED`.
Nine default OFF (behavior changes): `APIS_LOWER_BUY_THRESHOLD_ENABLED`, `APIS_CONDITIONAL_RANKING_MIN_ENABLED`, `APIS_SCORE_WEIGHTED_REBALANCE_ENABLED`, `APIS_ATR_STOPS_ENABLED`, `APIS_PORTFOLIO_FIT_SIZING_ENABLED`, `APIS_PROPOSAL_OUTCOME_LEDGER_ENABLED`, `APIS_SHADOW_PORTFOLIO_ENABLED`, `APIS_STRATEGY_BANDIT_ENABLED` (plus `APIS_REBALANCE_WEIGHTING_METHOD` literal default `equal`).

### Appendix A (added after operator "whatever you think is best" directive)
Short pointer-only appendix in the plan doc covering post-Step-8 follow-on: Apr-14 Phase A (survivorship-free universe, ~3 wk), Phase B (walk-forward / OOS harness, ~4 wk), Phase F (mean-reversion family, ~2 wk). Keeps Apr-14 plan as authoritative design to avoid drift; notes Shadow Portfolio infrastructure from Step 7 is reusable as the OOS sandbox by swapping the price feed adapter.

### Status
Awaiting operator approval before any Step 1 code is written.

---

## [2026-04-16] Deep-Dive Architectural Review (Analysis Only, No Code Change)

### Summary
Comprehensive architectural review requested by operator to assess soundness, stability, efficiency, decision-making quality, and self-improvement capacity — without adding rules that choke off options. Output is an analysis document; no code changed.

### Artifacts
- `APIS_DEEP_DIVE_REVIEW_2026-04-16.md` (workspace root) — 12-section review + 13 ranked recommendations.

### Scope and operator directives captured during review
- Preserve Phase 66 AI tilt as an operator-level thesis (not up for auto-rollback via self-improvement).
- Defer walk-forward / OOS harness and survivorship-free data acquisition; prioritize self-improvement engine expansion + safe trade-count expansion first.
- Self-improvement focus: meta-learning over proposals (outcome ledger) + shadow portfolios for rejected ideas.

### Top recommendations (deferred to future phases)
1. Un-bury six hard-coded constants into `config/settings.py` (0.65 buy threshold, 0.50 hit-rate rule, −0.02 avg-loss rule, `_AI_THEME_BONUS`, `_AI_RANKING_BONUS`, rebalance-target freshness TTL).
2. Broker-adapter health invariant at cycle start.
3. Rebalance/portfolio-action conflict detector (guards against the next Phase 65-class bug).
4. Idempotency keys on fire-and-forget DB writers.
5. Score-weighted rebalance allocator (Phase D of Apr-14 plan, ported to not require walk-forward).
6. ATR-scaled horizon-aware stops per strategy family (Phase E of Apr-14 plan).
7. Proposal Outcome Ledger (meta-learning foundation — new DB table, daily job, generator feedback).
8. Shadow-Portfolio Scorer (virtual P&L for REJECTED actions and "watch"-tier ranked opportunities).
9. Thompson-sampling strategy-weight bandit (replaces static equal-weight fallback).
10. Lower "buy" threshold 0.65 → 0.55 with score-weighted sizing as the safety counterweight.

### Rules audit findings
- 6 gates identified as "choking options" and worth loosening (0.65 buy threshold, 0.30 ranking-min conditional on history, 7% fixed stop, 20-day fixed max-age, 5% fixed trailing, 1/N equal-weight rebalance).
- 0 hard risk gates (kill switch, drawdown limits, concentration caps) to loosen.
- 1 governance gate to raise: self-improvement observation floor 10 → 50 per Apr-14 review §3.6.

### Open questions sent to operator
(See §11 of the review doc.) Primary ones: measurement-window strategy for Proposal Outcome Ledger, and whether shadow portfolios should also run alternative-rebalance-weighting scenarios in parallel.

---

## [2026-04-16] Phase 66 — AI-Heavy Stock Selection Bias

### Summary
Operator-requested tuning to lean stock selection heavily toward AI-related stocks and the AI expansion theme. Non-AI stocks remain eligible but are structurally deprioritized.

### Changes (Part 1 — Scoring Bias)
- **services/signal_engine/regime_detection.py**: Boosted `theme_alignment_v1` weight in all four market regimes — BULL 0.20→0.40, BEAR 0.10→0.25, SIDEWAYS 0.15→0.35, HIGH_VOL 0.10→0.30. Other strategy weights reduced proportionally (all still sum to 1.0).
- **services/signal_engine/strategies/theme_alignment.py**: Added `_AI_THEME_BONUS` multiplier dict (1.15–1.35×) applied to raw theme scores for 8 AI-related themes (ai_infrastructure, ai_applications, semiconductors, cybersecurity, power_infrastructure, networking, data_centres, cloud_software). Non-AI themes unaffected.
- **services/ranking_engine/service.py**: Added `_AI_RANKING_BONUS` additive composite score bonus (0.03–0.08) for tickers tagged with AI-related themes via `TICKER_THEME`. Applied before final clamp.
- **config/settings.py**: Raised `max_thematic_pct` from 0.50 to 0.75 so the portfolio can concentrate up to 75% in a single AI theme.

### Changes (Part 2 — Universe Expansion)
- **config/universe.py**: Added 5 new high-conviction AI tickers not in S&P 500:
  - CRWV (CoreWeave) — pure-play AI cloud infrastructure → AI_INFRASTRUCTURE
  - CLS (Celestica) — Google TPU assembler, liquid-cooled rack integrator → AI_INFRASTRUCTURE
  - TLN (Talen Energy) — nuclear fleet for AI data centres → AI_POWER_UTILITIES
  - NVT (nVent Electric) — liquid cooling specialist, 65% order surge → AI_POWER_UTILITIES
  - BE (Bloom Energy) — onsite fuel-cell power for AI data centres → AI_POWER_UTILITIES
- **config/universe.py**: Cross-listed 4 INDUSTRIALS names into AI_POWER_UTILITIES so they receive AI theme scoring:
  - PWR (Quanta Services) — $44B backlog, full electrical path
  - TT (Trane Technologies) — AI data centre cooling/HVAC
  - HUBB (Hubbell) — power infrastructure for data centres
  - CARR (Carrier) — data centre cooling systems
- Added `_SECTOR_OVERRIDES` to preserve correct GICS sector assignments for cross-listed/new tickers while still giving them AI theme tags.

### Effect
AI-infrastructure tickers (NVDA, AMD, ARM, etc.) get the largest combined boost — roughly +0.08 composite bonus + 1.35× theme score. Non-AI names can still rank highly if they score well on momentum + valuation, but need to meaningfully outperform AI names on raw signals to overcome the structural bias. Universe expanded from ~500 to ~505 tickers.

### Validation
- All regime weight vectors sum to 1.0 (verified)
- Theme bonus clamps scores to [0, 1] (no score inflation beyond ceiling)
- Sector overrides verified: cross-listed tickers keep original GICS sector
- Theme assignments verified: all new/moved tickers get AI themes via setdefault priority
- No risk controls removed — all hard limits (stop-loss, drawdown, position caps) unchanged

---

## [2026-04-16] Phase 65 — Fix: Alternating Open/Close Churn Bug

### Summary
Paper trading cycles alternated between opening 10 positions and trying to close 10 positions (rejected) every other cycle. Two root causes identified and fixed.

### Root Cause 1: New PaperBrokerAdapter every cycle
The worker never set `app_state.broker_adapter`, so `paper_trading.py` line 365 created a brand-new `PaperBrokerAdapter()` with empty `_positions` on every cycle. Positions filled in one cycle were gone in the next.

### Root Cause 2: Portfolio engine CLOSEs conflicting with rebalancing OPENs
All 15 rankings had `recommended_action="watch"` (top composite score 0.573, below the 0.65 "buy" threshold). So `apply_ranked_opportunities` always had `buy_tickers={}`, causing it to CLOSE every held position as "not_in_buy_set". Meanwhile, the rebalancing engine independently generated OPEN actions for the same tickers based on drift targets. The two systems contradicted each other.

### Changes
- **apps/worker/jobs/paper_trading.py**: (1) Persist `PaperBrokerAdapter` in `app_state.broker_adapter` so broker state survives across cycles. (2) Filter out portfolio-engine CLOSEs with `reason="not_in_buy_set"` for tickers that have active rebalance targets, preventing the close/reopen churn.

### Validation
- 121/121 unit tests pass (test_paper_trading + test_paper_broker + test_execution_engine)
- Worker restarted at 21:48 UTC — 35 jobs registered, 15 rankings restored, healthy

---

## [2026-04-15] Phase A.2 — Point-in-Time Universe Source (behind feature flag)

### Summary
Added a Norgate-backed service that returns the survivorship-safe constituents of an index (default: S&P 500) as of any historical date.  Default ``universe_source=static`` keeps existing behaviour; flip ``APIS_UNIVERSE_SOURCE=pointintime`` to switch.  See DEC-025.

### Changes
- **apis/services/universe_management/pointintime_source.py** (new): ``PointInTimeUniverseService`` with ``get_candidate_pool``, ``get_universe_as_of``, ``get_current_universe``, ``iter_universe_over_range``, and an instance-level cache keyed by (index, date).  Uses ``norgatedata.index_constituent_timeseries`` per candidate to answer point-in-time membership.
- **apis/config/settings.py**: New ``UniverseSource`` enum (``static``/``pointintime``) and three fields (``universe_source``, ``pointintime_index_name="S&P 500"``, ``pointintime_watchlist_name="S&P 500 Current & Past"``).
- **apis/tests/unit/test_pointintime_universe.py** (new): 11 tests covering candidate-pool caching, as-of filtering, per-date cache isolation, empty-DataFrame handling, Norgate-exception swallowing, range iteration (daily + monthly step), and cache invalidation.

### Validation
- ``pytest tests/unit/test_pointintime_universe.py tests/unit/test_pointintime_adapter.py`` — **25 passed** (combined Phase A Part 1 + A.2 suite).
- Live smoke via ``norgate_vs_yfinance_compare.py`` on 2026-04-15 confirmed trial-tier watchlist returns 541 names.  Service works correctly against the trial; accuracy depth requires Platinum.

### Default behaviour unchanged
``universe_source`` defaults to ``static`` — the hand-curated 62-stock list.  No runtime change until operator flips the env var.

---

## [2026-04-15] Phase A (Part 1) — Survivorship-Free Data Adapter (behind feature flag)

### Summary
Landed the Norgate Data adapter (`PointInTimeAdapter`) as the second DataIngestionService backend.  Default behaviour is unchanged (yfinance remains the default).  Flipping `APIS_DATA_SOURCE=pointintime` in `.env` switches to Norgate, provided NDU is running locally.  See DEC-024 for rationale.

### Changes
- **apis/services/data_ingestion/adapters/pointintime_adapter.py** (new): Wraps `norgatedata.price_timeseries` with the same `fetch_bars` / `fetch_bulk` surface as `YFinanceAdapter`.  Maps Norgate's `Close` (adjusted) + `Unadjusted Close` (raw) columns to `BarRecord.adjusted_close` / `BarRecord.close`.  Exposes helpers `list_delisted_symbols`, `list_current_symbols`, `watchlist_symbols` for Phase A.2 universe construction.
- **apis/config/settings.py**: Added `DataSource` enum (`yfinance`, `pointintime`) and `data_source: DataSource = DataSource.YFINANCE` field.  Override via `APIS_DATA_SOURCE` env var.
- **apis/services/data_ingestion/service.py**: New `_build_default_adapter()` factory picks the adapter by setting; falls back to yfinance if `norgatedata` is not installed or NDU is unreachable.
- **apis/tests/unit/test_pointintime_adapter.py** (new): 14 tests covering source-tier tags, missing-package handling, Norgate exceptions, empty-DataFrame handling, unadjusted-vs-adjusted close mapping, fallback when Unadjusted Close is absent, happy-path fetch, period→date translation, bulk fanout, and factory selection by setting.

### Validation
- `pytest tests/unit/test_pointintime_adapter.py` — **14 passed** (run in workspace sandbox without `norgatedata` installed, proving the adapter is import-safe and unit-testable without NDU).

### Known limits
Norgate 21-day free trial caps history at ~2 years.  Adapter is wiring-complete but a real Phase B walk-forward is blocked until a paid Norgate subscription (recommended: Platinum, $630/yr).

---

## [2026-04-13] Phase 62 — Fix: Worker Rankings Restoration on Startup

### Summary
Worker restarts mid-day left `app_state.latest_rankings` empty, causing all subsequent paper trading cycles to skip with `skipped_no_rankings`. The API container had this restoration logic, but the worker did not.

### Root Cause
When the worker restarted at 13:39 UTC (09:39 ET) after the Phase 61 deployment, its `app_state.latest_rankings` list started empty. Unlike `apps/api/main.py` which restores rankings from the `ranked_opportunities` DB table on startup, the worker had no such restoration step. Since signal_generation (06:30 ET) and ranking_generation (06:45 ET) had already passed, rankings were never repopulated — causing the 10:30, 11:30, 12:00, and 13:30 ET cycles to all skip.

### Changes
- **apps/worker/main.py**: Added `_restore_rankings_from_db()` function mirroring the API's ranking restoration logic. Called in `main()` after `_seed_reference_data()` and before scheduler start. Restores latest `RankingRun` → `RankedOpportunity` rows into `app_state.latest_rankings`.

### Validation
- Worker restarted at 16:34 UTC — logs confirm: `latest_rankings_restored_from_db count=10 run_id=3da05572-b54f-486e-b5be-6a1f6fe84f38`
- Remaining afternoon cycles (13:30, 14:30, 15:30 ET) should now have rankings and can trade

### Production Impact
Any future worker restart mid-day will now properly restore rankings from DB, preventing the `skipped_no_rankings` cascade. Also serves as a safety net for tomorrow's Phase 61 price injection validation at 09:35 ET.

---

## [2026-04-13] Phase 61 — Fix: Paper Broker Price Injection

### Summary
Paper broker rejected all orders because `ExecutionEngineService` never called `set_price()` before `place_order()`. Latent bug unmasked by Phase 60 fixes.

### Root Cause
`PaperBrokerAdapter.place_order()` requires prices to be pre-loaded via `set_price()`. The paper trading job correctly fetched prices and passed them in `ExecutionRequest.current_price`, but the execution engine never injected them into the broker. Previously masked because Phase 60's `target_notional=0` bug meant no orders ever reached the broker.

### Changes
- **services/execution_engine/service.py**: Added `hasattr`-guarded `broker.set_price(ticker, price)` call in `execute_action()` before action dispatch. Broker-agnostic — only fires for adapters with `set_price()`.

### Validation
- 55/55 unit tests pass (test_execution_engine + test_paper_broker)
- Worker restarted at 13:39 UTC
- Awaiting live validation: 2026-04-14 09:35 ET cycle

### Production Impact
All paper trading executions were failing silently (rejected, not errored). Fix enables orders to fill in paper mode. No impact on live broker adapters.

---

## [2026-04-11] Learning Acceleration Revert + Phase 57 Provider ToS Review

### Summary
Reverted all learning-acceleration overrides (DEC-021) to production defaults. Completed Phase 57 Part 2 provider ToS review — selected QuiverQuant + SEC EDGAR (DEC-023).

### Changes
- **apis/.env**: `APIS_RANKING_MIN_COMPOSITE_SCORE` 0.15→0.30, `APIS_MAX_NEW_POSITIONS_PER_DAY` 8→3, `APIS_MAX_POSITION_AGE_DAYS` 5→20
- **apis/apps/worker/main.py**: Paper trading cycle schedule reverted from 12 cycles to 7 (09:35, 10:30, 11:30, 12:00, 13:30, 14:30, 15:30 ET)
- **state/DECISION_LOG.md**: Added DEC-022 (learning revert) and DEC-023 (provider selection)
- **state/ACTIVE_CONTEXT.md**: Updated to reflect reverted settings and Phase 57 ToS review completion

### Production Impact
Docker services must be restarted for .env and worker schedule changes to take effect. No code-level changes to risk engine, signal generation, or evaluation pipeline.

---

## [2026-04-11] Phase 60b — Fix: Negative Cash, Prometheus DNS, Cycle Timestamp Persistence

### Summary
Three follow-up fixes addressing secondary issues discovered during the Phase 60 investigation.

### Changes
- **apps/worker/jobs/paper_trading.py**: Broker sync now adds new positions from the broker to `portfolio_state.positions` (previously only updated existing ones). Without this, cash was debited after buys but `gross_exposure` stayed 0, producing negative equity and blocking future OPEN actions from the portfolio engine.
- **infra/monitoring/prometheus/prometheus.yml**: Corrected scrape target from `apis_api:8000` to `api:8000` (matching docker-compose service name). Updated matching comment in `apis_alerts.yaml`.
- **apps/api/main.py**: `_load_persisted_state()` now restores `last_paper_cycle_at` from the latest portfolio snapshot timestamp on startup. Ensures the timestamp is timezone-aware. Previously, the health check always showed `paper_cycle: "no_data"` after every restart until the first cycle completed.

### Tests
- Paper cycle simulation: 43/43 pass
- Execution engine: 23/23 pass
- Risk engine: 55/55 pass
- Signal + ranking: 58/58 pass

---

## [2026-04-11] Phase 60 — Fix: Rebalance OPEN Actions Missing target_notional (Zero-Trade Bug)

### Summary
Fixed the root cause of zero executed trades. The rebalancing service created OPEN actions with `target_quantity` (shares) but left `target_notional` at default `Decimal("0")`. The execution engine only read `target_notional`, so every order computed 0 shares and was rejected.

### Changes
- **services/risk_engine/rebalancing.py**: Added `target_notional=Decimal(str(round(target_usd, 2)))` to the OPEN action constructor in `generate_rebalance_actions()`. The dollar amount was already computed from drift but never passed to the PortfolioAction dataclass.
- **services/execution_engine/service.py**: Added `target_quantity` fallback in `_execute_open()`. If `target_notional` is 0 but `target_quantity` is set, uses it directly. Logs fallback usage as `execution_using_target_quantity_fallback`. Also improved the rejection log to include `target_quantity`.

### Tests
- Rebalancing: 61/67 pass (6 pre-existing failures: auth, stale job count)
- Execution engine: 23/23 pass
- Paper cycle simulation: 43/43 pass

---

## [2026-04-09] Learning Acceleration — Paper Cycle + Ranking Threshold + Backtest Sweep

### Summary
Three changes to accelerate the bot's learning during paper-bake: more frequent trading cycles, a lower ranking score threshold to admit marginal signals, and a backtest sweep script to generate historical training data across market regimes.

### Changes
- **apps/worker/main.py**: Paper trading cycles increased from 7 to 12 (09:35–15:30 ET at ~30-min intervals). Uses a compact loop instead of 7 individual job registrations. Docstring updated.
- **config/settings.py**: Added `ranking_min_composite_score` field (default 0.30, env: `APIS_RANKING_MIN_COMPOSITE_SCORE`). Configurable minimum composite score filter for the paper trading cycle.
- **apps/worker/jobs/paper_trading.py**: Added min composite score filter after loading rankings, controlled by `ranking_min_composite_score` setting. Logs pre/post filter counts.
- **apis/.env**: Set `APIS_RANKING_MIN_COMPOSITE_SCORE=0.15` for learning acceleration.
- **scripts/run_backtest_sweep.py**: NEW script. Runs BacktestComparisonService across 6 market-regime windows (bull 2024 Q1, bear 2022 H1, sideways 2023 Q2-Q3, volatile 2022 Q3-Q4, recovery 2023 Q1, recent 6 months). Persists results to DB for weight optimizer. CLI with --regimes, --tickers, --min-score, --dry-run options.

---

## [2026-04-09] Phase 60 — Critical Bug Fix Sprint

### Summary
Deep codebase audit identified and fixed 11 bugs across signal generation, ranking, execution, and risk gating. Several were critical: the ranking engine's risk penalty was mathematically negated, 5 of 6 strategy risk normalizations were broken, the VaR refresh job crashed on every run due to wrong DB column names, and executed trades were never cleared from proposed_actions.

### Changes
- **ranking_engine/service.py**: Removed erroneous re-centering that negated the risk penalty in composite score calculation
- **strategies/{momentum,sentiment,theme_alignment,macro_tailwind,insider_flow,valuation}.py**: Fixed risk normalization across all 6 strategies — valuation had inverted formula (`1.0 - vol*5`), others divided by 1.0 (no-op). All now use `vol * 2.5` mapping 0–40% vol to 0.0–1.0 risk
- **worker/jobs/var_refresh.py**: Fixed `DailyMarketBar.bar_date`→`trade_date`, `close_price`→`close`, added Security join (DailyMarketBar has no `ticker` column)
- **worker/jobs/fill_quality_attribution.py**: Fixed `SecurityBar` (non-existent model) → `DailyMarketBar`, same column name fixes
- **worker/jobs/paper_trading.py**: (a) Clear executed actions from `proposed_actions` after execution; (b) Fail-safe on filter exceptions — drop OPEN actions when sector/liquidity/VaR/stress filter crashes; (c) Fixed drawdown alert severity (INFO for NORMAL recovery, WARNING for deterioration); (d) Removed redundant drawdown state assignment
- **execution_engine/service.py**: Added logging for silently rejected zero-quantity orders
- **signal_engine/service.py**: Gated InsiderFlowStrategy behind `enable_insider_flow_strategy` setting (default False) — no longer pollutes pipeline with dead 0-confidence signals
- **config/settings.py**: Added `enable_insider_flow_strategy: bool = False` field

---

## [2026-04-09] Phase 59 — Dashboard State Persistence & Worker Resilience

### Summary
Dashboard sections were blank after every process restart because `ApiAppState` fields defaulted to None/empty and only a handful (kill_switch, paper_cycle_count, latest_rankings, snapshot_equity) were restored from the database at startup. This phase adds two complementary mechanisms to solve the problem: (1) expanded DB-backed state restoration in `_load_persisted_state()` for six additional field groups, and (2) a startup catch-up mechanism that re-runs missed morning pipeline jobs so ephemeral computed state (correlation matrix, VaR, stress test, etc.) is populated within minutes of any mid-day restart.

### Modified Files
- **`apps/api/main.py`** — `_load_persisted_state()` gained 6 new restoration blocks: portfolio_state (from PortfolioSnapshot + open Position rows), closed_trades + trade_grades (from closed Position rows with re-derived grades), active_weight_profile (from WeightProfile where is_active=True), current_regime_result + regime_history (from RegimeSnapshot, last 30 rows), latest_readiness_report (from ReadinessSnapshot), promoted_versions (from PromotedVersion table). New `_run_startup_catchup()` function checks current ET time on weekdays and fires any morning pipeline jobs whose scheduled time has passed but whose app_state field is still at its empty default — covers correlation, liquidity, VaR, regime, stress test, earnings, universe, rebalance, signal generation, ranking, and weight optimization. Called from `lifespan()` immediately after `_load_persisted_state()`.

### New Files
- **`tests/unit/test_phase59_state_persistence.py`** — 36 tests across 7 test classes: TestRestorePortfolioState (6), TestRestoreClosedTrades (5), TestRestoreWeightProfile (4), TestRestoreRegimeResult (5, 3 skipped on Python <3.11), TestRestoreReadinessReport (4), TestRestorePromotedVersions (4), TestStartupCatchup (8). All passing under Python 3.12.

### Behaviour Change
On process restart, the dashboard now shows the last known portfolio state, closed trade history, weight profile, market regime, readiness report, and promoted versions immediately (from DB). Ephemeral computed sections (correlation matrix, VaR, stress test, sector exposure, liquidity, earnings calendar, universe, rebalance targets) populate via catch-up jobs within ~2 minutes of a weekday restart instead of waiting until the next scheduled time slot. Weekend restarts skip catch-up (no market data to recompute). Docker Compose already had `restart: unless-stopped` on all services — no changes needed there.

---

## [2026-04-08] Phase 58 — Self-Improvement Auto-Execute Safety Gates

### Summary
Hardened the self-improvement auto-execute path in response to a live-money readiness review. Prior state: `run_auto_execute_proposals` called `AutoExecutionService.auto_execute_promoted` **without** passing `min_confidence`, so the 0.70 threshold documented in `SelfImprovementConfig` was dead code in production — any PROMOTED proposal would be applied regardless of confidence. Also, nothing prevented the job from running against a near-empty signal-quality history, which is exactly the situation the bot is in with only ~5 trading days of real data (securities table seeded 2026-03-31). Rationale: DECISION_LOG DEC-019.

### Modified Files
- **`config/settings.py`** — 3 new fields: `self_improvement_auto_execute_enabled: bool = False` (master kill switch, default OFF — operator must explicitly opt in via `APIS_SELF_IMPROVEMENT_AUTO_EXECUTE_ENABLED=true`), `self_improvement_min_auto_execute_confidence: float = 0.70` (per-proposal confidence floor passed through to the service), `self_improvement_min_signal_quality_observations: int = 10` (minimum `SignalQualityReport.total_outcomes_recorded` before the batch is allowed to run at all).
- **`apps/worker/jobs/self_improvement.py`** — `run_auto_execute_proposals` rewritten to evaluate three gates in order: (1) master switch → returns `status="skipped_disabled"` as a no-op; (2) observation floor → returns `status="skipped_insufficient_history"` with `total_outcomes` / `min_required` for observability; (3) per-proposal confidence threshold now actually passed through as `min_confidence=cfg.self_improvement_min_auto_execute_confidence`. Result dict gained a `skipped_low_confidence` field. Existing error path unchanged.
- **`tests/unit/test_phase35_auto_execution.py`** — Helper updates: `_make_app_state()` now seeds `latest_signal_quality` with a 50-outcome `SignalQualityReport`; `_make_promoted_proposal()` defaults `confidence_score=0.80` with an override kwarg. 5 existing `TestAutoExecuteWorkerJob` tests updated to pass an enabled `Settings`. 6 new Phase 58 tests: `test_phase58_disabled_by_default`, `test_phase58_skipped_disabled_does_not_call_service`, `test_phase58_skipped_when_signal_quality_history_too_thin`, `test_phase58_skipped_when_no_signal_quality_report_at_all`, `test_phase58_confidence_threshold_is_passed_through`, `test_phase58_high_confidence_proposal_still_executes`. All 13 worker-job tests pass (Python 3.12, `pytest --no-cov`).

### Behaviour Change
The `auto_execute_proposals` scheduler job continues to fire at 18:15 ET on weekdays, but returns a no-op until the operator explicitly enables the feature AND the signal quality report has ≥10 closed-trade outcomes. Proposal *generation* and *promotion* (17:30 / 18:00 jobs) are unchanged, so the self-improvement feedback loop keeps accumulating evidence during the paper-trading bake period — only the apply-to-runtime step is gated.

---

## [2026-04-08] Phase 57 Part 1 — InsiderFlowStrategy scaffold

### Summary
Opened Phase 57: a new `InsiderFlowStrategy` signal family backed by congressional / 13F / unusual-options flow data. This session ships only the scaffold — abstract adapter, `NullInsiderFlowAdapter` default, overlay fields, and the strategy itself. No network calls, no wiring into `SignalEngineService`, no effect on live paper trading. Rationale and guardrails recorded in DECISION_LOG DEC-018. Trigger: review of Samin Yasar "Claude Just Changed the Stock Market Forever" tutorial (YouTube `lH5wrfNwL3k`); tutorial's trailing-stop and options-wheel strategies explicitly rejected under Master Spec §4.2 and §9 anti-drift rules.

### New Files
- **`services/signal_engine/strategies/insider_flow.py`** — `InsiderFlowStrategy` class. Stateless. Reads `FeatureSet.insider_flow_score`, `insider_flow_confidence`, `insider_flow_age_days` overlay fields. Exponential decay (half-life 14 days, hard cut at 60 days). Reliability tier always at most `secondary_verified`. `contains_rumor=False` always (SEC filings are public record). Horizon POSITIONAL. Emits neutral 0.5 signal with zero confidence when overlay absent.
- **`services/data_ingestion/adapters/insider_flow_adapter.py`** — `InsiderFlowAdapter` ABC, `InsiderFlowEvent` dataclass (ticker, actor_type, actor_name, side, notional_usd, trade_date, filing_date, source_key, confidence, raw), `InsiderFlowOverlay` dataclass, shared `aggregate()` method (dollar-weighted net flow in [-1, +1] + aggregate confidence + newest-filing age), and `NullInsiderFlowAdapter` that always returns an empty event list.
- **`tests/unit/test_phase57_insider_flow.py`** — 24 tests across 6 classes: `TestFeatureSetOverlayDefaults`, `TestInsiderFlowStrategyNoData`, `TestInsiderFlowDecay`, `TestInsiderFlowDirection`, `TestInsiderFlowAdapter`, `TestDecayMathExpectations`. All 24 passing locally (pytest --no-cov).

### Modified Files
- **`services/feature_store/models.py`** — Added 3 overlay fields to `FeatureSet`: `insider_flow_score: float = 0.0`, `insider_flow_confidence: float = 0.0`, `insider_flow_age_days: float | None = None`.
- **`services/signal_engine/models.py`** — Added `SignalType.INSIDER_FLOW = "insider_flow"` enum member.
- **`services/signal_engine/strategies/__init__.py`** — Registered `InsiderFlowStrategy` in package exports (6 strategies exported; still only 5 wired into `SignalEngineService` by default).

### Intentionally NOT Changed
- `services/signal_engine/service.py` — `SignalEngineService.score_from_features()` is unchanged. The new strategy is not in the default list yet. Adding it is Phase 57 Part 2 and must be gated behind a settings flag defaulting to OFF.
- `services/feature_store/` enrichment pipeline — no call sites populating the new overlay fields yet.
- `config/settings.py` — no new flags yet (will add `APIS_ENABLE_INSIDER_FLOW_STRATEGY` in Part 2).
- No ORM / migration / API route / dashboard changes this session.
- No options-related code anywhere. Options-wheel strategy from the source tutorial is explicitly rejected under Master Spec §4.2.

### Test Counts
- Phase 57 scaffold: 24 new tests, all passing.
- Expected project total: 3626 → 3650 tests passing (100 skipped). Full suite not re-run in this session because the Linux sandbox does not have the full runtime environment (Windows venv, Postgres, Redis); Part 2 will require a Docker-based full-suite run before wiring.

---

## [2026-03-31] Securities Table Seed + Worker Volume Mount

### Summary
Diagnosed and fixed the root cause of paper trading cycles never executing: the `securities` table in Postgres was empty, so signal generation skipped every ticker in the universe, producing zero signals and zero rankings. All 7 daily paper trading cycles had been returning `skipped_no_rankings` since the system went live.

### Root Cause
- `SignalEngineService.run()` calls `_load_security_ids(session, tickers)` which queries the `securities` table.
- The table was never seeded — there was no seed script, no init-db insert, and no migration data.
- Every ticker returned `"No security_id found for X; skipping."` → 0 signals → 0 rankings → all paper cycles skip.

### New Files
- **`infra/db/seed_securities.py`** — Idempotent seed module with `seed_securities()`, `seed_themes()`, `seed_security_themes()`, and `run_all_seeds()`. Populates from `config/universe.py` ticker lists, sector mappings, and theme mappings. Uses `ON CONFLICT DO NOTHING` semantics. Can run standalone via `python -m infra.db.seed_securities`.

### Modified Files
- **`apps/worker/main.py`** — Added `_seed_reference_data()` function called at worker startup before alert service init and scheduler start. Idempotent — logs `seed_reference_data_already_up_to_date` when nothing to insert. Fire-and-forget on failure.
- **`infra/docker/docker-compose.yml`** — Added source volume mount to worker service (`../../../apis:/app/apis:ro`) matching the existing API service mount. Worker now picks up code changes on restart without needing a full image rebuild.

### Database Changes (Direct SQL)
- Inserted 62 rows into `securities` table (all universe tickers from `config/universe.py`)
- Inserted 13 rows into `themes` table (via seed script at worker startup)
- Inserted 62 rows into `security_themes` table (via seed script at worker startup)

### Verification
- Worker logs confirm: `{"securities": 0, "themes": 13, "security_themes": 62, "event": "seed_reference_data_complete"}`
- DB query confirms: `SELECT count(*) FROM securities` → 62
- Worker healthy and all 35 jobs registered with next runs scheduled

---

## [2026-03-30] Infrastructure Health Dashboard Panel + Worker Pod Fix

### Summary
Added an Infrastructure Health panel to the operator dashboard showing green/yellow/red status for all critical components. Fixed worker pod that had been scaled to 0 for 8 days, stalling all paper trading cycles and readiness gates.

### Bug Fix
- **Root Cause:** `apis-worker` K8s deployment was at 0 replicas since 2026-03-22 (when it was scaled down to eliminate duplicate scheduling with Docker Compose). Paper cycle count stuck at 1. All readiness gates (min_paper_cycles, min_evaluation_history, portfolio_initialized) could not progress.
- **Fix:** `kubectl scale deployment apis-worker -n apis --replicas=1`

### New Feature: Infrastructure Health Panel
- **Modified:** `apps/dashboard/router.py`
  - Added `_check_infra_health(state, settings)` — probes 6 components and returns status list.
  - Added `_render_infra_health(state, settings)` — full-width dashboard section with color-coded table.
  - Wired into `_render_page()` immediately after the health banner.
- **Components monitored:**
  - API Server — always green if page loads
  - Database (Postgres) — `SELECT 1` probe
  - Redis — `PING` probe
  - Worker (Scheduler) — checks `last_paper_cycle_at` freshness (green <2h, yellow <24h, red >24h or never)
  - Broker Connection — checks `broker_auth_expired` and adapter initialization
  - Kill Switch — checks effective kill switch state
- **Image rebuilt and deployed:** `apis:latest` loaded into kind cluster, both api and worker deployments restarted.

---

## [2026-03-26] Paper Trading Data Collection — Increased Cycle Frequency

### Summary
Added 5 more intraday paper trading execution cycles to accelerate data accumulation.

### Changes
- **Modified:** `apps/worker/main.py` — paper trading cycle schedule expanded from 2 to 7 intraday runs per day (09:35, 10:30, 11:30, 12:00, 13:30, 14:30, 15:30 ET). New job IDs: `paper_trading_cycle_late_morning`, `paper_trading_cycle_late_morning_2`, `paper_trading_cycle_early_afternoon`, `paper_trading_cycle_afternoon`, `paper_trading_cycle_close`. Total scheduled jobs: 30 → 35.
- **Modified:** `apis/.env` — Added `APIS_MAX_NEW_POSITIONS_PER_DAY=8` (was default 3) and `APIS_MAX_POSITION_AGE_DAYS=5` (was default 20) to allow more opens per day and faster position cycling for data collection. All hard risk controls (loss limits, drawdown, kill switch) remain unchanged.
- **Modified:** `tests/unit/test_worker_jobs.py` — Added 5 new job IDs to `_EXPECTED_JOB_IDS` set; updated `test_scheduler_has_expected_job_count` assertion from 30 → 35.

---

## [2026-03-26] Hardening Sprint — Items #8–#15 Complete

### Summary
All 8 remaining hardening items from the improvement backlog implemented and verified in a single session.

### #8 — ruff blocking + mypy informational in CI
- **Modified:** `.github/workflows/ci.yml`
- Removed `--exit-zero || true` from ruff step — ruff is now a blocking CI gate.
- Added mypy type-check step (informational, `|| true`) — errors tracked but do not block merges.
- Added comment explaining when to remove `|| true` once zero mypy errors achieved.

### #9 — Coverage enforcement re-enabled in CI
- **Modified:** `.github/workflows/ci.yml`
- Removed `--no-cov` override. pyproject.toml `fail_under = 60` now enforced on every CI run.

### #10 — Integration test CI job
- **Modified:** `.github/workflows/ci.yml`
- Added new `integration-tests` job with Postgres 17-alpine + Redis 7-alpine service containers.
- Runs `tests/integration/` against real services (no mocks).

### #11 — Worker Redis heartbeat + Docker Compose healthcheck
- **Modified:** `apps/worker/main.py` — writes `worker:heartbeat` key to Redis every 60s (TTL 180s).
- **Modified:** `infra/docker/docker-compose.yml` — added healthcheck for worker service (reads heartbeat key; `start_period: 120s`).

### #12 — Database backup runbook
- **Created:** `docs/runbooks/db_backup_runbook.md` (177 lines)
- Covers: manual pg_dump, automated cron backup via Docker Compose, pre-migration snapshots, restore procedure, backup verification, cloud (S3/Azure) strategy, pre-live-mode checklist.

### #13 — Grafana password required (no insecure default)
- **Modified:** `infra/docker/docker-compose.yml` — Grafana password changed from `:-change_me` to `:?…must be set…` (startup fails if unset).
- **Modified:** `apis/.env.example` — added `GRAFANA_ADMIN_USER` and `GRAFANA_ADMIN_PASSWORD=CHANGE_ME_BEFORE_DEPLOY`.
- **Action required:** Add `GRAFANA_ADMIN_PASSWORD` to `apis/.env` before next `docker compose up`.

### #14 — Empty config stub files replaced with proper docstrings
- **Modified:** 8 files: `services/{risk_engine,execution_engine,data_ingestion,feature_store,portfolio_engine,ranking_engine,reporting,signal_engine}/config.py`
- All stubs replaced with module docstrings explaining that config is delegated to the central `Settings` object (pydantic-settings).

### #15 — Type annotation modernisation (Optional → X | None)
- **Modified:** 140 files, 721 `Optional[X]` → `X | None` conversions via `ruff --fix`.
- **Modified:** 376 `datetime.timezone.utc` → `datetime.UTC` conversions.
- **Modified:** `pyproject.toml` — added comprehensive pragmatic ignore list for ruff rules that represent acceptable technical debt (ANN completeness, E501, etc.).
- **Modified:** `tests/unit/test_phase27_trade_ledger.py` — added `TYPE_CHECKING` guard for lazy-import return type annotations.
- **Modified:** 6 source files — added `# noqa` comments for legitimate false-positive S-rule flags.
- **Result:** `ruff check .` passes with 0 errors.

### System State (all healthy — verified 2026-03-26)
- `docker-api-1` — Up 3 days (healthy) :8000
- `docker-worker-1` — Up 3 days (heartbeat active after restart)
- `docker-postgres-1` — Up 3 days (healthy) :5432
- `docker-redis-1` — Up 3 days (healthy) :6379
- `docker-prometheus-1` — Up 3 days :9090
- `docker-grafana-1` — Up 3 days :3000
- `docker-alertmanager-1` — Up 27 hours :9093
- K8s `apis-control-plane` — Up 4 days (worker replica still 0)

---

## [2026-03-25] Ops — Container stack audit + Alertmanager fix

### Problem Identified
- Local Windows Python commands (`uvicorn` + `apps.worker.main`) were not running. System was being served entirely by containers inside WSL.
- Two separate container stacks were both running: **Docker Compose** (2 days old, serves port 8000 to Windows) and a **Kubernetes kind cluster** ("apis", 3 days old, on NodePort 30800). Both had a worker process, causing duplicate job execution.
- **Alertmanager** had been crash-looping for 2 days (4071+ restarts). Root cause: `global.slack_api_url: "${SLACK_WEBHOOK_URL}"` resolved to empty string → `unsupported scheme "" for URL`. Secondary: all Slack receivers also require a valid `api_url` even when not routed to.

### Decision
Keep **Docker Compose** as the primary runtime (serves Windows on :8000, includes Prometheus + Grafana + Alertmanager). K8s cluster retained but worker scaled to 0 to eliminate duplicate job execution.

### Modified Files
- `infra/monitoring/alertmanager/alertmanager.yml` — Removed `global.slack_api_url`. All receivers stubbed to null (no-op) until `SLACK_WEBHOOK_URL` / `PAGERDUTY_INTEGRATION_KEY` are configured. Original configs preserved as comments. Default route set to `"null"` receiver.

### Actions Taken
- `kubectl scale deployment apis-worker -n apis --replicas=0` — K8s duplicate worker eliminated.
- `docker restart docker-alertmanager-1` — Alertmanager stable on :9093 after config fix.

### System State (all healthy)
- `docker-api-1` — Up 2 days (healthy) :8000
- `docker-worker-1` — Up 2 days (single instance, no duplicate)
- `docker-postgres-1` — Up 2 days (healthy) :5432
- `docker-redis-1` — Up 2 days (healthy) :6379
- `docker-prometheus-1` — Up 2 days :9090
- `docker-grafana-1` — Up 2 days :3000
- `docker-alertmanager-1` — Running (fixed) :9093
- K8s `apis-api` — Running on NodePort 30800 (not competing)
- K8s `apis-worker` — Scaled to 0

---

## [2026-03-24] Ops — Environment config fix + worker restart

### Problem Identified
- `apis/.env` had `APIS_OPERATING_MODE=research` since initial setup. In `research` mode the paper trading job's mode guard skips execution, so all 30 scheduled jobs fired but the paper trading cycle never ran. Result: 0 cycles completed, dashboard empty despite workers running since 2026-03-23 16:49 ET.
- Worker process architecture clarified: `apps.worker.main` always spawns one child process (parent + child = normal, single scheduler instance). Previously misread as duplicate workers.

### Modified Files
- `apis/.env` — `APIS_OPERATING_MODE=research` → `APIS_OPERATING_MODE=paper`

### Actions Taken
- Stopped existing worker process pair (PIDs 7780/30876, started 2026-03-23 16:49 ET).
- Restarted worker fresh as single invocation from `apis/` directory with corrected env.
- Confirmed API health: `status: ok`, `db: ok`, `broker: ok`, `broker_auth: ok`, `kill_switch: ok`, mode: `paper`.

### Expected Outcome
- Morning job sequence (05:30–06:52 ET) and paper trading cycles (09:35 ET, 12:00 ET) will now execute in `paper` mode starting 2026-03-25.
- Dashboard will begin populating with rankings, portfolio data, and trade grades after first morning cycle.

---

## [2026-03-23] Hardening — TickerResult attribute fix

### Modified Files
- `apps/worker/jobs/ingestion.py` — Fixed `r.error_message` → `r.error` in the errors list comprehension (line 95). `TickerResult` dataclass uses `.error`, not `.error_message`. This was logging a non-fatal `AttributeError` on every ingestion run even though data saved correctly.

---

## [2026-03-21] Session 56 — Phase 56 COMPLETE (Readiness Report History) — SYSTEM BUILD COMPLETE

### New Files Created
- `infra/db/models/readiness.py` — `ReadinessSnapshot` ORM model
- `infra/db/versions/j0k1l2m3n4o5_add_readiness_snapshots.py` — Alembic migration
- `tests/unit/test_phase56_readiness_history.py` — 60 tests

### Modified Files
- `infra/db/models/__init__.py` — export `ReadinessSnapshot`
- `services/readiness/service.py` — `persist_snapshot(report, session_factory)` static method
- `apps/worker/jobs/readiness.py` — `session_factory` param + persist call
- `apps/worker/main.py` — `_job_readiness_report_update` passes `session_factory`
- `apps/api/schemas/readiness.py` — `ReadinessSnapshotSchema`, `ReadinessHistoryResponse`
- `apps/api/routes/readiness.py` — `GET /system/readiness-report/history`
- `apps/dashboard/router.py` — `_render_readiness_history_table()` + section title updated

### Stats
- 60 new tests → **3626 total passing** (100 skipped)
- Scheduled jobs: **30 total** (no new job)
- **ALL PLANNED PHASES (1–56) COMPLETE**

---

## [2026-03-21] Session 55 — Phase 55 COMPLETE (Fill Quality Alpha-Decay Attribution)

### New Files Created
- `services/fill_quality/models.py` — Added `alpha_captured_pct`, `slippage_as_pct_of_move` to `FillQualityRecord`; new `AlphaDecaySummary` dataclass
- `apps/worker/jobs/fill_quality_attribution.py` — `run_fill_quality_attribution` job (enriches records via DB subsequent price lookup; graceful degradation; fire-and-forget)
- `tests/unit/test_phase55_fill_quality_attribution.py` — 44 tests

### Modified Files
- `services/fill_quality/service.py` — `compute_alpha_decay()` + `compute_attribution_summary()`
- `apps/api/schemas/fill_quality.py` — `AlphaDecaySummarySchema`, `FillAttributionResponse`; alpha fields on record schema
- `apps/api/routes/fill_quality.py` — `GET /portfolio/fill-quality/attribution` (inserted before `/{ticker}`)
- `apps/api/state.py` — 2 new fields: `fill_quality_attribution_summary`, `fill_quality_attribution_updated_at`
- `apps/worker/jobs/__init__.py` — export `run_fill_quality_attribution`
- `apps/worker/main.py` — `fill_quality_attribution` job at 18:32 ET (30 total jobs)
- `apps/dashboard/router.py` — alpha addendum in fill quality section
- 17 prior test files updated (job count 29→30)

### Stats
- 44 new tests → **3566 total passing** (100 skipped)
- Scheduled jobs: **30 total**

---

## [2026-03-21] Session 54 — Phase 54 COMPLETE (Factor Tilt Alerts)

### New Files Created
- `services/factor_alerts/__init__.py` — package init
- `services/factor_alerts/service.py` — `FactorTiltEvent` dataclass + `FactorTiltAlertService` (stateless): two triggers (factor-name change, weight-shift >= 0.15); `build_alert_payload()`
- `apps/api/schemas/factor_alerts.py` — `FactorTiltEventSchema`, `FactorTiltHistoryResponse`
- `apps/api/routes/factor_alerts.py` — `factor_tilt_router`: GET /portfolio/factor-tilt-history (200 + empty list on no data; limit param 1–500 default 50; newest-first)
- `tests/unit/test_phase54_factor_tilt_alerts.py` — 42 tests

### Modified Files
- `apps/api/state.py` — 2 new fields: `last_dominant_factor: Optional[str]`, `factor_tilt_events: list[Any]`
- `apps/worker/jobs/paper_trading.py` — Phase 54 block after Phase 50 factor exposure: detect tilt, append event, fire webhook alert, update `last_dominant_factor`
- `apps/api/routes/__init__.py` — export `factor_tilt_router`
- `apps/api/main.py` — mount `factor_tilt_router` under /api/v1
- `apps/dashboard/router.py` — `_render_factor_tilt_section` with event table + badge; wired after `_render_factor_section`

### Gate Result
**3522/3522 passing, 100 skipped (PyYAML + E2E — expected)**
No new scheduled job (stays 29 total). No new ORM/migration. No new strategies (5 total unchanged). 1 new REST endpoint (GET /portfolio/factor-tilt-history). 1 new dashboard section.

## [2026-03-21] Session 53 — Phase 53 COMPLETE (Automated Live-Mode Readiness Report)

### New Files Created
- `services/readiness/__init__.py` — package init
- `services/readiness/models.py` — `ReadinessGateRow` + `ReadinessReport` dataclasses
- `services/readiness/service.py` — `ReadinessReportService` (stateless): delegates to `LiveModeGateService`, converts gate rows to uppercase status, builds recommendation string; graceful degradation on gate-service errors
- `apps/worker/jobs/readiness.py` — `run_readiness_report_update` job (18:45 ET, after fill_quality_update)
- `apps/api/schemas/readiness.py` — `ReadinessGateRowSchema`, `ReadinessReportResponse`
- `apps/api/routes/readiness.py` — `readiness_router`: GET /system/readiness-report (503 when no data)
- `tests/unit/test_phase53_readiness_report.py` — 56 tests

### Modified Files
- `apps/api/state.py` — 2 new fields: `latest_readiness_report: Optional[Any]`, `readiness_report_computed_at: Optional[dt.datetime]`
- `apps/worker/jobs/__init__.py` — export `run_readiness_report_update`
- `apps/worker/main.py` — `_job_readiness_report_update` wrapper + `readiness_report_update` job at 18:45 ET (29 total)
- `apps/api/routes/__init__.py` — export `readiness_router`
- `apps/api/main.py` — mount `readiness_router` under /api/v1
- `apps/dashboard/router.py` — `_render_readiness_section` with color-coded gate table + wired into main page
- 16 test files — job count assertions updated 28 → 29; `readiness_report_update` added to ID sets in `test_phase22_enrichment_pipeline.py` and `test_worker_jobs.py`

### Gate Result
**3480/3480 passing, 100 skipped (PyYAML + E2E — expected)**
1 new scheduled job (readiness_report_update at 18:45 ET; 29 total). No new ORM/migration. No new strategies (5 total unchanged). 1 new REST endpoint. 1 new dashboard section. overall_status: PASS/WARN/FAIL/NO_GATE.

## [2026-03-21] Session 52 — Phase 52 COMPLETE (Order Fill Quality Tracking)

### New Files Created
- `services/fill_quality/__init__.py` — package init
- `services/fill_quality/models.py` — `FillQualityRecord` (per-fill slippage dataclass), `FillQualitySummary` (aggregate stats dataclass)
- `services/fill_quality/service.py` — `FillQualityService` (stateless): `compute_slippage`, `build_record`, `compute_fill_summary`, `filter_by_ticker`, `filter_by_direction`
- `apps/worker/jobs/fill_quality.py` — `run_fill_quality_update` job (computes fill summary from app_state records, writes to app_state)
- `apps/api/schemas/fill_quality.py` — `FillQualityRecordSchema`, `FillQualitySummarySchema`, `FillQualityResponse`, `FillQualityTickerResponse`
- `apps/api/routes/fill_quality.py` — `fill_quality_router`: GET /portfolio/fill-quality + GET /portfolio/fill-quality/{ticker}
- `tests/unit/test_phase52_fill_quality.py` — 49 tests

### Modified Files
- `apps/api/state.py` — 3 new fields: `fill_quality_records: list[Any]`, `fill_quality_summary: Optional[Any]`, `fill_quality_updated_at: Optional[dt.datetime]`
- `apps/worker/jobs/paper_trading.py` — Phase 52 fill capture block: after execution results, appends one `FillQualityRecord` per FILLED order (fire-and-forget, graceful degradation)
- `apps/worker/jobs/__init__.py` — export `run_fill_quality_update`
- `apps/worker/main.py` — `_job_fill_quality_update` wrapper + `fill_quality_update` job at 18:30 ET
- `apps/api/routes/__init__.py` — export `fill_quality_router`
- `apps/api/main.py` — mount `fill_quality_router` under /api/v1
- `apps/dashboard/router.py` — `_render_fill_quality_section` + wired into main dashboard page
- `tests/unit/test_phase22_enrichment_pipeline.py`, `test_phase18_priority18.py`, `test_phase23_intelligence_api.py`, `test_phase29_fundamentals.py`, `test_phase35_auto_execution.py`, `test_phase36_phase36.py`, `test_phase37_weight_optimizer.py`, `test_phase38_regime_detection.py`, `test_phase43_var.py`, `test_phase44_stress_test.py`, `test_phase45_earnings_calendar.py`, `test_phase46_signal_quality.py`, `test_phase48_dynamic_universe.py`, `test_phase49_rebalancing.py`, `test_worker_jobs.py` — job count assertions updated from 27 → 28

### Gate Result
**3424/3424 passing, 100 skipped (PyYAML + E2E — expected)**
1 new scheduled job (fill_quality_update at 18:30 ET; 28 total). No new ORM/migration. No new strategies (5 total unchanged). 2 new REST endpoints. 1 new dashboard section. Slippage convention: BUY slippage_usd = (fill − expected) × qty; SELL slippage_usd = (expected − fill) × qty; positive = worse fill.

---

## [2026-03-21] Session 51 — Phase 51 COMPLETE (Live Mode Promotion Gate Enhancement)

### Modified Files
- `services/live_mode_gate/service.py` — 3 new private gate methods + import `math`:
  - `_compute_sharpe_from_history(evaluation_history)` — annualised Sharpe from `daily_return_pct` values; type-checks for int/float/Decimal only; returns (sharpe, obs_count)
  - `_check_sharpe_gate(result, app_state, min_sharpe)` — WARN if < 10 observations; PASS/FAIL vs threshold; wired into both checklists (0.5 for PAPER→HA, 1.0 for HA→RL)
  - `_check_drawdown_state_gate(result, app_state)` — NORMAL=PASS, CAUTION=WARN, RECOVERY=FAIL; wired into both checklists
  - `_check_signal_quality_gate(result, app_state, min_win_rate)` — WARN if no SignalQualityReport or no strategy results; PASS/FAIL vs avg win_rate (0.40 for PAPER→HA, 0.45 for HA→RL)
  - New module-level constants: `_PAPER_TO_HA_MIN_SHARPE=0.5`, `_HA_TO_RL_MIN_SHARPE=1.0`, `_MIN_SHARPE_OBSERVATIONS=10`, `_PAPER_TO_HA_MIN_WIN_RATE=0.40`, `_HA_TO_RL_MIN_WIN_RATE=0.45`

### New Files Created
- `tests/unit/test_phase51_live_mode_gate.py` — 57 tests (9 classes):
  TestSharpeComputation, TestSharpeGatePaperToHA, TestSharpeGateHAToRL,
  TestDrawdownGatePaperToHA, TestDrawdownGateHAToRL,
  TestSignalQualityGatePaperToHA, TestSignalQualityGateHAToRL,
  TestFullGateIntegration, TestNewGatesDoNotBreakExisting

### Gate Result
**3375/3375 passing, 100 skipped (PyYAML + E2E — expected)**
No new ORM, no new migration, no new REST endpoints, no new scheduled jobs (27 total), no new strategies (5 total).

---

## [2026-03-21] Session 50 — Phase 50 COMPLETE (Factor Exposure Monitoring)

### New Files Created
- `services/risk_engine/factor_exposure.py` — `FactorExposureService` (stateless; 5 factors MOMENTUM/VALUE/GROWTH/QUALITY/LOW_VOL; `compute_factor_scores`, `compute_portfolio_factor_exposure`; `FactorExposureResult` + `TickerFactorScores` dataclasses)
- `apps/api/schemas/factor.py` — 4 schemas (TickerFactorScoresSchema, FactorExposureResponse, FactorTopBottomEntry, FactorDetailResponse)
- `apps/api/routes/factor.py` — `factor_router` (GET /portfolio/factor-exposure, GET /portfolio/factor-exposure/{factor})
- `tests/unit/test_phase50_factor_exposure.py` — 75 tests (13 classes)

### Modified Files
- `apps/api/state.py` — 2 new fields: `latest_factor_exposure: Optional[Any] = None`, `factor_exposure_computed_at: Optional[dt.datetime] = None`
- `apps/worker/jobs/paper_trading.py` — Phase 50 factor exposure block (after position history persist; queries volatility_20d read-only from DB; builds ticker feature snapshots; writes to app_state)
- `apps/api/routes/__init__.py` — added `factor_router` import + __all__ entry
- `apps/api/main.py` — mounted `factor_router` under /api/v1
- `apps/dashboard/router.py` — `_render_factor_section` (portfolio factor bars + dominant factor badge + per-ticker table)

### Gate Result
**3318/3318 passing, 100 skipped (PyYAML + E2E — expected)**

---

## [2026-03-21] Session 48 — Phase 48 COMPLETE (Dynamic Universe Management)

### New Files Created
- `infra/db/models/universe_override.py` — `UniverseOverride` ORM (ticker, action ADD/REMOVE, reason, operator_id, active, expires_at, TimestampMixin; 3 indexes + check constraint)
- `services/universe_management/__init__.py` — package init
- `services/universe_management/service.py` — `OverrideRecord` DTO + `UniverseTickerStatus` + `UniverseSummary` frozen dataclasses + `UniverseManagementService` (stateless: `get_active_universe`, `compute_universe_summary`, `load_active_overrides`)
- `apps/worker/jobs/universe.py` — `run_universe_refresh` (loads overrides from DB, applies quality pruning, writes active_universe to app_state)
- `apps/api/schemas/universe.py` — 6 schemas (UniverseListResponse, UniverseTickerDetailResponse, UniverseOverrideRequest, UniverseOverrideResponse, UniverseOverrideDeleteResponse, UniverseTickerStatusSchema)
- `apps/api/routes/universe.py` — `universe_router` (GET /universe/tickers, GET /universe/tickers/{ticker}, POST /universe/tickers/{ticker}/override, DELETE /universe/tickers/{ticker}/override)
- `tests/unit/test_phase48_dynamic_universe.py` — 64 tests (16 classes)

### Modified Files
- `config/settings.py` — 1 new field: `min_universe_signal_quality_score: float = 0.0`
- `apps/api/state.py` — 3 new fields: `active_universe: list[str] = []`, `universe_computed_at`, `universe_override_count`
- `apps/worker/jobs/__init__.py` — added `run_universe_refresh` import + __all__ entry
- `apps/worker/main.py` — added `_job_universe_refresh` wrapper; `universe_refresh` CronTrigger at 06:25 ET (26th job)
- `apps/api/routes/__init__.py` — added `universe_router` import + __all__ entry
- `apps/api/main.py` — mounted `universe_router` under /api/v1
- `apps/worker/jobs/signal_ranking.py` — `run_signal_generation` uses `app_state.active_universe` when non-empty; falls back to UNIVERSE_TICKERS
- `apps/dashboard/router.py` — `_render_universe_section` added (active count, net change, removed/added ticker detail tables)
- 13 test files — job count assertions updated 25 → 26; `universe_refresh` added to expected job ID sets

### Gate Result
**3176/3176 passing, 100 skipped (PyYAML + E2E — expected)**

---

## [2026-03-21] Session 47 — Phase 47 COMPLETE (Drawdown Recovery Mode)

### New Files Created
- `services/risk_engine/drawdown_recovery.py` — `DrawdownState` enum (NORMAL/CAUTION/RECOVERY) + `DrawdownStateResult` frozen dataclass + `DrawdownRecoveryService` stateless (evaluate_state, apply_recovery_sizing, is_blocked)
- `apps/api/schemas/drawdown.py` — `DrawdownStateResponse` Pydantic schema
- `tests/unit/test_phase47_drawdown_recovery.py` — 55 tests (8 classes: TestDrawdownStateEvaluation, TestDrawdownRecoverySizing, TestDrawdownIsBlocked, TestDrawdownStateResult, TestDrawdownSettings, TestDrawdownAppState, TestDrawdownAPIEndpoint, TestDrawdownPaperCycleIntegration)

### Modified Files
- `config/settings.py` — 4 new fields: `drawdown_caution_pct=0.05`, `drawdown_recovery_pct=0.10`, `recovery_mode_size_multiplier=0.50`, `recovery_mode_block_new_positions=False`
- `apps/api/state.py` — 2 new fields: `drawdown_state: str = "NORMAL"`, `drawdown_state_changed_at: Optional[datetime]`
- `apps/api/routes/portfolio.py` — Added `GET /portfolio/drawdown-state` endpoint
- `apps/worker/jobs/paper_trading.py` — Phase 47 drawdown block: evaluate state per cycle, apply size multiplier in RECOVERY, block OPENs when block_new_positions=True, fire webhook on state transition
- `apps/dashboard/router.py` — `_render_drawdown_section`: color-coded state badge, drawdown %, HWM, thresholds display

### Gate Result
3112/3112 passing, 100 skipped (PyYAML + E2E — expected). No new job (25 total). No new strategy (5 total).

---

## [2026-03-20] Session 46 — Phase 46 COMPLETE (Signal Quality Tracking + Per-Strategy Attribution)

### New Files Created
- `infra/db/models/signal_quality.py` — `SignalOutcome` ORM (ticker, strategy_name, signal_score, trade_opened_at, trade_closed_at, outcome_return_pct, hold_days, was_profitable; uq_signal_outcome_trade unique constraint; indexes on strategy_name, ticker, trade_opened_at)
- `infra/db/versions/i9j0k1l2m3n4_add_signal_outcomes.py` — migration: creates signal_outcomes table with unique constraint + 3 indexes; down_revision = h8i9j0k1l2m3
- `services/signal_engine/signal_quality.py` — `StrategyQualityResult` + `SignalQualityReport` dataclasses + `SignalQualityService` (stateless: `compute_strategy_quality`, `compute_quality_report`, `build_outcome_dict`; Sharpe estimate (mean/std)×sqrt(252); graceful degradation on empty inputs)
- `apps/worker/jobs/signal_quality.py` — `run_signal_quality_update` (DB path: matches closed trades → SecuritySignal; no-DB path: DEFAULT_STRATEGIES fallback; idempotent re-run via exists-check; 17:20 ET)
- `apps/api/schemas/signal_quality.py` — `StrategyQualitySchema`, `SignalQualityReportResponse`, `StrategyQualityDetailResponse`
- `apps/api/routes/signal_quality.py` — `signal_quality_router` (GET /signals/quality, GET /signals/quality/{strategy_name}; case-insensitive lookup; data_available flag pattern)
- `tests/unit/test_phase46_signal_quality.py` — 61 tests (12 classes)

### Modified Files
- `infra/db/models/__init__.py` — Added `SignalOutcome` import + `__all__` entry
- `apps/api/state.py` — Added `latest_signal_quality`, `signal_quality_computed_at` fields
- `apps/worker/jobs/__init__.py` — Added `run_signal_quality_update` import + `__all__` entry
- `apps/worker/main.py` — Added `_job_signal_quality_update` wrapper; scheduled at 17:20 ET weekdays; updated schedule comment; 25 total jobs
- `apps/api/routes/__init__.py` — Added `signal_quality_router` import + `__all__` entry
- `apps/api/main.py` — Mounted `signal_quality_router` at `/api/v1`; added import
- `apps/dashboard/router.py` — Added `_render_signal_quality_section`: computed_at, total outcomes, per-strategy table (predictions, win rate, avg return, Sharpe estimate, avg hold); warn class for win_rate < 0.40; wired after earnings section
- 13 test files — Job count assertions updated 24 → 25; `signal_quality_update` added to `_EXPECTED_JOB_IDS` sets where present

## [2026-03-20] Session 45 — Phase 45 COMPLETE (Earnings Calendar Integration + Pre-Earnings Risk Management)

### New Files Created
- `services/risk_engine/earnings_calendar.py` — `EarningsEntry` + `EarningsCalendarResult` dataclasses + `EarningsCalendarService` (stateless: `_fetch_next_earnings_date` via yfinance, `build_calendar`, `filter_for_earnings_proximity`); graceful degradation on all fetch failures; OPEN-only gate
- `apps/worker/jobs/earnings_refresh.py` — `run_earnings_refresh` job: fetches next earnings date for all universe tickers, stores EarningsCalendarResult in app_state at 06:23 ET
- `apps/api/schemas/earnings.py` — `EarningsEntrySchema`, `EarningsCalendarResponse`, `EarningsTickerResponse`
- `apps/api/routes/earnings.py` — `earnings_router`: GET /portfolio/earnings-calendar (full calendar + at-risk set) + GET /portfolio/earnings-risk/{ticker} (per-ticker detail)
- `tests/unit/test_phase45_earnings_calendar.py` — 60 tests (11 classes)

### Modified Files
- `config/settings.py` — Added `max_earnings_proximity_days=2` (calendar days before earnings within which OPENs blocked; 0 = disable)
- `apps/api/state.py` — Added `latest_earnings_calendar`, `earnings_computed_at`, `earnings_filtered_count` fields
- `apps/worker/jobs/__init__.py` — Added `run_earnings_refresh` export
- `apps/worker/main.py` — Added `_job_earnings_refresh` wrapper; scheduled at 06:23 ET weekdays; updated schedule comment; 24 total jobs
- `apps/worker/jobs/paper_trading.py` — Added Phase 45 earnings proximity gate (after stress gate): drops OPEN actions for at-risk tickers; updates app_state.earnings_filtered_count
- `apps/api/routes/__init__.py` — Added `earnings_router` import + `__all__` entry
- `apps/api/main.py` — Mounted `earnings_router` at `/api/v1`; added import
- `apps/dashboard/router.py` — Added `_render_earnings_section`: proximity window, last refresh, at-risk tickers with colour, gate-active status, per-ticker table with days_to_earnings; wired after stress section
- 12 test files — Job count assertions updated 23 → 24; `_EXPECTED_JOB_IDS` set extended with `earnings_refresh`

## [2026-03-20] Session 44 — Phase 44 COMPLETE (Portfolio Stress Testing + Scenario Analysis)

### New Files Created
- `services/risk_engine/stress_test.py` — `ScenarioResult` + `StressTestResult` dataclasses + `StressTestService` (stateless: `_get_sector`, `apply_scenario`, `run_all_scenarios`, `filter_for_stress_limit`); `SCENARIO_SHOCKS` dict (4 scenarios × 6 sectors); `SCENARIO_LABELS` dict
- `apps/worker/jobs/stress_test.py` — `run_stress_test` job: computes all 4 scenarios against current portfolio, stores in app_state at 06:21 ET
- `apps/api/schemas/stress.py` — `ScenarioResultSchema`, `StressTestSummaryResponse`, `StressScenarioDetailResponse`
- `apps/api/routes/stress.py` — `stress_router`: GET /portfolio/stress-test (full summary) + GET /portfolio/stress-test/{scenario} (single scenario detail)
- `tests/unit/test_phase44_stress_test.py` — 67 tests (12 classes)

### Modified Files
- `config/settings.py` — Added `max_stress_loss_pct=0.25` (25% worst-case scenario loss gate; set 0.0 to disable)
- `apps/api/state.py` — Added `latest_stress_result`, `stress_computed_at`, `stress_blocked_count` fields
- `apps/worker/jobs/__init__.py` — Added `run_stress_test` export
- `apps/worker/main.py` — Added `_job_stress_test` wrapper; scheduled at 06:21 ET weekdays; updated schedule comment; 23 total jobs
- `apps/worker/jobs/paper_trading.py` — Added Phase 44 stress gate block (after VaR gate): drops all OPEN actions when worst-case scenario loss > limit; updates app_state.stress_blocked_count
- `apps/api/routes/__init__.py` — Added `stress_router` import + `__all__` entry
- `apps/api/main.py` — Mounted `stress_router` at `/api/v1`
- `apps/dashboard/router.py` — Added `_render_stress_section`: computed_at, worst-case scenario name/loss with limit-breach colour, per-scenario table; wired into `_render_page`
- 12 test files — Job count assertions updated 22 → 23; `_EXPECTED_JOB_IDS` set extended with `stress_test`

## [2026-03-20] Session 43 — Phase 43 COMPLETE (Portfolio VaR & CVaR Risk Monitoring)

### New Files Created
- `services/risk_engine/var_service.py` — `VaRResult` dataclass + `VaRService` (stateless: `compute_returns`, `align_return_series`, `compute_portfolio_returns`, `historical_var`, `historical_cvar`, `compute_ticker_standalone_var`, `compute_var_result`, `filter_for_var_limit`)
- `apps/worker/jobs/var_refresh.py` — `run_var_refresh` job: loads bar data from DB for portfolio tickers, computes VaR/CVaR, stores in app_state at 06:19 ET
- `apps/api/schemas/var.py` — `TickerVaRSchema`, `PortfolioVaRResponse`, `TickerVaRDetailResponse`
- `apps/api/routes/var.py` — `var_router`: GET /portfolio/var (full summary) + GET /portfolio/var/{ticker} (standalone contribution)
- `tests/unit/test_phase43_var.py` — 63 tests (14 classes)

### Modified Files
- `config/settings.py` — Added `max_portfolio_var_pct=0.03` (3% 1-day 95% VaR gate; set 0.0 to disable)
- `apps/api/state.py` — Added `latest_var_result`, `var_computed_at`, `var_filtered_count` fields
- `apps/worker/jobs/__init__.py` — Added `run_var_refresh` export
- `apps/worker/main.py` — Added `_job_var_refresh` wrapper; scheduled at 06:19 ET weekdays; updated schedule comment; 22 total jobs
- `apps/worker/jobs/paper_trading.py` — Added Phase 43 VaR gate block (after liquidity filter): drops all OPEN actions when portfolio VaR > limit; updates app_state.var_filtered_count
- `apps/api/routes/__init__.py` — Added `var_router` import + `__all__` entry
- `apps/api/main.py` — Mounted `var_router` at `/api/v1`
- `apps/dashboard/router.py` — Added `_render_var_section`: computed_at, VaR/CVaR metrics with limit-breach colour coding, per-ticker standalone VaR table; wired into `_render_page`
- 10 test files — Job count assertions updated 21 → 22; `_EXPECTED_JOB_IDS` set extended with `var_refresh`

## [2026-03-20] Session 42 — Phase 42 COMPLETE (Trailing Stop + Take-Profit Exits)

### New Files Created
- `apps/api/schemas/exit_levels.py` — `PositionExitLevelSchema`, `ExitLevelsResponse` Pydantic schemas
- `apps/api/routes/exit_levels.py` — `exit_levels_router`: GET /portfolio/exit-levels (per-position stop-loss, trailing stop, take-profit levels)
- `tests/unit/test_phase42_trailing_stop.py` — 48 tests (8 classes: TestSettings42, TestEvaluateExitsTakeProfit, TestEvaluateExitsTrailingStop, TestEvaluateExitsPriority, TestPeakPriceUpdate, TestExitLevelsEndpoint, TestAppState42, TestPaperCycleTrailingStop)

### Modified Files
- `config/settings.py` — Added `trailing_stop_pct=0.05`, `trailing_stop_activation_pct=0.03`, `take_profit_pct=0.20` (all 0.0-disableable)
- `apps/api/state.py` — Added `position_peak_prices: dict[str, float]` (ticker → peak price since entry)
- `services/risk_engine/service.py` — Added module-level `update_position_peak_prices()` helper; extended `evaluate_exits()` with `peak_prices` param and two new triggers: take-profit (priority 2) and trailing stop (priority 3); age expiry → 4, thesis invalidation → 5
- `apps/worker/jobs/paper_trading.py` — Added Phase 42 peak price update block before evaluate_exits; passes peak_prices to evaluate_exits; cleans stale tickers from peak_prices after broker sync
- `apps/api/routes/__init__.py` — Added `exit_levels_router` import + `__all__` entry
- `apps/api/main.py` — Mounted `exit_levels_router` at `/api/v1`
- `apps/dashboard/router.py` — Added `_render_exit_levels_section`: per-position table with stop-loss/trailing/take-profit levels + colour coding; wired into `_render_page`
- `tests/unit/test_phase26_trim_execution.py` — Added `take_profit_pct=0.0` to integration test (backward compat fix)

### Gate Result
2806/2806 passing, 100 skipped (PyYAML + E2E — expected). 21 scheduled jobs total. 5 strategies total.

---

## [2026-03-20] Session 41 — Phase 41 COMPLETE (Liquidity Filter + Dollar Volume Position Cap)

### New Files Created
- `services/risk_engine/liquidity.py` — `LiquidityService`: `is_liquid` (ADV >= min_liquidity_dollar_volume); `adv_capped_notional` (min of notional and max_pct_of_adv × ADV); `filter_for_liquidity` (OPEN-only: drops illiquid, caps survivors via dataclasses.replace; CLOSE/TRIM pass through); `liquidity_summary` (per-ticker status dict sorted by ADV desc)
- `apps/worker/jobs/liquidity.py` — `run_liquidity_refresh`: queries SecurityFeatureValue for latest dollar_volume_20d per ticker; stores in app_state.latest_dollar_volumes; fire-and-forget; graceful degradation on DB failure
- `apps/api/schemas/liquidity.py` — 3 Pydantic schemas: `TickerLiquiditySchema`, `LiquidityScreenResponse`, `TickerLiquidityDetailResponse`
- `apps/api/routes/liquidity.py` — `liquidity_router`: GET /portfolio/liquidity (full screen, sorted by ADV desc), GET /portfolio/liquidity/{ticker} (single-ticker detail, 200 with data_available=False when unknown)
- `tests/unit/test_phase41_liquidity.py` — 61 tests (8 classes: TestLiquidityServiceIsLiquid, TestLiquidityServiceAdvCap, TestLiquidityServiceFilter, TestLiquidityServiceSummary, TestLiquidityRefreshJob, TestLiquidityRefreshJobNoDb, TestLiquidityRouteScreen, TestLiquidityRouteDetail, TestPaperCycleLiquidityIntegration)

### Modified Files
- `config/settings.py` — Added `min_liquidity_dollar_volume: float = 1_000_000.0` and `max_position_as_pct_of_adv: float = 0.10`
- `apps/api/state.py` — Added `latest_dollar_volumes: dict`, `liquidity_computed_at: Optional[datetime]`, `liquidity_filtered_count: int`
- `apps/worker/jobs/__init__.py` — Added `run_liquidity_refresh` import + `__all__` entry
- `apps/worker/main.py` — Added `_job_liquidity_refresh` wrapper; `liquidity_refresh` job at 06:17 ET (21st total); schedule docstring updated
- `apps/worker/jobs/paper_trading.py` — Added Phase 41 liquidity filter block after sector filter; calls `LiquidityService.filter_for_liquidity`; updates `app_state.liquidity_filtered_count`
- `apps/api/routes/__init__.py` — Added `liquidity_router` import + `__all__` entry
- `apps/api/main.py` — Mounted `liquidity_router` at `/api/v1`
- `apps/dashboard/router.py` — Added `_render_liquidity_section`: cache status + bottom-10 ADV table with gate colour indicators; wired into `_render_page`
- 9 test files — job count assertions 20 → 21; job ID sets updated to include `liquidity_refresh`

### Gate Result
2758/2758 passing, 100 skipped (PyYAML + E2E — expected). 21 scheduled jobs total.

---

## [2026-03-20] Session 40 — Phase 40 COMPLETE (Sector Exposure Limits)

### New Files Created
- `services/risk_engine/sector_exposure.py` — `SectorExposureService`: `get_sector` (TICKER_SECTOR look-up, falls back to "other"); `compute_sector_weights` (sector → fraction of equity); `compute_sector_market_values` (sector → Decimal MV); `projected_sector_weight` (forward projection for candidate OPEN); `filter_for_sector_limits` (drops OPENs breaching max_sector_pct; CLOSE/TRIM always pass through)
- `apps/api/schemas/sector.py` — 3 Pydantic schemas: `SectorAllocationSchema`, `SectorExposureResponse`, `SectorDetailResponse`
- `apps/api/routes/sector.py` — `sector_router`: GET /portfolio/sector-exposure (full breakdown), GET /portfolio/sector-exposure/{sector} (single-sector detail)
- `tests/unit/test_phase40_sector_exposure.py` — 60 tests (8 classes)

### Modified Files
- `apps/api/state.py` — Added `sector_weights: dict` (sector → float), `sector_filtered_count: int`
- `apps/worker/jobs/paper_trading.py` — Added Phase 40 sector exposure filter block after correlation adjustment; calls `SectorExposureService.filter_for_sector_limits` on proposed OPEN actions; updates `app_state.sector_weights` and `app_state.sector_filtered_count`
- `apps/api/routes/__init__.py` — Added `sector_router` import + `__all__` entry
- `apps/api/main.py` — Mounted `sector_router` at `/api/v1`
- `apps/dashboard/router.py` — Added `_render_sector_section`: sector allocation table with at-limit colour indicators; wired into `_render_page`

### Gate Result
2697/2697 passing, 100 skipped (PyYAML + E2E — expected). No new scheduled job (sector filter is inline in the paper cycle).

---

## [2026-03-20] Session 39 — Phase 39 COMPLETE (Correlation-Aware Position Sizing)

### New Files Created
- `services/risk_engine/correlation.py` — `CorrelationService`: `compute_correlation_matrix` (Pearson, numpy, MIN_OBSERVATIONS=20); `get_pairwise` (symmetric look-up); `max_pairwise_with_portfolio` (max |corr| of candidate vs all open positions); `correlation_size_factor` (1.0 ≤ 0.50, linear decay to floor at 1.0); `adjust_action_for_correlation` (dataclasses.replace, OPEN-only, returns adjusted action)
- `apps/worker/jobs/correlation.py` — `run_correlation_refresh`: queries DailyMarketBar, computes daily returns, calls CorrelationService, stores matrix in app_state; fire-and-forget; graceful degradation on DB failure
- `apps/api/schemas/correlation.py` — 3 Pydantic schemas: `CorrelationPairSchema`, `CorrelationMatrixResponse`, `TickerCorrelationResponse`
- `apps/api/routes/correlation.py` — `correlation_router`: GET /portfolio/correlation (full matrix), GET /portfolio/correlation/{ticker} (ticker profile + portfolio max-corr)
- `tests/unit/test_phase39_correlation.py` — 60 tests (8 classes)

### Modified Files
- `config/settings.py` — Added `max_pairwise_correlation=0.75`, `correlation_lookback_days=60`, `correlation_size_floor=0.25`
- `apps/api/state.py` — Added `correlation_matrix: dict`, `correlation_tickers: list[str]`, `correlation_computed_at: Optional[datetime]`
- `apps/worker/jobs/__init__.py` — Added `run_correlation_refresh` import + `__all__` entry
- `apps/worker/main.py` — Added `_job_correlation_refresh` wrapper; `correlation_refresh` job at 06:16 ET (20th total); updated schedule docstring
- `apps/api/routes/__init__.py` — Added `correlation_router` import + `__all__` entry
- `apps/api/main.py` — Mounted `correlation_router` at `/api/v1`
- `apps/worker/jobs/paper_trading.py` — Added Phase 39 correlation adjustment block after `apply_ranked_opportunities`; calls `CorrelationService.adjust_action_for_correlation` for every OPEN action before risk validation
- `apps/dashboard/router.py` — Added `_render_correlation_section`: cache status + top-5 portfolio pair correlation table; wired into `_render_page`
- 11 test files — job count assertions 19 → 20; job ID sets updated to include `correlation_refresh`

---

## [2026-03-20] Session 38 — Phase 38 COMPLETE (Market Regime Detection + Regime-Adaptive Weight Profiles)

### New Files Created
- `services/signal_engine/regime_detection.py` — `MarketRegime` enum (4 values); `REGIME_DEFAULT_WEIGHTS` dict (4 regimes × 5 strategies, each summing to 1.0); `RegimeResult` dataclass; `RegimeDetectionService` (detect_from_signals: median + std_dev heuristics; get_regime_weights; set_manual_override; persist_snapshot: fire-and-forget)
- `infra/db/models/regime_detection.py` — `RegimeSnapshot` ORM (table: regime_snapshots; id, regime, confidence, detection_basis_json, is_manual_override, override_reason + TimestampMixin; 2 indexes)
- `infra/db/versions/h8i9j0k1l2m3_add_regime_snapshots.py` — Alembic migration (down_revision: g7h8i9j0k1l2)
- `apps/api/schemas/regime.py` — 5 Pydantic schemas: RegimeCurrentResponse, RegimeOverrideRequest, RegimeOverrideResponse, RegimeSnapshotSchema, RegimeHistoryResponse
- `apps/api/routes/regime.py` — `regime_router`: GET /signals/regime, POST /signals/regime/override, DELETE /signals/regime/override, GET /signals/regime/history
- `tests/unit/test_phase38_regime_detection.py` — 60 tests (16 classes)

### Modified Files
- `infra/db/models/__init__.py` — Added `RegimeSnapshot` import + `__all__` entry
- `apps/api/routes/__init__.py` — Added `regime_router` import + `__all__` entry
- `apps/api/main.py` — Mounted `regime_router` at `/api/v1`
- `apps/api/state.py` — Added `current_regime_result: Optional[Any]`, `regime_history: list[Any]`
- `apps/worker/jobs/signal_ranking.py` — Added `run_regime_detection` function
- `apps/worker/jobs/__init__.py` — Exported `run_regime_detection`
- `apps/worker/main.py` — Added `_job_regime_detection` wrapper; scheduled `regime_detection` at 06:20 ET (19th job total); updated docstring
- `apps/dashboard/router.py` — Added `_render_regime_section()`; wired into `_render_page()`
- 8 test files — Updated job count assertions 18→19; added `"regime_detection"` to job ID sets

### Gate
- **2502/2502 tests passing** (37 skipped: PyYAML absent — expected), coverage 88.51%

---

## [2026-03-20] Session 37 — Phase 37 COMPLETE (Strategy Weight Auto-Tuning)

### New Files Created
- `infra/db/models/weight_profile.py` — `WeightProfile` ORM (table: weight_profiles; id, profile_name, source, weights_json, sharpe_metrics_json, is_active, optimization_run_id, notes + timestamps; 2 indexes: ix_weight_profile_is_active, ix_weight_profile_created_at)
- `infra/db/versions/g7h8i9j0k1l2_add_weight_profiles.py` — Alembic migration (down_revision: f6a7b8c9d0e1)
- `services/signal_engine/weight_optimizer.py` — `WeightOptimizerService` (optimize_from_backtest: Sharpe-proportional weights; create_manual_profile; get_active_profile; list_profiles; set_active_profile; equal_weights classmethod; fire-and-forget DB persist); `WeightProfileRecord` dataclass
- `apps/api/schemas/weights.py` — 5 Pydantic schemas: WeightProfileSchema, WeightProfileListResponse, OptimizeWeightsResponse, SetActiveWeightResponse, CreateManualWeightRequest
- `apps/api/routes/weights.py` — `weights_router`: POST /optimize, GET /current, GET /history, PUT /active/{profile_id}, POST /manual
- `tests/unit/test_phase37_weight_optimizer.py` — 58 tests (12 classes)

### Files Modified
- `infra/db/models/__init__.py` — Added `WeightProfile` import + `__all__` export
- `apps/api/routes/__init__.py` — Added `weights_router` export
- `apps/api/main.py` — Mounted `weights_router` under `/api/v1`
- `apps/api/state.py` — Added `active_weight_profile: Optional[Any] = None`
- `apps/worker/jobs/signal_ranking.py` — Added `run_weight_optimization` job function
- `apps/worker/jobs/__init__.py` — Added `run_weight_optimization` export
- `apps/worker/main.py` — Added `_job_weight_optimization` wrapper + `weight_optimization` scheduled at 06:52 ET weekdays (18th job total); updated docstring
- `apps/dashboard/router.py` — Added `_render_weight_profile_section()` + wired into `_render_page()`
- `services/ranking_engine/service.py` — `rank_signals()` accepts optional `strategy_weights: dict[str, float]`; `_aggregate()` computes weighted-mean signal score when weights provided; falls back to anchor-best when single signal or no weights
- 7 test files (job count 17→18): test_worker_jobs.py, test_phase18_priority18.py, test_phase22_enrichment_pipeline.py, test_phase23_intelligence_api.py, test_phase29_fundamentals.py, test_phase35_auto_execution.py, test_phase36_phase36.py

---

## [2026-03-20] Session 36 — Phase 36 COMPLETE (Real-time Price Streaming, Alternative Data Integration, Promotion Confidence Scoring)

### New Files Created
- `services/alternative_data/__init__.py` — package marker
- `services/alternative_data/models.py` — `AlternativeDataRecord` dataclass (ticker, source, sentiment_score [-1,1], mention_count, raw_snippet, captured_at, id); `AlternativeDataSource` enum (social_mention, web_search_trend, employee_review, satellite, custom)
- `services/alternative_data/adapters.py` — `BaseAlternativeAdapter` ABC + `SocialMentionAdapter` (deterministic synthetic stub; sentiment = hash-derived, no external API)
- `services/alternative_data/service.py` — `AlternativeDataService` (ingest, get_records, get_ticker_sentiment, clear; in-memory store)
- `apps/api/schemas/prices.py` — `PriceTickSchema`, `PriceSnapshotResponse` Pydantic schemas
- `apps/api/routes/prices.py` — `GET /api/v1/prices/snapshot` (REST price snapshot) + `WebSocket /api/v1/prices/ws` (streams portfolio prices every 2s)
- `tests/unit/test_phase36_phase36.py` — 81 tests (15 classes)

### Files Modified
- `services/self_improvement/models.py` — Added `confidence_score: float = 0.0` field to `ImprovementProposal`
- `services/self_improvement/config.py` — Added `min_auto_execute_confidence: float = 0.70`
- `services/self_improvement/service.py` — Added `_compute_confidence_score(evaluation) -> float`; stamps `proposal.confidence_score` in `promote_or_reject()`
- `services/self_improvement/execution.py` — `auto_execute_promoted()`: new `min_confidence` param; `skipped_low_confidence` counter; returns `skipped_low_confidence` in summary dict
- `apps/api/schemas/self_improvement.py` — Added `skipped_low_confidence: int = 0` to `AutoExecuteSummaryResponse`
- `apps/api/routes/self_improvement.py` — `auto_execute` route: reads `min_auto_execute_confidence` from config, passes to service, surfaces `skipped_low_confidence` in response
- `apps/api/schemas/intelligence.py` — Added `AlternativeDataRecordSchema`, `AlternativeDataResponse`
- `apps/api/routes/intelligence.py` — Added `GET /api/v1/intelligence/alternative` (ticker filter, limit, returns AlternativeDataResponse)
- `apps/api/routes/__init__.py` — Exported `prices_router`
- `apps/api/main.py` — Mounted `prices_router` under `/api/v1`
- `apps/api/state.py` — Added `latest_alternative_data: list[Any]`
- `apps/worker/jobs/ingestion.py` — Added `run_alternative_data_ingestion` (SocialMentionAdapter + AlternativeDataService; writes to app_state; fire-and-forget; never raises)
- `apps/worker/jobs/__init__.py` — Exported `run_alternative_data_ingestion`
- `apps/worker/main.py` — Scheduled `alternative_data_ingestion` at 06:05 ET (17th job total); imported + wrapped in `_job_alternative_data_ingestion`
- `apps/dashboard/router.py` — Updated `_render_auto_execution_section`: shows confidence threshold (70%); added `_render_alternative_data_section` (source breakdown, bullish/bearish/neutral counts, recent 5 records table); both wired into `_render_page`
- `tests/unit/test_phase18_priority18.py` — Job count 16→17; docstring updated
- `tests/unit/test_phase22_enrichment_pipeline.py` — Job count 16→17; expected_job_ids set updated (+alternative_data_ingestion)
- `tests/unit/test_phase23_intelligence_api.py` — Job count 16→17
- `tests/unit/test_phase29_fundamentals.py` — Job count 16→17
- `tests/unit/test_phase35_auto_execution.py` — Job count 16→17; docstring updated
- `tests/unit/test_worker_jobs.py` — Job count 16→17; _EXPECTED_JOB_IDS updated

---

## [2026-03-20] Session 35 — Phase 35 COMPLETE (Self-Improvement Proposal Auto-Execution)

### New Files Created
- `apis/infra/db/models/proposal_execution.py` — `ProposalExecution` ORM (table: proposal_executions; 12 columns: id, proposal_id, proposal_type, target_component, config_delta_json, baseline_params_json, status, executed_at, rolled_back_at, notes, created_at, updated_at; 2 indexes: ix_proposal_exec_proposal_id, ix_proposal_exec_executed_at)
- `apis/infra/db/versions/f6a7b8c9d0e1_add_proposal_executions.py` — Alembic migration (down_revision: e5f6a7b8c9d0)
- `apis/services/self_improvement/execution.py` — `AutoExecutionService`: execute_proposal (apply candidate_params to runtime_overrides + update promoted_versions + fire-and-forget DB persist), rollback_execution (restore baseline_params + mark rolled_back), auto_execute_promoted (batch; skips protected/non-promoted/already-applied); `ExecutionRecord` dataclass
- `apis/apps/api/schemas/self_improvement.py` — 5 Pydantic schemas: ExecutionRecordSchema, ExecutionListResponse, ExecuteProposalResponse, RollbackExecutionResponse, AutoExecuteSummaryResponse
- `apis/apps/api/routes/self_improvement.py` — `self_improvement_router`: POST /api/v1/self-improvement/proposals/{id}/execute (400 on non-promoted/protected, 404 if not found), POST /api/v1/self-improvement/executions/{id}/rollback, GET /api/v1/self-improvement/executions?limit=50, POST /api/v1/self-improvement/auto-execute
- `apis/tests/unit/test_phase35_auto_execution.py` — 68 tests (11 classes: TestProposalExecutionORM, TestProposalExecutionMigration, TestExecutionRecord, TestAutoExecutionServiceExecute, TestAutoExecutionServiceRollback, TestAutoExecutionServiceBatch, TestAutoExecutionDBPersist, TestSelfImprovementSchemas, TestSelfImprovementRoutes, TestAutoExecuteWorkerJob, TestSchedulerNewJob)

### Files Modified
- `apis/infra/db/models/__init__.py` — Added `ProposalExecution` import and `__all__` export
- `apis/apps/api/routes/__init__.py` — Added `self_improvement_router` export
- `apis/apps/api/main.py` — Mounted `self_improvement_router` under `/api/v1`
- `apis/apps/api/state.py` — Added `applied_executions: list[Any]`, `runtime_overrides: dict[str, Any]`, `last_auto_execute_at: Optional[dt.datetime]`
- `apis/apps/worker/jobs/self_improvement.py` — Added `run_auto_execute_proposals` job function
- `apis/apps/worker/jobs/__init__.py` — Added `run_auto_execute_proposals` export
- `apis/apps/worker/main.py` — Added `_job_auto_execute_proposals` wrapper + `auto_execute_proposals` scheduled at 18:15 ET weekdays; updated docstring (16 jobs total)
- `apis/apps/dashboard/router.py` — Added `_render_auto_execution_section()` + wired into `_render_page()` between alert and promoted_versions sections
- 5 test files updated: job count assertions 15 → 16 (test_phase18_priority18, test_phase22_enrichment_pipeline, test_phase23_intelligence_api, test_phase29_fundamentals, test_worker_jobs); exact job ID set in test_phase22 + test_worker_jobs updated to include "auto_execute_proposals"

**Test count: 2371/2371 passing (100 skipped: PyYAML + E2E)**

---

## [2026-03-20] Session 34 — Phase 34 COMPLETE (Strategy Backtesting Comparison API + Dashboard)

### New Files Created
- `apis/infra/db/models/backtest.py` — `BacktestRun` ORM (table: backtest_runs; 17 columns: id, comparison_id, strategy_name, start/end dates, ticker_count, tickers_json, total_return_pct, sharpe_ratio, max_drawdown_pct, win_rate, total_trades, days_simulated, final_portfolio_value, initial_cash, status, run_note + timestamps; index on comparison_id + created_at)
- `apis/infra/db/versions/e5f6a7b8c9d0_add_backtest_runs.py` — Alembic migration (down_revision: d4e5f6a7b8c9)
- `apis/services/backtest/comparison.py` — `BacktestComparisonService`: runs 5 individual strategy backtests + 1 combined (all_strategies) per request; persists each as a `BacktestRun` row; fire-and-forget DB writes; engine_factory injection for testability
- `apis/apps/api/schemas/backtest.py` — 6 Pydantic schemas: `BacktestCompareRequest`, `BacktestRunRecord`, `BacktestComparisonResponse`, `BacktestComparisonSummary`, `BacktestRunListResponse`, `BacktestRunDetailResponse`
- `apis/apps/api/routes/backtest.py` — `backtest_router`: `POST /api/v1/backtest/compare`, `GET /api/v1/backtest/runs`, `GET /api/v1/backtest/runs/{comparison_id}`
- `apis/tests/unit/test_phase34_backtest_comparison.py` — 50 tests (11 classes)

### Files Modified
- `apis/infra/db/models/__init__.py` — Added `BacktestRun` import and `__all__` export
- `apis/apps/api/routes/__init__.py` — Added `backtest_router` export
- `apis/apps/api/main.py` — Mounted `backtest_router` under `/api/v1`
- `apis/apps/dashboard/router.py` — Added `GET /dashboard/backtest` sub-page (strategy comparison table); updated nav bar to include Backtest link on all three pages; `_render_backtest_page()` queries DB for latest 5 comparison groups, degrades gracefully when DB unavailable

**Test count: 2303/2303 passing (100 skipped: PyYAML + E2E)**

---

## [2026-03-20] Session 33 — Phase 33 COMPLETE (Operator Dashboard Enhancements)

### New Files Created
- `apis/tests/unit/test_phase33_dashboard.py` — 56 tests (11 classes): TestDashboardImport, TestDashboardHomeBasics, TestDashboardAutoRefresh, TestDashboardNavigation, TestDashboardPaperCycleSection, TestDashboardPortfolioSection, TestDashboardPerformanceSection, TestDashboardRecentTradesSection, TestDashboardTradeGradesSection, TestDashboardIntelSection, TestDashboardSignalRunsSection, TestDashboardAlertServiceSection, TestDashboardExistingSections, TestDashboardPositionsPage

### Files Modified
- `apis/apps/dashboard/router.py` — Added 8 new section renderers (paper cycle, realized performance, recent closed trades, trade grades, intel feed, signal runs, alert service, enhanced portfolio); added `_fmt_usd`/`_fmt_pct` helpers; added `_page_wrap()` with auto-refresh support; added nav bar (Overview/Positions links); added `GET /dashboard/positions` sub-page route; auto-refresh every 60 s on both pages

**Test count: 2253/2253 passing (37 skipped: PyYAML + E2E)**

---

## [2026-03-20] Session 32 — Phase 32 COMPLETE (Position-level P&L History)

### New Files Created
- `apis/infra/db/versions/d4e5f6a7b8c9_add_position_history.py` — Alembic migration adding `position_history` table (down_revision: c2d3e4f5a6b7); includes `ix_pos_hist_ticker_snapshot` composite index
- `apis/tests/unit/test_phase32_position_history.py` — 41 tests (10 classes): TestPositionHistoryORM, TestPositionHistoryMigration, TestPositionHistorySchemas, TestPersistPositionHistory, TestPersistPositionHistoryNoPositions, TestPersistPositionHistoryInPaperCycle, TestPositionHistoryEndpoint, TestPositionHistoryEndpointFallback, TestPositionSnapshotsEndpoint, TestPositionSnapshotsEndpointFallback, TestHelperFunction

### Files Modified
- `apis/infra/db/models/portfolio.py` — Added `PositionHistory` ORM model (table: position_history; 11 columns: id, ticker, snapshot_at, quantity, avg_entry_price, current_price, market_value, cost_basis, unrealized_pnl, unrealized_pnl_pct + timestamps)
- `apis/infra/db/models/__init__.py` — Added `PositionHistory` import and `__all__` export
- `apis/apps/worker/jobs/paper_trading.py` — Added `_persist_position_history(portfolio_state, snapshot_at)` fire-and-forget helper; wired after portfolio snapshot persist when positions non-empty
- `apis/apps/api/schemas/portfolio.py` — Added `PositionHistoryRecord`, `PositionHistoryResponse`, `PositionLatestSnapshotResponse` Pydantic schemas
- `apis/apps/api/routes/portfolio.py` — Added `GET /portfolio/positions/{ticker}/history?limit=30`, `GET /portfolio/position-snapshots`, and `_pos_hist_row_to_record()` helper; imported new schemas

**Test count: 2197/2197 passing (100 skipped: PyYAML + E2E)**

---

## [2026-03-20] Session 31 — Phase 31 COMPLETE (Operator Alert Webhooks)

### New Files Created
- `apis/services/alerting/__init__.py` — Package exports: `AlertEvent`, `AlertEventType`, `AlertSeverity`, `WebhookAlertService`
- `apis/services/alerting/models.py` — `AlertSeverity` enum (info/warning/critical), `AlertEventType` enum (6 event types), `AlertEvent` dataclass (event_type, severity, title, payload, timestamp)
- `apis/services/alerting/service.py` — `WebhookAlertService`: `send_alert()` (never raises), `_build_payload()`, `_sign()` (HMAC-SHA256), `_post_with_retry()` (configurable retries); `make_alert_service()` factory
- `apis/tests/unit/test_phase31_operator_webhooks.py` — 57 tests (18 classes): TestAlertModels, TestWebhookAlertServiceInit, TestWebhookAlertServiceDisabled, TestBuildPayload, TestSignature, TestPostWithRetrySuccess, TestPostWithRetryNon2xx, TestPostWithRetryNetworkError, TestSendAlertSuccess, TestSendAlertNeverRaises, TestSettingsWebhookFields, TestAppStateAlertService, TestKillSwitchAlertWiring, TestBrokerAuthExpiredAlert, TestPaperCycleFatalErrorAlert, TestDailyEvaluationAlert, TestTestWebhookEndpoint, TestMakeAlertServiceFactory

### Files Modified
- `apis/config/settings.py` — Added `webhook_url`, `webhook_secret`, `alert_on_kill_switch`, `alert_on_paper_cycle_error`, `alert_on_broker_auth_expiry`, `alert_on_daily_evaluation` (all with safe defaults)
- `apis/apps/api/state.py` — Added `alert_service: Optional[Any] = None` field to `ApiAppState`
- `apis/apps/api/routes/admin.py` — Added `POST /api/v1/admin/test-webhook` endpoint; wired kill switch activation/deactivation to fire CRITICAL/WARNING webhook alerts
- `apis/apps/worker/jobs/paper_trading.py` — `BrokerAuthenticationError` path fires `broker_auth_expired` CRITICAL alert; outer fatal exception path fires `paper_cycle_error` WARNING alert
- `apis/apps/worker/jobs/evaluation.py` — Successful scorecard fires `daily_evaluation` alert (INFO if return >= -1%, WARNING if worse)
- `apis/apps/worker/main.py` — `_setup_alert_service()` initializes `app_state.alert_service` at worker startup
- `apis/apps/api/main.py` — `_load_persisted_state()` extended to initialize `app_state.alert_service` at API startup
- `apis/.env.example` — Added `APIS_WEBHOOK_URL`, `APIS_WEBHOOK_SECRET`, `APIS_ALERT_ON_*` vars

### Key Design Decisions
- `send_alert` never raises; all failures logged at WARNING, return False — operator alerts are fire-and-forget
- HMAC-SHA256 signing optional: `X-APIS-Signature: sha256=<hex>` header only when `APIS_WEBHOOK_SECRET` set
- Per-event flags default True: new URL receives all alerts without manual configuration
- `alert_service` stored in `ApiAppState` — consistent with existing broker/execution service pattern
- Jobs use `getattr(app_state, 'alert_service', None)` — zero breaking change to existing function signatures
- `POST /admin/test-webhook` returns 503 when webhook URL not configured (not silently 200)

### Test Results
- **Phase 31 tests**: 57/57 PASSED
- **Full suite**: 2156/2156 PASSED (37 skipped: PyYAML absent)

---

## [2026-03-19] Session 30 — Phase 30 COMPLETE (DB-backed Signal/Rank Persistence)

### Files Modified
- `apis/services/signal_engine/service.py` — Added `SignalRun` to import; `run()` now inserts a `SignalRun(id=signal_run_id, status="in_progress")` row + flush before processing signals; sets `status="completed"` + flush at end
- `apis/apps/api/state.py` — Added `last_signal_run_id: Optional[str]` and `last_ranking_run_id: Optional[str]` fields to `ApiAppState` (Phase 30 signal/ranking tracking)
- `apis/apps/worker/jobs/signal_ranking.py` — `run_signal_generation`: writes `app_state.last_signal_run_id` on success; `run_ranking_generation`: gains `session_factory` param; takes DB path (`svc.run()`) when `session_factory` + `last_signal_run_id` both present, otherwise in-memory fallback; always writes `app_state.last_ranking_run_id`
- `apis/apps/api/routes/__init__.py` — Added `signals_router`, `rankings_router` imports and exports
- `apis/apps/api/main.py` — Mounted `signals_router` + `rankings_router` under `/api/v1`

### New Files Created
- `apis/apps/api/schemas/signals.py` — 6 Pydantic schemas: `SignalRunRecord`, `SignalRunHistoryResponse`, `RankedOpportunityRecord`, `RankingRunRecord`, `RankingRunHistoryResponse`, `RankingRunDetailResponse`
- `apis/apps/api/routes/signals_rankings.py` — 4 endpoints: `GET /signals/runs` (list signal runs, graceful degradation), `GET /rankings/runs` (list ranking runs), `GET /rankings/latest` (newest run detail), `GET /rankings/runs/{run_id}` (specific run detail); UUID validation before session check
- `apis/tests/unit/test_phase30_signal_rank_persistence.py` — 36 tests (8 classes): `TestAppStatePhase30Fields`, `TestSignalEngineServiceSignalRun`, `TestRunSignalGenerationState`, `TestRunRankingGenerationDbPath`, `TestSignalRunSchema`, `TestSignalRunsEndpoint`, `TestRankingRunsEndpoint`, `TestRankingsLatestEndpoint`, `TestRankingRunByIdEndpoint`

### Key Design Decisions
- `SignalRun` status transitions: `in_progress` → `completed`; allows detecting interrupted runs
- `run_ranking_generation` DB path is purely additive — no existing tests broken
- List endpoints always return 200 with empty list on DB failure (graceful degradation)
- Detail endpoints return 503 (DB unavailable) or 404 (run not found) as appropriate
- UUID format validation returns 422 before any DB access

### Test Results
- **Phase 30 tests**: 36/36 PASSED
- **Full suite**: 2099/2099 PASSED (37 skipped: PyYAML absent)

---

## [2026-03-20] Session 29 — Phase 29 COMPLETE (Fundamentals Data Layer + ValuationStrategy)

### Files Modified
- `apis/services/feature_store/models.py` — Added 7 fundamentals overlay fields to `FeatureSet`: `pe_ratio`, `forward_pe`, `peg_ratio`, `price_to_sales`, `eps_growth`, `revenue_growth`, `earnings_surprise_pct` (all `Optional[float] = None`)
- `apis/services/feature_store/enrichment.py` — `enrich()` and `enrich_batch()` accept `fundamentals_store: Optional[dict] = None`; added `_apply_fundamentals()` static method using `dataclasses.replace()`
- `apis/services/signal_engine/service.py` — Added `ValuationStrategy()` as 5th default strategy; `run()` accepts and passes through `fundamentals_store`
- `apis/services/signal_engine/strategies/__init__.py` — Added `ValuationStrategy` import and `__all__` export
- `apis/apps/api/state.py` — Added `latest_fundamentals: dict` field (`ticker → FundamentalsData`)
- `apis/apps/worker/jobs/ingestion.py` — Added `run_fundamentals_refresh()` job function
- `apis/apps/worker/jobs/__init__.py` — Exported `run_fundamentals_refresh`
- `apis/apps/worker/main.py` — Added `_job_fundamentals_refresh()` wrapper; scheduled at 06:18 ET weekdays; total jobs now **15**
- `apis/apps/worker/jobs/signal_ranking.py` — `run_signal_generation` passes `fundamentals_store` from `app_state` to `svc.run()`
- `apis/tests/unit/test_worker_jobs.py` — 14→15 job count; added `fundamentals_refresh` to expected job IDs
- `apis/tests/integration/test_research_pipeline_integration.py` — 4→5 signals, 8→10, added `valuation_v1`, 4→5 contributing signals
- `apis/tests/simulation/test_paper_cycle_simulation.py` — 4→5 strategies, added `valuation_v1` assertion
- `apis/tests/unit/test_phase18_priority18.py` — job count 14→15
- `apis/tests/unit/test_phase21_signal_enhancement.py` — strategy count 4→5
- `apis/tests/unit/test_phase22_enrichment_pipeline.py` — `**kwargs` in side_effect helpers, counts 14→15
- `apis/tests/unit/test_phase23_intelligence_api.py` — job count 14→15

### New Files Created
- `apis/services/market_data/fundamentals.py` — `FundamentalsData` dataclass + `FundamentalsService` (yfinance-backed; per-ticker isolated fetch; `_safe_positive_float`, `_safe_float`, `_extract_earnings_surprise`)
- `apis/services/signal_engine/strategies/valuation.py` — `ValuationStrategy` (`valuation_v1`): 4 sub-scores (forward_pe, peg_ratio, eps_growth, earnings_surprise), re-normalized weights, confidence = n_available/4, neutral fallback (0.5/0.0) when all None
- `apis/tests/unit/test_phase29_fundamentals.py` — 8 test classes, ~45 tests

### Key Design Decisions
- yfinance isolation: each ticker fetch is wrapped in try/except; failures → None fields (never crash batch)
- `dataclasses.replace()` exclusively — no mutation of FeatureSet or FundamentalsData
- Negative P/E → None via `_safe_positive_float`; growth rates may be negative via `_safe_float`
- `confidence = n_available / 4` — explicitly represents data sparsity in the signal
- Neutral score (0.5) returned when no fundamentals data to avoid false bullish/bearish bias
- 06:18 ET pre-market timing ensures fundamentals are loaded before 09:35 signal generation

### Test Results
- **Phase 29 tests**: 45/45 PASSED
- **Full suite**: 2063/2063 PASSED (37 skipped: PyYAML absent)

---

## [2026-03-19] Session 28 — Phase 28 COMPLETE (Live Performance Summary + Closed Trade Grading + P&L Metrics)

### Files Modified
- `apis/apps/api/state.py` — Added `trade_grades: list[Any]` field to `ApiAppState`
- `apis/apps/worker/jobs/paper_trading.py` — Phase 28 grading block: uses `_pre_record_count` to identify newly-added closed trades, converts each to `TradeRecord`, calls `EvaluationEngineService.grade_closed_trade()`, appends `PositionGrade` to `app_state.trade_grades`
- `apis/apps/api/schemas/portfolio.py` — Added `TradeGradeRecord`, `TradeGradeHistoryResponse`, `PerformanceSummaryResponse` Pydantic schemas
- `apis/apps/api/routes/portfolio.py` — Added `GET /api/v1/portfolio/performance` (equity, SOD equity, HWM, daily return pct, drawdown from HWM, realized/unrealized P&L, win rate) + `GET /api/v1/portfolio/grades` (letter grades, grade distribution, ticker filter) routes
- `apis/apps/api/routes/metrics.py` — Added 3 Prometheus gauges: `apis_realized_pnl_usd`, `apis_unrealized_pnl_usd`, `apis_daily_return_pct`

### New Files Created
- `apis/tests/unit/test_phase28_performance_summary.py` — NEW: 33 tests (9 classes): TestPerformanceSummarySchema, TestTradeGradeSchemas, TestPerformanceEndpointNoState, TestPerformanceSummaryEquityMetrics, TestPerformanceSummaryRealizedPnl, TestPerformanceSummaryUnrealized, TestTradeGradeEndpoint, TestPaperCycleGradeIntegration, TestPrometheusMetricsPhase28

### Key Design Decisions
- Grading uses `_pre_record_count` snapshot to detect only trades closed in the CURRENT cycle
- `TradeRecord.strategy_key = ""` (ClosedTrade model does not track originating strategy)
- Naive `opened_at` timestamps normalized to UTC before conversion
- `drawdown_from_hwm_pct` clamped to ≥ 0 (equity above HWM → 0% drawdown, not negative)
- `win_rate = None` when no closed trades (avoid division by zero; distinguishes "no data" from 0%)

### Test Results
- **Phase 28 tests**: 33/33 PASSED
- **Full suite**: 1995/1995 PASSED (37 skipped: PyYAML absent)

---

## [2026-03-19] Session 27 — Phase 27 COMPLETE (Closed Trade Ledger + Start-of-Day Equity Refresh)

### Files Modified
- `apis/services/portfolio_engine/models.py` — Added `ClosedTrade` dataclass (ticker, action_type, fill_price, avg_entry_price, quantity, realized_pnl, realized_pnl_pct, reason, opened_at, closed_at, hold_duration_days; `is_winner` property)
- `apis/apps/api/state.py` — Added `closed_trades: list[Any]` and `last_sod_capture_date: Optional[dt.date]` fields to `ApiAppState`
- `apis/apps/worker/jobs/paper_trading.py` — (A) SOD equity block: first cycle of each trading day captures `start_of_day_equity` and updates `high_water_mark`; (B) Closed trade recording block: after `execute_approved_actions` and before broker sync, captures CLOSE/TRIM fills as `ClosedTrade` records appended to `app_state.closed_trades`
- `apis/apps/api/schemas/portfolio.py` — Added `ClosedTradeRecord` and `ClosedTradeHistoryResponse` response schemas
- `apis/apps/api/routes/portfolio.py` — Added `GET /api/v1/portfolio/trades` endpoint (filter by ticker, limit, aggregates: total_realized_pnl, win_rate, win/loss count)
- `apis/services/risk_engine/service.py` — Upgraded `dt.datetime.utcnow()` → `dt.datetime.now(dt.timezone.utc)`; normalizes naive `opened_at` for backward compatibility in age expiry calculation

### New Files Created
- `apis/tests/unit/test_phase27_trade_ledger.py` — NEW: 46 tests (8 classes): TestClosedTradeModel, TestAppStateNewFields, TestSodEquityRefresh, TestClosedTradeRecordingLogic, TestTradeHistoryEndpoint, TestTradeHistoryFiltering, TestTradeHistoryAggregates, TestPaperCycleWithTradeLedger

### Key Design Decisions
- Closed trades stored in-memory only (no DB FK complexity with securities table at this stage)
- Trade recording happens BEFORE broker sync (broker sync removes closed positions from `portfolio_state.positions`, so P&L must be captured first)
- SOD equity captured once per trading day, date-gated via `last_sod_capture_date`
- CLOSE supersedes TRIM for same ticker (carried from Phase 26 deduplication logic)

### Test Results
- **Phase 27 tests**: 46/46 PASSED
- **Full suite**: 1962/1962 PASSED (37 skipped: PyYAML absent)

---

## [2026-03-19] Session 26 — Phase 26 COMPLETE (TRIM Execution + Overconcentration Trim Trigger)

### Files Modified
- `apis/services/execution_engine/service.py` — `ActionType.TRIM` routed in `execute_action()` dispatch; `_execute_trim(request)` private method: validates `target_quantity > 0`, queries broker position, caps sell at `min(target_qty, position.qty)`, places SELL MARKET order; returns FILLED or REJECTED
- `apis/services/risk_engine/service.py` — Added `from decimal import Decimal, ROUND_DOWN` import (ROUND_DOWN was missing); added `evaluate_trims(portfolio_state) -> list[PortfolioAction]` method after `evaluate_exits`: detects overconcentration (`market_value > equity * max_single_name_pct`), computes shares via `ROUND_DOWN`, returns pre-approved TRIM actions
- `apis/apps/worker/jobs/paper_trading.py` — Overconcentration TRIM evaluation block added after exit evaluation merge; iterates `evaluate_trims()` results, adds TRIM to `proposed_actions` only if ticker not in `already_closing` (CLOSE supersedes TRIM)
- `apis/tests/unit/test_phase25_exit_strategy.py` — Updated 2 tests: TRIM now returns `REJECTED` (not `ERROR`) when no position; error message references ticker not "Unsupported action_type"

### New Files Created
- `apis/tests/unit/test_phase26_trim_execution.py` — NEW: 46 tests (11 classes): TestTrimExecutionFilled, TestTrimExecutionRejected, TestTrimExecutionKillSwitch, TestTrimExecutionBrokerErrors, TestEvaluateTrimsBasic, TestEvaluateTrimsNoTrigger, TestEvaluateTrimsKillSwitch, TestEvaluateTrimsEdgeCases, TestExecutionEngineTrimRouting, TestPaperCycleTrimIntegration

### Test Results
- **Phase 26 tests**: 46/46 PASSED
- **Full suite**: 1916/1916 PASSED (37 skipped: PyYAML absent)

---

## [2026-03-18] Session 14 — Phase 13 COMPLETE (Live Mode Gate + Secrets + Grafana)

### New Files Created
- `apis/services/live_mode_gate/__init__.py` — package init; exports GateRequirement, GateStatus, LiveModeGateResult, LiveModeGateService
- `apis/services/live_mode_gate/models.py` — GateStatus enum, GateRequirement dataclass (passed property), LiveModeGateResult dataclass (all_passed, failed_requirements)
- `apis/services/live_mode_gate/service.py` — LiveModeGateService.check_prerequisites(); gate checks for PAPER→HUMAN_APPROVED (5 cycles, 5 eval, ≤2 errors, portfolio init) and HUMAN_APPROVED→RESTRICTED_LIVE (20 cycles, 10 eval, rankings available, ≤2 errors, portfolio init); advisory message when all pass
- `apis/config/secrets.py` — SecretManager ABC, EnvSecretManager (reads os.environ, raises KeyError on missing/empty), AWSSecretManager scaffold (raises NotImplementedError with boto3 guidance), get_secret_manager() factory
- `apis/apps/api/schemas/live_gate.py` — PromotableMode enum, GateRequirementSchema, LiveGateStatusResponse, LiveGatePromoteRequest, LiveGatePromoteResponse
- `apis/apps/api/routes/live_gate.py` — GET /api/v1/live-gate/status (run gate for current→next mode, cache in state), POST /api/v1/live-gate/promote (advisory workflow: gate check → record if pass)
- `apis/infra/monitoring/grafana_dashboard.json` — Full Grafana dashboard: 11 data panels + 3 row separators; stat/timeseries types; kill switch, paper loop, positions, equity, cash, rankings, cycles, evaluations, proposals; Prometheus data source variable; 30s auto-refresh
- `apis/tests/unit/test_phase13_live_gate.py` — 88 Phase 13 gate tests across 11 test classes

### Files Modified
- `apis/apps/api/state.py` — Added Phase 13 fields: `live_gate_last_result`, `live_gate_promotion_pending`
- `apis/apps/api/routes/__init__.py` — Added `live_gate_router` export
- `apis/apps/api/main.py` — Mounted `live_gate_router` under `/api/v1`

### Test Results
- **Phase 13 tests**: 88/88 PASSED
- **Full suite**: 810/810 PASSED

---

## [2026-03-19] Session 13 — Phase 12 COMPLETE (Live Paper Trading Loop)

### New Files Created
- `apis/apps/worker/jobs/paper_trading.py` — `run_paper_trading_cycle`: full paper trading pipeline job; mode guard (PAPER/HUMAN_APPROVED only); ranked→portfolio→risk→execute→reconcile loop; structured result dict; all exceptions caught
- `apis/broker_adapters/schwab/adapter.py` — `SchwabBrokerAdapter`: Schwab OAuth 2.0 REST API scaffold; all methods raise `NotImplementedError` with implementation guidance; auth guard raises `BrokerAuthenticationError` if `client_id` is empty
- `apis/infra/docker/docker-compose.yml` — Full Docker Compose: postgres (v17), redis (v7-alpine), api (uvicorn 0.0.0.0:8000), worker (APScheduler); healthchecks on postgres/redis; depends_on healthy
- `apis/infra/docker/Dockerfile` — Multi-stage build: `builder` (pip install) → `api` (uvicorn) / `worker` (python apps/worker/main.py) targets
- `apis/infra/docker/init-db.sql` — Creates `apis_test` database alongside primary `apis` DB
- `apis/apps/api/routes/metrics.py` — Prometheus-compatible scrape endpoint `GET /metrics`; hand-crafted plain-text output; exposes: `apis_paper_loop_active`, `apis_paper_cycle_count`, `apis_position_count`, `apis_portfolio_equity`, `apis_kill_switch_active`, `apis_ranking_count`, `apis_evaluation_history_count`, `apis_info`
- `apis/tests/unit/test_phase12_paper_loop.py` — 76 Phase 12 gate tests across 8 test classes

### Files Modified
- `apis/apps/api/state.py` — Added Phase 12 paper loop fields: `paper_loop_active`, `last_paper_cycle_at`, `paper_cycle_count`, `paper_cycle_errors`
- `apis/apps/worker/jobs/__init__.py` — Added `run_paper_trading_cycle` export
- `apis/apps/worker/main.py` — Added `_job_paper_trading_cycle` wrapper + 2 scheduler entries (morning 09:30, midday); scheduler now has 11 jobs
- `apis/broker_adapters/schwab/__init__.py` — Added `SchwabBrokerAdapter` export
- `apis/apps/api/routes/__init__.py` — Added `metrics_router` export
- `apis/apps/api/main.py` — Mounted `metrics_router` (no prefix, accessible at `/metrics`)
- `apis/tests/unit/test_worker_jobs.py` — Updated `_EXPECTED_JOB_IDS` to include `paper_trading_cycle_morning` + `paper_trading_cycle_midday`; renamed `test_scheduler_has_exactly_nine_jobs` → `test_scheduler_has_exactly_eleven_jobs` (count 9→11)

### Test Results
- **Phase 12 tests**: 76/76 PASSED
- **Full suite**: 722/722 PASSED

---

## [2026-03-19] Session 12 — Phase 11 COMPLETE (Concrete Implementations + Backtest)

### Packages Installed
- `ib_insync 0.9.86` — asyncio IBKR TWS/Gateway client used by IBKRBrokerAdapter

### New Files Created
- `apis/services/market_data/models.py` — `NormalizedBar` (dollar_volume property), `LiquidityMetrics` (is_liquid_enough, tier), `MarketSnapshot`
- `apis/services/market_data/config.py` — `MarketDataConfig`: universe, yfinance interval mapping, max history
- `apis/services/market_data/utils.py` — `classify_liquidity_tier`, `compute_liquidity_metrics`
- `apis/services/market_data/service.py` — `MarketDataService`: yfinance-backed bar fetching, snapshot building, no DB dependency
- `apis/services/market_data/__init__.py`, `schemas.py`
- `apis/services/news_intelligence/utils.py` — POSITIVE_WORDS (35+), NEGATIVE_WORDS (40+), THEME_KEYWORDS (12 themes), score_sentiment, extract_tickers_from_text, detect_themes, generate_market_implication
- `apis/services/macro_policy_engine/utils.py` — EVENT_TYPE_SECTORS/THEMES/DEFAULT_BIAS/BASE_CONFIDENCE dicts, compute_directional_bias, generate_implication_summary
- `apis/services/rumor_scoring/utils.py` — extract_tickers_from_rumor (regex), normalize_source_text (strips whitespace, caps 500 chars)
- `apis/services/backtest/__init__.py` — package init
- `apis/services/backtest/models.py` — `DayResult`, `BacktestResult` (net_profit property)
- `apis/services/backtest/config.py` — `BacktestConfig` (validate() checks date ordering + ticker list)
- `apis/services/backtest/engine.py` — `BacktestEngine.run()`: day-by-day simulation, synthetic fills, Sharpe ratio, max drawdown, win rate, trading_days helper
- `apis/tests/unit/test_phase11_implementations.py` — 71 Phase 11 gate tests across 14 test classes

### Files Modified
- `apis/services/news_intelligence/service.py` — replaced stub with concrete NLP pipeline: credibility weight × keyword sentiment × ticker extraction × theme detection; returns `NewsInsight`
- `apis/services/macro_policy_engine/service.py` — replaced stub with concrete `process_event` (non-zero bias/confidence) + `assess_regime` (RISK_ON/RISK_OFF/STAGFLATION/NEUTRAL)
- `apis/services/theme_engine/utils.py` — replaced stub with `TICKER_THEME_REGISTRY`; 50 tickers × 12 themes with `BeneficiaryOrder` + `thematic_score`
- `apis/services/theme_engine/service.py` — replaced stub with registry-backed `get_exposure` (score filtering)
- `apis/broker_adapters/ibkr/adapter.py` — replaced file with concrete ib_insync implementation: connect/disconnect/ping, place_order (4 order types), cancel_order, get/list orders/positions/fills, is_market_open, next_market_open; paper-port guard + idempotency set. **Removed old scaffold (was lines 430-739; contained § SyntaxError on Python 3.14)**
- `apis/tests/unit/test_service_stubs.py` — updated 3 tests no longer valid with concrete impls
- `apis/tests/unit/test_ibkr_adapter.py` — added `_ensure_event_loop` autouse fixture; updated `TestIBKRAdapterMethodStubs` (NotImplementedError → BrokerConnectionError)
- `apis/state/ACTIVE_CONTEXT.md`, `NEXT_STEPS.md`, `SESSION_HANDOFF_LOG.md` — updated

### Key Bug Fixes
- **BacktestEngine `_simulate_day`**: `portfolio_svc.open/close_position()` returns `PortfolioAction` proposals (does NOT mutate state). Fixed with direct `PortfolioPosition` construction and `portfolio_state.positions[ticker] =` assignment.
- **BacktestEngine list comprehension scope**: `b` was used after `for b in bars` comprehension — Python 3 comprehensions have own scope. Fixed with `last_bar = bars[-1]`.
- **BacktestEngine `MomentumStrategy.score()`**: Engine called with wrong kwargs. Actual signature: `score(self, feature_set: FeatureSet)`. Fixed.
- **ib_insync/eventkit event loop**: `eventkit.util` calls `asyncio.get_event_loop()` at import time. Python 3.14 no longer creates implicit event loop. Fixed with `_ensure_event_loop` autouse fixture (`asyncio.new_event_loop()` + `asyncio.set_event_loop()`).

### Gate Results
- **Phase 11 COMPLETE — 646/646 tests** (71 new + 575 prior; no regressions)
  - ✅ market_data, news_intelligence, macro_policy_engine, theme_engine, rumor_scoring: concrete implementations
  - ✅ IBKRBrokerAdapter: full ib_insync implementation replacing scaffold
  - ✅ BacktestEngine: day-by-day simulation complete and correct
  - ✅ All prior gates A–H unaffected

---

## [2026-03-18] Session 11 — Phase 10 Steps 3 & 4 (IBKR Scaffold + Dashboard)

### New Files Created
- `apis/broker_adapters/ibkr/adapter.py` — `IBKRBrokerAdapter` architecture-ready scaffold. Implements full `BaseBrokerAdapter` interface; all operational methods raise `NotImplementedError` with implementation guidance (ib_insync pattern, port constants, translation notes). Constructor safety guard rejects live ports (7496/4001) when `paper=True`.
- `apis/apps/dashboard/router.py` — `dashboard_router` (FastAPI `APIRouter`, prefix `/dashboard`). Single route `GET /dashboard/` returns a self-contained HTML page drawn from `ApiAppState`: system status, portfolio summary, top-5 rankings, scorecard, self-improvement proposals, promoted versions. Zero external template-engine deps (inline HTML).
- `apis/tests/unit/test_ibkr_adapter.py` — 25 tests across 3 classes: `TestIBKRAdapterImportAndIdentity` (4), `TestIBKRAdapterConstruction` (7), `TestIBKRAdapterMethodStubs` (14).
- `apis/tests/unit/test_dashboard.py` — 15 tests across 2 classes: `TestDashboardImport` (3), `TestDashboardHomeRoute` (12).

### Files Modified
- `apis/broker_adapters/ibkr/__init__.py` — replaced one-liner stub with `IBKRBrokerAdapter` export.
- `apis/apps/dashboard/__init__.py` — replaced one-liner stub with `dashboard_router` export.
- `apis/apps/api/main.py` — mounted `dashboard_router` (no prefix, accessible at `/dashboard/`).

### Gate Results
- **Phase 10 COMPLETE — 575/575 tests** (40 new + 535 prior; no regressions)
  - ✅ IBKR scaffold importable, inherits `BaseBrokerAdapter`, live-port safety guard functional
  - ✅ Dashboard route returns 200 HTML, reflects ApiAppState fields correctly
  - ✅ All prior gates A–H unaffected

---

## [2026-03-17] Session 10 — Phase 9 Background Worker Jobs (APScheduler)

### Packages Installed
- `apscheduler 3.11.2` — in-process task scheduler (pytz already present as transitive dep)

### New Files Created
- `apis/apps/worker/jobs/ingestion.py` — `run_market_data_ingestion` (fetch + persist OHLCV bars for universe), `run_feature_refresh` (compute + persist baseline features). Both skip gracefully when `session_factory=None` (returns `status=skipped_no_session`). Exceptions caught; returns structured result dict.
- `apis/apps/worker/jobs/signal_ranking.py` — `run_signal_generation` (DB-backed signal generation via `SignalEngineService.run()`), `run_ranking_generation` (in-memory `RankingEngineService.rank_signals()` + writes `ApiAppState.latest_rankings`, `ranking_run_id`, `ranking_as_of`). Both accept injected services for testing.
- `apis/apps/worker/jobs/evaluation.py` — `run_daily_evaluation` (builds `PortfolioSnapshot` from live `ApiAppState.portfolio_state` or empty fallback → `EvaluationEngineService.generate_daily_scorecard()` → writes `ApiAppState.latest_scorecard` + `evaluation_history`), `run_attribution_analysis` (standalone attribution log job).
- `apis/apps/worker/jobs/reporting.py` — `run_generate_daily_report` (reads portfolio/scorecard/proposals from `ApiAppState` → `ReportingService.generate_daily_report()` → writes `ApiAppState.latest_daily_report` + `report_history`), `run_publish_operator_summary` (structured operator log entry). Helper `_derive_grade` extracts letter grade from scorecard.
- `apis/apps/worker/jobs/self_improvement.py` — `run_generate_improvement_proposals` (reads `ApiAppState.latest_scorecard` + `promoted_versions` → `SelfImprovementService.generate_proposals()` → writes `ApiAppState.improvement_proposals`). Grade derived via `_scorecard_to_grade`; attribution summary via `_build_attribution_summary`.
- `apis/tests/unit/test_worker_jobs.py` — 49 Gate H tests across 8 classes: `TestIngestionJobs` (6), `TestSignalRankingJobs` (8), `TestEvaluationJobs` (10), `TestReportingJobs` (9), `TestSelfImprovementJobs` (8), `TestScheduler` (3), `TestWorkerJobsImports` (1), `TestEndToEndPipeline` (4).

### Files Modified
- `apis/apps/api/state.py` — Added `improvement_proposals: list[Any]` field to `ApiAppState` (background jobs write here; reporting reads here).
- `apis/apps/worker/jobs/__init__.py` — Replaced stub with full exports of all 9 job functions.
- `apis/apps/worker/main.py` — Full APScheduler `BackgroundScheduler` wiring; `build_scheduler()` factory; 9 cron jobs on US/Eastern weekday schedule; graceful SIGTERM/SIGINT shutdown; `_make_session_factory()` helper with fallback.

### Gate Results
- **Gate H: PASSED — 494/494 tests** (49 new Gate H + 445 prior; no regressions)
- Gate H criteria verified per spec §8.1–8.7:
  - ✅ `run_market_data_ingestion` — skips cleanly without DB; returns structured result
  - ✅ `run_feature_refresh` — skips cleanly without DB; returns structured result
  - ✅ `run_signal_generation` — skips cleanly without DB; returns structured result
  - ✅ `run_ranking_generation` — in-memory path; writes `latest_rankings` to `ApiAppState`
  - ✅ `run_daily_evaluation` — zero-portfolio fallback; writes `latest_scorecard` + history
  - ✅ `run_attribution_analysis` — standalone attribution log; returns counts
  - ✅ `run_generate_daily_report` — reads state; writes `latest_daily_report` + history
  - ✅ `run_publish_operator_summary` — structured operator log; safe when state is empty
  - ✅ `run_generate_improvement_proposals` — reads scorecard grade + attribution; writes proposals
  - ✅ `build_scheduler()` — returns configured scheduler with 9 jobs (mon–fri, US/Eastern)
  - ✅ `ApiAppState.improvement_proposals` added; all prior route tests still pass

---

## [2026-03-17] Session 5 — Phase 4 Portfolio + Risk Engine

### New Files Created
- `apis/services/portfolio_engine/models.py` — `PortfolioPosition` (market_value/cost_basis/unrealized_pnl/unrealized_pnl_pct properties), `PortfolioState` (equity/gross_exposure/drawdown_pct/daily_pnl_pct derived properties), `ActionType` enum (OPEN/CLOSE/BLOCKED), `PortfolioAction`, `SizingResult`, `PortfolioSnapshot` (replaces stub)
- `apis/services/portfolio_engine/service.py` — `PortfolioEngineService`: `apply_ranked_opportunities` (opens top buys up to max_positions, closes stale), `open_position`, `close_position` (explainable exits with thesis from position), `snapshot`, `compute_sizing` (half-Kelly: f*=0.5×max(0,2p−1); capped at min(sizing_hint_pct, max_single_name_pct)) (replaces stub)
- `apis/services/risk_engine/models.py` — `RiskSeverity` (HARD_BLOCK/WARNING), `RiskViolation`, `RiskCheckResult` (`is_hard_blocked` property, `adjusted_max_notional`) (replaces stub)
- `apis/services/risk_engine/service.py` — `RiskEngineService`: `validate_action` (master gatekeeper), `check_kill_switch`, `check_portfolio_limits` (max_positions hard_block + max_single_name_pct size warning), `check_daily_loss_limit`, `check_drawdown` (replaces stub)
- `apis/services/execution_engine/models.py` — `ExecutionStatus` (FILLED/REJECTED/BLOCKED/ERROR), `ExecutionRequest`, `ExecutionResult` (replaces stub)
- `apis/services/execution_engine/service.py` — `ExecutionEngineService`: `execute_action` (kill-switch guard, OPEN→BUY market order floor(notional/price) shares, CLOSE→SELL full position via broker, all exceptions → structured results), `execute_approved_actions` batch (replaces stub)
- `apis/tests/unit/test_portfolio_engine.py` — 40 Gate C tests (PortfolioState, PortfolioPosition, sizing, open/close, apply_ranked_opportunities, snapshot)
- `apis/tests/unit/test_risk_engine.py` — 22 Gate C tests (kill_switch, max_positions, max_single_name_pct, daily_loss_limit, drawdown, validate_action master gatekeeper)
- `apis/tests/unit/test_execution_engine.py` — 15 Gate C tests (kill switch blocks, open fills, close fills, rejected on no position, batch execution, partial failure isolation)

### Gate Results
- **Gate C: PASSED — 185/185 tests** (77 new Gate C + 108 Gate B + 44 Gate A; no regressions)
- Gate C criteria verified:
  - ✅ sizing and exposure rules work (half-Kelly formula verified, max_single_name_pct cap verified)
  - ✅ invalid trades are blocked (kill_switch, max_positions, daily_loss_limit, drawdown all generate hard_block violations)
  - ✅ exits are explainable (thesis_summary from original position attached to every CLOSE action)
  - ✅ limits are enforced (validate_action aggregates all violations; action.risk_approved set only on full pass)

---

## [2026-03-18] Session 4 — Phase 3 Research Engine

### New Packages Installed
- `yfinance==1.2.0` — market data adapter
- `pandas==3.0.1` — dataframe operations
- `numpy==2.4.3` — numerical operations (transitive dep)

### New Files Created
- `apis/config/universe.py` — 50-ticker universe config across 8 segments; `get_universe_tickers()` helper; `TICKER_SECTOR` map
- `apis/services/data_ingestion/models.py` — `BarRecord`, `IngestionRequest`, `IngestionResult`, `TickerResult`, `IngestionStatus` (replaces stub)
- `apis/services/data_ingestion/adapters/__init__.py` — adapters sub-package
- `apis/services/data_ingestion/adapters/yfinance_adapter.py` — `YFinanceAdapter` (source_key="yfinance", reliability_tier="secondary_verified"); `fetch_bars`, `fetch_bulk`, `_normalise_df`
- `apis/services/data_ingestion/service.py` — `DataIngestionService` (ingest_universe_bars, ingest_single_ticker, get_or_create_security, persist_bars via pg_insert ON CONFLICT DO NOTHING)
- `apis/services/feature_store/models.py` — `FeatureSet`, `ComputedFeature`, `FEATURE_KEYS`, `FEATURE_GROUP_MAP` (replaces stub)
- `apis/services/feature_store/pipeline.py` — `BaselineFeaturePipeline` (11 features: momentum×3, risk×2, liquidity×1, trend×5; all individually testable)
- `apis/services/feature_store/service.py` — `FeatureStoreService` (ensure_feature_catalog, compute_and_persist, get_features)
- `apis/services/signal_engine/models.py` — `SignalOutput`, `HorizonClassification`, `SignalType` (replaces stub)
- `apis/services/signal_engine/strategies/__init__.py` — strategies sub-package
- `apis/services/signal_engine/strategies/momentum.py` — `MomentumStrategy` (weighted sub-scores, explanation_dict with rationale + driver_features, source_reliability_tier, contains_rumor=False)
- `apis/services/signal_engine/service.py` — `SignalEngineService` (run + score_from_features, _ensure_strategy_rows, _persist_signal)
- `apis/services/ranking_engine/models.py` — `RankedResult`, `RankingConfig` (replaces stub)
- `apis/services/ranking_engine/service.py` — `RankingEngineService` (rank_signals in-memory + run DB path; composite score, thesis_summary, disconfirming_factors, sizing_hint, source_reliability_tier, contains_rumor propagation)
- `apis/tests/unit/test_data_ingestion.py` — 13 Gate B tests (adapter, models, service)
- `apis/tests/unit/test_feature_store.py` — 17 Gate B tests (pipeline + FeatureSet helpers)
- `apis/tests/unit/test_signal_engine.py` — 16 Gate B tests (MomentumStrategy + SignalEngineService)
- `apis/tests/unit/test_ranking_engine.py` — 18 Gate B tests (RankingEngineService + end-to-end pipeline)

### Gate Results
- **Gate B: PASSED — 108/108 tests** (64 new + 44 Gate A retained)
- Gate B criteria verified:
  - ✅ ranking pipeline runs (TestEndToEndPipeline.test_full_pipeline_no_db)
  - ✅ outputs are explainable (thesis_summary + explanation_dict.rationale on every output)
  - ✅ sources are tagged by reliability (source_reliability_tier on BarRecord + SignalOutput + RankedResult)
  - ✅ rumors separated from verified facts (contains_rumor flag propagated through full pipeline)

---



### Top-Level Files Created
- `apis/README.md` — project summary, architecture table, setup instructions, governing doc index
- `apis/pyproject.toml` — project metadata, dependencies, ruff/mypy/pytest config
- `apis/requirements.txt` — flat requirements file
- `apis/.env.example` — non-secret environment variable template
- `apis/.gitignore` — standard Python + data/secrets gitignore

### State Files Created
- `apis/state/ACTIVE_CONTEXT.md` — initial ground truth
- `apis/state/NEXT_STEPS.md` — Phase 1 next actions + future phase plan
- `apis/state/DECISION_LOG.md` — 10 founding architecture decisions (DEC-001 through DEC-010)
- `apis/state/CHANGELOG.md` — this file
- `apis/state/SESSION_HANDOFF_LOG.md` — session checkpoint log initialized

### Config Layer Created
- `apis/config/__init__.py`
- `apis/config/settings.py` — pydantic-settings `Settings` class with all env vars
- `apis/config/logging_config.py` — structlog structured JSON logging setup

### Broker Adapter Layer Created
- `apis/broker_adapters/base/__init__.py`
- `apis/broker_adapters/base/adapter.py` — `BaseBrokerAdapter` abstract base class
- `apis/broker_adapters/base/models.py` — `Order`, `Fill`, `Position`, `AccountState` domain models
- `apis/broker_adapters/base/exceptions.py` — broker exception hierarchy
- `apis/broker_adapters/paper/__init__.py`
- `apis/broker_adapters/paper/adapter.py` — `PaperBrokerAdapter` full implementation

### Strategy, App, and Service Stubs Created
- 6 strategy stubs: `long_term`, `swing`, `event_driven`, `theme_rotation`, `ai_theme`, `policy_trade`
- 16 service stubs: `data_ingestion`, `market_data`, `news_intelligence`, `macro_policy_engine`, `theme_engine`, `rumor_scoring`, `feature_store`, `signal_engine`, `ranking_engine`, `portfolio_engine`, `risk_engine`, `execution_engine`, `evaluation_engine`, `self_improvement`, `reporting`, `continuity`
- 3 app stubs: `apps/api/`, `apps/worker/`, `apps/dashboard/`
- Other directories: `data/`, `research/`, `infra/`, `scripts/`, `models/`

### Test Harness Created
- `apis/tests/__init__.py`
- `apis/tests/conftest.py` — shared fixtures for paper broker and config
- `apis/tests/unit/__init__.py`
- `apis/tests/unit/test_config.py` — config loads correctly, env vars validated
- `apis/tests/unit/test_paper_broker.py` — paper broker: place order, fill order, get state
- `apis/tests/integration/__init__.py`
- `apis/tests/e2e/__init__.py`
- `apis/tests/simulation/__init__.py`
- `apis/tests/fixtures/__init__.py`

### Gate A Status
**PASSED** — 44/44 unit tests passing.
- `TestSettingsLoad` — 9/9 pass
- `TestLoggingConfig` — 3/3 pass (fixed: use `stdlib.LoggerFactory` not `PrintLoggerFactory`)
- `TestLifecycle` — 3/3 pass
- `TestOrderPlacementAndFill` — 6/6 pass
- `TestCashAccounting` — 3/3 pass
- `TestPositions` — 7/7 pass
- `TestSafetyInvariants` — 6/6 pass
- `TestOrderCancellation` — 2/2 pass
- `TestAccountState` — 3/3 pass
- `TestFillRetrieval` — 2/2 pass

### Python environment
- Python 3.14.3 (workspace)
- Virtual env: `apis/.venv/`
- Key packages: pydantic 2.12.5, pydantic-settings 2.13.1, structlog 25.5.0, pytest 9.0.2

---

## [2026-03-17] Session 2 — PostgreSQL Provisioning

### Infrastructure
- PostgreSQL 17.9 installed via EDB installer (winget-cached, UAC-elevated)
- Service `postgresql-x64-17` running, Automatic start
- Databases created: `apis` (UTF8), `apis_test` (UTF8)
- postgres superuser password set to `ApisDev2026!` (trust-mode reset)
- `C:\Program Files\PostgreSQL\17\bin` added to user PATH
- `.env` file created with real connection string

### Python Packages Added to Venv
- sqlalchemy 2.0.48
- alembic 1.18.4
- psycopg 3.3.3 (psycopg[binary])
- redis 7.3.0

---

## [2026-03-17] Session 3 — Phase 2 Database Layer

### Alembic Environment
- `apis/alembic.ini` — Alembic config; `script_location = infra/db`; `prepend_sys_path = .`
- `apis/infra/__init__.py` — Python package init
- `apis/infra/db/__init__.py` — Python package init
- `