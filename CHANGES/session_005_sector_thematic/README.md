# Session 005 — Sector/Thematic Concentration Checks in validate_action

**Date:** 2026-03-22
**Todo Item:** #5 — Add sector/thematic concentration checks into core validate_action pipeline

---

## Problem

`max_sector_pct` and `max_thematic_pct` both exist in `Settings`, but:

- **Sector**: enforced only as a batch pre-filter in `paper_trading.py` (dropping actions
  from a list). Any future code path that calls `validate_action()` directly bypasses this limit.
- **Thematic**: `max_thematic_pct` exists in Settings and is exposed in the config API endpoint,
  but was **never enforced anywhere** in the trading pipeline.

Both limits now live inside `validate_action()` so every action, from every code path, is checked.

---

## Changes

### `apis/config/universe.py`
- Added `TICKER_THEME: Final[dict[str, str]]` — maps each universe ticker to its primary
  investment theme (`"ai_infrastructure"`, `"cloud_software"`, `"semiconductors"`,
  `"mega_cap_tech"`, `"healthcare"`, `"financials"`, `"energy"`, `"consumer"`).
- Where a ticker belongs to multiple themes, the most *specific* theme wins
  (e.g. `NVDA` → `"ai_infrastructure"` rather than `"mega_cap_tech"`).

### `apis/services/risk_engine/thematic_exposure.py` *(new file)*
- `ThematicExposureService` — stateless, parallel to the existing `SectorExposureService`.
- `get_theme(ticker)` — returns theme label from `TICKER_THEME`, falls back to `"other"`.
- `projected_thematic_weight(ticker, notional, positions, equity)` — computes post-trade
  theme concentration before any order is submitted.
- `compute_thematic_weights(positions, equity)` — current theme weights (for dashboards).
- `filter_for_thematic_limits(actions, portfolio_state, settings)` — batch filter (mirrors
  `SectorExposureService.filter_for_sector_limits()`).

### `apis/services/risk_engine/service.py`
- Added `check_sector_concentration(action, portfolio_state)` — hard-blocks OPEN actions
  that would push any sector's projected weight above `max_sector_pct`. Passes gracefully
  with a warning on import errors.
- Added `check_thematic_concentration(action, portfolio_state)` — same logic for themes.
- Both wired into `validate_action()` checks pipeline (rules #8 and #9).
- Updated module docstring.

### `apis/tests/unit/test_risk_engine.py`
- 10 new tests: `TestSectorConcentration` (5 tests) + `TestThematicConcentration` (5 tests).
- Updated module docstring.

---

## Files Changed

| File | Change |
|------|--------|
| `apis/config/universe.py` | New `TICKER_THEME` mapping |
| `apis/services/risk_engine/thematic_exposure.py` | **NEW** — `ThematicExposureService` |
| `apis/services/risk_engine/service.py` | Two new check methods + wired into `validate_action()` |
| `apis/tests/unit/test_risk_engine.py` | 10 new tests |

---

## How to Revert This Change

### Option A — Copy from originals + delete new file

```
cd "<project root>"

copy CHANGES\session_005_sector_thematic\originals\universe.py               apis\config\universe.py
copy CHANGES\session_005_sector_thematic\originals\risk_engine_service.py    apis\services\risk_engine\service.py
copy CHANGES\session_005_sector_thematic\originals\test_risk_engine.py       apis\tests\unit\test_risk_engine.py
del apis\services\risk_engine\thematic_exposure.py
```

On Linux/Mac use `cp`/`rm` instead.

### Option B — Apply patches in reverse + delete new file

```bash
cd "<project root>"

patch -R apis/config/universe.py                     < CHANGES/session_005_sector_thematic/universe.patch
patch -R apis/services/risk_engine/service.py        < CHANGES/session_005_sector_thematic/risk_engine_service.patch
patch -R apis/tests/unit/test_risk_engine.py         < CHANGES/session_005_sector_thematic/test_risk_engine.patch
rm apis/services/risk_engine/thematic_exposure.py
```

The new file `thematic_exposure.py` is preserved as `thematic_exposure_NEW.py` in this folder
for reference.

---

## Test Results After This Change

- 55/55 tests pass in `test_risk_engine.py` (45 pre-existing + 10 new sector/thematic tests)
- 23/23 tests pass in `test_execution_engine.py` (no regressions)
- 51/51 non-REST tests pass in `test_phase40_sector_exposure.py` (no regressions;
  9 REST endpoint tests require `fastapi` which is not installed in the Linux VM — pre-existing)
