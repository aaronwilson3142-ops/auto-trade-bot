# Session 001 — Fix Runtime Kill Switch Gap

**Date:** 2026-03-22
**Todo Item:** #1 — Fix runtime kill switch gap in RiskEngineService + ExecutionEngineService

---

## Problem

`RiskEngineService.check_kill_switch()` and `ExecutionEngineService`'s kill switch guard both
only checked `settings.kill_switch` (the env-var flag set at startup). The runtime flag
`app_state.kill_switch_active` — toggled via `POST /api/v1/admin/kill-switch` without
restarting the process — was invisible to both services. Any code path calling them directly
would silently bypass a live kill switch activation.

---

## Files Changed

| File | Change |
|------|--------|
| `apis/services/risk_engine/service.py` | Added `kill_switch_fn` param; updated `check_kill_switch()` + `evaluate_trims()` |
| `apis/services/execution_engine/service.py` | Added `kill_switch_fn` param; updated kill switch re-check in `execute_action()` |
| `apis/apps/worker/jobs/paper_trading.py` | Wire `_ks_fn = lambda: app_state.kill_switch_active` into both services |
| `apis/tests/unit/test_risk_engine.py` | 8 new tests for runtime kill switch behavior |
| `apis/tests/unit/test_execution_engine.py` | 4 new tests for runtime kill switch behavior |

---

## How to Revert This Change

### Option A — Copy from originals (simplest)

```
cd "<project root>"

copy CHANGES\session_001_kill_switch\originals\risk_engine_service.py      apis\services\risk_engine\service.py
copy CHANGES\session_001_kill_switch\originals\execution_engine_service.py apis\services\execution_engine\service.py
copy CHANGES\session_001_kill_switch\originals\paper_trading.py            apis\apps\worker\jobs\paper_trading.py
copy CHANGES\session_001_kill_switch\originals\test_risk_engine.py         apis\tests\unit\test_risk_engine.py
copy CHANGES\session_001_kill_switch\originals\test_execution_engine.py    apis\tests\unit\test_execution_engine.py
```

On Linux/Mac, use `cp` instead of `copy`.

### Option B — Apply patches in reverse (patch tool required)

```bash
cd "<project root>"

patch -R apis/services/risk_engine/service.py         < CHANGES/session_001_kill_switch/risk_engine_service.patch
patch -R apis/services/execution_engine/service.py    < CHANGES/session_001_kill_switch/execution_engine_service.patch
patch -R apis/apps/worker/jobs/paper_trading.py       < CHANGES/session_001_kill_switch/paper_trading.patch
patch -R apis/tests/unit/test_risk_engine.py          < CHANGES/session_001_kill_switch/test_risk_engine.patch
patch -R apis/tests/unit/test_execution_engine.py     < CHANGES/session_001_kill_switch/test_execution_engine.patch
```

---

## Test Results After This Change

- 47/47 tests pass in `test_risk_engine.py` + `test_execution_engine.py`
- 39 original tests unchanged; 11 new tests added (8 risk engine, 3 execution engine)
