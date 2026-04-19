# APIS Health Log

Auto-generated daily health check results.

---

## 2026-04-19 02:15 UTC — Deep-Dive Scheduled Run (5 AM CT Saturday 2026-04-18) — **RED**

Scheduled autonomous run of the APIS Daily Deep-Dive Health Check (8 sections). Operator was not present.

**Severity: RED** — production-paper Postgres was polluted by what appears to be a test-suite run sometime between 01:39:23 and 01:40:14 UTC (≈90 min before this run began). The clean $100k baseline that was in place at 2026-04-18 16:37 UTC has been overwritten.

### §1 Infrastructure — GREEN
All 7 containers healthy, Alertmanager 0 active, worker+api logs clean of crash-triad regressions.

### §2 Execution + Data Audit — **RED**
- `portfolio_snapshots`: 27 rows in last 4h, all from a 01:40 burst. Latest row: `cash=$49,665.68 / gross=$3,831.92 / equity=$53,497.60` (vs. $100k baseline at 16:37 UTC).
- `positions`: 3 rows opened in 0.5s window 01:40:11.776 → 01:40:12.272. 1 still open: NVDA `6307f4e2-…` qty 19 @ $201.78, **`origin_strategy=NULL`**.
- `orders` last-4h: **0**. Positions written directly without order — clear test-fixture signature.
- Phase 63 phantom-cash guard did **not** trigger (cash > 0). Operator approval required for cleanup; standing authority excludes DB writes.

### §3 Code + Schema — YELLOW
- Git: clean against `origin/main`, no unpushed commits, no stale branches. Dirty: `state/DECISION_LOG.md` (4 lines, will commit) + 1 scratch ps1.
- Alembic: head `o5p6q7r8s9t0`, single head ✓. `alembic check` reports ~25 cosmetic drift items (TIMESTAMP↔DateTime types, comment wording, one missing `ix_proposal_executions_proposal_id`). Non-functional.
- Pytest: **358 passed / 2 failed** (matches DEC-021 baseline — phase22 scheduler-count drift only).

### §4 Config + Gate Verification — GREEN
All 10 critical APIS_* flags verified against `apis/config/settings.py` defaults — no drift, no auto-fixes applied.

### Overall: **RED** (driven by §2 test-data pollution)

Full §1–§4 detail is in `apis/state/HEALTH_LOG.md`. Operator email sent to aaron.wilson3142@gmail.com.

---

## Health Check — 2026-03-29 18:57 local

**Overall Status:** HEALTHY

### Docker Containers
| Container | Status | Notes |
|-----------|--------|-------|
| docker-api-1 | Up 5 hours (healthy) | Port 8000 |
| docker-worker-1 | Up 10 hours (healthy) | |
| docker-grafana-1 | Up 2 days | Port 3000 |
| docker-prometheus-1 | Up 7 days | Port 9090 |
| docker-alertmanager-1 | Up 4 days | Port 9093 |
| docker-postgres-1 | Up 7 days (healthy) | Port 5432 |
| docker-redis-1 | Up 7 days (healthy) | Port 6379 |

### API Health Endpoint
- Result: HTTP 200 — `{"status":"ok","service":"api","mode":"paper","timestamp":"2026-03-29T23:56:41.087572+00:00","components":{"db":"ok","broker":"not_connected","scheduler":"no_data","broker_auth":"ok","kill_switch":"ok"}}`
- Note: `broker: not_connected` and `scheduler: no_data` observed — overall status remains "ok"; likely expected in paper mode without active broker session.

### Kubernetes Pods
- `apis-api-68f79b74d8-9f446`: Running (1/1, 0 restarts, age 7d5h)
- `postgres-0`: Running (1/1, 1 restart — normal, age 7d22h)
- `redis-79d54f5d6-nxkmh`: Running (1/1, 1 restart — normal, age 7d22h)
- Worker deployment: Scaled to 0 (intentional — not flagged)

### Issues Found
- None

### Fixes Applied
- None required

### Post-Fix Status
- N/A — no fixes needed

### Action Required
- None

---

## Health Check - 2026-03-30 05:11 local

**Overall Status:** HEALTHY

### Docker Containers
| Container | Status | Notes |
|-----------|--------|-------|
| docker-api-1 | Up 16 hours (healthy) | Port 8000 |
| docker-worker-1 | Up 20 hours (healthy) | |
| docker-grafana-1 | Up 2 days | Port 3000 |
| docker-prometheus-1 | Up 7 days | Port 9090 |
| docker-alertmanager-1 | Up 4 days | Port 9093 |
| docker-postgres-1 | Up 7 days (healthy) | Port 5432 |
| docker-redis-1 | Up 7 days (healthy) | Port 6379 |

### API Health Endpoint
- Result: HTTP 200 -- `{"status":"ok","service":"api","mode":"paper","timestamp":"2026-03-30T10:11:02.795813+00:00","components":{"db":"ok","broker":"not_connected","scheduler":"no_data","broker_auth":"ok","kill_switch":"ok"}}`
- Note: `broker: not_connected` and `scheduler: no_data` persist from yesterday -- expected in paper mode without an active broker session.

### Kubernetes Pods
- `apis-api-68f79b74d8-9f446`: Running (1/1, 0 restarts, age 7d15h)
- `postgres-0`: Running (1/1, 1 restart - normal, age 8d)
- `redis-79d54f5d6-nxkmh`: Running (1/1, 1 restart - normal, age 8d)
- Worker deployment: Scaled to 0 (intentional - not flagged)

### Issues Found
- None

### Fixes Applied
- None required

### Post-Fix Status
- N/A -- no fixes needed

### Action Required
- None

---
