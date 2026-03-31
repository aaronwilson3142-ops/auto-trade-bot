# Session 007 — Tighten CORS from Wildcard

**Date:** 2026-03-22
**Todo Item:** #7 — Tighten CORS from `allow_origins=["*"]` to specific allowed origins

---

## Problem

`main.py` configured the CORS middleware with:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # any browser origin allowed
    allow_methods=["GET", "POST"],
    allow_headers=["*"],   # any header allowed
)
```

`allow_origins=["*"]` is appropriate for public APIs but not for a locally-run
trading bot.  It allows any website the operator visits in their browser to make
credentialled cross-origin requests to the API.  Combined with the operator token
(added in session 006) the practical risk is low, but defence-in-depth calls for
tightening it.  `allow_headers=["*"]` is similarly permissive — only
`Authorization` and `Content-Type` are actually needed.

---

## Changes

### `apis/config/settings.py`

- Added `allowed_cors_origins: list[str]` field (env var
  `APIS_ALLOWED_CORS_ORIGINS`) in the "API Server" section.
- Default value: `["http://localhost:8000", "http://127.0.0.1:8000",
  "http://localhost:3000", "http://127.0.0.1:3000"]`
  - Ports 8000: FastAPI app itself + Swagger UI (docs page makes cross-origin
    requests back to the same API when `servers` includes a different host).
  - Port 3000: Grafana (from `docker-compose.yml`).
  - No other browser-accessible services in the stack (Prometheus 9090,
    Alertmanager 9093, Redis 6379, and Postgres 5432 are non-browser services).
- The field accepts a JSON-encoded list via env var:
  `APIS_ALLOWED_CORS_ORIGINS='["http://myhost:8080"]'`

### `apis/apps/api/main.py`

- `allow_origins=["*"]` → `allow_origins=settings.allowed_cors_origins`
- `allow_headers=["*"]` → `allow_headers=["Authorization", "Content-Type"]`
  - `Authorization`: required for the operator bearer token (session 006).
  - `Content-Type`: required for POST request bodies.
  - No other custom headers are needed by this API.

### `apis/tests/unit/test_cors.py` *(new file)*

- 10 tests across two classes: `TestAllowedCorsOriginsDefault` (6) and
  `TestAllowedCorsOriginsOverride` (4).
- Covers: default is a list (not a string), default contains both localhost:8000
  and 127.0.0.1:8000 and localhost:3000, wildcard is absent, override replaces
  default, empty list is valid, multiple origins preserved, env var JSON parsing.

---

## Routes / Origins Summary

| Exposed port | Service | In default allowed_cors_origins? |
|---|---|---|
| 8000 | APIS FastAPI + Swagger UI | ✅ `http://localhost:8000` + `http://127.0.0.1:8000` |
| 3000 | Grafana | ✅ `http://localhost:3000` + `http://127.0.0.1:3000` |
| 9090 | Prometheus | ❌ (not a browser API client) |
| 9093 | Alertmanager | ❌ (not a browser API client) |
| 5432 | PostgreSQL | ❌ (not a browser service) |
| 6379 | Redis | ❌ (not a browser service) |

---

## How to Revert This Change

### Option A — Copy from originals + delete new test file

```
cd "<project root>"

copy CHANGES\session_007_cors\originals\settings.py  apis\config\settings.py
copy CHANGES\session_007_cors\originals\main.py       apis\apps\api\main.py
del apis\tests\unit\test_cors.py
```

On Linux/Mac use `cp`/`rm` instead.

### Option B — Apply patches in reverse + delete new test file

```bash
cd "<project root>"

patch -R apis/config/settings.py < CHANGES/session_007_cors/settings.patch
patch -R apis/apps/api/main.py   < CHANGES/session_007_cors/main.patch
rm apis/tests/unit/test_cors.py
```

---

## Test Results After This Change

- 10/10 tests pass in `test_cors.py` (new)
