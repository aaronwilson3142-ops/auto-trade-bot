"""
Phase 77 + 78 regression tests
==============================

Phase 77 (DEC-077): Alembic UNIQUE (security_id, opened_at) on positions.
The Phase 75 ``_persist_positions`` upsert already guarantees this property at
the Python layer; the migration adds a DB-level guard so any future regression
fails at the engine boundary instead of accumulating dupe rows silently.

Phase 78 (DEC-078): defence-in-depth ``Security.is_active = True`` filter at
both the signal-engine candidate-resolution layer
(``SignalEngineService._load_security_ids``) and the ranking-engine signal-load
layer (``RankingEngineService._load_signals_from_db``).  Mirrors the Phase 76
risk-engine ``inactive_ticker`` rule so HOLX (and the 13 stale delisted S&P 500
names) never enter the proposal pipeline at all.

These tests are DB-free: they inspect ORM ``__table_args__``, the Alembic
migration module, and the compiled SQL of the two filter call sites.
"""
from __future__ import annotations

import importlib
import re
import uuid
from unittest.mock import MagicMock

import sqlalchemy as sa

# ─────────────────────────────────────────────────────────────────────────────
# Phase 77 — UNIQUE (security_id, opened_at) on positions
# ─────────────────────────────────────────────────────────────────────────────


class TestPhase77UniqueConstraintORM:
    """ORM-level reflection of the new UNIQUE constraint."""

    def test_position_table_args_contains_unique_security_opened_at(self) -> None:
        from infra.db.models import Position

        constraints = [
            arg
            for arg in Position.__table_args__
            if isinstance(arg, sa.UniqueConstraint)
        ]
        assert constraints, "Position.__table_args__ must declare at least one UniqueConstraint"

        names = {c.name for c in constraints}
        assert "uq_positions_security_id_opened_at" in names, (
            f"Phase 77 UniqueConstraint missing; found {names}"
        )

        target = next(c for c in constraints if c.name == "uq_positions_security_id_opened_at")
        cols = [c.name for c in target.columns]
        assert cols == ["security_id", "opened_at"], (
            f"UniqueConstraint columns must be (security_id, opened_at); got {cols}"
        )

    def test_position_table_unique_constraint_visible_via_metadata(self) -> None:
        """Constraint must also be present on ``Position.__table__.constraints`` so
        ``Base.metadata.create_all`` and Alembic autogenerate diffs see it."""
        from infra.db.models import Position

        names = {
            c.name
            for c in Position.__table__.constraints
            if isinstance(c, sa.UniqueConstraint)
        }
        assert "uq_positions_security_id_opened_at" in names


class TestPhase77MigrationModule:
    """Alembic migration file shape — revision chain, table name, columns."""

    def test_migration_module_is_importable(self) -> None:
        mod = importlib.import_module(
            "infra.db.versions.q7r8s9t0u1v2_add_positions_unique_security_opened_at"
        )
        assert mod.revision == "q7r8s9t0u1v2"
        assert mod.down_revision == "p6q7r8s9t0u1"
        assert mod.branch_labels is None
        assert mod.depends_on is None

    def test_migration_constants_match_orm_names(self) -> None:
        """The migration's module-level constants must agree with the ORM
        ``__table_args__`` UniqueConstraint name + table name."""
        mod = importlib.import_module(
            "infra.db.versions.q7r8s9t0u1v2_add_positions_unique_security_opened_at"
        )
        assert mod._CONSTRAINT_NAME == "uq_positions_security_id_opened_at"
        assert mod._TABLE_NAME == "positions"

    def test_migration_upgrade_creates_unique_constraint(self) -> None:
        """Static check: upgrade() body references create_unique_constraint
        with the right table + columns. Avoids running real Alembic ops
        in a unit test."""
        import inspect

        mod = importlib.import_module(
            "infra.db.versions.q7r8s9t0u1v2_add_positions_unique_security_opened_at"
        )
        src = inspect.getsource(mod.upgrade)
        assert "create_unique_constraint" in src
        # Constraint name + table referenced via module constants — verify
        # the call site reaches them, not their literal values.
        assert "_CONSTRAINT_NAME" in src
        assert "_TABLE_NAME" in src
        # Must reference both columns of the constraint.
        assert "security_id" in src
        assert "opened_at" in src

    def test_migration_downgrade_drops_constraint(self) -> None:
        import inspect

        mod = importlib.import_module(
            "infra.db.versions.q7r8s9t0u1v2_add_positions_unique_security_opened_at"
        )
        src = inspect.getsource(mod.downgrade)
        assert "drop_constraint" in src
        assert "_CONSTRAINT_NAME" in src
        assert "_TABLE_NAME" in src
        assert 'type_="unique"' in src


# ─────────────────────────────────────────────────────────────────────────────
# Phase 78 — Strategy-side is_active=True filter (defence-in-depth)
# ─────────────────────────────────────────────────────────────────────────────


def _captured_select_sql(mock_session_execute_call) -> str:
    """Compile a captured SQLAlchemy select to a literal SQL string."""
    stmt = mock_session_execute_call.args[0]
    return str(
        stmt.compile(
            dialect=sa.dialects.postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


class TestPhase78SignalEngineIsActiveFilter:
    """SignalEngineService._load_security_ids must filter on is_active=True."""

    def test_load_security_ids_filters_by_is_active(self) -> None:
        from services.signal_engine.service import SignalEngineService

        session = MagicMock()
        session.execute.return_value.all.return_value = [("AAPL", uuid.uuid4())]

        SignalEngineService._load_security_ids(session, ["AAPL", "HOLX"])

        assert session.execute.called
        sql = _captured_select_sql(session.execute.call_args)

        # The compiled SQL must reference securities.is_active in the WHERE.
        # Match on the column reference rather than literal "= true" so the
        # test stays robust if the dialect renders the boolean differently.
        assert re.search(r"securities\.is_active", sql, re.IGNORECASE), (
            f"_load_security_ids must filter on is_active; compiled SQL: {sql}"
        )

    def test_load_security_ids_returns_only_resolved_tickers(self) -> None:
        """Inactive tickers (not returned by the SELECT) must be absent
        from the resolved dict — no silent zero-id stubs."""
        from services.signal_engine.service import SignalEngineService

        active_id = uuid.uuid4()
        session = MagicMock()
        # Simulate the DB returning only the active ticker AAPL.
        session.execute.return_value.all.return_value = [("AAPL", active_id)]

        result = SignalEngineService._load_security_ids(
            session, ["AAPL", "HOLX", "JNPR"]
        )
        assert result == {"AAPL": active_id}
        assert "HOLX" not in result
        assert "JNPR" not in result


class TestPhase78RankingEngineIsActiveFilter:
    """RankingEngineService._load_signals_from_db must filter on is_active=True."""

    def test_load_signals_from_db_filters_by_is_active(self) -> None:
        from services.ranking_engine.service import RankingEngineService

        session = MagicMock()
        session.execute.return_value.all.return_value = []

        RankingEngineService._load_signals_from_db(session, uuid.uuid4())

        assert session.execute.called
        sql = _captured_select_sql(session.execute.call_args)

        assert re.search(r"securities\.is_active", sql, re.IGNORECASE), (
            f"_load_signals_from_db must filter on is_active; compiled SQL: {sql}"
        )

    def test_load_signals_from_db_returns_empty_on_no_rows(self) -> None:
        """Sanity: when the filter excludes all rows, the result is an empty
        list, not None."""
        from services.ranking_engine.service import RankingEngineService

        session = MagicMock()
        session.execute.return_value.all.return_value = []

        outputs = RankingEngineService._load_signals_from_db(session, uuid.uuid4())
        assert outputs == []
