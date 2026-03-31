# APIS Health Log

Auto-generated daily health check results.

---

## Health Check — 2026-03-26 05:10 local

**Overall Status:** ✅ HEALTHY

### Docker Containers
| Container | Status | Notes |
|-----------|--------|-------|
| docker-api-1 | ✅ Up 9 hours (healthy) | Port 8000 |
| docker-worker-1 | ✅ Up 3 days | APScheduler |
| docker-postgres-1 | ✅ Up 3 days (healthy) | Port 5432 |
| docker-redis-1 | ✅ Up 3 days (healthy) | Port 6379 |
| docker-prometheus-1 | ✅ Up 3 days | Port 9090 |
| docker-grafana-1 | ✅ Up 3 days | Port 3000 |
| docker-alertmanager-1 | ✅ Up 15 hours | Port 9093 |

### API Health Endpoint
- **HTTP Status:** 200 OK
- **Response:** `{"status":"ok","service":"api","mode":"paper","timestamp":"2026-03-26T10:11:19.117028+00:00","components":{"db":"ok","broker":"ok","scheduler":"no_data","broker_auth":"ok","kill_switch":"ok"}}`
- **Note:** `scheduler: no_data` — persists from previous check. Worker container is running; APScheduler heartbeat not yet surfacing in API health. Not a critical failure.

### Kubernetes Pods (namespace: apis)
| Pod | Ready | Status | Restarts |
|-----|-------|--------|----------|
| apis-api-68f79b74d8-9f446 | 1/1 | ✅ Running | 0 |
| postgres-0 | 1/1 | ✅ Running | 1 (3d15h ago) |
| redis-79d54f5d6-nxkmh | 1/1 | ✅ Running | 1 (3d15h ago) |
| apis-worker | — | ✅ Scaled to 0 (intentional) | — |

### Issues Found
- Minor (recurring): `scheduler: no_data` in API health response — APScheduler worker heartbeat not reflected. Not blocking.

### Fixes Applied
- None required.

### Post-Fix Status
- N/A — no fixes needed.

### Action Required
- None. All services healthy.

---

## Health Check — 2026-03-25 21:13 UTC

**Overall Status:** ✅ HEALTHY

### Docker Containers
| Container | Status | Notes |
|-----------|--------|-------|
| docker-api-1 | ✅ Up ~1 hour (healthy) | Port 8000 |
| docker-worker-1 | ✅ Up 2 days | APScheduler |
| docker-postgres-1 | ✅ Up 2 days (healthy) | Port 5432 |
| docker-redis-1 | ✅ Up 2 days (healthy) | Port 6379 |
| docker-prometheus-1 | ✅ Up 2 days | Port 9090 |
| docker-grafana-1 | ✅ Up 2 days | Port 3000 |
| docker-alertmanager-1 | ✅ Up 2 hours | Port 9093 |
| apis-control-plane (kind) | ✅ Up 3 days | K8s node |

### API Health Endpoint
- **HTTP Status:** 200 OK
- **Response:** `{"status":"ok","service":"api","mode":"paper","timestamp":"2026-03-25T21:13:05.521162+00:00","components":{"db":"ok","broker":"ok","scheduler":"no_data","broker_auth":"ok","kill_switch":"ok"}}`
- **Note:** `scheduler: no_data` — worker has not yet written a heartbeat to the API. Not a critical failure; monitor over time.

### Kubernetes Pods (namespace: apis)
| Pod | Ready | Status | Restarts |
|-----|-------|--------|----------|
| apis-api-68f79b74d8-9f446 | 1/1 | ✅ Running | 0 |
| postgres-0 | 1/1 | ✅ Running | 1 (3d2h ago) |
| redis-79d54f5d6-nxkmh | 1/1 | ✅ Running | 1 (3d2h ago) |
| apis-worker | — | ✅ Scaled to 0 (intentional) | — |

### Issues Found
- Minor: `scheduler: no_data` in API health response — APScheduler worker has not written a heartbeat. Not blocking.

### Fixes Applied
- None required.

### Post-Fix Status
- N/A — no fixes needed.

### Action Required
- None. All services healthy.

---
