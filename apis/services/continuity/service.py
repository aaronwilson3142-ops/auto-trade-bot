"""Continuity Service.

Responsibilities:
  1. take_snapshot(app_state, settings) → ContinuitySnapshot
       Serialize key ApiAppState fields into a portable snapshot object.
  2. save_snapshot(snapshot, path) → None
       Persist the snapshot as JSON to disk (fire-and-forget; never raises).
  3. load_snapshot(path) → Optional[ContinuitySnapshot]
       Read the most recent snapshot from disk.  Returns None when the file
       does not exist, is corrupt, or is too old (> max_snapshot_age_hours).
  4. get_session_context(app_state, settings) → SessionContext
       Produce a human-readable context dict for handoff-log entries.

Design rules
------------
- No DB access — file-based only so it can run even when Postgres is down.
- All I/O errors are swallowed and logged at WARNING; the service never
  raises to its callers.
- Path defaults come from ContinuityConfig; callers may override.

Spec references
---------------
- APIS_MASTER_SPEC.md § 3.5 (Continuity)
- SESSION_CONTINUITY_AND_EXECUTION_PROTOCOL.md § 5 (Mandatory Continuity Rule)
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
from typing import TYPE_CHECKING, Any

from services.continuity.config import ContinuityConfig
from services.continuity.models import ContinuitySnapshot, SessionContext

if TYPE_CHECKING:
    from apps.api.state import ApiAppState
    from config.settings import Settings

logger = logging.getLogger(__name__)


class ContinuityService:
    """Snapshot and session-context helper for ApiAppState.

    Args:
        config: Optional ContinuityConfig.  Defaults to ContinuityConfig().
    """

    def __init__(self, config: ContinuityConfig | None = None) -> None:
        self._config = config or ContinuityConfig()

    # ── Snapshot creation ─────────────────────────────────────────────────

    def take_snapshot(self, app_state: ApiAppState, settings: Settings) -> ContinuitySnapshot:
        """Serialize key ApiAppState fields into a ContinuitySnapshot.

        Args:
            app_state:  The shared ApiAppState singleton.
            settings:   Current Settings instance.

        Returns:
            ContinuitySnapshot populated with the current values.
        """
        ps = app_state.portfolio_state
        return ContinuitySnapshot(
            snapshot_at=dt.datetime.now(dt.UTC).isoformat(),
            operating_mode=settings.operating_mode.value,
            kill_switch_active=(
                app_state.kill_switch_active or bool(settings.kill_switch)
            ),
            paper_cycle_count=app_state.paper_cycle_count,
            portfolio_equity=float(ps.equity) if ps is not None else None,
            portfolio_cash=float(ps.cash) if ps is not None else None,
            portfolio_positions=len(ps.positions) if ps is not None else 0,
            ranking_count=len(app_state.latest_rankings),
            broker_auth_expired=app_state.broker_auth_expired,
            last_paper_cycle_at=(
                app_state.last_paper_cycle_at.isoformat()
                if app_state.last_paper_cycle_at is not None
                else None
            ),
            pending_proposals=len(app_state.improvement_proposals),
        )

    # ── Persistence ───────────────────────────────────────────────────────

    def save_snapshot(
        self,
        snapshot: ContinuitySnapshot,
        path: str | None = None,
    ) -> None:
        """Write *snapshot* as JSON to *path* (or the configured default).

        Never raises — I/O errors are logged at WARNING level only.

        Args:
            snapshot:  The snapshot to persist.
            path:      Optional override for the full file path.  Defaults to
                       ``{config.snapshot_dir}/{config.snapshot_filename}``.
        """
        if path is None:
            path = os.path.join(self._config.snapshot_dir, self._config.snapshot_filename)
        try:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(snapshot.to_dict(), fh, indent=2, default=str)
        except Exception as exc:  # noqa: BLE001
            logger.warning("continuity_save_snapshot_failed %s", exc)

    def load_snapshot(
        self,
        path: str | None = None,
    ) -> ContinuitySnapshot | None:
        """Read the latest snapshot from *path*.

        Returns None if the file does not exist, cannot be parsed,
        or is older than ``config.max_snapshot_age_hours``.

        Args:
            path:  Optional override; defaults to the configured path.

        Returns:
            Deserialized ContinuitySnapshot, or None.
        """
        if path is None:
            path = os.path.join(self._config.snapshot_dir, self._config.snapshot_filename)
        try:
            if not os.path.exists(path):
                return None
            # Staleness check
            mtime = os.path.getmtime(path)
            age_hours = (dt.datetime.now().timestamp() - mtime) / 3600
            if age_hours > self._config.max_snapshot_age_hours:
                logger.warning("continuity_snapshot_too_old %.1f hours", age_hours)
                return None
            with open(path, encoding="utf-8") as fh:
                data: dict[str, Any] = json.load(fh)
            return ContinuitySnapshot.from_dict(data)
        except Exception as exc:  # noqa: BLE001
            logger.warning("continuity_load_snapshot_failed %s", exc)
            return None

    # ── Session context ───────────────────────────────────────────────────

    def get_session_context(
        self,
        app_state: ApiAppState,
        settings: Settings,
    ) -> SessionContext:
        """Produce a human-readable SessionContext for handoff-log entries.

        Args:
            app_state:  The shared ApiAppState singleton.
            settings:   Current Settings instance.

        Returns:
            SessionContext populated with the current values.
        """
        snap = self.take_snapshot(app_state, settings)
        effective_kill = snap.kill_switch_active

        lines: list[str] = [
            f"mode={snap.operating_mode}",
            f"paper_cycles={snap.paper_cycle_count}",
            f"equity={snap.portfolio_equity}",
            f"positions={snap.portfolio_positions}",
            f"rankings={snap.ranking_count}",
            f"proposals={snap.pending_proposals}",
            f"kill_switch={'ACTIVE' if effective_kill else 'off'}",
            f"broker_auth={'expired' if snap.broker_auth_expired else 'ok'}",
        ]
        return SessionContext(
            snapshot_at=snap.snapshot_at,
            operating_mode=snap.operating_mode,
            paper_cycle_count=snap.paper_cycle_count,
            portfolio_equity=snap.portfolio_equity or 0.0,
            portfolio_positions=snap.portfolio_positions,
            kill_switch_active=effective_kill,
            broker_auth_expired=snap.broker_auth_expired,
            ranking_count=snap.ranking_count,
            pending_proposals=snap.pending_proposals,
            summary_lines=lines,
        )
