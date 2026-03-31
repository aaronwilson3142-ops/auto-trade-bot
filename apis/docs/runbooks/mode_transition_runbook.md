# APIS — Operating Mode Transition Runbook

**Version:** 1.0  
**Last Updated:** 2026-03-18  
**Owner:** APIS Operator  
**Spec reference:** APIS_MASTER_SPEC.md §3.1, §5

---

## Overview

APIS operates in a strict staged progression:

```
RESEARCH  →  BACKTEST  →  PAPER  →  HUMAN_APPROVED  →  RESTRICTED_LIVE
```

Each transition requires an explicit operator action plus pre-flight validation.  
**You cannot skip stages.**  
**RESTRICTED_LIVE cannot be set via environment variable alone** — the `Settings` validator blocks it; it requires both this runbook completion and a spec revision.

---

## Transition 1: RESEARCH → PAPER

### When to attempt this
- Backtest validation is complete (≥30 days of backtested history, Sharpe ≥ 0.5, max drawdown ≤ 15 %)
- All unit + integration tests pass (`pytest tests/unit/ --no-cov -q` → 0 failures)
- Live API credentials are provisioned (Alpaca paper or Schwab paper account)
- Database is migrated and healthy (`alembic upgrade head; alembic check`)

### Pre-flight checklist

#### 1. Environment validation
- [ ] `APIS_OPERATING_MODE` is currently `research` (confirm: `GET /system/status`)
- [ ] `APIS_KILL_SWITCH` is `false`
- [ ] `APIS_ENV` is `production` or `staging` (not `development` for real paper)
- [ ] `.env` or Kubernetes Secret has valid broker credentials

#### 2. Database health
```bash
# In the running api container or local:
curl http://localhost:8000/health
# Expect: {"status": "ok", "components": {"db": "ok", ...}}
```
- [ ] `components.db` == `"ok"`
- [ ] Alembic head migration applied (`alembic current` matches `alembic heads`)

#### 3. Broker connectivity
```bash
curl http://localhost:8000/health
```
- [ ] `components.broker` == `"ok"` or `"not_connected"` (adapter will connect on first job run)
- If broker shows `"error"`, investigate adapter logs before proceeding

#### 4. Live gate pre-check (advisory)
```bash
curl http://localhost:8000/api/v1/live-gate/status
```
- Review output for gate requirement statuses
- `PAPER → HUMAN_APPROVED` gate requirements will all show `not_met` at this stage — that is expected; you are going to `PAPER` first, not `HUMAN_APPROVED`

#### 5. Risk controls confirmed
- [ ] `APIS_MAX_POSITIONS` = 10 (MVP hard cap)
- [ ] `APIS_DAILY_LOSS_LIMIT_PCT` ≤ 0.02
- [ ] `APIS_WEEKLY_DRAWDOWN_LIMIT_PCT` ≤ 0.05
- [ ] `APIS_MAX_SINGLE_NAME_PCT` ≤ 0.20

#### 6. Secrets backend
- [ ] `APIS_SECRET_BACKEND` = `production` → `AWSSecretManager` used; AWS credentials valid
- [ ] OR `APIS_SECRET_BACKEND` = `development` → `EnvSecretManager`; all credential env vars set

### Transition steps

1. **Update the environment variable:**
   ```bash
   # .env file
   APIS_OPERATING_MODE=paper
   ```
   or in Kubernetes:
   ```bash
   kubectl patch configmap apis-config -n apis \
     --type merge -p '{"data":{"APIS_OPERATING_MODE":"paper"}}'
   ```

2. **Restart the API + Worker:**
   ```bash
   # Docker Compose:
   docker compose restart api worker

   # Kubernetes:
   kubectl rollout restart deployment/apis-api -n apis
   kubectl rollout restart deployment/apis-worker -n apis
   ```

3. **Verify mode active:**
   ```bash
   curl http://localhost:8000/system/status
   # Expect: {"mode": "paper", ...}
   ```

4. **Monitor first paper cycle:**
   - Wait for `paper_trading_cycle_morning` job (09:30 ET) or trigger manually
   - Check `GET /api/v1/portfolio/` for paper positions
   - Check `GET /api/v1/evaluation/scorecard` for first paper scorecard

5. **Log the transition** in `state/DECISION_LOG.md`

### Rollback
```bash
APIS_OPERATING_MODE=research
docker compose restart api worker
# Verify: GET /system/status → {"mode": "research"}
```

---

## Transition 2: PAPER → HUMAN_APPROVED

### Prerequisites (programmatic gate)
Call `GET /api/v1/live-gate/status` — all of the following must return `met`:

| Requirement | Threshold |
|---|---|
| `paper_cycle_count` | ≥ 5 completed cycles |
| `evaluation_history` length | ≥ 5 daily evaluations |
| `paper_cycle_errors` | ≤ 2 |
| `portfolio_state` | initialized (cash > 0) |

### Manual gate checklist (operator review)

- [ ] Daily scorecards reviewed for ≥ 5 trading days
- [ ] Drawdown never exceeded 5 % in paper session
- [ ] Kill switch was never triggered unintentionally
- [ ] Fills reconciled correctly (no phantom positions, no negative cash)
- [ ] Broker adapter connectivity stable (check `components.broker` in `/health`)
- [ ] Self-improvement proposals are reasonable (review `/api/v1/improvement/proposals`)

### Transition steps

1. Check advisory via API:
   ```bash
   curl -X POST http://localhost:8000/api/v1/live-gate/promote \
     -H "Content-Type: application/json" \
     -d '{"target_mode": "human_approved"}'
   ```
   Expected: `"promotable": true, "message": "All gate requirements met."`

2. Update env and restart (same as above but `APIS_OPERATING_MODE=human_approved`)

3. Verify: `GET /system/status` → `{"mode": "human_approved"}`

4. In `HUMAN_APPROVED` mode, the worker proposes trades but **does not auto-execute**.  
   Operator reviews via `GET /api/v1/actions/` and approves via `POST /api/v1/actions/review`.

---

## Transition 3: HUMAN_APPROVED → RESTRICTED_LIVE

> ⚠️ **This transition requires a spec revision, not just an env var change.**  
> The `Settings` validator blocks `RESTRICTED_LIVE` when set via environment.  
> You must update `config/settings.py` and remove the validator guard **after** completing this runbook.

### Prerequisites (programmatic gate)
All `HUMAN_APPROVED → RESTRICTED_LIVE` gate requirements must be `met`:

| Requirement | Threshold |
|---|---|
| `paper_cycle_count` | ≥ 20 completed cycles |
| `evaluation_history` length | ≥ 10 daily evaluations |
| `paper_cycle_errors` | ≤ 2 |
| `portfolio_state` initialized | yes |
| `latest_rankings` available | yes (non-empty) |

### Additional manual requirements

- [ ] Minimum 30 days of paper trading history reviewed
- [ ] Benchmark-relative performance positive (Sharpe ≥ 0.5 vs SPY)
- [ ] No open CRITICAL alerts in Grafana / Prometheus for ≥ 7 days
- [ ] AWS Secrets rotation hook tested: `POST /api/v1/admin/invalidate-secrets` with valid token
- [ ] Kubernetes/Docker health checks passing with 0 restart loops for ≥ 48 h
- [ ] Risk engine kill switch tested end-to-end in paper mode
- [ ] Operator notified at every proposed trade for ≥ 2 weeks in HUMAN_APPROVED mode
- [ ] External review / second opinion from independent operator (recommended)

### Spec revision required before proceeding

Edit `config/settings.py` `validate_operating_mode` to allow `RESTRICTED_LIVE`, or remove the guard.  Log this change as a decision in `state/DECISION_LOG.md`.

---

## Emergency Kill Switch

In any mode, the kill switch halts all new position opening immediately:

```bash
# .env or Kubernetes:
APIS_KILL_SWITCH=true
docker compose restart api worker

# Verify:
curl http://localhost:8000/system/status
# Expect: {"kill_switch": true, ...}
```

All existing positions remain open; only new opens are blocked.  
To close all positions, use `POST /api/v1/actions/review` with CLOSE actions after consulting the portfolio snapshot.

---

## Post-Transition Checklist (any mode)

- [ ] `GET /health` → status `"ok"` or `"degraded"` (not `"down"`)
- [ ] `GET /system/status` → `mode` matches expected value
- [ ] `GET /api/v1/live-gate/status` → gate requirements visible
- [ ] Grafana dashboard accessible at port 3000; all panels populated
- [ ] Prometheus scraping at port 9090; no stale scrapes
- [ ] `state/DECISION_LOG.md` entry added with: timestamp, old mode, new mode, operator, rationale
- [ ] `state/CHANGELOG.md` entry added

---

## Related Commands Reference

```bash
# Check current mode
curl http://localhost:8000/system/status | python -m json.tool

# Live gate status
curl http://localhost:8000/api/v1/live-gate/status | python -m json.tool

# Promote advisory  
curl -X POST http://localhost:8000/api/v1/live-gate/promote \
  -H "Content-Type: application/json" \
  -d '{"target_mode": "human_approved"}' | python -m json.tool

# Invalidate secrets cache (rotation hook)
curl -X POST http://localhost:8000/api/v1/admin/invalidate-secrets \
  -H "Authorization: Bearer YOUR_ADMIN_ROTATION_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"secret_name": "apis/production/secrets"}'

# Health check
curl http://localhost:8000/health | python -m json.tool

# Tail API logs (Docker Compose)
docker compose logs -f api

# Tail Worker logs
docker compose logs -f worker

# Apply DB migrations
docker compose exec api alembic upgrade head

# Run unit tests (should be 0 failures before any mode transition)
cd apis && python -m pytest tests/unit/ --no-cov -q
```
