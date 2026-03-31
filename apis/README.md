# APIS — Autonomous Portfolio Intelligence System

## Purpose

APIS is a disciplined, modular, auditable portfolio operating system for U.S. equities.

It ingests market, macro, political, sector, company, news, and rumor/chatter inputs; generates ranked stock ideas; manages a paper portfolio under strict risk rules; grades itself daily; and improves itself in a controlled, benchmarked, reversible way.

This is a serious portfolio operating system, not a hype demo.

---

## Architecture Summary

APIS is composed of cleanly-separated services:

| Service | Responsibility |
|---|---|
| `data_ingestion` | Fetch, normalize, and stage raw source inputs |
| `market_data` | Price/bar normalization, liquidity and technical metrics |
| `news_intelligence` | News parsing, credibility tagging, entity extraction |
| `macro_policy_engine` | Policy, tariff, geopolitical, regulatory signal structuring |
| `theme_engine` | Company-to-theme mapping, second-order beneficiary logic |
| `rumor_scoring` | Low-confidence chatter with decay and reliability discounting |
| `feature_store` | Versioned engineered feature persistence and retrieval |
| `signal_engine` | Raw signal generation by strategy family |
| `ranking_engine` | Signal merging, ranking, action suggestions, thesis summaries |
| `portfolio_engine` | Portfolio state, sizing proposals, exposure accounting |
| `risk_engine` | Pre-trade hard gatekeeper — no bypass allowed |
| `execution_engine` | Approved actions → broker orders via adapter layer |
| `evaluation_engine` | Daily grading, benchmarking, attribution |
| `self_improvement` | Proposals, challenger evaluation, promotion policy |
| `reporting` | Daily scorecards, summaries, operator reports |
| `continuity` | State file helpers, checkpoint utilities |

---

## Operating Modes

1. **Research Mode** — ranked ideas and theses only, no execution
2. **Backtest Mode** — historical simulation with costs and slippage
3. **Paper Trading Mode** — live data, paper broker execution
4. **Human-Approved Live Mode** — proposes trades, user approves
5. **Restricted Autonomous Live Mode** — only after strict validation gates

---

## Safety Constraints (Non-Negotiable)

- U.S. equities only
- Long-only
- No margin, no leverage, no options, no futures
- Maximum 10 active positions
- Risk engine is a hard gatekeeper on all execution paths
- Self-improvement cannot self-promote without policy gates
- Must not jump stages (research → backtest → paper → live)
- Every decision must be explainable and logged

---

## Setup

### Requirements

- Python 3.11+
- PostgreSQL
- Redis
- Alpaca account (paper trading)

### Install

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install dependencies
pip install -e ".[dev]"

# Copy and configure environment
cp .env.example .env
# Edit .env with your config

# Run migrations
alembic upgrade head

# Run tests
pytest
```

---

## Governing Documents

| File | Purpose |
|---|---|
| `01_CLAUDE_KICKOFF_PROMPT.md` | Session start instructions and build authority |
| `02_APIS_MASTER_SPEC.md` | Master system specification |
| `03_SESSION_CONTINUITY_AND_EXECUTION_PROTOCOL.md` | Session continuity protocol |
| `04_APIS_BUILD_RUNBOOK.md` | Practical build sequence and QA gates |
| `05_INITIAL_REPO_STRUCTURE.md` | Repo layout specification |
| `06_DATABASE_AND_SCHEMA_SPEC.md` | Database schema specification |
| `07_API_AND_SERVICE_BOUNDARIES_SPEC.md` | Service ownership and API surface |

## Project State Files

| File | Purpose |
|---|---|
| `state/ACTIVE_CONTEXT.md` | Current ground truth |
| `state/NEXT_STEPS.md` | Next ordered actions |
| `state/DECISION_LOG.md` | Architecture decisions and rationale |
| `state/CHANGELOG.md` | Concrete changes made |
| `state/SESSION_HANDOFF_LOG.md` | Session checkpoint entries |
