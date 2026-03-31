# Session 004 — Add Max New Positions Per Day Limit

**Date:** 2026-03-22
**Todo Item:** #4 — Add max new positions per day limit to RiskEngineService

---

## Problem

The spec states a "max number of new positions per day" constraint, but neither `Settings`
nor `RiskEngineService` enforced it.  On a volatile day the system could open 5–10 new
positions in a single cycle, amplifying exposure well beyond the intended daily entry pace.

---

## Changes

### `apis/config/settings.py`
- Added `max_new_positions_per_day: int = Field(default=3, ge=1, le=10)` under Risk Controls.
  Default of 3 is a conservative entry pace for a paper portfolio capped at 10 positions.

### `apis/services/portfolio_engine/models.py`
- Added `daily_opens_count: int = 0` field to `PortfolioState`.
  The caller (paper trading job) must increment this by 1 after each successful OPEN fill
  and reset it to 0 at the start of each trading day.

### `apis/services/risk_engine/service.py`
- Added `check_daily_position_cap(action, portfolio_state)` method: hard-blocks OPEN actions
  when `portfolio_state.daily_opens_count >= settings.max_new_positions_per_day`.
  CLOSE and TRIM actions are never affected.
- Wired `check_daily_position_cap()` into the `validate_action()` checks pipeline.
- Updated module docstring rule list (rule #7).

### `apis/tests/unit/test_risk_engine.py`
- 8 new tests in `TestDailyPositionCap`.
- Updated module docstring.

---

## Caller Responsibility

The paper trading job (or any future live cycle) must:
1. Increment `portfolio_state.daily_opens_count += 1` immediately after each confirmed OPEN fill.
2. Reset `portfolio_state.daily_opens_count = 0` at the start of each new trading day
   (alongside resetting `start_of_day_equity`).

Until incremented, the counter defaults to 0 and the check never blocks — safe behavior
for the first run of the day.

---

## Files Changed

| File | Change |
|------|--------|
| `apis/config/settings.py` | New `max_new_positions_per_day` field |
| `apis/services/portfolio_engine/models.py` | New `daily_opens_count` field |
| `apis/services/risk_engine/service.py` | New `check_daily_position_cap()` + wired into `validate_action()` |
| `apis/tests/unit/test_risk_engine.py` | 8 new tests in `TestDailyPositionCap` |

---

## How to Revert This Change

### Option A — Copy from originals

```
cd "<project root>"

copy CHANGES\session_004_daily_position_cap\originals\settings.py               apis\config\settings.py
copy CHANGES\session_004_daily_position_cap\originals\portfolio_engine_models.py apis\services\portfolio_engine\models.py
copy CHANGES\session_004_daily_position_cap\originals\risk_engine_service.py     apis\services\risk_engine\service.py
copy CHANGES\session_004_daily_position_cap\originals\test_risk_engine.py        apis\tests\unit\test_risk_engine.py
```

On Linux/Mac use `cp` instead of `copy`.

### Option B — Apply patches in reverse

```bash
cd "<project root>"

patch -R apis/config/settings.py                        < CHANGES/session_004_daily_position_cap/settings.patch
patch -R apis/services/portfolio_engine/models.py       < CHANGES/session_004_daily_position_cap/portfolio_engine_models.patch
patch -R apis/services/risk_engine/service.py           < CHANGES/session_004_daily_position_cap/risk_engine_service.patch
patch -R apis/tests/unit/test_risk_engine.py            < CHANGES/session_004_daily_position_cap/test_risk_engine.patch
```

---

## Test Results After This Change

- 45/45 tests pass in `test_risk_engine.py` (37 pre-existing + 8 new daily position cap tests)
- 23/23 tests pass in `test_execution_engine.py` (no regressions)
