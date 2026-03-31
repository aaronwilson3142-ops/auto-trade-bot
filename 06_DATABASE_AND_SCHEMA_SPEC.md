# DATABASE_AND_SCHEMA_SPEC.md
Version: 1.0
Project: Autonomous Portfolio Intelligence System (APIS)
Status: Initial database and schema specification

## 1. Purpose

This file defines the initial database design for APIS.

The schema must support:
- market and source ingestion
- derived features
- signal generation
- ranking results
- portfolio state
- orders and fills
- evaluation and attribution
- controlled self-improvement
- continuity and auditability

The schema should favor clarity, traceability, and reproducibility over cleverness.

## 2. Database Strategy

### 2.1 Primary Database
Use PostgreSQL as the primary relational store.

### 2.2 Supporting Stores
Redis may be used for:
- caching
- job coordination
- lightweight queues
- ephemeral runtime state

Do not use Redis as the system of record for critical portfolio truth.

### 2.3 Design Principles
- timestamps on critical records
- explicit status fields
- append-friendly history where practical
- no silent overwrites of important state
- support reproducible snapshots
- keep audit trails

## 3. Core Schema Domains

The initial schema is divided into:
1. reference data
2. source ingestion
3. derived analytics
4. strategy and ranking
5. portfolio and execution
6. evaluation
7. self-improvement
8. continuity and audit

## 4. Reference Tables

### 4.1 `securities`
Purpose:
Master list of tradable instruments in scope.

Suggested columns:
- `id` UUID PK
- `ticker` VARCHAR UNIQUE NOT NULL
- `name` VARCHAR NOT NULL
- `asset_type` VARCHAR NOT NULL
- `exchange` VARCHAR
- `sector` VARCHAR
- `industry` VARCHAR
- `country` VARCHAR
- `currency` VARCHAR
- `is_active` BOOLEAN DEFAULT TRUE
- `created_at` TIMESTAMP NOT NULL
- `updated_at` TIMESTAMP NOT NULL

Notes:
- MVP focus is U.S. equities
- keep room for future extension

### 4.2 `themes`
Purpose:
Canonical theme registry.

Suggested columns:
- `id` UUID PK
- `theme_key` VARCHAR UNIQUE NOT NULL
- `theme_name` VARCHAR NOT NULL
- `description` TEXT
- `created_at` TIMESTAMP NOT NULL
- `updated_at` TIMESTAMP NOT NULL

Examples:
- ai_infrastructure
- semiconductors
- data_center_power
- cybersecurity
- defense
- energy_policy
- reshoring

### 4.3 `security_themes`
Purpose:
Maps securities to themes.

Suggested columns:
- `id` UUID PK
- `security_id` UUID FK -> securities.id
- `theme_id` UUID FK -> themes.id
- `relationship_type` VARCHAR NOT NULL
- `confidence_score` NUMERIC(8,4)
- `source_method` VARCHAR
- `created_at` TIMESTAMP NOT NULL
- `updated_at` TIMESTAMP NOT NULL

`relationship_type` examples:
- primary_beneficiary
- secondary_beneficiary
- supplier
- infrastructure
- indirect_exposure

## 5. Source Ingestion Tables

### 5.1 `sources`
Purpose:
Registry of data/news/policy/chatter sources.

Suggested columns:
- `id` UUID PK
- `source_key` VARCHAR UNIQUE NOT NULL
- `source_name` VARCHAR NOT NULL
- `source_type` VARCHAR NOT NULL
- `reliability_tier` VARCHAR NOT NULL
- `default_weight` NUMERIC(8,4)
- `is_active` BOOLEAN DEFAULT TRUE
- `created_at` TIMESTAMP NOT NULL
- `updated_at` TIMESTAMP NOT NULL

### 5.2 `source_events`
Purpose:
Stores normalized ingested source items.

Suggested columns:
- `id` UUID PK
- `source_id` UUID FK -> sources.id
- `event_type` VARCHAR NOT NULL
- `headline` TEXT
- `body_text` TEXT
- `event_timestamp` TIMESTAMP
- `ingested_at` TIMESTAMP NOT NULL
- `url` TEXT
- `raw_payload_ref` TEXT
- `credibility_score` NUMERIC(8,4)
- `decay_score` NUMERIC(8,4)
- `is_verified` BOOLEAN DEFAULT FALSE
- `metadata_json` JSONB
- `created_at` TIMESTAMP NOT NULL
- `updated_at` TIMESTAMP NOT NULL

### 5.3 `security_event_links`
Purpose:
Links source events to impacted securities.

Suggested columns:
- `id` UUID PK
- `source_event_id` UUID FK -> source_events.id
- `security_id` UUID FK -> securities.id
- `link_reason` VARCHAR
- `impact_direction` VARCHAR
- `impact_confidence` NUMERIC(8,4)
- `created_at` TIMESTAMP NOT NULL
- `updated_at` TIMESTAMP NOT NULL

## 6. Market Data Tables

### 6.1 `daily_market_bars`
Purpose:
Daily OHLCV and related values.

Suggested columns:
- `id` UUID PK
- `security_id` UUID FK -> securities.id
- `trade_date` DATE NOT NULL
- `open` NUMERIC(18,6)
- `high` NUMERIC(18,6)
- `low` NUMERIC(18,6)
- `close` NUMERIC(18,6)
- `adjusted_close` NUMERIC(18,6)
- `volume` BIGINT
- `vwap` NUMERIC(18,6)
- `created_at` TIMESTAMP NOT NULL
- `updated_at` TIMESTAMP NOT NULL

Unique constraint:
- (`security_id`, `trade_date`)

### 6.2 `security_liquidity_metrics`
Purpose:
Derived liquidity stats by date.

Suggested columns:
- `id` UUID PK
- `security_id` UUID FK -> securities.id
- `metric_date` DATE NOT NULL
- `avg_dollar_volume_20d` NUMERIC(18,6)
- `avg_share_volume_20d` NUMERIC(18,6)
- `atr_14` NUMERIC(18,6)
- `volatility_20d` NUMERIC(18,6)
- `float_shares` BIGINT
- `market_cap` NUMERIC(20,2)
- `created_at` TIMESTAMP NOT NULL
- `updated_at` TIMESTAMP NOT NULL

## 7. Derived Analytics Tables

### 7.1 `features`
Purpose:
Catalog of available engineered features.

Suggested columns:
- `id` UUID PK
- `feature_key` VARCHAR UNIQUE NOT NULL
- `feature_name` VARCHAR NOT NULL
- `feature_group` VARCHAR NOT NULL
- `description` TEXT
- `created_at` TIMESTAMP NOT NULL
- `updated_at` TIMESTAMP NOT NULL

### 7.2 `security_feature_values`
Purpose:
Stores computed feature values by security and timestamp.

Suggested columns:
- `id` UUID PK
- `security_id` UUID FK -> securities.id
- `feature_id` UUID FK -> features.id
- `as_of_timestamp` TIMESTAMP NOT NULL
- `feature_value_numeric` NUMERIC(20,8)
- `feature_value_text` TEXT
- `source_version` VARCHAR
- `created_at` TIMESTAMP NOT NULL
- `updated_at` TIMESTAMP NOT NULL

Indexes:
- (`security_id`, `as_of_timestamp`)
- (`feature_id`, `as_of_timestamp`)

## 8. Strategy, Signal, and Ranking Tables

### 8.1 `strategies`
Purpose:
Registry of strategy families/configurations.

Suggested columns:
- `id` UUID PK
- `strategy_key` VARCHAR UNIQUE NOT NULL
- `strategy_name` VARCHAR NOT NULL
- `strategy_family` VARCHAR NOT NULL
- `is_active` BOOLEAN DEFAULT TRUE
- `config_version` VARCHAR
- `created_at` TIMESTAMP NOT NULL
- `updated_at` TIMESTAMP NOT NULL

### 8.2 `signal_runs`
Purpose:
Top-level record of a signal-generation run.

Suggested columns:
- `id` UUID PK
- `run_timestamp` TIMESTAMP NOT NULL
- `run_mode` VARCHAR NOT NULL
- `universe_name` VARCHAR
- `config_version` VARCHAR
- `status` VARCHAR NOT NULL
- `notes` TEXT
- `created_at` TIMESTAMP NOT NULL
- `updated_at` TIMESTAMP NOT NULL

### 8.3 `security_signals`
Purpose:
Stores signal outputs per security.

Suggested columns:
- `id` UUID PK
- `signal_run_id` UUID FK -> signal_runs.id
- `security_id` UUID FK -> securities.id
- `strategy_id` UUID FK -> strategies.id
- `signal_type` VARCHAR NOT NULL
- `signal_score` NUMERIC(12,6)
- `confidence_score` NUMERIC(12,6)
- `risk_score` NUMERIC(12,6)
- `catalyst_score` NUMERIC(12,6)
- `liquidity_score` NUMERIC(12,6)
- `horizon_classification` VARCHAR
- `explanation_json` JSONB
- `created_at` TIMESTAMP NOT NULL
- `updated_at` TIMESTAMP NOT NULL

### 8.4 `ranking_runs`
Purpose:
Top-level record for final ranking.

Suggested columns:
- `id` UUID PK
- `signal_run_id` UUID FK -> signal_runs.id
- `run_timestamp` TIMESTAMP NOT NULL
- `config_version` VARCHAR
- `status` VARCHAR NOT NULL
- `created_at` TIMESTAMP NOT NULL
- `updated_at` TIMESTAMP NOT NULL

### 8.5 `ranked_opportunities`
Purpose:
Final ranked opportunities.

Suggested columns:
- `id` UUID PK
- `ranking_run_id` UUID FK -> ranking_runs.id
- `security_id` UUID FK -> securities.id
- `rank_position` INTEGER NOT NULL
- `composite_score` NUMERIC(12,6)
- `portfolio_fit_score` NUMERIC(12,6)
- `recommended_action` VARCHAR NOT NULL
- `target_horizon` VARCHAR
- `thesis_summary` TEXT
- `disconfirming_factors` TEXT
- `sizing_hint_pct` NUMERIC(8,4)
- `created_at` TIMESTAMP NOT NULL
- `updated_at` TIMESTAMP NOT NULL

## 9. Portfolio and Execution Tables

### 9.1 `portfolio_snapshots`
Purpose:
Daily or intraday portfolio truth.

Suggested columns:
- `id` UUID PK
- `snapshot_timestamp` TIMESTAMP NOT NULL
- `mode` VARCHAR NOT NULL
- `cash_balance` NUMERIC(20,4)
- `gross_exposure` NUMERIC(20,4)
- `net_exposure` NUMERIC(20,4)
- `equity_value` NUMERIC(20,4)
- `drawdown_pct` NUMERIC(12,6)
- `notes` TEXT
- `created_at` TIMESTAMP NOT NULL
- `updated_at` TIMESTAMP NOT NULL

### 9.2 `positions`
Purpose:
Current and historical position records.

Suggested columns:
- `id` UUID PK
- `security_id` UUID FK -> securities.id
- `opened_at` TIMESTAMP NOT NULL
- `closed_at` TIMESTAMP
- `status` VARCHAR NOT NULL
- `entry_price` NUMERIC(18,6)
- `exit_price` NUMERIC(18,6)
- `quantity` NUMERIC(20,6)
- `cost_basis` NUMERIC(20,4)
- `market_value` NUMERIC(20,4)
- `unrealized_pnl` NUMERIC(20,4)
- `realized_pnl` NUMERIC(20,4)
- `strategy_id` UUID FK -> strategies.id
- `thesis_snapshot_json` JSONB
- `created_at` TIMESTAMP NOT NULL
- `updated_at` TIMESTAMP NOT NULL

### 9.3 `orders`
Purpose:
Order intent and submission tracking.

Suggested columns:
- `id` UUID PK
- `broker_order_ref` VARCHAR
- `security_id` UUID FK -> securities.id
- `position_id` UUID FK -> positions.id
- `order_timestamp` TIMESTAMP NOT NULL
- `order_type` VARCHAR NOT NULL
- `side` VARCHAR NOT NULL
- `quantity` NUMERIC(20,6)
- `notional_amount` NUMERIC(20,4)
- `limit_price` NUMERIC(18,6)
- `stop_price` NUMERIC(18,6)
- `status` VARCHAR NOT NULL
- `idempotency_key` VARCHAR
- `decision_snapshot_json` JSONB
- `created_at` TIMESTAMP NOT NULL
- `updated_at` TIMESTAMP NOT NULL

### 9.4 `fills`
Purpose:
Execution fills and reconciliation.

Suggested columns:
- `id` UUID PK
- `order_id` UUID FK -> orders.id
- `fill_timestamp` TIMESTAMP NOT NULL
- `fill_quantity` NUMERIC(20,6)
- `fill_price` NUMERIC(18,6)
- `fees` NUMERIC(20,4)
- `liquidity_flag` VARCHAR
- `created_at` TIMESTAMP NOT NULL
- `updated_at` TIMESTAMP NOT NULL

### 9.5 `risk_events`
Purpose:
Captured risk breaches or warnings.

Suggested columns:
- `id` UUID PK
- `event_timestamp` TIMESTAMP NOT NULL
- `event_type` VARCHAR NOT NULL
- `severity` VARCHAR NOT NULL
- `security_id` UUID FK -> securities.id
- `position_id` UUID FK -> positions.id
- `details_json` JSONB
- `resolved_at` TIMESTAMP
- `created_at` TIMESTAMP NOT NULL
- `updated_at` TIMESTAMP NOT NULL

## 10. Evaluation Tables

### 10.1 `evaluation_runs`
Purpose:
Top-level daily or periodic grading record.

Suggested columns:
- `id` UUID PK
- `run_timestamp` TIMESTAMP NOT NULL
- `evaluation_period_start` DATE
- `evaluation_period_end` DATE
- `mode` VARCHAR NOT NULL
- `status` VARCHAR NOT NULL
- `benchmark_set` VARCHAR
- `created_at` TIMESTAMP NOT NULL
- `updated_at` TIMESTAMP NOT NULL

### 10.2 `evaluation_metrics`
Purpose:
Metric store for each evaluation run.

Suggested columns:
- `id` UUID PK
- `evaluation_run_id` UUID FK -> evaluation_runs.id
- `metric_key` VARCHAR NOT NULL
- `metric_value` NUMERIC(20,8)
- `metric_text` TEXT
- `created_at` TIMESTAMP NOT NULL
- `updated_at` TIMESTAMP NOT NULL

Examples:
- net_pnl
- realized_pnl
- unrealized_pnl
- max_drawdown
- hit_rate
- turnover
- profit_factor
- sharpe_like
- sortino_like

### 10.3 `performance_attribution`
Purpose:
Stores attribution slices for performance analysis.

Suggested columns:
- `id` UUID PK
- `evaluation_run_id` UUID FK -> evaluation_runs.id
- `attribution_type` VARCHAR NOT NULL
- `attribution_key` VARCHAR NOT NULL
- `attribution_value` NUMERIC(20,8)
- `details_json` JSONB
- `created_at` TIMESTAMP NOT NULL
- `updated_at` TIMESTAMP NOT NULL

Examples:
- sector
- theme
- strategy_family
- catalyst_class
- news_policy_influence
- rumor_influence

## 11. Self-Improvement Tables

### 11.1 `improvement_proposals`
Purpose:
Candidate changes generated by the self-improvement engine.

Suggested columns:
- `id` UUID PK
- `proposal_timestamp` TIMESTAMP NOT NULL
- `proposal_type` VARCHAR NOT NULL
- `target_component` VARCHAR NOT NULL
- `baseline_version` VARCHAR
- `candidate_version` VARCHAR
- `proposal_summary` TEXT
- `expected_benefit` TEXT
- `status` VARCHAR NOT NULL
- `created_at` TIMESTAMP NOT NULL
- `updated_at` TIMESTAMP NOT NULL

### 11.2 `improvement_evaluations`
Purpose:
Benchmark results for candidate proposals.

Suggested columns:
- `id` UUID PK
- `proposal_id` UUID FK -> improvement_proposals.id
- `evaluation_timestamp` TIMESTAMP NOT NULL
- `result_status` VARCHAR NOT NULL
- `baseline_metrics_json` JSONB
- `candidate_metrics_json` JSONB
- `comparison_summary` TEXT
- `guardrail_passed` BOOLEAN
- `created_at` TIMESTAMP NOT NULL
- `updated_at` TIMESTAMP NOT NULL

### 11.3 `promoted_versions`
Purpose:
Registry of accepted configs/models/prompts.

Suggested columns:
- `id` UUID PK
- `component_type` VARCHAR NOT NULL
- `component_key` VARCHAR NOT NULL
- `version_label` VARCHAR NOT NULL
- `promotion_timestamp` TIMESTAMP NOT NULL
- `promotion_reason` TEXT
- `rollback_reference` VARCHAR
- `created_at` TIMESTAMP NOT NULL
- `updated_at` TIMESTAMP NOT NULL

## 12. Continuity and Audit Tables

### 12.1 `decision_audit`
Purpose:
Structured audit log for major project/system decisions.

Suggested columns:
- `id` UUID PK
- `decision_timestamp` TIMESTAMP NOT NULL
- `decision_type` VARCHAR NOT NULL
- `summary` TEXT NOT NULL
- `details_json` JSONB
- `source_ref` TEXT
- `created_at` TIMESTAMP NOT NULL
- `updated_at` TIMESTAMP NOT NULL

### 12.2 `session_checkpoints`
Purpose:
Structured mirror of session handoff log information.

Suggested columns:
- `id` UUID PK
- `checkpoint_timestamp` TIMESTAMP NOT NULL
- `capacity_trigger` VARCHAR
- `objective` TEXT
- `current_stage` VARCHAR
- `current_status` TEXT
- `files_changed_json` JSONB
- `qa_status` VARCHAR
- `open_items_json` JSONB
- `risks_json` JSONB
- `continuity_notes` TEXT
- `created_at` TIMESTAMP NOT NULL
- `updated_at` TIMESTAMP NOT NULL

## 13. Minimum Indexing Priorities

At minimum, index:
- `securities.ticker`
- `daily_market_bars (security_id, trade_date)`
- `source_events.event_timestamp`
- `security_feature_values (security_id, as_of_timestamp)`
- `security_signals (signal_run_id, security_id)`
- `ranked_opportunities (ranking_run_id, rank_position)`
- `positions.status`
- `orders.status`
- `fills.fill_timestamp`
- `evaluation_runs.run_timestamp`
- `improvement_proposals.status`

## 14. Snapshot and Reproducibility Rules

The system must be able to reconstruct:
- what the portfolio looked like
- what signals existed
- what data influenced a decision
- what model/config version was active
- what improvement proposal changed behavior

Therefore:
- do not overwrite critical historical rows without preserving traceability
- store version references in ranking, signals, and evaluations
- preserve thesis and decision snapshots for trades

## 15. Initial Migration Order

Create in this order:
1. reference tables
2. source tables
3. market-data tables
4. feature tables
5. strategy/signal/ranking tables
6. portfolio/execution tables
7. evaluation tables
8. self-improvement tables
9. continuity/audit tables

## 16. MVP Implementation Guidance

For MVP, it is acceptable to start with a reduced subset:

Required first tables:
- `securities`
- `themes`
- `security_themes`
- `sources`
- `source_events`
- `daily_market_bars`
- `features`
- `security_feature_values`
- `strategies`
- `signal_runs`
- `security_signals`
- `ranking_runs`
- `ranked_opportunities`
- `portfolio_snapshots`
- `positions`
- `orders`
- `fills`
- `evaluation_runs`
- `evaluation_metrics`
- `improvement_proposals`
- `improvement_evaluations`

Then expand.

## 17. Final Directive

Favor explicitness over shortcuts.
The database must make APIS explainable, reproducible, and auditable.

If a schema simplification makes the system harder to audit or resume, it is the wrong simplification.
