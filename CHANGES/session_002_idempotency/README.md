# Session 002 — Fix Idempotency Key to Be Deterministic

**Date:** 2026-03-22
**Todo Item:** #2 — Fix idempotency key to be deterministic

---

## Problem

`ExecutionEngineService._make_idempotency_key()` was calling `uuid.uuid4()` on every
invocation:

```python
return f"{action.ticker}_{suffix}_{uuid.uuid4()}"
```

Because a fresh UUID is generated on every call, each retry of the same action submits
a brand-new key.  Both the paper broker and Alpaca adapter maintain a set of submitted
keys and raise `DuplicateOrderError` only when the same key is seen twice — so this
guard was completely bypassed by the rotating key.  A transient network hiccup (or a
crash-and-restart mid-execution) would result in duplicate orders being placed.

`PortfolioAction` already carries `id: str = field(default_factory=lambda: str(uuid.uuid4()))` —
a stable UUID generated **once** at action creation.  Using that as the key anchor
means all retries of the same action share the same idempotency key, enabling correct
broker-side deduplication.

---

## Files Changed

| File | Change |
|------|--------|
| `apis/services/execution_engine/service.py` | Replace `uuid.uuid4()` with `action.id` in `_make_idempotency_key`; remove unused `import uuid`; update module docstring |
| `apis/tests/unit/test_execution_engine.py` | 5 new tests in `TestIdempotencyKey` class |

---

## How to Revert This Change

### Option A — Copy from originals (simplest)

```
cd "<project root>"

copy CHANGES\session_002_idempotency\originals\execution_engine_service.py apis\services\execution_engine\service.py
copy CHANGES\session_002_idempotency\originals\test_execution_engine.py     apis\tests\unit\test_execution_engine.py
```

On Linux/Mac, use `cp` instead of `copy`.

### Option B — Apply patches in reverse (patch tool required)

```bash
cd "<project root>"

patch -R apis/services/execution_engine/service.py  < CHANGES/session_002_idempotency/execution_engine_service.patch
patch -R apis/tests/unit/test_execution_engine.py   < CHANGES/session_002_idempotency/test_execution_engine.patch
```

---

## Test Results After This Change

- 23/23 tests pass in `test_execution_engine.py` (18 pre-existing + 5 new idempotency tests)
- 29/29 tests pass in `test_risk_engine.py` (no regressions)
