# APIS_MASTER_SPEC.md
Version: 2.0
Project: Autonomous Portfolio Intelligence System (APIS)
Owner: Personal use
Status: Governing build specification

## 1. Purpose

Build a disciplined autonomous portfolio management system for U.S. equities that can research, rank, paper trade, evaluate performance daily, and improve itself in a controlled way before any guarded live deployment.

This project is not a hype demo. It is a persistent operating system for portfolio decision-making.

The platform must be designed to:
- ingest market, macro, political, sector, company, news, and rumor/chatter inputs
- generate stock ideas across low-priced stocks, small caps, mid caps, large caps, and mega caps
- classify ideas by short-term, swing, medium-term, and long-term horizon
- decide buy / hold / trim / sell / avoid
- manage portfolio cash, sizing, exposure, and exits
- grade itself daily based on gains, losses, drawdowns, and benchmark-relative performance
- self-improve in a controlled, auditable, benchmarked way

## 2. Project-Specific Product Vision

APIS should behave like a hybrid of:
- an institutional research engine
- a policy / macro / politics signal interpreter
- a portfolio risk manager
- an execution system
- a daily evaluator
- a controlled self-improvement system

APIS must specifically reason about themes and spillovers such as:
- AI growth and second-order beneficiaries
- semiconductors, compute, data centers, cooling, power demand, networking, memory, and hyperscaler capex
- defense spending and geopolitical escalation
- tariffs, reshoring, industrial policy, and supply-chain relocation
- energy policy, drilling, LNG, pipelines, utilities, nuclear, and grid load growth
- cybersecurity spending
- healthcare innovation and regulatory catalysts
- rates, inflation, labor, and credit sensitivity
- analyst revisions, earnings beats/misses, guidance changes
- political rhetoric, executive actions, agency rules, sanctions, trade restrictions
- news credibility and rumor propagation

Example project-specific behavior:
If AI adoption is expected to expand, APIS must not only identify obvious AI leaders but also second-order beneficiaries such as suppliers, infrastructure, power, networking, cooling, storage, or software vendors that may benefit downstream.

## 3. Non-Negotiable Principles

### 3.1 Safety and Rollout Discipline
The system must launch in this order:
1. Research only
2. Historical backtest
3. Paper trading
4. Human-approved live trading
5. Restricted autonomous live trading

Do not skip stages.

### 3.2 Controlled Self-Improvement
The system may optimize:
- feature weights
- ranking weights
- prompt structures
- source credibility weighting
- thresholds
- timing rules
- position-sizing parameters
- exit parameters
- regime classification logic

The system may not:
- silently remove risk controls
- promote untested logic directly to live trading
- mutate critical production code without rollback and validation
- auto-raise risk limits
- auto-expand scope into options, leverage, or unrestricted shorting without an explicit spec revision

### 3.3 Explainability
Every recommendation and trade decision must state:
- what action is proposed
- why it is proposed
- supporting evidence
- disconfirming evidence
- catalyst class
- confidence level
- expected horizon
- expected risk
- portfolio impact

### 3.4 Auditability
Every decision must be logged with:
- timestamp
- strategy family
- signal snapshot
- source evidence
- confidence score
- risk score
- sizing rationale
- execution outcome
- post-trade evaluation

### 3.5 Continuity
The build system must preserve project continuity across sessions through mandatory handoff logs, state files, decision logs, and resumable instructions.

The system must treat continuity as a first-class requirement, not a convenience.

## 4. Initial Scope

### 4.1 In Scope for MVP
- U.S. equities
- long-only
- no margin
- no leverage
- no options
- no futures
- paper trading first
- maximum 10 active positions
- recommendation engine
- portfolio engine
- risk engine
- daily grading
- controlled self-improvement
- API and/or simple dashboard

### 4.2 Explicitly Out of Scope for MVP
- unrestricted autonomous live trading
- options strategies
- leveraged ETFs as core strategy
- high-frequency trading
- self-modifying core code in production
- unbounded web scraping without source-quality controls

## 5. Operating Modes

### 5.1 Research Mode
Produces ranked ideas, theses, expected horizon, and simulated actions only.

### 5.2 Backtest Mode
Runs historical simulations with transaction costs, slippage assumptions, liquidity rules, and exposure caps.

### 5.3 Paper Trading Mode
Uses current data and paper broker execution to simulate real operations.

### 5.4 Human-Approved Live Mode
Proposes trades; user must approve before execution.

### 5.5 Restricted Autonomous Live Mode
Only after passing strict validation gates and only with hard limits.

## 6. High-Level Architecture

### 6.1 Major Services
- Data Ingestion Service
- Market Data Service
- News / Politics / Macro Intelligence Service
- Theme and Relationship Engine
- Rumor / Chatter Scoring Service
- Feature Store
- Signal Engine
- Ranking Engine
- Portfolio Construction Engine
- Risk Engine
- Broker Adapter Layer
- Execution Engine
- Evaluation Engine
- Experiment Registry
- Daily Review Engine
- Self-Improvement Engine
- Notification / Reporting Engine
- API / Dashboard

### 6.2 Mandatory Separation of Concerns
Keep these independent:
- signal generation
- recommendation ranking
- risk checks
- execution
- evaluation
- self-improvement
- session continuity and handoff logging

## 7. Data Domains

### 7.1 Market Data
- daily OHLCV
- intraday where available and justified
- corporate actions
- float, market cap, average volume
- volatility metrics
- gaps, trend, momentum, and liquidity metrics

### 7.2 Fundamentals
- growth
- margins
- cash flow
- leverage
- valuation ratios
- earnings surprise history
- guidance revisions
- analyst estimate changes

### 7.3 News, Politics, and Macro
- policy changes
- tariffs and sanctions
- executive orders and rhetoric
- agency and regulatory developments
- commodity shocks
- labor/inflation/rate signals
- geopolitics and defense developments
- industry-specific regulatory moves

### 7.4 Theme Mapping
Map companies to themes such as:
- AI infrastructure
- semiconductors
- cloud and software
- data center construction
- power/utilities
- cybersecurity
- reshoring/manufacturing
- defense
- energy
- healthcare innovation

### 7.5 Rumor and Chatter
Rumors may affect score inputs, but:
- must receive lower reliability weighting than verified sources
- must decay quickly
- must never override hard risk controls
- must remain traceable in decision logs

## 8. Signal and Scoring Framework

Each security should receive:
- composite opportunity score
- confidence score
- downside risk score
- liquidity score
- catalyst score
- time-horizon classification
- valuation sensitivity score
- macro/policy fit score
- portfolio fit score

Signal families should include:
- momentum/trend
- valuation
- earnings revisions
- AI/theme exposure
- policy tailwind / headwind
- macro sensitivity
- sentiment/news shift
- quality/balance sheet
- unusual activity
- liquidity quality

## 9. Portfolio Construction Rules

The portfolio engine must determine:
- whether to enter
- target size
- whether to add
- whether to trim
- whether to exit
- whether to raise cash

Initial mandatory rules:
- max 10 positions
- max single-name allocation
- max sector allocation
- max thematic allocation
- cap low-liquidity exposure
- confidence-adjusted sizing
- volatility-aware sizing
- no averaging down without explicit rule support
- no new positions after daily loss-limit breach
- no entry if thesis quality is high but liquidity is unacceptable

## 10. Risk Engine

### 10.1 Hard Controls
- daily realized loss limit
- daily total loss limit
- weekly drawdown limit
- monthly drawdown limit
- max position size
- max number of new positions per day
- max low-float / low-liquidity exposure
- kill switch
- duplicate-order prevention
- stale-price and stale-signal prevention

### 10.2 Exit Logic
- thesis invalidation
- time-window expiration
- stop or volatility-based exit
- downgrade on evidence deterioration
- trim on overconcentration
- profit capture when reward/risk degrades

## 11. Execution Layer

### 11.1 Broker Strategy
Use a broker abstraction interface first.

Build in this order:
1. paper broker simulator
2. Alpaca paper-trading adapter
3. architecture-ready IBKR adapter
4. optional future Schwab adapter

### 11.2 Order Protections
- idempotent order submission
- order reconciliation
- fill tracking
- hours checks
- account-state sync
- pre-trade risk validation
- slippage monitoring

## 12. Performance Evaluation

### 12.1 Daily Metrics
- net P&L
- realized P&L
- unrealized P&L
- hit rate
- average winner
- average loser
- turnover
- cash ratio
- active exposure
- sector concentration
- theme concentration

### 12.2 Risk Metrics
- max drawdown
- rolling drawdown
- volatility
- Sharpe-like metric
- Sortino-like metric
- profit factor
- exposure stability
- tail-event sensitivity

### 12.3 Benchmarking
Compare against:
- SPY
- QQQ
- IWM
- cash baseline
- internal equal-weight basket where relevant

### 12.4 Attribution
Attribute performance by:
- strategy family
- theme
- sector
- catalyst class
- time horizon
- policy/news influence
- rumor influence
- sizing quality
- timing quality
- exit quality

## 13. Controlled Self-Improvement Framework

### 13.1 What the System May Improve
- prompts
- feature transformations
- source weights
- ranking thresholds
- confidence calibration
- risk-adjusted sizing formulas
- holding-period rules
- regime classifier behavior

### 13.2 What It May Not Improve Without Explicit Approval
- core safety rules
- live-trading permissions
- max capital allocation rules
- scope expansion into options, leverage, or unrestricted shorting
- destructive database or architecture changes

### 13.3 Improvement Loop
Daily:
1. ingest prior results
2. run attribution
3. identify whether mistakes came from signal quality, source weighting, timing, sizing, exits, or regime mismatch
4. propose changes
5. test changes against rolling baselines
6. compare to control
7. promote only when risk-adjusted results improve and guardrails hold
8. log accepted and rejected changes

## 14. Repository Layout

```text
/apis
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
  /research
    /experiments
    /benchmarks
  /state
    ACTIVE_CONTEXT.md
    SESSION_HANDOFF_LOG.md
    DECISION_LOG.md
    CHANGELOG.md
    NEXT_STEPS.md
  /tests
    /unit
    /integration
    /e2e
    /simulation
  /infra
    /docker
    /db
    /deploy
    /monitoring
  /docs
    /specs
    /runbooks
    /decision_logs
  /scripts
  /config
  README.md
```

## 15. Required State Files

These files are mandatory and must be actively maintained by the build tool:
- `state/ACTIVE_CONTEXT.md`
- `state/SESSION_HANDOFF_LOG.md`
- `state/DECISION_LOG.md`
- `state/NEXT_STEPS.md`
- `state/CHANGELOG.md`

Their purpose:
- ACTIVE_CONTEXT.md = current truth of the project
- SESSION_HANDOFF_LOG.md = chronological continuity entries
- DECISION_LOG.md = important architecture/product/risk decisions
- NEXT_STEPS.md = ordered remaining work
- CHANGELOG.md = concrete changes made

## 16. Testing Requirements

### 16.1 Mandatory Test Layers
- unit tests
- integration tests
- end-to-end tests
- simulation tests
- smoke tests for scheduled jobs
- evaluation consistency tests
- regression tests for promoted changes

### 16.2 Mandatory QA Gate
After any meaningful change:
1. run tests relevant to the change
2. run requirement-compliance review
3. run risk-control review
4. run performance sanity review
5. log QA outcome
6. do not declare completion until QA status is PASS or known remaining risks are explicitly listed

## 17. Daily Review Report

Each day the system must produce:
- portfolio snapshot
- best and worst contributors
- trades entered/exited
- active theses
- new themes detected
- macro/political changes
- mistakes made
- proposed improvements
- whether those improvements passed testing
- current risk status
- next recommended actions

## 18. Initial Build Phases

### Phase 0
- repo scaffolding
- state file scaffolding
- architecture and config
- logging
- testing harness

### Phase 1
- stock universe definition
- ingestion framework
- baseline signal engine
- ranking output
- thesis generation

### Phase 2
- backtest engine
- benchmark comparison
- report generation

### Phase 3
- paper trading engine
- portfolio state sync
- evaluation engine
- daily grading

### Phase 4
- self-improvement proposal system
- challenger/baseline framework
- promotion rules

### Phase 5
- human-approved live mode
- live adapter integration
- stronger observability
- kill switch flow

## 19. Mandatory Development Standards

- typed Python where practical
- config-driven architecture
- no hidden magic values
- versioned prompts and thresholds
- isolated, testable modules
- explicit logs for every critical action
- reversible promotions where possible
- continuity logging is required, not optional

## 20. Final Directive

Build APIS as a disciplined portfolio operating system.

Priority order:
1. correctness
2. risk discipline
3. continuity
4. observability
5. reliability
6. explainability
7. performance
8. iteration speed
9. UI polish

Do not cut corners on:
- risk engine
- evaluation framework
- self-improvement controls
- broker abstraction
- continuity and session handoff logging


## 21. Tooling and Plugin Utilization Policy

The build agent must make full use of all relevant tools, integrations, plugins, SDKs, libraries, frameworks, validation utilities, and automation helpers available in its working environment when those tools materially improve:
- build quality
- implementation speed
- code correctness
- testing coverage
- validation depth
- observability
- reproducibility
- deployment readiness

Rules:
- use all relevant available tools rather than manually reinventing what a reliable tool already provides
- prefer high-signal tools that improve implementation, testing, linting, type checking, schema validation, migration handling, monitoring, QA, and deployment discipline
- install needed packages, libraries, SDKs, and plugins when required for the project, provided they are appropriate, maintainable, and justified
- do not avoid a useful tool merely for convenience
- do not add unnecessary tooling bloat; every tool should serve a clear purpose
- document important tooling choices in `state/DECISION_LOG.md` and `state/CHANGELOG.md`

Examples of relevant tool categories:
- package/dependency managers
- formatters and linters
- type checkers
- test runners
- coverage tools
- migration tools
- API schema/documentation tools
- task runners
- Docker/dev environment tooling
- observability and logging tools
- broker SDKs
- data connectors
- backtesting helpers when appropriate
- QA and validation tooling

The project should use the best relevant tools available to the build environment, not the fewest.
