# Session 003 — Add Monthly Drawdown Limit

**Date:** 2026-03-22
**Todo Item:** #3 — Add monthly drawdown limit to Settings + RiskEngineService

---

## Problem

The APIS spec (§10.1) explicitly lists a monthly drawdown limit as a required risk control.
`Settings` only had `weekly_drawdown_limit_pct`; `RiskEngineService.check_drawdown()` only
enforced the weekly check.  A portfolio could lose 10–20% in a single month across multiple
weeks without triggering any block on new positions.

---

## Changes

### `apis/config/settings.py`
- Added `monthly_drawdown_limit_pct: float = Field(default=0.10, gt=0.0, le=0.50)` under
  the Risk Controls section, defaulting to 10% MTD loss cap.

### `apis/services/portfolio_engine/models.py`
- Added `start_of_month_equity: Optional[Decimal] = None` field to `PortfolioState`
  (parallel to `start_of_day_equity`; must be seeded from the most recent month-start snapshot).
- Added `monthly_pnl_pct` property (parallel to `daily_pnl_pct`) that computes MTD P&L
  as a fraction of `start_of_month_equity`.

### `apis/services/risk_engine/service.py`
- Added `check_monthly_drawdown(portfolio_state)` method: blocks new OPEN actions when
  `monthly_pnl_pct < -monthly_drawdown_limit_pct`.  Skips gracefully with a warning when
  `start_of_month_equity` is None.
- Wired `check_monthly_drawdown()` into the `validate_action()` checks pipeline.
- Updated module docstring rule list (rule #6).

### `apis/tests/unit/test_risk_engine.py`
- 8 new tests in `TestMonthlyDrawdown` class.
- Updated module docstring.

---

## Files Changed

| File | Change |
|------|--------|
| `apis/config/settings.py` | New `monthly_drawdown_limit_pct` field |
| `apis/services/portfolio_engine/models.py` | New `start_of_month_equity` field + `monthly_pnl_pct` property |
| `apis/services/risk_engine/service.py` | New `check_monthly_drawdown()` + wired into `validate_action()` |
| `apis/tests/unit/test_risk_engine.py` | 8 new tests in `TestMonthlyDrawdown` |

---

## Seeding `start_of_month_equity`

The caller (paper trading job or any future live cycle) must set `portfolio_state.start_of_month_equity`
at session start, reading the equity value from the first-of-month `PortfolioSnapshot` persisted
to the DB (same pattern used for `start_of_day_equity`).  Until it is seeded, the monthly drawdown
check is skipped with a warning — it never false-blocks on missing data.

---

## How to Revert This Change

### Option A — Copy from originals (simplest)

```
cd "<project root>"

copy CHANGES\session_003_monthly_drawdown\originals\settings.py               apis\config\settings.py
copy CHANGES\session_003_monthly_drawdown\originals\portfolio_engine_models.py apis\services\portfolio_engine\models.py
copy CHANGES\session_003_monthly_drawdown\originals\risk_engine_service.py     apis\services\risk_engine\service.py
copy CHANGES\session_003_monthly_drawdown\originals\test_risk_engine.py        apis\tests\unit\test_risk_engine.py
```

On Linux/Mac use `cp` instead of `copy`.

### Option B — Apply patches in reverse

```bash
cd "<project root>"

patch -R apis/config/settings.py                        < CHANGES/session_003_monthly_drawdown/settings.patch
patch -R apis/services/portfolio_engine/models.py       < CHANGES/session_003_monthly_drawdown/portfolio_engine_models.patch
patch -R apis/services/risk_engine/service.py           < CHANGES/session_003_monthly_drawdown/risk_engine_service.patch
patch -R apis/tests/unit/test_risk_engine.py            < CHANGES/session_003_monthly_drawdown/test_risk_engine.patch
```

---

## Test Results After This Change

- 37/37 tests pass in `test_risk_engine.py` (29 pre-existing + 8 new monthly drawdown tests)
- 23/23 tests pass in `test_execution_engine.py` (no regressions)
