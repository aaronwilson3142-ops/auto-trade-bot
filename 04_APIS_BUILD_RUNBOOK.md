# APIS_BUILD_RUNBOOK.md
Version: 1.0
Project: Autonomous Portfolio Intelligence System (APIS)
Status: Practical implementation and QA runbook

## 1. Purpose

This runbook converts the APIS spec into a practical build sequence with mandatory QA and continuity actions.

Use it alongside:
- `APIS_MASTER_SPEC.md`
- `SESSION_CONTINUITY_AND_EXECUTION_PROTOCOL.md`

## 2. Initial File Creation Order

Create these first:
1. `README.md`
2. `APIS_MASTER_SPEC.md`
3. `SESSION_CONTINUITY_AND_EXECUTION_PROTOCOL.md`
4. `state/ACTIVE_CONTEXT.md`
5. `state/NEXT_STEPS.md`
6. `state/DECISION_LOG.md`
7. `state/CHANGELOG.md`
8. `state/SESSION_HANDOFF_LOG.md`
9. base repo/app structure
10. test harness
11. config scaffolding

## 3. State File Minimum Content

### `state/ACTIVE_CONTEXT.md`
Must include:
- current phase
- current scope
- what modules exist
- what is next
- current restrictions
- current risks

### `state/NEXT_STEPS.md`
Must include:
- numbered build tasks
- blockers
- validation tasks
- handoff reminders

### `state/DECISION_LOG.md`
Must include:
- timestamp
- decision
- alternatives considered
- rationale
- consequences

### `state/CHANGELOG.md`
Must include:
- timestamp
- file/module change
- short description

### `state/SESSION_HANDOFF_LOG.md`
Must use the checkpoint template from the continuity protocol.

## 4. Recommended MVP Build Order

### Step 1: Foundation
- scaffold repo
- scaffold state files
- define configs
- define logging
- define environment strategy
- create BrokerAdapter interface
- create paper broker adapter

### Step 2: Research Engine
- define stock universe
- build data ingestion stubs
- build source reliability model
- build baseline feature pipeline
- build ranking output
- build thesis generator

### Step 3: Portfolio and Risk
- build portfolio state models
- build sizing logic
- build exposure rules
- build exits
- build kill switch

### Step 4: Evaluation
- build daily grading
- benchmark comparisons
- attribution engine
- daily report output

### Step 5: Self-Improvement
- build proposal generator
- challenger/baseline evaluator
- promotion rules
- improvement logs

### Step 6: Paper Trading
- integrate Alpaca paper or equivalent
- reconcile fills
- monitor slippage
- produce daily operational report

## 5. Mandatory QA Gates

### Gate A: After Scaffolding
Confirm:
- repo structure exists
- state files exist
- continuity protocol is being followed
- tests can run
- config loads cleanly

### Gate B: After Research Engine
Confirm:
- ranking pipeline runs
- outputs are explainable
- sources are tagged by reliability
- rumors are separated from verified facts

### Gate C: After Portfolio/Risk
Confirm:
- sizing and exposure rules work
- invalid trades are blocked
- exits are explainable
- limits are enforced

### Gate D: After Evaluation
Confirm:
- daily scorecard is generated
- benchmarks compare correctly
- drawdown metrics compute correctly
- attribution fields populate

### Gate E: After Self-Improvement
Confirm:
- proposals are logged
- baseline comparison works
- no unsafe auto-promotion occurs
- accepted changes are traceable

### Gate F: After Paper Trading
Confirm:
- order flow works
- reconciliations work
- duplicate order prevention works
- P&L and holdings stay consistent

## 6. Mandatory Review Questions

Before marking any milestone complete, answer:
1. Did this change follow APIS_MASTER_SPEC?
2. Did this session follow the continuity protocol?
3. Were all important decisions logged?
4. Were NEXT_STEPS updated?
5. Was QA run?
6. Could another session resume cleanly?
7. Did we avoid silent scope creep?
8. Did we keep MVP risk limits intact?

## 7. Practical Notes for This Project

For APIS specifically:
- do not let politics/news become vague narrative fluff; convert them into structured signals
- do not let rumor inputs dominate rankings
- do not reward raw gains without adjusting for risk and concentration
- do not confuse thematic conviction with liquidity quality
- prefer robust architecture over flashy UI
- keep continuity logs clean enough that a fresh session can resume without guesswork

## 8. Definition of Done for MVP

The MVP is done when APIS can:
- ingest data from approved sources
- generate explainable ranked stock ideas
- classify short-term vs long-term opportunities
- size paper positions under risk rules
- track paper portfolio state
- produce daily grading and attribution
- propose controlled improvements
- maintain clean continuity across sessions through state files

## 9. Final Rule

If a task is completed but the state files and handoff logs are not updated, the task is not actually complete.


## 10. Tooling and Plugin Activation Checklist

For APIS, the builder must deliberately use the relevant tools available in the environment rather than doing everything by hand.

Before and during implementation, verify whether the project should use:
- dependency and environment management tools
- formatter/linter tools
- type-checking tools
- test and coverage tools
- migration/database tools
- API schema and docs generation tools
- scheduling/job orchestration tools
- Docker/container tooling
- monitoring/logging/observability tooling
- broker SDKs and official client libraries
- data-provider SDKs or connectors
- QA/review/validation tools

Rules:
- install the needed packages/plugins when justified
- prefer official SDKs and stable tools where available
- avoid unnecessary tool sprawl
- document the chosen stack and why it was chosen
- include tool setup in repo bootstrap and QA where appropriate

A milestone is not truly complete if the builder skipped an obviously relevant tool that would have materially improved quality or verification.
