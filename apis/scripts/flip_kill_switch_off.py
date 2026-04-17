"""
Flip the kill switch OFF — DB + runtime.

Run with the APIS Python environment active:

    cd apis
    python scripts/flip_kill_switch_off.py

What it does
------------
1. Sets ``system_state.kill_switch_active = "false"`` in the DB (the value
   that ``_load_persisted_state`` reads on API startup).
2. Clears the ``activated_at`` / ``activated_by`` metadata.
3. Optionally POSTs to ``/api/v1/admin/kill-switch`` to flip the live
   runtime flag — if the API is up and ``APIS_OPERATOR_TOKEN`` is in env.

This is a deliberate safety toggle — run it only when you have verified
that the underlying issue that tripped the kill switch has been fixed.
"""
from __future__ import annotations

import os
import sys


def _flip_db_row() -> None:
    # Import lazily so the script still prints a sensible error if deps
    # are missing rather than blowing up at module import.
    from infra.db.models.system_state import (
        KEY_KILL_SWITCH_ACTIVATED_AT,
        KEY_KILL_SWITCH_ACTIVATED_BY,
        KEY_KILL_SWITCH_ACTIVE,
        SystemStateEntry,
    )
    from infra.db.session import db_session

    with db_session() as db:
        for key, val in (
            (KEY_KILL_SWITCH_ACTIVE, "false"),
            (KEY_KILL_SWITCH_ACTIVATED_AT, ""),
            (KEY_KILL_SWITCH_ACTIVATED_BY, ""),
        ):
            row = db.get(SystemStateEntry, key)
            if row is None:
                row = SystemStateEntry(key=key, value_text=val)
                db.add(row)
            else:
                row.value_text = val
        print(f"[ok] DB kill_switch_active set to 'false'")


def _flip_runtime_via_api() -> None:
    token = os.environ.get("APIS_OPERATOR_TOKEN")
    if not token:
        print("[skip] APIS_OPERATOR_TOKEN not set — skipping live API call")
        return
    host = os.environ.get("APIS_API_HOST", "127.0.0.1")
    port = os.environ.get("APIS_API_PORT", "8000")
    url = f"http://{host}:{port}/api/v1/admin/kill-switch"
    try:
        import httpx
    except Exception:
        print("[skip] httpx not installed — skipping live API call")
        return
    try:
        r = httpx.post(
            url,
            headers={"Authorization": f"Bearer {token}"},
            json={"active": False, "reason": "flip-off-after-phase63-recovery"},
            timeout=5.0,
        )
        r.raise_for_status()
        print(f"[ok] runtime kill_switch flipped off via API ({r.status_code})")
    except Exception as exc:
        print(f"[warn] API call failed ({exc}); DB value will take effect on next restart")


def main() -> int:
    # Make sure the 'apis' package root is on sys.path so imports work
    # whether this is run as 'python scripts/flip_kill_switch_off.py' or
    # 'python -m scripts.flip_kill_switch_off' from the apis/ directory.
    here = os.path.dirname(os.path.abspath(__file__))
    apis_root = os.path.abspath(os.path.join(here, ".."))
    if apis_root not in sys.path:
        sys.path.insert(0, apis_root)

    try:
        _flip_db_row()
    except Exception as exc:
        print(f"[error] DB flip failed: {exc}")
        return 1

    _flip_runtime_via_api()
    print("[done] kill switch is OFF")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
