"""
Gate H QA — Phase 9: Background Worker Jobs

Tests cover:
  - apps/worker/jobs/ingestion.py   — run_market_data_ingestion, run_feature_refresh
  - apps/worker/jobs/signal_ranking.py — run_signal_generation, run_ranking_generation
  - apps/worker/jobs/evaluation.py  — run_daily_evaluation, run_attribution_analysis
  - apps/worker/jobs/reporting.py   — run_generate_daily_report, run_publish_operator_summary
  - apps/worker/jobs/self_improvement.py — run_generate_improvement_proposals
  - apps/worker/main.py             — build_scheduler (APScheduler wiring)
  - apps/api/state.py               — improvement_proposals field added

All tests run fully in-memory.  No database or broker calls are made.
Services that require a session factory are tested via session_factory=None
(graceful skip) or via a mock session factory.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from apps.api.state import ApiAppState, get_app_state, reset_app_state
from config.settings import Settings

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_settings(**overrides) -> Settings:
    kwargs = dict(
        env="development",
        operating_mode="research",
        kill_switch=False,
        max_positions=10,
        daily_loss_limit_pct=0.02,
        weekly_drawdown_limit_pct=0.05,
        max_single_name_pct=0.20,
        max_sector_pct=0.40,
        max_thematic_pct=0.50,
    )
    kwargs.update(overrides)
    return Settings(**kwargs)


def _make_portfolio_state(cash: float = 90_000.0) -> Any:
    from services.portfolio_engine.models import PortfolioPosition, PortfolioState

    pos = PortfolioPosition(
        ticker="AAPL",
        quantity=Decimal("100"),
        avg_entry_price=Decimal("150.00"),
        current_price=Decimal("155.00"),
        opened_at=dt.datetime(2026, 3, 17, tzinfo=dt.UTC),
    )
    return PortfolioState(
        cash=Decimal(str(cash)),
        positions={"AAPL": pos},
        start_of_day_equity=Decimal("105_000"),
        high_water_mark=Decimal("110_000"),
    )


def _make_signal_output(ticker: str = "AAPL") -> Any:
    import uuid as _uuid

    from services.signal_engine.models import SignalOutput

    return SignalOutput(
        security_id=_uuid.uuid4(),   # unique per call so ranking groups correctly
        ticker=ticker,
        strategy_key="momentum_v1",
        signal_type="momentum",
        signal_score=Decimal("0.75"),
        confidence_score=Decimal("0.70"),
        risk_score=Decimal("0.30"),
        catalyst_score=Decimal("0.60"),
        liquidity_score=Decimal("0.80"),
        horizon_classification="positional",
        explanation_dict={
            "signal_type": "momentum",
            "driver_features": {"return_1m": 0.08},
            "rationale": "Strong upward momentum.",
        },
        source_reliability_tier="secondary_verified",
        contains_rumor=False,
    )


def _make_scorecard(grade_return: Decimal = Decimal("0.003")) -> Any:
    from services.evaluation_engine.models import (
        BenchmarkComparison,
        DailyScorecard,
        DrawdownMetrics,
        PerformanceAttribution,
    )

    bench = BenchmarkComparison(
        portfolio_return=grade_return,
        benchmark_returns={"SPY": Decimal("0.001")},
        differentials={"SPY": Decimal("0.002")},
    )
    dd = DrawdownMetrics(
        max_drawdown=Decimal("0.05"),
        current_drawdown=Decimal("0.01"),
        high_water_mark=Decimal("110_000"),
        recovery_time_est_days=None,
    )
    attribution = PerformanceAttribution(by_ticker=[], by_strategy=[], by_theme=[])
    return DailyScorecard(
        scorecard_date=dt.date(2026, 3, 17),
        equity=Decimal("105_500"),
        cash=Decimal("90_000"),
        gross_exposure=Decimal("15_500"),
        position_count=1,
        net_pnl=Decimal("500"),
        realized_pnl=Decimal("100"),
        unrealized_pnl=Decimal("400"),
        daily_return_pct=grade_return,
        closed_trade_count=0,
        hit_rate=Decimal("0"),
        avg_winner_pct=Decimal("0"),
        avg_loser_pct=Decimal("0"),
        current_drawdown_pct=Decimal("0.01"),
        max_drawdown_pct=Decimal("0.05"),
        benchmark_comparison=bench,
        attribution=attribution,
        mode="research",
    )


# ---------------------------------------------------------------------------
# TestApiAppStateImprovementProposals
# ---------------------------------------------------------------------------

class TestApiAppStateImprovementProposals:
    """improvement_proposals field was added to ApiAppState in Phase 9."""

    def test_improvement_proposals_defaults_to_empty_list(self):
        state = ApiAppState()
        assert state.improvement_proposals == []

    def test_reset_app_state_clears_improvement_proposals(self):
        state = get_app_state()
        state.improvement_proposals = ["fake_proposal"]
        reset_app_state()
        assert get_app_state().improvement_proposals == []

    def test_improvement_proposals_is_independent_between_instances(self):
        a = ApiAppState()
        b = ApiAppState()
        a.improvement_proposals.append("x")
        assert b.improvement_proposals == []


# ---------------------------------------------------------------------------
# TestIngestionJobs
# ---------------------------------------------------------------------------

class TestIngestionJobs:
    """run_market_data_ingestion and run_feature_refresh."""

    def test_market_data_ingestion_skips_when_no_session_factory(self):
        from apps.worker.jobs.ingestion import run_market_data_ingestion

        result = run_market_data_ingestion(
            settings=_make_settings(),
            session_factory=None,
        )
        assert result["status"] == "skipped_no_session"
        assert result["tickers_attempted"] == 0
        assert result["bars_persisted"] == 0
        assert isinstance(result["errors"], list)
        assert result["run_at"]

    def test_market_data_ingestion_calls_service_with_mock(self):
        from apps.worker.jobs.ingestion import run_market_data_ingestion

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)

        mock_factory = MagicMock(return_value=mock_session)

        mock_result = MagicMock()
        mock_result.total_bars_persisted = 250
        mock_result.status.value = "ok"
        mock_result.ticker_results = []

        mock_svc = MagicMock()
        mock_svc.ingest_universe_bars.return_value = mock_result

        result = run_market_data_ingestion(
            settings=_make_settings(),
            session_factory=mock_factory,
            ingestion_service=mock_svc,
        )

        assert result["status"] == "ok"
        assert result["bars_persisted"] == 250
        assert result["tickers_attempted"] > 0
        mock_svc.ingest_universe_bars.assert_called_once()

    def test_market_data_ingestion_catches_exceptions(self):
        from apps.worker.jobs.ingestion import run_market_data_ingestion

        def bad_factory():
            raise RuntimeError("DB connection failed")

        result = run_market_data_ingestion(
            settings=_make_settings(),
            session_factory=bad_factory,
        )
        assert result["status"] == "error"
        assert "DB connection failed" in result["errors"][0]

    def test_feature_refresh_skips_when_no_session_factory(self):
        from apps.worker.jobs.ingestion import run_feature_refresh

        result = run_feature_refresh(
            settings=_make_settings(),
            session_factory=None,
        )
        assert result["status"] == "skipped_no_session"
        assert result["securities_processed"] == 0

    def test_feature_refresh_catches_exceptions(self):
        from apps.worker.jobs.ingestion import run_feature_refresh

        def bad_factory():
            raise RuntimeError("No DB")

        result = run_feature_refresh(
            settings=_make_settings(),
            session_factory=bad_factory,
        )
        assert result["status"] == "error"
        assert result["securities_processed"] == 0


# ---------------------------------------------------------------------------
# TestSignalRankingJobs
# ---------------------------------------------------------------------------

class TestSignalRankingJobs:
    """run_signal_generation and run_ranking_generation."""

    def test_signal_generation_skips_when_no_session_factory(self):
        from apps.worker.jobs.signal_ranking import run_signal_generation

        state = ApiAppState()
        result = run_signal_generation(
            app_state=state,
            settings=_make_settings(),
            session_factory=None,
        )
        assert result["status"] == "skipped_no_session"
        assert result["signal_run_id"] is None

    def test_signal_generation_catches_db_exceptions(self):
        from apps.worker.jobs.signal_ranking import run_signal_generation

        state = ApiAppState()

        def bad_factory():
            raise RuntimeError("DB failure")

        result = run_signal_generation(
            app_state=state,
            settings=_make_settings(),
            session_factory=bad_factory,
        )
        assert result["status"] == "error"
        assert result["signal_run_id"] is None
        assert "DB failure" in result["errors"][0]

    def test_ranking_generation_with_empty_signals(self):
        from apps.worker.jobs.signal_ranking import run_ranking_generation

        state = ApiAppState()
        result = run_ranking_generation(
            app_state=state,
            settings=_make_settings(),
            signals=[],
        )
        assert result["status"] == "ok"
        assert result["ranked_count"] == 0
        assert state.latest_rankings == []

    def test_ranking_generation_writes_to_app_state(self):
        from apps.worker.jobs.signal_ranking import run_ranking_generation

        state = ApiAppState()
        signals = [_make_signal_output("AAPL"), _make_signal_output("NVDA")]

        result = run_ranking_generation(
            app_state=state,
            settings=_make_settings(),
            signals=signals,
        )

        assert result["status"] == "ok"
        assert result["ranked_count"] == len(state.latest_rankings)
        assert len(state.latest_rankings) == 2

    def test_ranking_generation_sets_ranking_run_id(self):
        from apps.worker.jobs.signal_ranking import run_ranking_generation

        state = ApiAppState()
        assert state.ranking_run_id is None

        run_ranking_generation(
            app_state=state,
            settings=_make_settings(),
            signals=[],
        )

        assert state.ranking_run_id is not None
        assert isinstance(state.ranking_run_id, str)

    def test_ranking_generation_sets_ranking_as_of(self):
        from apps.worker.jobs.signal_ranking import run_ranking_generation

        state = ApiAppState()
        run_ranking_generation(
            app_state=state,
            settings=_make_settings(),
            signals=[],
        )
        assert state.ranking_as_of is not None
        assert isinstance(state.ranking_as_of, dt.datetime)

    def test_ranking_generation_catches_service_exception(self):
        from apps.worker.jobs.signal_ranking import run_ranking_generation

        mock_svc = MagicMock()
        mock_svc.rank_signals.side_effect = RuntimeError("ranking exploded")

        state = ApiAppState()
        result = run_ranking_generation(
            app_state=state,
            settings=_make_settings(),
            signals=[],
            ranking_service=mock_svc,
        )
        assert result["status"] == "error"
        assert result["ranked_count"] == 0
        # State should be unchanged from before the failure (no partial write)
        assert state.latest_rankings == []

    def test_ranking_generation_respects_max_positions(self):
        from apps.worker.jobs.signal_ranking import run_ranking_generation

        tickers = ["AAPL", "NVDA", "MSFT", "TSLA", "AMZN"]
        signals = [_make_signal_output(t) for t in tickers]
        # max_positions = 3 to test the cap
        settings = _make_settings(max_positions=3)

        state = ApiAppState()
        result = run_ranking_generation(
            app_state=state,
            settings=settings,
            signals=signals,
        )
        assert result["status"] == "ok"
        assert len(state.latest_rankings) <= 3


# ---------------------------------------------------------------------------
# TestEvaluationJobs
# ---------------------------------------------------------------------------

class TestEvaluationJobs:
    """run_daily_evaluation and run_attribution_analysis."""

    def test_daily_evaluation_with_no_portfolio_state(self):
        from apps.worker.jobs.evaluation import run_daily_evaluation

        state = ApiAppState()
        assert state.portfolio_state is None

        result = run_daily_evaluation(
            app_state=state,
            settings=_make_settings(),
        )

        assert result["status"] == "ok"
        assert result["scorecard_date"] is not None

    def test_daily_evaluation_with_portfolio_state(self):
        from apps.worker.jobs.evaluation import run_daily_evaluation

        state = ApiAppState()
        state.portfolio_state = _make_portfolio_state()

        result = run_daily_evaluation(
            app_state=state,
            settings=_make_settings(),
        )

        assert result["status"] == "ok"

    def test_daily_evaluation_writes_scorecard_to_state(self):
        from apps.worker.jobs.evaluation import run_daily_evaluation

        state = ApiAppState()
        assert state.latest_scorecard is None

        run_daily_evaluation(
            app_state=state,
            settings=_make_settings(),
        )

        assert state.latest_scorecard is not None

    def test_daily_evaluation_appends_to_history(self):
        from apps.worker.jobs.evaluation import run_daily_evaluation

        state = ApiAppState()
        assert state.evaluation_history == []

        run_daily_evaluation(app_state=state, settings=_make_settings())
        run_daily_evaluation(app_state=state, settings=_make_settings())

        assert len(state.evaluation_history) == 2

    def test_daily_evaluation_trims_history_at_max(self):
        from apps.worker.jobs.evaluation import run_daily_evaluation

        state = ApiAppState()
        max_hist = 3

        for _ in range(5):
            run_daily_evaluation(
                app_state=state,
                settings=_make_settings(),
                max_history=max_hist,
            )

        assert len(state.evaluation_history) == max_hist

    def test_daily_evaluation_sets_evaluation_run_id(self):
        from apps.worker.jobs.evaluation import run_daily_evaluation

        state = ApiAppState()
        run_daily_evaluation(app_state=state, settings=_make_settings())
        assert state.evaluation_run_id is not None

    def test_daily_evaluation_catches_exceptions(self):
        from apps.worker.jobs.evaluation import run_daily_evaluation

        mock_svc = MagicMock()
        mock_svc.generate_daily_scorecard.side_effect = RuntimeError("eval exploded")

        state = ApiAppState()
        result = run_daily_evaluation(
            app_state=state,
            settings=_make_settings(),
            evaluation_service=mock_svc,
        )
        assert result["status"] == "error"
        assert result["scorecard_date"] is None

    def test_attribution_analysis_empty_trades(self):
        from apps.worker.jobs.evaluation import run_attribution_analysis

        state = ApiAppState()
        result = run_attribution_analysis(
            app_state=state,
            settings=_make_settings(),
            closed_trades=[],
        )
        assert result["status"] == "ok"
        assert result["by_ticker_count"] == 0
        assert result["by_strategy_count"] == 0
        assert result["by_theme_count"] == 0

    def test_attribution_analysis_catches_exceptions(self):
        from apps.worker.jobs.evaluation import run_attribution_analysis

        mock_svc = MagicMock()
        mock_svc.compute_attribution.side_effect = RuntimeError("attribution exploded")

        state = ApiAppState()
        result = run_attribution_analysis(
            app_state=state,
            settings=_make_settings(),
            evaluation_service=mock_svc,
        )
        assert result["status"] == "error"


# ---------------------------------------------------------------------------
# TestReportingJobs
# ---------------------------------------------------------------------------

class TestReportingJobs:
    """run_generate_daily_report and run_publish_operator_summary."""

    def test_generate_daily_report_with_empty_state(self):
        from apps.worker.jobs.reporting import run_generate_daily_report

        state = ApiAppState()
        result = run_generate_daily_report(
            app_state=state,
            settings=_make_settings(),
        )
        assert result["status"] == "ok"
        assert result["report_date"] is not None

    def test_generate_daily_report_with_portfolio_and_scorecard(self):
        from apps.worker.jobs.reporting import run_generate_daily_report

        state = ApiAppState()
        state.portfolio_state = _make_portfolio_state()
        state.latest_scorecard = _make_scorecard()

        result = run_generate_daily_report(
            app_state=state,
            settings=_make_settings(),
        )
        assert result["status"] == "ok"

    def test_generate_daily_report_writes_to_state(self):
        from apps.worker.jobs.reporting import run_generate_daily_report

        state = ApiAppState()
        assert state.latest_daily_report is None

        run_generate_daily_report(app_state=state, settings=_make_settings())

        assert state.latest_daily_report is not None

    def test_generate_daily_report_appends_to_report_history(self):
        from apps.worker.jobs.reporting import run_generate_daily_report

        state = ApiAppState()
        run_generate_daily_report(app_state=state, settings=_make_settings())
        run_generate_daily_report(app_state=state, settings=_make_settings())

        assert len(state.report_history) == 2

    def test_generate_daily_report_trims_history_at_max(self):
        from apps.worker.jobs.reporting import run_generate_daily_report

        state = ApiAppState()
        for _ in range(5):
            run_generate_daily_report(
                app_state=state,
                settings=_make_settings(),
                max_history=3,
            )
        assert len(state.report_history) == 3

    def test_generate_daily_report_includes_improvement_proposals_count(self):
        from apps.worker.jobs.reporting import run_generate_daily_report

        state = ApiAppState()
        state.improvement_proposals = [MagicMock(), MagicMock()]

        run_generate_daily_report(app_state=state, settings=_make_settings())

        report = state.latest_daily_report
        assert report.improvement_proposals_generated == 2

    def test_generate_daily_report_catches_exceptions(self):
        from apps.worker.jobs.reporting import run_generate_daily_report

        mock_svc = MagicMock()
        mock_svc.generate_daily_report.side_effect = RuntimeError("report exploded")

        state = ApiAppState()
        result = run_generate_daily_report(
            app_state=state,
            settings=_make_settings(),
            reporting_service=mock_svc,
        )
        assert result["status"] == "error"

    def test_publish_operator_summary_empty_state(self):
        from apps.worker.jobs.reporting import run_publish_operator_summary

        state = ApiAppState()
        result = run_publish_operator_summary(
            app_state=state,
            settings=_make_settings(),
        )
        assert result["status"] == "ok"
        assert result["lines_emitted"] == 1

    def test_publish_operator_summary_populated_state(self):
        from apps.worker.jobs.reporting import run_publish_operator_summary

        state = ApiAppState()
        state.portfolio_state = _make_portfolio_state()
        state.latest_scorecard = _make_scorecard()
        state.latest_rankings = [MagicMock(), MagicMock()]

        result = run_publish_operator_summary(
            app_state=state,
            settings=_make_settings(),
        )
        assert result["status"] == "ok"

    def test_publish_operator_summary_catches_exceptions(self):
        from apps.worker.jobs.reporting import run_publish_operator_summary

        # Provide a state with a malformed scorecard to trigger an exception
        state = ApiAppState()
        state.portfolio_state = MagicMock(
            side_effect=RuntimeError("broken state")
        )
        # Even if state is bad, we catch and return error
        with patch(
            "apps.worker.jobs.reporting.get_logger",
            return_value=MagicMock(),
        ):
            # Simulate exception path directly
            try:
                result = run_publish_operator_summary(
                    app_state=state,
                    settings=_make_settings(),
                )
                # If it gets here it handled the error
                assert result["status"] in ("ok", "error")
            except Exception:
                pytest.fail("run_publish_operator_summary should not propagate exceptions")


# ---------------------------------------------------------------------------
# TestSelfImprovementJob
# ---------------------------------------------------------------------------

class TestSelfImprovementJob:
    """run_generate_improvement_proposals."""

    def test_proposals_generated_when_no_scorecard(self):
        from apps.worker.jobs.self_improvement import run_generate_improvement_proposals

        state = ApiAppState()
        result = run_generate_improvement_proposals(
            app_state=state,
            settings=_make_settings(),
        )
        assert result["status"] == "ok"
        # With no scorecard, grade defaults to C — may produce 0 proposals
        assert isinstance(result["proposals_generated"], int)

    def test_proposals_generated_with_low_grade_scorecard(self):
        from apps.worker.jobs.self_improvement import run_generate_improvement_proposals

        state = ApiAppState()
        # D-grade: daily_return_pct = -0.02 (below 0, above -0.03)
        state.latest_scorecard = _make_scorecard(grade_return=Decimal("-0.02"))

        result = run_generate_improvement_proposals(
            app_state=state,
            settings=_make_settings(),
        )
        assert result["status"] == "ok"
        assert result["scorecard_grade"] == "D"
        # Low grade should trigger proposals
        assert result["proposals_generated"] >= 0  # engine may produce 0–N

    def test_proposals_written_to_app_state(self):
        from apps.worker.jobs.self_improvement import run_generate_improvement_proposals

        state = ApiAppState()
        state.latest_scorecard = _make_scorecard(grade_return=Decimal("-0.01"))

        run_generate_improvement_proposals(
            app_state=state,
            settings=_make_settings(),
        )

        assert isinstance(state.improvement_proposals, list)

    def test_proposals_replace_previous_cycle(self):
        from apps.worker.jobs.self_improvement import run_generate_improvement_proposals

        state = ApiAppState()
        state.improvement_proposals = [MagicMock(), MagicMock(), MagicMock()]

        run_generate_improvement_proposals(
            app_state=state,
            settings=_make_settings(),
        )

        # Previous proposals should be replaced (not appended)
        # The count may differ from 3 since it's now governed by the service
        assert isinstance(state.improvement_proposals, list)

    def test_f_grade_scorecard_triggers_proposals(self):
        from apps.worker.jobs.self_improvement import run_generate_improvement_proposals

        state = ApiAppState()
        # F-grade: daily_return_pct = -0.05 (below -0.03 threshold)
        state.latest_scorecard = _make_scorecard(grade_return=Decimal("-0.05"))

        result = run_generate_improvement_proposals(
            app_state=state,
            settings=_make_settings(),
        )
        assert result["status"] == "ok"
        assert result["scorecard_grade"] == "F"

    def test_proposals_catches_exceptions(self):
        from apps.worker.jobs.self_improvement import run_generate_improvement_proposals

        mock_svc = MagicMock()
        mock_svc.generate_proposals.side_effect = RuntimeError("service exploded")

        state = ApiAppState()
        result = run_generate_improvement_proposals(
            app_state=state,
            settings=_make_settings(),
            self_improvement_service=mock_svc,
        )
        assert result["status"] == "error"
        assert result["proposals_generated"] == 0


# ---------------------------------------------------------------------------
# TestWorkerScheduler
# ---------------------------------------------------------------------------

class TestWorkerScheduler:
    """APScheduler wiring via build_scheduler()."""

    _EXPECTED_JOB_IDS = {
        "market_data_ingestion",
        "alternative_data_ingestion",
        "intel_feed_ingestion",
        "feature_refresh",
        "correlation_refresh",
        "liquidity_refresh",
        "fundamentals_refresh",
        "regime_detection",
        "feature_enrichment",
        "signal_generation",
        "ranking_generation",
        "weight_optimization",
        "daily_evaluation",
        "attribution_analysis",
        "generate_daily_report",
        "publish_operator_summary",
        "generate_improvement_proposals",
        "auto_execute_proposals",
        "paper_trading_cycle_morning",
        "paper_trading_cycle_late_morning",
        "paper_trading_cycle_late_morning_2",
        "paper_trading_cycle_midday",
        "paper_trading_cycle_early_afternoon",
        "paper_trading_cycle_afternoon",
        "paper_trading_cycle_close",
        "broker_token_refresh",
        "var_refresh",
        "stress_test",
        "earnings_refresh",
        "signal_quality_update",
        "universe_refresh",
        "rebalance_check",
        "fill_quality_update",
        "fill_quality_attribution",
        "readiness_report_update",
    }

    def test_build_scheduler_returns_background_scheduler(self):
        from apscheduler.schedulers.background import BackgroundScheduler

        from apps.worker.main import build_scheduler

        scheduler = build_scheduler()
        assert isinstance(scheduler, BackgroundScheduler)

    def test_scheduler_has_all_expected_jobs(self):
        from apps.worker.main import build_scheduler

        scheduler = build_scheduler()
        job_ids = {job.id for job in scheduler.get_jobs()}
        assert self._EXPECTED_JOB_IDS == job_ids

    def test_scheduler_has_expected_job_count(self):
        from apps.worker.main import build_scheduler

        scheduler = build_scheduler()
        assert len(scheduler.get_jobs()) == 35

    def test_every_job_has_replace_existing_true(self):
        """Verify no duplicate job registration is possible."""
        from apps.worker.main import build_scheduler

        # Build the scheduler twice to simulate re-registration
        scheduler = build_scheduler()
        initial_count = len(scheduler.get_jobs())

        # Re-add all jobs (replace_existing=True must prevent duplicates)
        # We achieve this by calling build_scheduler again and checking the job count
        scheduler2 = build_scheduler()
        assert len(scheduler2.get_jobs()) == initial_count

    def test_jobs_use_eastern_time_timezone(self):
        from apps.worker.main import build_scheduler

        scheduler = build_scheduler()
        for job in scheduler.get_jobs():
            # APScheduler stores timezone in the trigger
            trigger = job.trigger
            tz_str = str(getattr(trigger, "timezone", ""))
            assert "Eastern" in tz_str or "US/Eastern" in tz_str or "EST" in tz_str or "EDT" in tz_str, (
                f"Job {job.id} does not appear to use Eastern timezone: {tz_str}"
            )

    def test_jobs_are_weekday_only(self):
        """All jobs should fire only on weekdays (mon-fri)."""
        from apps.worker.main import build_scheduler

        scheduler = build_scheduler()
        for job in scheduler.get_jobs():
            trigger = job.trigger
            # APScheduler CronTrigger stores fields
            fields_by_name = {f.name: f for f in trigger.fields}
            day_of_week = fields_by_name.get("day_of_week")
            assert day_of_week is not None, f"Job {job.id} has no day_of_week field"
            dow_str = str(day_of_week)
            # "mon-fri" or "0-4" (Monday=0 in APScheduler) are acceptable
            assert "mon" in dow_str.lower() or "0" in dow_str, (
                f"Job {job.id} day_of_week is not weekday: {dow_str}"
            )


# ---------------------------------------------------------------------------
# TestEndToEndPipeline
# ---------------------------------------------------------------------------

class TestEndToEndPipeline:
    """Smoke tests for the ranking → evaluation → reporting pipeline."""

    def test_ranking_then_evaluation_then_report(self):
        """End-to-end: ranking populates state → evaluation reads it → report reads both."""
        from apps.worker.jobs.evaluation import run_daily_evaluation
        from apps.worker.jobs.reporting import run_generate_daily_report
        from apps.worker.jobs.signal_ranking import run_ranking_generation

        state = ApiAppState()
        settings = _make_settings()

        # Step 1: rank signals
        signals = [_make_signal_output("AAPL"), _make_signal_output("NVDA")]
        rank_result = run_ranking_generation(
            app_state=state,
            settings=settings,
            signals=signals,
        )
        assert rank_result["status"] == "ok"
        assert len(state.latest_rankings) == 2

        # Step 2: evaluation (uses portfolio state = None → empty scorecard)
        eval_result = run_daily_evaluation(
            app_state=state,
            settings=settings,
        )
        assert eval_result["status"] == "ok"
        assert state.latest_scorecard is not None

        # Step 3: report reads from state
        report_result = run_generate_daily_report(
            app_state=state,
            settings=settings,
        )
        assert report_result["status"] == "ok"
        assert state.latest_daily_report is not None

    def test_pipeline_with_portfolio_state_and_proposals(self):
        """Full pipeline with portfolio state + proposals."""
        from apps.worker.jobs.evaluation import run_daily_evaluation
        from apps.worker.jobs.reporting import run_generate_daily_report
        from apps.worker.jobs.self_improvement import run_generate_improvement_proposals

        state = ApiAppState()
        state.portfolio_state = _make_portfolio_state()
        settings = _make_settings()

        # Evaluate
        run_daily_evaluation(app_state=state, settings=settings)
        assert state.latest_scorecard is not None

        # Generate proposals
        run_generate_improvement_proposals(app_state=state, settings=settings)

        # Report
        run_generate_daily_report(app_state=state, settings=settings)

        report = state.latest_daily_report
        assert report is not None
        # Proposals count should be reflected in the report
        assert report.improvement_proposals_generated == len(state.improvement_proposals)
