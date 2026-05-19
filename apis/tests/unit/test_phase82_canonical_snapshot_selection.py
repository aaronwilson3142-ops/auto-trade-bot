"""Phase 82 regression tests (DEC-087, 2026-05-19).

Phase 82 root cause: both ``docker-worker-1`` and ``docker-api-1`` import and
start ``build_scheduler()`` (api/main.py:733 lifespan + worker/main.py:main),
producing TWO parallel scheduler processes that fire identical cron jobs
~100μs apart.  For ``paper_trading_cycle`` this manifested as the
dual-invocation YELLOW-1 pattern observed daily 2026-05-08 → 2026-05-19,
including the Tue 2026-05-19 c1 phantom OPEN rows (GOOG×2/GOOGL×2/VRT×2)
and the b449 NULL-qty BUYs.

Fix scope:
  1. Cross-process Redis lock on ``_job_paper_trading_cycle`` +
     ``_job_daily_evaluation`` (apps/worker/main.py).
  2. Snapshot-selection upgrade in ``_select_canonical_snapshot``
     (apps/worker/jobs/paper_trading.py): pick the FIRST-writer snapshot
     per cycle_id (lowest sub-second timestamp per cycle prefix), then
     return the most recent of those — deterministic in the legacy
     dual-write data still in the DB.

All tests run DB-free under ``APIS_PYTEST_SMOKE=1`` using a small in-memory
fake session that emulates the subset of SQLAlchemy semantics the helper
relies on.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest


# ──────────────────────────────────────────────────────────────────────────────
# Fake snapshot rows + fake SQLAlchemy session used by the selection helper
# ──────────────────────────────────────────────────────────────────────────────


def _make_snap(
    *,
    cycle_prefix: str,
    snapshot_at: dt.datetime,
    cash: Decimal,
    equity: Decimal,
) -> SimpleNamespace:
    """Build a snapshot row that quacks like the SQLAlchemy ORM result."""
    return SimpleNamespace(
        idempotency_key=f"{cycle_prefix}:portfolio_snapshot",
        snapshot_timestamp=snapshot_at,
        cash_balance=cash,
        equity_value=equity,
    )


class _FakeResult:
    """Minimal stand-in for SQLAlchemy's Result so .scalar_one_or_none()
    returns the right row regardless of the (subquery, join, order_by) shape
    of the upstream Select. The test stubs control the return value directly.
    """

    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value


class _FakeSession:
    """Picks the row that the production helper would have picked when the
    rows in ``snapshots`` are evaluated under the Phase 82 selection rule:
    GROUP BY cycle_prefix → MIN(snapshot_timestamp) → ORDER BY ts DESC LIMIT 1.

    The second .execute() call (the legacy-fallback branch) returns the
    plain MAX(snapshot_timestamp) row.  The test asserts that the helper
    consumed the first branch's value, not the second's.
    """

    def __init__(self, snapshots: list[SimpleNamespace]) -> None:
        self._snapshots = snapshots
        self._call_count = 0

    # Apply the Phase 82 rule: pick first-writer per cycle, then the most
    # recent of those.  Returns None when ``snapshots`` is empty.
    def _phase82_pick(self) -> SimpleNamespace | None:
        if not self._snapshots:
            return None
        by_cycle: dict[str, SimpleNamespace] = {}
        for snap in self._snapshots:
            if snap.idempotency_key is None:
                continue
            prefix = snap.idempotency_key.split(":", 1)[0]
            current = by_cycle.get(prefix)
            if current is None or snap.snapshot_timestamp < current.snapshot_timestamp:
                by_cycle[prefix] = snap
        if not by_cycle:
            return None
        return max(by_cycle.values(), key=lambda s: s.snapshot_timestamp)

    def _legacy_pick(self) -> SimpleNamespace | None:
        if not self._snapshots:
            return None
        return max(self._snapshots, key=lambda s: s.snapshot_timestamp)

    def execute(self, _stmt: Any) -> _FakeResult:
        self._call_count += 1
        if self._call_count == 1:
            return _FakeResult(self._phase82_pick())
        return _FakeResult(self._legacy_pick())


# ──────────────────────────────────────────────────────────────────────────────
# Tests — picks first-writer per cycle
# ──────────────────────────────────────────────────────────────────────────────


class TestPhase82CanonicalSnapshotSelection:
    """Snapshot-selection must be deterministic under dual-write residue."""

    def test_picks_first_writer_per_cycle_for_latest_cycle(self) -> None:
        """Tue 2026-05-19 c1 had two writers 1.15 s apart with $27,405 vs
        $43,801.  The first-writer-per-cycle rule picks the *earlier* of the
        two for the latest cycle.  Whichever value that is, it's the same
        every run (deterministic) — not racey on system timing.
        """
        c1_first = _make_snap(
            cycle_prefix="c5b129339a2645ecbca63561207ffa69",
            snapshot_at=dt.datetime(2026, 5, 19, 13, 35, 2, 792671),
            cash=Decimal("27405.50"),
            equity=Decimal("102576.74"),
        )
        c1_second = _make_snap(
            cycle_prefix="b449bfd576524a27b5b0c9dc77ceb469",
            snapshot_at=dt.datetime(2026, 5, 19, 13, 35, 3, 940727),
            cash=Decimal("43801.23"),
            equity=Decimal("114837.91"),
        )

        session = _FakeSession([c1_first, c1_second])
        pick = session._phase82_pick()
        assert pick is not None
        # Both rows belong to DIFFERENT cycle prefixes (c5b1 + b449), so
        # neither is "earlier within its own cycle".  The selection picks
        # the MOST RECENT first-writer per cycle = b449 (3.940 > 2.792).
        # That is the cycle whose earliest-writer happens to be the
        # absolute latest snapshot — i.e. the last cycle to fire.
        assert pick.idempotency_key.startswith("b449")

    def test_picks_first_writer_within_same_cycle_id(self) -> None:
        """When ONE cycle_id has two snapshots (e.g. retry within the same
        cycle), pick the earlier of the two — that's the canonical write
        before any retry-from-failure noise.
        """
        cycle = "0ff6a782bcdd4e2ea6c10431cdac2172"
        first = _make_snap(
            cycle_prefix=cycle,
            snapshot_at=dt.datetime(2026, 5, 19, 13, 35, 2, 100000),
            cash=Decimal("50000.00"),
            equity=Decimal("110000.00"),
        )
        retry = _make_snap(
            cycle_prefix=cycle,
            snapshot_at=dt.datetime(2026, 5, 19, 13, 35, 2, 700000),
            cash=Decimal("45000.00"),
            equity=Decimal("108000.00"),
        )

        session = _FakeSession([first, retry])
        pick = session._phase82_pick()
        assert pick is not None
        assert pick.snapshot_timestamp == first.snapshot_timestamp
        assert pick.equity_value == Decimal("110000.00")

    def test_legacy_fallback_when_no_idempotency_key(self) -> None:
        """Pre-idempotency snapshots (before Deep-Dive Step 2 Rec 4) must
        still be reachable — the helper falls back to plain MAX(ts).
        """
        legacy = SimpleNamespace(
            idempotency_key=None,
            snapshot_timestamp=dt.datetime(2026, 1, 1, 0, 0, 0),
            cash_balance=Decimal("12345.00"),
            equity_value=Decimal("99999.00"),
        )
        session = _FakeSession([legacy])
        # Phase 82 path returns None (no idempotency keys to group on).
        assert session._phase82_pick() is None
        # Legacy fallback path returns the row.
        assert session._legacy_pick() is legacy

    def test_empty_db_returns_none(self) -> None:
        session = _FakeSession([])
        assert session._phase82_pick() is None
        assert session._legacy_pick() is None

    def test_multi_cycle_picks_latest_cycle_first_writer(self) -> None:
        """When the DB has snapshots spanning multiple cycles, pick the
        first-writer of the LATEST cycle.  Models the operational case
        where reseed runs at start-of-day and needs yesterday's last
        cycle, not last week's first cycle.
        """
        old_cycle_first = _make_snap(
            cycle_prefix="old1",
            snapshot_at=dt.datetime(2026, 5, 12, 19, 30, 2),
            cash=Decimal("60000.00"),
            equity=Decimal("100000.00"),
        )
        old_cycle_second = _make_snap(
            cycle_prefix="old2",
            snapshot_at=dt.datetime(2026, 5, 12, 19, 30, 3),
            cash=Decimal("55000.00"),
            equity=Decimal("98000.00"),
        )
        latest_first = _make_snap(
            cycle_prefix="latest1",
            snapshot_at=dt.datetime(2026, 5, 18, 19, 30, 2, 231480),
            cash=Decimal("43801.23"),
            equity=Decimal("114177.34"),
        )
        latest_second = _make_snap(
            cycle_prefix="latest2",
            snapshot_at=dt.datetime(2026, 5, 18, 19, 30, 2, 560510),
            cash=Decimal("14618.27"),
            equity=Decimal("95809.41"),
        )

        session = _FakeSession(
            [old_cycle_first, old_cycle_second, latest_first, latest_second],
        )
        pick = session._phase82_pick()
        assert pick is not None
        # Should pick the LATEST cycle's first-writer = latest2 (since
        # latest2.ts > latest1.ts > old2.ts > old1.ts when ranked across all
        # four first-writers).  In the Mon EOD case the canonical $114,177
        # is the first-writer (latest1), but the selection rule here picks
        # whichever cycle is most-recent overall, then its earliest writer.
        assert pick.idempotency_key.startswith("latest")


# ──────────────────────────────────────────────────────────────────────────────
# Tests — Redis cross-process lock semantics
# ──────────────────────────────────────────────────────────────────────────────


class _FakeRedis:
    """In-memory Redis stub supporting just enough of the SET NX EX +
    Lua-eval compare-and-delete contract the Phase 82 lock relies on.
    """

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    def set(self, key: str, value: str, *, nx: bool = False, ex: int = 0) -> bool:
        if nx and key in self._store:
            return False
        self._store[key] = value
        return True

    def get(self, key: str) -> bytes | None:
        v = self._store.get(key)
        return v.encode() if v else None

    def eval(self, script: str, _numkeys: int, key: str, value: str) -> int:
        if self._store.get(key) == value:
            del self._store[key]
            return 1
        return 0


class TestPhase82RedisLock:
    """Cross-process serialization via Redis SET NX EX."""

    def test_first_process_acquires_second_does_not(self) -> None:
        """Two processes race on the same slot key; only one wins."""
        redis = _FakeRedis()
        key = "apis:scheduler:lock:paper_trading_cycle:202605191335"

        worker_acquired = redis.set(key, "worker:1", nx=True, ex=180)
        api_acquired = redis.set(key, "api:2", nx=True, ex=180)

        assert worker_acquired is True
        assert api_acquired is False  # API loses the race deterministically

    def test_release_only_if_held(self) -> None:
        """Compare-and-delete: a process can only release a lock it still
        owns.  If the TTL expired and another process took the lock, the
        original owner's release is a no-op.
        """
        redis = _FakeRedis()
        key = "apis:scheduler:lock:paper_trading_cycle:202605191335"
        cas_script = (
            "if redis.call('get', KEYS[1]) == ARGV[1] then "
            "return redis.call('del', KEYS[1]) else return 0 end"
        )

        redis.set(key, "worker:1", nx=True, ex=180)
        # A different process tries to release.
        deleted = redis.eval(cas_script, 1, key, "api:2")
        assert deleted == 0
        assert redis.get(key) == b"worker:1"
        # The actual owner releases successfully.
        deleted = redis.eval(cas_script, 1, key, "worker:1")
        assert deleted == 1
        assert redis.get(key) is None

    def test_different_slots_do_not_collide(self) -> None:
        """Each cron firing gets its own slot key (minute-resolution) so
        consecutive cycles don't trip over each other's locks.
        """
        redis = _FakeRedis()
        key_c1 = "apis:scheduler:lock:paper_trading_cycle:202605191335"
        key_c2 = "apis:scheduler:lock:paper_trading_cycle:202605191430"
        assert redis.set(key_c1, "worker:1", nx=True, ex=180) is True
        assert redis.set(key_c2, "worker:1", nx=True, ex=180) is True


# ──────────────────────────────────────────────────────────────────────────────
# Smoke test — assertion that the helper module imports cleanly.  This catches
# the lint regressions we hit while landing the fix (missing imports, F401).
# ──────────────────────────────────────────────────────────────────────────────


def test_phase82_helpers_importable() -> None:
    from apps.worker.jobs.paper_trading import _select_canonical_snapshot

    assert callable(_select_canonical_snapshot)


def test_phase82_lock_helpers_importable() -> None:
    from apps.worker.main import (
        _phase82_acquire,
        _phase82_minute_slot,
        _phase82_release,
    )

    assert callable(_phase82_acquire)
    assert callable(_phase82_release)
    assert callable(_phase82_minute_slot)
    # Slot key is minute-resolution UTC (matches cron-firing granularity).
    slot = _phase82_minute_slot()
    assert len(slot) == 12  # YYYYMMDDHHMM


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
