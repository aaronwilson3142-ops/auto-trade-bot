# Session 006 — API-Wide Operator Token Authentication

**Date:** 2026-03-22
**Todo Item:** #6 — Add API-wide operator token authentication (all non-health routes)

---

## Problem

Only two groups of routes required a bearer token:
- `admin.*` — using `APIS_ADMIN_ROTATION_TOKEN` (AWS rotation Lambda only)
- `intelligence POST` — using `APIS_OPERATOR_API_KEY` (external data feed pushers)

Every other `/api/v1/*` route — portfolio state, proposed actions, recommendations,
backtest results, live-gate status, config, signals, rankings, sector exposure, etc. —
was completely unauthenticated. Any process on the same network could read or trigger
sensitive operations without any credentials.

---

## Changes

### `apis/config/settings.py`
- Added `operator_token: str = ""` field (env var `APIS_OPERATOR_TOKEN`).
  Placed first in the Admin/Ops section so its purpose as the primary API gate is clear.
  Empty string = all `/api/v1/*` routes return 503, preventing silent open access.

### `apis/apps/api/deps.py`
- Added `_token_matches()` — constant-time HMAC comparison (same pattern as admin.py).
- Added `require_operator_token(credentials, settings)` FastAPI dependency:
  - 503 when `operator_token` is empty (misconfigured, not just unauthorized)
  - 401 + `WWW-Authenticate: Bearer` when token is missing or wrong
  - Silent pass when token matches
- Added `OperatorTokenDep = Depends(require_operator_token)` convenience alias.
- Uses `HTTPBearer(auto_error=False)` so the scheme shows up in the OpenAPI/Swagger UI.

### `apis/apps/api/main.py`
- Added `OperatorTokenDep` to import from `deps`.
- Added `_AUTH = [OperatorTokenDep]` list for easy one-place maintenance.
- Applied `dependencies=_AUTH` to all 29 `/api/v1/*` `include_router()` calls.
- `readiness_router` and `metrics_router` kept without auth (must respond before
  token is configured; scraped by monitoring infrastructure).
- `/health` and `/system/status` endpoints defined directly in `main.py` remain open.
- `/dashboard` (read-only HTML dashboard) remains open per its spec note.

### `apis/tests/unit/test_operator_auth.py` *(new file)*
- 15 tests: `TestTokenMatches` (5) + `TestRequireOperatorToken` (10).
- Covers: 503 on empty config, 401 on wrong/missing token, 401 on case mismatch,
  401 on whitespace token, correct pass-through, WWW-Authenticate header presence,
  503 detail mentions env var, long tokens, tokens with special chars.

---

## Routes Protected vs. Remaining Open

| Route group | Auth required? |
|-------------|---------------|
| `/api/v1/*` (all 29 routers) | ✅ `Authorization: Bearer <APIS_OPERATOR_TOKEN>` |
| `/api/v1/readiness/*` | ❌ Open (health probes) |
| `/metrics` | ❌ Open (Prometheus scraping) |
| `/health` | ❌ Open (docker healthcheck) |
| `/system/status` | ❌ Open (monitoring) |
| `/dashboard/*` | ❌ Open (localhost/trusted-net per spec) |

---

## How to Revert This Change

### Option A — Copy from originals + delete new file

```
cd "<project root>"

copy CHANGES\session_006_api_auth\originals\settings.py  apis\config\settings.py
copy CHANGES\session_006_api_auth\originals\deps.py       apis\apps\api\deps.py
copy CHANGES\session_006_api_auth\originals\main.py       apis\apps\api\main.py
del apis\tests\unit\test_operator_auth.py
```

On Linux/Mac use `cp`/`rm` instead.

### Option B — Apply patches in reverse + delete new file

```bash
cd "<project root>"

patch -R apis/config/settings.py    < CHANGES/session_006_api_auth/settings.patch
patch -R apis/apps/api/deps.py      < CHANGES/session_006_api_auth/deps.patch
patch -R apis/apps/api/main.py      < CHANGES/session_006_api_auth/main.patch
rm apis/tests/unit/test_operator_auth.py
```

---

## Test Results After This Change

- 15/15 tests pass in `test_operator_auth.py` (new)
- 55/55 tests pass in `test_risk_engine.py` (no regressions)
- 23/23 tests pass in `test_execution_engine.py` (no regressions)
