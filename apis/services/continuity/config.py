"""Continuity service configuration."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ContinuityConfig:
    """Configuration for ContinuityService.

    Attributes:
        snapshot_dir:  Directory (relative to repo root) where snapshot JSON
                       files are written.  Created on first use if it does not
                       exist.
        snapshot_filename:  File name inside *snapshot_dir* for the latest
                            snapshot.  Overwritten on each call to
                            ``save_snapshot``.
        max_snapshot_age_hours:  If the snapshot on disk is older than this,
                                 ``load_snapshot`` returns None so stale state
                                 is never silently restored.
    """

    snapshot_dir: str = "data/snapshots"
    snapshot_filename: str = "latest_state.json"
    max_snapshot_age_hours: int = 48
