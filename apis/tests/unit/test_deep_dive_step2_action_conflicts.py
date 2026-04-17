"""Deep-Dive Plan Step 2 Rec 2 — action-conflict detector tests.

Covers the full truth-table for ``resolve_action_conflicts``:

* Empty input → empty output, zero conflicts.
* No conflicts → input returned unchanged.
* OPEN vs CLOSE with different composite_scores → higher wins.
* OPEN vs CLOSE tied → OPEN wins by tie-break rule.
* Disabled feature flag → passthrough with zero conflicts.
* Alert function fired once per conflict.
* Three-way conflict (OPEN + CLOSE + CLOSE) resolves without double-dropping.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from services.action_orchestrator.invariants import (
    ActionConflict,
    ActionConflictReport,
    assert_no_action_conflicts,
    resolve_action_conflicts,
)


# ── Stub types mirroring PortfolioAction / RankedResult shape ─────────────────


@dataclass
class _EnumLike:
    """Minimal Enum-ish object with .value used by _action_type_str."""

    value: str


@dataclass
class _RR:
    composite_score: float | None = None


@dataclass
class _Action:
    ticker: str
    action_type: _EnumLike
    ranked_result: _RR | None = None
    # carry a marker for identity testing
    marker: str = ""


def _open(ticker: str, score: float | None = None, marker: str = "") -> _Action:
    return _Action(
        ticker=ticker,
        action_type=_EnumLike(value="open"),
        ranked_result=_RR(composite_score=score),
        marker=marker or f"{ticker}-OPEN",
    )


def _close(ticker: str, score: float | None = None, marker: str = "") -> _Action:
    return _Action(
        ticker=ticker,
        action_type=_EnumLike(value="close"),
        ranked_result=_RR(composite_score=score),
        marker=marker or f"{ticker}-CLOSE",
    )


def _trim(ticker: str, score: float | None = None, marker: str = "") -> _Action:
    return _Action(
        ticker=ticker,
        action_type=_EnumLike(value="trim"),
        ranked_result=_RR(composite_score=score),
        marker=marker or f"{ticker}-TRIM",
    )


class _Settings:
    def __init__(self, enabled: bool = True) -> None:
        self.action_conflict_detector_enabled = enabled


# ── Tests ────────────────────────────────────────────────────────────────────


def test_empty_actions_returns_empty_report():
    report = resolve_action_conflicts([])
    assert isinstance(report, ActionConflictReport)
    assert report.conflicts == []
    assert report.resolved_actions == []
    assert report.had_conflicts is False


def test_no_conflicts_passes_through():
    actions = [_open("AAPL", 0.5), _close("MSFT", 0.8), _trim("GOOGL", 0.3)]
    report = resolve_action_conflicts(actions)
    assert report.conflicts == []
    # Same objects, same order (identity preservation).
    assert [a.marker for a in report.resolved_actions] == [
        "AAPL-OPEN",
        "MSFT-CLOSE",
        "GOOGL-TRIM",
    ]


def test_open_close_conflict_higher_score_wins():
    """OPEN score 0.7, CLOSE score 0.2 → OPEN kept."""
    a_open = _open("AAPL", 0.7)
    a_close = _close("AAPL", 0.2)
    report = resolve_action_conflicts([a_open, a_close])

    assert len(report.conflicts) == 1
    conflict = report.conflicts[0]
    assert conflict.ticker == "AAPL"
    assert conflict.kept_action_type == "open"
    assert conflict.dropped_action_type == "close"
    assert conflict.resolution_reason == "higher_composite_score"

    assert len(report.resolved_actions) == 1
    assert report.resolved_actions[0].marker == "AAPL-OPEN"


def test_close_beats_open_when_close_score_higher():
    a_open = _open("AAPL", 0.1)
    a_close = _close("AAPL", 0.9)
    report = resolve_action_conflicts([a_open, a_close])

    assert len(report.conflicts) == 1
    conflict = report.conflicts[0]
    assert conflict.kept_action_type == "close"
    assert conflict.dropped_action_type == "open"


def test_tie_score_prefers_open():
    a_open = _open("AAPL", 0.5)
    a_close = _close("AAPL", 0.5)
    report = resolve_action_conflicts([a_close, a_open])  # put CLOSE first

    assert len(report.conflicts) == 1
    conflict = report.conflicts[0]
    assert conflict.kept_action_type == "open"
    assert conflict.resolution_reason == "tie_break_prefer_open"


def test_both_scores_none_ties_to_open():
    a_open = _open("AAPL")  # score None
    a_close = _close("AAPL")
    report = resolve_action_conflicts([a_close, a_open])

    assert len(report.conflicts) == 1
    assert report.conflicts[0].kept_action_type == "open"


def test_settings_flag_off_is_passthrough():
    """When action_conflict_detector_enabled=False, skip detection entirely."""
    a_open = _open("AAPL", 0.7)
    a_close = _close("AAPL", 0.2)
    settings = _Settings(enabled=False)
    report = resolve_action_conflicts([a_open, a_close], settings=settings)

    assert report.conflicts == []
    assert len(report.resolved_actions) == 2


def test_alert_fn_fires_once_per_conflict():
    """The alert callback is invoked once per conflict with the record."""
    a_open = _open("AAPL", 0.7)
    a_close = _close("AAPL", 0.2)
    b_open = _open("MSFT", 0.9)
    b_close = _close("MSFT", 0.1)

    calls: list[ActionConflict] = []

    def _alert(c: ActionConflict) -> None:
        calls.append(c)

    report = resolve_action_conflicts(
        [a_open, a_close, b_open, b_close], alert_fn=_alert
    )

    assert len(report.conflicts) == 2
    assert len(calls) == 2
    assert {c.ticker for c in calls} == {"AAPL", "MSFT"}


def test_alert_fn_exception_does_not_corrupt_result():
    a_open = _open("AAPL", 0.7)
    a_close = _close("AAPL", 0.2)

    def _bad_alert(_c: ActionConflict) -> None:
        raise RuntimeError("webhook down")

    # Should still produce a clean report even though alert raised.
    report = resolve_action_conflicts(
        [a_open, a_close], alert_fn=_bad_alert
    )
    assert len(report.conflicts) == 1
    assert len(report.resolved_actions) == 1


def test_different_tickers_do_not_conflict():
    """OPEN AAPL vs CLOSE MSFT is not a conflict (different tickers)."""
    actions = [_open("AAPL", 0.5), _close("MSFT", 0.5)]
    report = resolve_action_conflicts(actions)
    assert report.conflicts == []
    assert len(report.resolved_actions) == 2


def test_convenience_wrapper_returns_cleaned_list():
    a_open = _open("AAPL", 0.7)
    a_close = _close("AAPL", 0.2)

    cleaned = assert_no_action_conflicts([a_open, a_close])
    assert len(cleaned) == 1
    assert cleaned[0].marker == "AAPL-OPEN"


def test_open_vs_trim_is_not_a_conflict():
    """TRIM is a size-reducing action, not opposing to OPEN — pass through."""
    a_open = _open("AAPL", 0.5)
    a_trim = _trim("AAPL", 0.9)  # higher score but not OPEN/CLOSE pair
    report = resolve_action_conflicts([a_open, a_trim])
    assert report.conflicts == []
    assert len(report.resolved_actions) == 2


def test_multi_conflict_resolves_independently_per_ticker():
    actions = [
        _open("AAPL", 0.6),
        _close("AAPL", 0.1),  # should lose
        _open("MSFT", 0.1),  # should lose
        _close("MSFT", 0.6),
    ]
    report = resolve_action_conflicts(actions)

    assert len(report.conflicts) == 2
    survivors = {a.marker for a in report.resolved_actions}
    assert survivors == {"AAPL-OPEN", "MSFT-CLOSE"}
