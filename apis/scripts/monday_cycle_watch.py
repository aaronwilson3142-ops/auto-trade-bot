"""
Monday 09:35 ET baseline paper-cycle watcher.

Run this after the first paper_trading_cycle_morning job fires on
Monday 2026-04-20 (or any post-maintenance baseline day) to confirm the
four watch-list checks from ``apis/state/NEXT_STEPS.md`` are green:

    (a) The cycle completed without ``broker_adapter_missing_with_live_positions``
        or ``_fire_ks()`` TypeErrors in the worker log.
    (b) Trades opened against the clean $100k cash ledger — no phantom
        broker ledger restoration from a prior crash-triad cycle.
    (c) New ``positions`` rows carry non-NULL ``origin_strategy`` (Step 5
        Deferred Finisher, commit d08875d, landed 2026-04-18).
    (d) The cycle itself wrote a new ``portfolio_snapshots`` row — i.e. not
        just the manual 2026-04-18 cleanup insert still being the latest
        row.

Usage (from the apis/ directory with the APIS Python env active)::

    cd apis
    python scripts/monday_cycle_watch.py                    # defaults to today
    python scripts/monday_cycle_watch.py --date 2026-04-20  # pin a day

Exit code is 0 if all four checks pass, 1 otherwise. The script prints a
small structured summary at the end that can be piped into HEALTH_LOG.md.

Design notes
------------
- Read-only by contract. No writes, no container manipulation.
- Fails loudly: each check prints what it found so an operator can
  triage without re-running.
- Keeps subprocess-to-docker dependency optional — if ``docker`` is not on
  PATH, the worker-log check is reported as ``skipped`` (not a hard fail)
  so the script is still useful on a devbox that queries a remote DB
  directly.
- Per-check output prefix: ``[ok]`` / ``[fail]`` / ``[skip]``.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass

# ──────────────────────────────────────────────────────────────────────────────
# Constants — the error patterns we are confirming the ABSENCE of
# ──────────────────────────────────────────────────────────────────────────────
FIRE_KS_ERROR = "_fire_ks() takes 0 positional arguments but 1 was given"
BROKER_MISSING_ERROR = "broker_adapter_missing_with_live_positions"

# Phantom-cleanup fingerprint the 2026-04-18 cleanup row carries.
PHANTOM_CLEANUP_NOTE = "Phantom broker state reset 2026-04-18"


# ──────────────────────────────────────────────────────────────────────────────
@dataclass
class CheckResult:
    name: str
    passed: bool | None  # None ⇒ skipped
    detail: str

    @property
    def prefix(self) -> str:
        if self.passed is None:
            return "[skip]"
        return "[ok]" if self.passed else "[fail]"


# ──────────────────────────────────────────────────────────────────────────────
# (a) Worker-log grep
# ──────────────────────────────────────────────────────────────────────────────
def check_worker_logs_clean(cycle_date: dt.date) -> CheckResult:
    """Grep docker-worker-1 logs for either crash signature since cycle_date 09:00 ET."""
    if shutil.which("docker") is None:
        return CheckResult(
            "worker_logs_clean",
            None,
            "docker not on PATH — skipping worker-log scrape (check manually: "
            f"`docker logs docker-worker-1 --since {cycle_date.isoformat()}T13:00:00 "
            f"| grep -E '_fire_ks|broker_adapter_missing'`)",
        )

    # Use --since with an ISO UTC timestamp. Cycle runs at 09:35 ET = 13:35 UTC
    # during EDT; we look back to 13:00 UTC to catch startup-phase errors too.
    since = f"{cycle_date.isoformat()}T13:00:00"
    try:
        result = subprocess.run(  # noqa: S603
            ["docker", "logs", "docker-worker-1", "--since", since],  # noqa: S607 — operator-only CLI shim; `docker` always in PATH
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return CheckResult("worker_logs_clean", False, "docker logs call timed out")
    except FileNotFoundError:
        return CheckResult(
            "worker_logs_clean",
            None,
            "docker binary vanished between shutil.which and subprocess.run — unusual",
        )

    combined = (result.stdout or "") + "\n" + (result.stderr or "")
    hits = []
    if FIRE_KS_ERROR in combined:
        hits.append(FIRE_KS_ERROR)
    if BROKER_MISSING_ERROR in combined:
        hits.append(BROKER_MISSING_ERROR)

    if hits:
        return CheckResult(
            "worker_logs_clean",
            False,
            f"found {len(hits)} known-bad pattern(s) since {since}: "
            + "; ".join(hits)
            + " — regression vs 63fa33e + d08875d; bisect immediately",
        )
    return CheckResult(
        "worker_logs_clean",
        True,
        f"no '_fire_ks' or 'broker_adapter_missing' patterns in worker logs since {since}",
    )


# ──────────────────────────────────────────────────────────────────────────────
# DB-backed checks — (b), (c), (d)
# ──────────────────────────────────────────────────────────────────────────────
def _db_session_factory():
    """Lazy import so the script still exits cleanly if APIS deps are missing."""
    from infra.db.session import db_session  # type: ignore

    return db_session


def check_portfolio_snapshot_written_today(cycle_date: dt.date) -> CheckResult:
    """Confirm the cycle wrote a portfolio_snapshots row on cycle_date — not just the cleanup row from 2026-04-18."""
    try:
        db_session = _db_session_factory()
    except Exception as exc:  # pragma: no cover - depends on env
        return CheckResult("portfolio_snapshot_written", False, f"db import failed: {exc}")

    from sqlalchemy import text  # type: ignore

    with db_session() as db:
        row = db.execute(
            text(
                """
                SELECT snapshot_date, cash, equity, gross_exposure, note
                FROM portfolio_snapshots
                ORDER BY snapshot_date DESC
                LIMIT 1
                """
            )
        ).fetchone()

    if row is None:
        return CheckResult(
            "portfolio_snapshot_written",
            False,
            "portfolio_snapshots is empty — expected at minimum the 2026-04-18 cleanup row",
        )

    snap_date, cash, equity, gross, note = row
    snap_iso = snap_date.isoformat() if hasattr(snap_date, "isoformat") else str(snap_date)

    if note and PHANTOM_CLEANUP_NOTE in str(note):
        return CheckResult(
            "portfolio_snapshot_written",
            False,
            f"latest snapshot is still the 2026-04-18 phantom cleanup row ({snap_iso}) — "
            f"cycle did not persist its own snapshot",
        )

    # Cash should be positive — phantom-triad runs left cash at ~ -$80k.
    if cash is not None and float(cash) < 0:
        return CheckResult(
            "portfolio_snapshot_written",
            False,
            f"snapshot {snap_iso} has cash={cash} — negative cash is a phantom-ledger regression",
        )

    if snap_date and hasattr(snap_date, "date"):
        snap_date_only = snap_date.date()
    elif isinstance(snap_date, dt.date):
        snap_date_only = snap_date
    else:
        snap_date_only = None

    if snap_date_only is not None and snap_date_only < cycle_date:
        return CheckResult(
            "portfolio_snapshot_written",
            False,
            f"latest snapshot is {snap_iso}, before cycle_date {cycle_date.isoformat()} — "
            f"cycle did not run or did not persist",
        )

    return CheckResult(
        "portfolio_snapshot_written",
        True,
        f"latest snapshot {snap_iso} cash={cash} equity={equity} gross={gross} — "
        f"written on/after cycle_date",
    )


def check_new_positions_have_origin_strategy(cycle_date: dt.date) -> CheckResult:
    """Confirm every position opened on or after cycle_date carries a non-NULL origin_strategy."""
    try:
        db_session = _db_session_factory()
    except Exception as exc:  # pragma: no cover
        return CheckResult("positions_origin_strategy", False, f"db import failed: {exc}")

    from sqlalchemy import text  # type: ignore

    with db_session() as db:
        rows = db.execute(
            text(
                """
                SELECT ticker, origin_strategy, opened_at
                FROM positions
                WHERE opened_at >= :cycle_date
                ORDER BY opened_at DESC
                """
            ),
            {"cycle_date": dt.datetime.combine(cycle_date, dt.time.min)},
        ).fetchall()

    if not rows:
        return CheckResult(
            "positions_origin_strategy",
            None,
            f"no positions opened on/after {cycle_date.isoformat()} — cycle may still be pending "
            f"or a no-open day; check portfolio_snapshot / worker log if unexpected",
        )

    missing = [r for r in rows if r.origin_strategy in (None, "")]
    if missing:
        sample = ", ".join(f"{r.ticker}@{r.opened_at}" for r in missing[:5])
        return CheckResult(
            "positions_origin_strategy",
            False,
            f"{len(missing)}/{len(rows)} new positions have NULL origin_strategy "
            f"(first 5: {sample}) — Step 5 wiring regression",
        )

    sample = ", ".join(f"{r.ticker}={r.origin_strategy}" for r in rows[:5])
    return CheckResult(
        "positions_origin_strategy",
        True,
        f"all {len(rows)} new positions carry origin_strategy (first 5: {sample})",
    )


def check_cash_against_clean_100k() -> CheckResult:
    """Confirm the broker ledger opens against a clean ~$100k starting point."""
    try:
        db_session = _db_session_factory()
    except Exception as exc:  # pragma: no cover
        return CheckResult("clean_100k_start", False, f"db import failed: {exc}")

    from sqlalchemy import text  # type: ignore

    # We use portfolio_snapshots as the proxy — the 2026-04-18 cleanup row was
    # cash=$100k / equity=$100k / gross=$0. A successful cycle should leave
    # cash+gross roughly equal to equity, with equity close to $100k before
    # any material P&L accumulates.
    with db_session() as db:
        row = db.execute(
            text(
                """
                SELECT cash, equity, gross_exposure
                FROM portfolio_snapshots
                ORDER BY snapshot_date DESC
                LIMIT 1
                """
            )
        ).fetchone()

    if row is None:
        return CheckResult("clean_100k_start", False, "portfolio_snapshots is empty")

    cash, equity, gross = (float(v) if v is not None else 0.0 for v in row)
    # Equity within $5k of $100k at the very first cycle is reasonable.
    # Later cycles may drift; the threshold is intentionally loose and is a
    # sanity check, not a P&L gate.
    if abs(equity - 100_000) > 5_000:
        return CheckResult(
            "clean_100k_start",
            False,
            f"equity={equity:.2f} drifts >$5k from $100k baseline — investigate before flipping flags",
        )
    if cash < 0:
        return CheckResult(
            "clean_100k_start",
            False,
            f"cash={cash:.2f} negative — phantom-ledger regression",
        )
    return CheckResult(
        "clean_100k_start",
        True,
        f"cash={cash:.2f} equity={equity:.2f} gross={gross:.2f} — clean $100k baseline holds",
    )


# ──────────────────────────────────────────────────────────────────────────────
def _ensure_apis_on_syspath() -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    apis_root = os.path.abspath(os.path.join(here, ".."))
    if apis_root not in sys.path:
        sys.path.insert(0, apis_root)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--date",
        default=dt.date.today().isoformat(),
        help="Cycle date in ISO format (default: today)",
    )
    args = parser.parse_args()

    try:
        cycle_date = dt.date.fromisoformat(args.date)
    except ValueError:
        print(f"[fatal] --date must be ISO YYYY-MM-DD, got {args.date!r}")
        return 2

    _ensure_apis_on_syspath()

    checks = [
        check_worker_logs_clean(cycle_date),
        check_cash_against_clean_100k(),
        check_new_positions_have_origin_strategy(cycle_date),
        check_portfolio_snapshot_written_today(cycle_date),
    ]

    print(f"# Monday baseline cycle watch — {cycle_date.isoformat()}")
    print()
    for c in checks:
        print(f"{c.prefix} {c.name}: {c.detail}")
    print()

    failed = [c for c in checks if c.passed is False]
    skipped = [c for c in checks if c.passed is None]
    if failed:
        print(f"[summary] {len(failed)} FAIL, {len(skipped)} skip, "
              f"{len(checks) - len(failed) - len(skipped)} ok — do NOT flip flags today")
        return 1
    if skipped:
        print(f"[summary] {len(skipped)} skip, {len(checks) - len(skipped)} ok — "
              f"resolve skips before flipping flags")
        return 0
    print(f"[summary] {len(checks)}/{len(checks)} ok — baseline cycle is green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
