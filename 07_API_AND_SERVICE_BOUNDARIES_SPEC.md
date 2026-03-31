# API_AND_SERVICE_BOUNDARIES_SPEC.md
Version: 1.0
Project: Autonomous Portfolio Intelligence System (APIS)
Status: API, service ownership, and workflow boundary specification

## 1. Purpose

This file defines:
- service ownership boundaries
- inter-service responsibilities
- internal workflow handoffs
- initial API surface
- background jobs
- event and scheduling expectations
- what must not be coupled together

Its purpose is to stop APIS from turning into a tangled codebase where strategy logic, broker logic, risk rules, evaluation, and reporting all blur together.

This file is a governing architecture constraint for the project.

It works alongside:
- `APIS_MASTER_SPEC.md`
- `SESSION_CONTINUITY_AND_EXECUTION_PROTOCOL.md`
- `APIS_BUILD_RUNBOOK.md`
- `INITIAL_REPO_STRUCTURE.md`
- `DATABASE_AND_SCHEMA_SPEC.md`

## 2. Core Boundary Principles

### 2.1 Separation of Concerns
The following concerns must remain separate:
- data ingestion
- signal generation
- ranking
- portfolio construction
- risk validation
- execution
- evaluation
- reporting
- self-improvement
- continuity logging

### 2.2 No Direct Bypass Rule
No strategy or signal component may:
- place broker orders directly
- bypass risk checks
- overwrite portfolio truth directly
- promote its own configuration
- edit continuity state without going through defined utilities

### 2.3 Explainability Preservation
Any service that transforms recommendations must preserve enough context for downstream explainability.

That means:
- upstream scores must remain inspectable
- ranking transformations must remain inspectable
- risk overrides must remain inspectable
- execution blocks must remain inspectable

### 2.4 Controlled Side Effects
Only designated services may create side effects:
- execution engine may submit orders
- reporting service may publish reports
- continuity service may update state files
- self-improvement service may create proposals, but not self-promote without policy gates

## 3. Service Ownership Model

## 3.1 `data_ingestion`
Owns:
- retrieval of raw source data
- source normalization
- source metadata capture
- ingestion scheduling inputs
- source reliability tagging inputs

Does not own:
- final feature engineering
- ranking
- portfolio logic
- risk logic
- trading decisions

Inputs:
- source configs
- source registry
- scheduler triggers

Outputs:
- normalized source records
- ingestion status
- source error records

## 3.2 `market_data`
Owns:
- price/bar normalization
- liquidity metrics
- technical indicator calculations
- corporate-action-adjusted series where used
- market calendar helpers

Does not own:
- trade decisions
- ranking
- broker logic

Inputs:
- raw/staged market data

Outputs:
- curated bars
- derived liquidity and volatility metrics
- price-based feature inputs

## 3.3 `news_intelligence`
Owns:
- parsing and summarizing news items
- source reliability and credibility tagging
- extraction of market-relevant entities and implications
- identification of verified vs unverified information

Does not own:
- final trading recommendations
- execution
- direct portfolio changes

Inputs:
- normalized source events

Outputs:
- structured news insights
- credibility-weighted interpretations
- security/event links

## 3.4 `macro_policy_engine`
Owns:
- interpretation of policy, politics, regulation, tariffs, sanctions, macro developments, and geopolitical shifts
- mapping those developments into sector/theme/security implications
- structured policy-factor outputs

Does not own:
- execution
- direct ranking output without going through ranking pipeline

Inputs:
- source events
- curated macro/policy data
- theme maps

Outputs:
- policy signals
- macro regime indicators
- sector/theme implication objects

## 3.5 `theme_engine`
Owns:
- company-to-theme mapping
- first-order and second-order beneficiary logic
- thematic dependency relationships

Project-specific requirement:
This service must support APIS’s goal of identifying not only direct AI winners but also second-order beneficiaries such as suppliers, networking, storage, utilities, cooling, power infrastructure, and other downstream beneficiaries.

Does not own:
- order placement
- direct portfolio mutations

Inputs:
- securities
- themes
- source intelligence
- feature/context inputs

Outputs:
- security-theme mappings
- thematic exposure scores
- beneficiary relationship records

## 3.6 `rumor_scoring`
Owns:
- lower-confidence chatter ingestion interpretations
- explicit reliability discounting
- decay rules
- rumor contribution scoring

Does not own:
- final recommendation authority
- risk overrides

Inputs:
- low-confidence source events
- credibility rules

Outputs:
- rumor influence scores
- confidence penalties
- decay-adjusted influence values

## 3.7 `feature_store`
Owns:
- engineered feature registration
- feature persistence
- time-stamped feature retrieval
- feature version traceability

Does not own:
- final ranking
- trading decisions
- execution

Inputs:
- market data
- news intelligence
- policy engine outputs
- theme scores
- rumor scores

Outputs:
- versioned feature values for downstream consumers

## 3.8 `signal_engine`
Owns:
- raw signal generation by strategy family
- signal-level explanation objects
- confidence and risk sub-scores at the signal layer

Does not own:
- final portfolio decision
- broker execution
- final sizing authority

Inputs:
- feature values
- strategy configs

Outputs:
- security-level signal outputs
- signal run records

## 3.9 `ranking_engine`
Owns:
- merging and weighting signal outputs
- recommendation ranking
- action suggestion generation
- horizon classification
- portfolio-fit pre-scores

Does not own:
- final position sizing
- final pre-trade risk approval
- execution

Inputs:
- signal outputs
- ranking configs
- portfolio context when needed for fit

Outputs:
- ranked opportunities
- recommended actions
- thesis summaries

## 3.10 `portfolio_engine`
Owns:
- portfolio state models
- target allocations
- candidate position sizing proposals
- add/trim/exit proposal generation
- cash/exposure accounting

Does not own:
- hard risk approval
- order submission

Inputs:
- ranked opportunities
- current portfolio state
- allocation rules

Outputs:
- proposed portfolio actions
- target size proposals
- updated portfolio snapshots after validated actions

## 3.11 `risk_engine`
Owns:
- pre-trade rule validation
- portfolio concentration checks
- drawdown limits
- loss limits
- liquidity constraints
- kill switch decisions
- blocked-action reasons

This service is a hard gatekeeper.

Does not own:
- idea generation
- signal generation
- broker execution

Inputs:
- portfolio action proposals
- current portfolio state
- risk configs
- market/liquidity context

Outputs:
- pass/fail decisions
- warnings
- adjusted allowable sizing ranges
- risk event records

## 3.12 `execution_engine`
Owns:
- translation of approved actions into orders
- idempotent order submission
- order/fill reconciliation orchestration
- broker interaction through adapters only
- execution status updates

Does not own:
- strategy logic
- ranking logic
- risk policy definition

Inputs:
- risk-approved actions
- broker adapter
- market-hours context
- order settings

Outputs:
- orders
- fills
- execution events
- reconciliation updates

## 3.13 `evaluation_engine`
Owns:
- daily grading
- benchmark comparisons
- risk-adjusted metrics
- performance attribution
- trade-quality review
- evaluation records

Does not own:
- order placement
- self-promotion of changes

Inputs:
- portfolio snapshots
- positions
- orders/fills
- benchmark data
- historical run data

Outputs:
- evaluation runs
- evaluation metrics
- attribution results

## 3.14 `self_improvement`
Owns:
- proposal generation for controlled changes
- challenger-vs-baseline evaluation requests
- candidate config/model/prompt comparisons
- improvement recommendation logs

Does not own:
- direct live promotion without policy checks
- direct mutation of production logic
- broker activity

Inputs:
- evaluation results
- attribution
- baseline versions
- config/model registries

Outputs:
- improvement proposals
- evaluation requests
- promotion recommendations

## 3.15 `reporting`
Owns:
- daily reports
- scorecards
- summaries
- admin/operator outputs
- human-readable rationale packages

Does not own:
- trade execution
- signal generation
- direct risk enforcement

Inputs:
- rankings
- portfolio state
- evaluation results
- self-improvement results

Outputs:
- daily review report
- recommendation summaries
- performance summaries
- alert-ready payloads

## 3.16 `continuity`
Owns:
- state-file formatting helpers
- checkpoint generation helpers
- change summaries
- continuity compliance checks

Does not own:
- trading decisions
- ranking
- execution

Inputs:
- current project/build status
- files changed
- QA outputs
- next steps
- major decisions

Outputs:
- updated markdown state files
- checkpoint entries
- continuity alerts

## 4. Required End-to-End Workflow Boundaries

## 4.1 Research / Recommendation Workflow
Flow:
1. `data_ingestion`
2. `market_data`
3. `news_intelligence`
4. `macro_policy_engine`
5. `theme_engine`
6. `rumor_scoring`
7. `feature_store`
8. `signal_engine`
9. `ranking_engine`
10. `reporting`

At this stage:
- no broker execution
- no portfolio mutation required
- output is ranked recommendations and rationale

## 4.2 Portfolio Construction Workflow
Flow:
1. `ranking_engine`
2. `portfolio_engine`
3. `risk_engine`
4. `reporting`

At this stage:
- position proposals may be created
- but nothing is sent to a broker unless execution is explicitly triggered later

## 4.3 Paper / Live Execution Workflow
Flow:
1. `portfolio_engine`
2. `risk_engine`
3. `execution_engine`
4. broker adapter
5. `execution_engine` reconciliation
6. `portfolio_engine` state refresh
7. `evaluation_engine`
8. `reporting`

Rule:
No step may skip `risk_engine`.

## 4.4 Daily Evaluation Workflow
Flow:
1. portfolio/order/fill data collection
2. `evaluation_engine`
3. `reporting`
4. `self_improvement`
5. continuity updates if project/build work occurred

## 4.5 Controlled Self-Improvement Workflow
Flow:
1. `evaluation_engine` produces results
2. `self_improvement` creates proposal
3. challenger/baseline evaluation runs
4. guardrail checks
5. promotion recommendation recorded
6. only approved mechanism updates version registry

Rule:
No strategy or model promotes itself directly.

## 5. Internal APIs vs External APIs

### 5.1 Internal APIs
Internal service interfaces may be:
- Python service calls
- internal message queues
- job payloads
- repository-layer access patterns

Use the simplest architecture that remains clear and testable.
Do not over-microservice the MVP.

### 5.2 External APIs
The public-facing API should be limited, stable, and explainable.
Start small.

## 6. Initial External API Surface (MVP)

The MVP API should expose read-heavy endpoints first, with limited action endpoints.

Base path suggestion:
`/api/v1`

## 6.1 Health and System Endpoints

### `GET /health`
Purpose:
Basic application health check.

Response example:
```json
{
  "status": "ok",
  "service": "api",
  "timestamp": "2026-03-17T12:00:00Z"
}
```

### `GET /system/status`
Purpose:
Return current system mode and high-level operating status.

Should include:
- environment
- mode (research/backtest/paper/live-approval/restricted-live)
- latest ranking run id if available
- latest evaluation run id if available
- kill switch status

## 6.2 Recommendation Endpoints

### `GET /recommendations/latest`
Purpose:
Return the latest ranked opportunities.

Should support filters such as:
- horizon
- sector
- theme
- min_score
- limit

Response should include:
- ticker
- rank
- recommended_action
- composite_score
- confidence_score when available
- target_horizon
- thesis_summary
- disconfirming_factors
- sizing_hint_pct

### `GET /recommendations/{ticker}`
Purpose:
Return the latest recommendation details for one security.

Should include:
- latest scores
- theme mapping
- key catalysts
- risk flags
- rationale summary
- recent rank history if available

## 6.3 Portfolio Endpoints

### `GET /portfolio`
Purpose:
Return current portfolio state.

Should include:
- cash balance
- equity value
- gross/net exposure
- active positions
- drawdown metrics
- concentration indicators

### `GET /portfolio/positions`
Purpose:
Return current positions.

### `GET /portfolio/positions/{ticker}`
Purpose:
Return detailed position data and thesis snapshot.

## 6.4 Order / Action Review Endpoints

For MVP, keep execution endpoints tightly controlled.

### `GET /actions/proposed`
Purpose:
Return currently proposed portfolio actions awaiting approval or review.

### `POST /actions/review`
Purpose:
Approve or reject one or more proposed actions in human-approved mode.

Request example:
```json
{
  "action_ids": ["uuid-1", "uuid-2"],
  "decision": "approve",
  "note": "Approved after manual review"
}
```

Important:
This endpoint should only be active in approved operating modes.

## 6.5 Evaluation Endpoints

### `GET /evaluation/latest`
Purpose:
Return latest evaluation summary.

Should include:
- net P&L
- realized/unrealized P&L
- hit rate
- drawdown
- benchmark-relative performance
- attribution highlights

### `GET /evaluation/history`
Purpose:
Return historical evaluation summaries with date filters.

## 6.6 Reporting Endpoints

### `GET /reports/daily/latest`
Purpose:
Return the latest daily report.

### `GET /reports/daily/history`
Purpose:
Return historical daily reports.

## 6.7 Admin / Config Visibility Endpoints

### `GET /config/active`
Purpose:
Show active non-secret versions and identifiers.

Should include:
- ranking config version
- strategy config versions
- feature version label
- promoted model/prompt versions
- current mode

### `GET /risk/status`
Purpose:
Show current risk posture and any active warnings.

Should include:
- loss limit status
- kill switch state
- concentration warnings
- blocked action count

## 7. Deferred API Surface

Do not build these too early:
- broad public write APIs for arbitrary trade placement
- unrestricted config mutation endpoints
- auto-promotion endpoints without guardrails
- heavy dashboard customization APIs
- multi-user account APIs
- options or margin workflow endpoints

## 8. Suggested Internal Command / Job Interfaces

These are not necessarily public HTTP endpoints.
They may be worker jobs, service methods, or internal tasks.

## 8.1 Ingestion Jobs
- `run_market_data_ingestion`
- `run_news_ingestion`
- `run_macro_policy_ingestion`
- `run_source_normalization`

## 8.2 Signal / Ranking Jobs
- `run_feature_refresh`
- `run_signal_generation`
- `run_ranking_generation`

## 8.3 Portfolio / Risk Jobs
- `run_portfolio_rebalance_proposal`
- `run_pretrade_risk_validation`

## 8.4 Execution Jobs
- `submit_approved_actions`
- `reconcile_orders_and_fills`
- `refresh_broker_state`

## 8.5 Evaluation Jobs
- `run_daily_evaluation`
- `run_benchmark_comparison`
- `run_attribution_analysis`

## 8.6 Improvement Jobs
- `generate_improvement_proposals`
- `evaluate_candidate_config`
- `record_promotion_decision`

## 8.7 Reporting Jobs
- `generate_daily_report`
- `publish_operator_summary`

## 8.8 Continuity Jobs
- `verify_state_file_freshness`
- `append_session_checkpoint`
- `sync_decision_and_change_logs`

## 9. API Schema Guidelines

### 9.1 Response Rules
API responses should:
- be explicit
- avoid hidden magic fields
- expose version labels where relevant
- preserve explainability fields
- include timestamps

### 9.2 Error Rules
Errors should:
- be structured
- include reason codes
- include blocked-by component where relevant
- avoid vague messages

Example:
```json
{
  "error": {
    "code": "RISK_RULE_BLOCKED",
    "message": "Proposed position exceeds single-name concentration limit.",
    "source": "risk_engine"
  }
}
```

### 9.3 Mode Awareness
Endpoints that can trigger action must be mode-aware.
Example:
- in research mode, order-review approval endpoints should reject with a clear explanation
- in paper mode, action approval may create paper orders only

## 10. Service Communication Rules

### 10.1 Allowed Communication Patterns
Preferred MVP patterns:
- shared application service layer
- explicit service interfaces
- repository pattern for persistence
- background jobs for scheduled work

Do not introduce distributed complexity too early.

### 10.2 Forbidden Coupling
Do not allow:
- `signal_engine` importing broker adapters
- `ranking_engine` writing orders
- `execution_engine` inventing strategy logic
- `reporting` modifying portfolio state
- `self_improvement` writing directly to live configs without approval path

## 11. Security and Access Control Boundaries

Even for personal use, keep boundaries clean.

### 11.1 Public/Operator Distinction
Separate:
- read-only informational endpoints
- approval endpoints
- administrative visibility endpoints

### 11.2 Secret Handling
No endpoint should ever expose:
- broker secrets
- raw credentials
- private tokens
- unsafe internal secrets

### 11.3 Action Authorization
If the system later adds auth, action endpoints must require stronger permissions than read-only endpoints.

## 12. Initial Build Sequence for APIs and Boundaries

Build in this order:

### Phase A: Read APIs
1. `GET /health`
2. `GET /system/status`
3. `GET /recommendations/latest`
4. `GET /recommendations/{ticker}`
5. `GET /portfolio`
6. `GET /evaluation/latest`
7. `GET /reports/daily/latest`

### Phase B: Internal Jobs
1. feature refresh job
2. signal generation job
3. ranking generation job
4. daily evaluation job
5. daily report job

### Phase C: Controlled Review Actions
1. proposed actions retrieval
2. review/approve/reject endpoint
3. paper execution flow
4. reconciliation flow

### Phase D: Admin Visibility
1. config visibility
2. risk status
3. active warnings
4. latest improvement proposal summaries

## 13. Project-Specific Guardrails for APIS

For this project specifically:
- keep the MVP read-heavy and explanation-heavy
- prioritize recommendation and evaluation visibility over trade-trigger convenience
- make the AI/politics/theme logic inspectable
- make second-order beneficiary logic observable in outputs
- never let rumor scoring become an opaque black box
- keep manual review in the loop before any live-capable workflow
- preserve a clear paper-trading path before live execution

## 14. QA Requirements for API and Boundary Work

A boundary/API milestone is not complete unless it passes:
- route correctness tests
- schema validation tests
- mode-awareness tests
- risk-block propagation tests
- service-boundary review
- explainability field review
- continuity file updates

Questions to ask after each milestone:
1. Did any service boundary get blurred?
2. Can risk blocks be traced clearly?
3. Can recommendations still be explained end-to-end?
4. Did any endpoint expose unsafe mutation too early?
5. Were continuity files updated?

## 15. Final Directive

Build APIS with clean boundaries.

If a component becomes more convenient by bypassing architecture boundaries, do not do it.
That convenience will become technical debt fast.

The system must remain explainable, testable, auditable, and resumable across sessions.


## 16. Tooling, SDK, and Integration Rule

All services and apps should use the most relevant stable tools and official SDKs available for their responsibilities.

Examples:
- broker adapters should prefer official broker SDKs where practical
- database layers should use appropriate migration and schema tools
- API layers should use schema validation and documentation tooling
- worker/job layers should use appropriate scheduling or orchestration tooling
- QA should use linting, typing, testing, coverage, and validation tools
- observability should use logging/monitoring tools rather than ad hoc print-debugging alone

Do not force manual implementations where a reliable relevant tool clearly improves correctness, safety, or maintainability.
