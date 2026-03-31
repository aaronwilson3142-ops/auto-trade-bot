# INITIAL_REPO_STRUCTURE.md
Version: 1.0
Project: Autonomous Portfolio Intelligence System (APIS)
Status: Required repository and file structure specification

## 1. Purpose

This file defines the initial repository structure for APIS.
Its purpose is to prevent ad hoc folder creation, reduce architecture drift, and make the system predictable across sessions.

This file is subordinate to:
- `SESSION_CONTINUITY_AND_EXECUTION_PROTOCOL.md`
- `APIS_MASTER_SPEC.md`

But it is the governing source for repo layout, initial scaffolding, and file placement.

## 2. Top-Level Repository Layout

```text
/apis
  README.md
  pyproject.toml
  requirements.txt
  .env.example
  .gitignore

  /apps
    /api
    /dashboard
    /worker

  /services
    /data_ingestion
    /market_data
    /news_intelligence
    /macro_policy_engine
    /theme_engine
    /rumor_scoring
    /feature_store
    /signal_engine
    /ranking_engine
    /portfolio_engine
    /risk_engine
    /execution_engine
    /evaluation_engine
    /self_improvement
    /reporting
    /continuity

  /broker_adapters
    /base
    /paper
    /alpaca
    /ibkr
    /schwab

  /strategies
    /long_term
    /swing
    /event_driven
    /theme_rotation
    /ai_theme
    /policy_trade

  /models
    /prompts
    /configurations
    /registries

  /data
    /raw
    /staged
    /curated
    /snapshots
    /external_reference

  /state
    ACTIVE_CONTEXT.md
    NEXT_STEPS.md
    DECISION_LOG.md
    CHANGELOG.md
    SESSION_HANDOFF_LOG.md

  /research
    /experiments
    /benchmarks
    /notes

  /tests
    /unit
    /integration
    /e2e
    /simulation
    /fixtures

  /infra
    /docker
    /db
    /deploy
    /monitoring

  /docs
    /specs
    /runbooks
    /decision_logs
    /architecture
    /reports

  /scripts
  /config
```

## 3. Mandatory Top-Level Files

### 3.1 `README.md`
Must include:
- project summary
- architecture summary
- setup instructions
- operating modes
- safety constraints
- where the governing markdown files live

### 3.2 `pyproject.toml`
Must define:
- project metadata
- Python version
- core tooling
- linting/format/test tool config where practical

### 3.3 `requirements.txt`
May exist in addition to `pyproject.toml` if convenient, but do not allow package sprawl without purpose.

### 3.4 `.env.example`
Must define only non-secret placeholders such as:
- database URL placeholder
- redis URL placeholder
- broker key variable names
- feature flags
- environment names

Never commit real secrets.

### 3.5 `.gitignore`
Must include:
- virtual environments
- caches
- local data dumps
- secrets
- logs where appropriate
- notebook temp artifacts
- compiled Python outputs

## 4. App Layer Rules

### 4.1 `/apps/api`
Purpose:
- external API surface for ranked ideas, portfolio state, reports, health checks, and admin actions

Typical contents:
```text
/apps/api
  main.py
  routes/
  schemas/
  dependencies/
  middleware/
```

### 4.2 `/apps/dashboard`
Purpose:
- lightweight operator/admin dashboard
- not the primary focus early in MVP

Typical contents:
```text
/apps/dashboard
  app/
  assets/
```

### 4.3 `/apps/worker`
Purpose:
- scheduled jobs
- evaluation runs
- report generation
- ingestion jobs
- self-improvement jobs

Typical contents:
```text
/apps/worker
  main.py
  jobs/
  schedulers/
```

## 5. Service Layer Rules

Each service folder must represent a bounded responsibility.
Do not mix unrelated concerns inside one service.

### 5.1 Required Standard Service Layout
Each service should start with a structure like:

```text
/service_name
  __init__.py
  service.py
  models.py
  schemas.py
  config.py
  utils.py
  README.md
```

If a service becomes large, it may expand into:
```text
/service_name
  __init__.py
  service.py
  config.py
  domain/
  adapters/
  repositories/
  tests/
```

### 5.2 Service Responsibilities

#### `/services/data_ingestion`
Fetch, normalize, and stage raw source inputs.

#### `/services/market_data`
Market-price handling, liquidity metrics, technical calculations, and price normalization.

#### `/services/news_intelligence`
Processing of news, source tagging, credibility scoring, extraction of market-relevant implications.

#### `/services/macro_policy_engine`
Structured interpretation of policy, macro, regulation, tariffs, sanctions, and geopolitics.

#### `/services/theme_engine`
Maps companies to themes and identifies first-order and second-order beneficiaries.

#### `/services/rumor_scoring`
Handles lower-confidence chatter with explicit decay and reliability rules.

#### `/services/feature_store`
Stores derived features used by signals and ranking.

#### `/services/signal_engine`
Generates raw signal outputs.

#### `/services/ranking_engine`
Produces final ranked opportunities after combining signals and filters.

#### `/services/portfolio_engine`
Tracks holdings, target allocations, entries, trims, exits, and cash state.

#### `/services/risk_engine`
Applies pre-trade, post-trade, portfolio-wide, and drawdown rules.

#### `/services/execution_engine`
Turns approved decisions into broker actions.

#### `/services/evaluation_engine`
Calculates daily grading, risk metrics, benchmarking, and attribution.

#### `/services/self_improvement`
Generates and evaluates candidate changes under control rules.

#### `/services/reporting`
Produces daily scorecards, reports, and summaries.

#### `/services/continuity`
Owns state-file updates, checkpoint formatting, and session continuity utilities.

## 6. Broker Adapter Rules

### 6.1 `/broker_adapters/base`
Must contain the abstract broker interface and common domain models.

Expected files:
```text
/broker_adapters/base
  __init__.py
  adapter.py
  models.py
  exceptions.py
```

### 6.2 `/broker_adapters/paper`
Must be implemented before any live adapter.
This is the first operational broker.

### 6.3 `/broker_adapters/alpaca`
Paper and later guarded live integration path.

### 6.4 `/broker_adapters/ibkr`
Scaffold early if helpful, but do not make it a blocker for MVP paper trading.

### 6.5 `/broker_adapters/schwab`
Optional later extension.

## 7. Strategy Layer Rules

Strategies must not directly bypass portfolio, risk, or execution layers.

Each strategy folder should contain:
```text
/strategy_name
  __init__.py
  strategy.py
  config.py
  README.md
```

Initial strategy families:
- `long_term`
- `swing`
- `event_driven`
- `theme_rotation`
- `ai_theme`
- `policy_trade`

These are logical buckets, not permission to overbuild all of them immediately.

## 8. Models Layer Rules

### 8.1 `/models/prompts`
Versioned prompts for structured reasoning components.

### 8.2 `/models/configurations`
Versioned scoring/ranking/improvement configs.

### 8.3 `/models/registries`
Tracks promoted model/prompt/config versions.

Do not allow unversioned prompt sprawl.

## 9. Data Layer Rules

### 9.1 `/data/raw`
Untouched or lightly normalized source inputs.

### 9.2 `/data/staged`
Cleaned and standardized intermediate inputs.

### 9.3 `/data/curated`
Inputs ready for signals, ranking, and portfolio use.

### 9.4 `/data/snapshots`
Time-based copies used for reproducibility and backtesting.

### 9.5 `/data/external_reference`
Static or slow-changing reference datasets.

## 10. State Layer Rules

The `/state` folder is mandatory and operationally critical.

### Required files
- `ACTIVE_CONTEXT.md`
- `NEXT_STEPS.md`
- `DECISION_LOG.md`
- `CHANGELOG.md`
- `SESSION_HANDOFF_LOG.md`

The system must treat missing or stale state files as a project health issue.

## 11. Tests Layer Rules

### Required structure
```text
/tests
  /unit
  /integration
  /e2e
  /simulation
  /fixtures
```

### Rules
- every major service needs unit tests
- cross-service flows need integration tests
- scheduled workflows need end-to-end or simulation coverage
- risk and execution logic require especially strong test coverage

## 12. Infra Layer Rules

### `/infra/docker`
Docker assets.

### `/infra/db`
Migrations, schema helpers, and seed tools.

### `/infra/deploy`
Deployment and environment scripts.

### `/infra/monitoring`
Observability config, dashboards, or alert definitions.

## 13. Docs Layer Rules

### `/docs/specs`
Formal specifications.

### `/docs/runbooks`
Operator and build runbooks.

### `/docs/decision_logs`
Long-form design rationale if needed.

### `/docs/architecture`
Architecture diagrams and narratives.

### `/docs/reports`
Generated project summaries or milestone reports.

## 14. Config Layer Rules

The `/config` folder should contain structured config such as:
- environments
- scoring weights
- risk limits
- feature flags
- source reliability settings

Do not hardcode values when they belong in config.

## 15. Mandatory Scaffolding Sequence

When initializing the repo, create in this order:
1. top-level files
2. `/state` files
3. `/apps`
4. `/services`
5. `/broker_adapters`
6. `/tests`
7. `/config`
8. `/infra`
9. `/docs`
10. base QA/test setup

## 16. Repo Health Rules

The repo should fail quality review if:
- state files are missing
- service boundaries are ignored
- broker logic is mixed into strategy code
- risk logic is bypassed
- prompts/configs are unversioned
- tests are absent for critical modules
- continuity files are stale after major changes

## 17. Final Directive

Use this structure to reduce chaos.
Do not invent random folders unless there is a strong reason, and if a new folder is introduced, record it in:
- `state/DECISION_LOG.md`
- `state/CHANGELOG.md`
