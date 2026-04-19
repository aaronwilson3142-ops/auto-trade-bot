"""
Phase 57 Part 2 — Concrete InsiderFlowAdapter providers + enrichment wiring.

Covers (DEC-024 / 2026-04-18):
    - insider_flow_factory returns Null adapter on missing creds / unknown
      provider and never raises
    - QuiverQuantAdapter parses a realistic row into an InsiderFlowEvent,
      honours lookback_days, drops malformed rows, and swallows network errors
    - SECEdgarFormFourAdapter resolves tickers via injected CIK map, parses
      Form 4 XML into BUY/SELL events, skips unknown tickers, and requires
      a non-empty User-Agent
    - FeatureEnrichmentService wires the adapter through to overlay fields
      (score, confidence, age_days) and degrades gracefully on adapter errors

All HTTP is stubbed — no real network calls.
"""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any

import pytest

from services.data_ingestion.adapters.insider_flow_adapter import (
    InsiderFlowAdapter,
    InsiderFlowEvent,
    NullInsiderFlowAdapter,
)
from services.data_ingestion.adapters.insider_flow_factory import (
    _CompositeInsiderFlowAdapter,
    build_insider_flow_adapter,
)
from services.data_ingestion.adapters.quiverquant_adapter import QuiverQuantAdapter
from services.data_ingestion.adapters.sec_edgar_form4_adapter import (
    SECEdgarFormFourAdapter,
)
from services.feature_store.enrichment import FeatureEnrichmentService
from services.feature_store.models import FeatureSet


# ---------------------------------------------------------------------------
# Fake HTTP plumbing
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, *, status_code: int, json_payload: Any = None, text: str = ""):
        self.status_code = status_code
        self._json_payload = json_payload
        self.text = text

    def json(self) -> Any:
        if isinstance(self._json_payload, Exception):
            raise self._json_payload
        return self._json_payload


class _FakeHttpClient:
    """Record calls and return the pre-loaded queue of responses."""

    def __init__(self, responses: list[_FakeResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, dict]] = []

    def get(self, url: str, headers: dict | None = None) -> _FakeResponse:
        self.calls.append((url, dict(headers or {})))
        if not self._responses:
            return _FakeResponse(status_code=500)
        return self._responses.pop(0)

    def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Dummy engine / intelligence stand-ins so we can spin up the enrichment
# service without touching the real implementations.
# ---------------------------------------------------------------------------


class _StubThemeEngine:
    def get_exposure(self, ticker: str) -> Any:
        class _M:
            mappings: list = []
        return _M()


class _StubMacroPolicy:
    def assess_regime(self, policy_signals: list) -> Any:
        class _R:
            class _RegimeEnum:
                value = "neutral"
            regime = _RegimeEnum()
        return _R()


class _StubNewsIntel:  # only referenced via default constructor path
    pass


# ---------------------------------------------------------------------------
# insider_flow_factory
# ---------------------------------------------------------------------------


class _StubSettings:
    def __init__(
        self,
        *,
        provider: str = "null",
        quiverquant_api_key: str = "",
        sec_edgar_user_agent: str = "",
    ) -> None:
        self.insider_flow_provider = provider
        self.quiverquant_api_key = quiverquant_api_key
        self.sec_edgar_user_agent = sec_edgar_user_agent


class TestInsiderFlowFactory:
    def test_default_null_returns_null_adapter(self) -> None:
        adapter = build_insider_flow_adapter(settings=_StubSettings())
        assert isinstance(adapter, NullInsiderFlowAdapter)

    def test_unknown_provider_falls_back_to_null(self) -> None:
        adapter = build_insider_flow_adapter(
            settings=_StubSettings(provider="this_provider_does_not_exist")
        )
        assert isinstance(adapter, NullInsiderFlowAdapter)

    def test_quiverquant_missing_key_falls_back_to_null(self) -> None:
        adapter = build_insider_flow_adapter(
            settings=_StubSettings(provider="quiverquant", quiverquant_api_key="")
        )
        assert isinstance(adapter, NullInsiderFlowAdapter)

    def test_quiverquant_with_key_returns_real_adapter(self) -> None:
        adapter = build_insider_flow_adapter(
            settings=_StubSettings(
                provider="quiverquant", quiverquant_api_key="secret"
            )
        )
        assert isinstance(adapter, QuiverQuantAdapter)

    def test_sec_edgar_without_user_agent_falls_back(self) -> None:
        adapter = build_insider_flow_adapter(
            settings=_StubSettings(provider="sec_edgar", sec_edgar_user_agent="")
        )
        assert isinstance(adapter, NullInsiderFlowAdapter)

    def test_sec_edgar_with_user_agent_returns_real_adapter(self) -> None:
        adapter = build_insider_flow_adapter(
            settings=_StubSettings(
                provider="sec_edgar",
                sec_edgar_user_agent="APIS ops@example.com",
            )
        )
        assert isinstance(adapter, SECEdgarFormFourAdapter)

    def test_composite_both_creds_returns_composite(self) -> None:
        adapter = build_insider_flow_adapter(
            settings=_StubSettings(
                provider="composite",
                quiverquant_api_key="k",
                sec_edgar_user_agent="APIS ops@example.com",
            )
        )
        assert isinstance(adapter, _CompositeInsiderFlowAdapter)

    def test_composite_partial_creds_returns_single(self) -> None:
        adapter = build_insider_flow_adapter(
            settings=_StubSettings(
                provider="composite", quiverquant_api_key="k",
            )
        )
        assert isinstance(adapter, QuiverQuantAdapter)

    def test_composite_no_creds_falls_back_to_null(self) -> None:
        adapter = build_insider_flow_adapter(
            settings=_StubSettings(provider="composite")
        )
        assert isinstance(adapter, NullInsiderFlowAdapter)


# ---------------------------------------------------------------------------
# QuiverQuantAdapter
# ---------------------------------------------------------------------------


def _qq_row(
    *,
    transaction: str = "Purchase",
    txn_date: str = "2026-04-01",
    report_date: str = "2026-04-05",
    amount_low: str | None = "1001",
    amount_high: str | None = "15000",
    amount: str | None = None,
    actor: str = "Jane Doe",
) -> dict:
    row: dict[str, Any] = {
        "Transaction": transaction,
        "TransactionDate": txn_date,
        "ReportDate": report_date,
        "Representative": actor,
    }
    if amount is not None:
        row["Amount"] = amount
    if amount_low is not None:
        row["Range_Lower"] = amount_low
    if amount_high is not None:
        row["Range_Upper"] = amount_high
    return row


class TestQuiverQuantAdapter:
    def test_requires_api_key(self) -> None:
        with pytest.raises(ValueError):
            QuiverQuantAdapter(api_key="")

    def test_parses_buy_row_with_bracket_amount(self) -> None:
        http = _FakeHttpClient([
            _FakeResponse(status_code=200, json_payload=[_qq_row()]),
        ])
        adapter = QuiverQuantAdapter(
            api_key="k",
            min_interval_s=0.0,
            http_client=http,
        )
        events = adapter.fetch_events(
            ["NVDA"], lookback_days=90, as_of=dt.date(2026, 4, 18)
        )
        assert len(events) == 1
        ev = events[0]
        assert ev.ticker == "NVDA"
        assert ev.side == "BUY"
        assert ev.notional_usd == Decimal("8000.5")  # midpoint of 1001..15000
        assert ev.source_key == "quiverquant"
        assert ev.actor_type == "congress"
        assert ev.filing_date == dt.date(2026, 4, 5)
        assert ev.trade_date == dt.date(2026, 4, 1)

    def test_parses_sell_with_explicit_amount(self) -> None:
        http = _FakeHttpClient([
            _FakeResponse(
                status_code=200,
                json_payload=[
                    _qq_row(
                        transaction="sale_full",
                        amount="50000",
                        amount_low=None,
                        amount_high=None,
                    )
                ],
            )
        ])
        adapter = QuiverQuantAdapter(api_key="k", min_interval_s=0.0, http_client=http)
        events = adapter.fetch_events(
            ["MSFT"], lookback_days=90, as_of=dt.date(2026, 4, 18)
        )
        assert len(events) == 1
        assert events[0].side == "SELL"
        assert events[0].notional_usd == Decimal("50000")

    def test_unknown_transaction_is_skipped(self) -> None:
        http = _FakeHttpClient([
            _FakeResponse(
                status_code=200,
                json_payload=[_qq_row(transaction="option_exercise")],
            )
        ])
        adapter = QuiverQuantAdapter(api_key="k", min_interval_s=0.0, http_client=http)
        events = adapter.fetch_events(
            ["GOOG"], lookback_days=90, as_of=dt.date(2026, 4, 18)
        )
        assert events == []

    def test_row_outside_lookback_is_skipped(self) -> None:
        old = _qq_row(txn_date="2025-01-01", report_date="2025-01-05")
        http = _FakeHttpClient([_FakeResponse(status_code=200, json_payload=[old])])
        adapter = QuiverQuantAdapter(api_key="k", min_interval_s=0.0, http_client=http)
        events = adapter.fetch_events(
            ["AAPL"], lookback_days=30, as_of=dt.date(2026, 4, 18)
        )
        assert events == []

    def test_404_returns_empty_not_raises(self) -> None:
        http = _FakeHttpClient([_FakeResponse(status_code=404)])
        adapter = QuiverQuantAdapter(api_key="k", min_interval_s=0.0, http_client=http)
        assert adapter.fetch_events(["ZZZ"]) == []

    def test_500_with_retries_exhausted_returns_empty(self) -> None:
        http = _FakeHttpClient([
            _FakeResponse(status_code=500),
            _FakeResponse(status_code=500),
            _FakeResponse(status_code=500),
            _FakeResponse(status_code=500),
        ])
        adapter = QuiverQuantAdapter(
            api_key="k",
            min_interval_s=0.0,
            max_retries=2,
            http_client=http,
        )
        assert adapter.fetch_events(["AAPL"]) == []

    def test_authorization_header_sent(self) -> None:
        http = _FakeHttpClient([_FakeResponse(status_code=200, json_payload=[])])
        adapter = QuiverQuantAdapter(
            api_key="test-secret", min_interval_s=0.0, http_client=http
        )
        adapter.fetch_events(["AAPL"])
        assert http.calls
        url, headers = http.calls[0]
        assert "AAPL" in url
        assert headers.get("Authorization") == "Bearer test-secret"

    def test_empty_ticker_list_short_circuits(self) -> None:
        http = _FakeHttpClient([])
        adapter = QuiverQuantAdapter(api_key="k", min_interval_s=0.0, http_client=http)
        assert adapter.fetch_events([]) == []
        assert http.calls == []

    def test_malformed_row_is_skipped_not_raises(self) -> None:
        bad = {"Transaction": "Purchase"}  # no dates, no amount
        http = _FakeHttpClient([_FakeResponse(status_code=200, json_payload=[bad])])
        adapter = QuiverQuantAdapter(api_key="k", min_interval_s=0.0, http_client=http)
        assert adapter.fetch_events(["AAPL"]) == []


# ---------------------------------------------------------------------------
# SECEdgarFormFourAdapter
# ---------------------------------------------------------------------------


_FORM4_XML_BUY = """<?xml version="1.0"?>
<ownershipDocument>
  <reportingOwner>
    <reportingOwnerId>
      <rptOwnerName>John Insider</rptOwnerName>
    </reportingOwnerId>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <transactionDate><value>2026-04-02</value></transactionDate>
      <transactionCoding>
        <transactionCode>A</transactionCode>
      </transactionCoding>
      <transactionAmounts>
        <transactionShares><value>1000</value></transactionShares>
        <transactionPricePerShare><value>150.25</value></transactionPricePerShare>
      </transactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>
"""

_FORM4_XML_SELL = """<?xml version="1.0"?>
<ownershipDocument>
  <reportingOwner>
    <reportingOwnerId>
      <rptOwnerName>Sally Officer</rptOwnerName>
    </reportingOwnerId>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <transactionDate><value>2026-04-03</value></transactionDate>
      <transactionCoding>
        <transactionCode>D</transactionCode>
      </transactionCoding>
      <transactionAmounts>
        <transactionShares><value>500</value></transactionShares>
        <transactionPricePerShare><value>200.00</value></transactionPricePerShare>
      </transactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>
"""


class TestSECEdgarFormFourAdapter:
    def test_requires_user_agent(self) -> None:
        with pytest.raises(ValueError):
            SECEdgarFormFourAdapter(user_agent="")

    def test_skips_tickers_without_cik(self) -> None:
        http = _FakeHttpClient([])
        adapter = SECEdgarFormFourAdapter(
            user_agent="APIS ops@example.com",
            ticker_to_cik={},
            min_interval_s=0.0,
            http_client=http,
        )
        assert adapter.fetch_events(["AAPL"]) == []
        assert http.calls == []

    def test_pads_cik_in_submissions_url(self) -> None:
        http = _FakeHttpClient([
            _FakeResponse(
                status_code=200,
                text='{"filings": {"recent": {"form": [], "filingDate": [], "accessionNumber": [], "primaryDocument": []}}}',
            )
        ])
        adapter = SECEdgarFormFourAdapter(
            user_agent="APIS ops@example.com",
            ticker_to_cik={"AAPL": "320193"},
            min_interval_s=0.0,
            http_client=http,
        )
        adapter.fetch_events(["AAPL"], as_of=dt.date(2026, 4, 18))
        url, _ = http.calls[0]
        assert "CIK0000320193.json" in url

    def test_parses_buy_form4(self) -> None:
        submissions_json = (
            '{"filings": {"recent": {'
            '"form": ["4"],'
            '"filingDate": ["2026-04-05"],'
            '"accessionNumber": ["0000320193-26-000001"],'
            '"primaryDocument": ["wf-form4_1.xml"]'
            "}}}"
        )
        http = _FakeHttpClient([
            _FakeResponse(status_code=200, text=submissions_json),
            _FakeResponse(status_code=200, text=_FORM4_XML_BUY),
        ])
        adapter = SECEdgarFormFourAdapter(
            user_agent="APIS ops@example.com",
            ticker_to_cik={"AAPL": "320193"},
            min_interval_s=0.0,
            http_client=http,
        )
        events = adapter.fetch_events(
            ["AAPL"], lookback_days=90, as_of=dt.date(2026, 4, 18)
        )
        assert len(events) == 1
        ev = events[0]
        assert ev.ticker == "AAPL"
        assert ev.side == "BUY"
        assert ev.actor_type == "insider_form4"
        assert ev.notional_usd == Decimal("150250.00")  # 1000 * 150.25
        assert ev.filing_date == dt.date(2026, 4, 5)
        assert ev.source_key == "sec_edgar_form4"

    def test_parses_sell_form4(self) -> None:
        submissions_json = (
            '{"filings": {"recent": {'
            '"form": ["4"],'
            '"filingDate": ["2026-04-05"],'
            '"accessionNumber": ["0000789019-26-000002"],'
            '"primaryDocument": ["wf-form4_1.xml"]'
            "}}}"
        )
        http = _FakeHttpClient([
            _FakeResponse(status_code=200, text=submissions_json),
            _FakeResponse(status_code=200, text=_FORM4_XML_SELL),
        ])
        adapter = SECEdgarFormFourAdapter(
            user_agent="APIS ops@example.com",
            ticker_to_cik={"MSFT": "789019"},
            min_interval_s=0.0,
            http_client=http,
        )
        events = adapter.fetch_events(
            ["MSFT"], lookback_days=90, as_of=dt.date(2026, 4, 18)
        )
        assert len(events) == 1
        assert events[0].side == "SELL"
        assert events[0].notional_usd == Decimal("100000.00")

    def test_filters_non_form4(self) -> None:
        submissions_json = (
            '{"filings": {"recent": {'
            '"form": ["10-K"],'
            '"filingDate": ["2026-04-05"],'
            '"accessionNumber": ["0000320193-26-000001"],'
            '"primaryDocument": ["10k.htm"]'
            "}}}"
        )
        http = _FakeHttpClient([
            _FakeResponse(status_code=200, text=submissions_json),
        ])
        adapter = SECEdgarFormFourAdapter(
            user_agent="APIS ops@example.com",
            ticker_to_cik={"AAPL": "320193"},
            min_interval_s=0.0,
            http_client=http,
        )
        assert adapter.fetch_events(
            ["AAPL"], as_of=dt.date(2026, 4, 18)
        ) == []

    def test_form4_outside_lookback_is_skipped(self) -> None:
        submissions_json = (
            '{"filings": {"recent": {'
            '"form": ["4"],'
            '"filingDate": ["2024-01-01"],'
            '"accessionNumber": ["0000320193-24-000001"],'
            '"primaryDocument": ["wf-form4_1.xml"]'
            "}}}"
        )
        http = _FakeHttpClient([
            _FakeResponse(status_code=200, text=submissions_json),
        ])
        adapter = SECEdgarFormFourAdapter(
            user_agent="APIS ops@example.com",
            ticker_to_cik={"AAPL": "320193"},
            min_interval_s=0.0,
            http_client=http,
        )
        assert adapter.fetch_events(
            ["AAPL"], lookback_days=30, as_of=dt.date(2026, 4, 18)
        ) == []


# ---------------------------------------------------------------------------
# FeatureEnrichmentService insider-flow wiring
# ---------------------------------------------------------------------------


class _StaticInsiderFlowAdapter(InsiderFlowAdapter):
    """Test adapter: returns a fixed set of events regardless of input."""

    SOURCE_KEY = "test_static"

    def __init__(self, events: list[InsiderFlowEvent]) -> None:
        self._events = events
        self.fetch_calls = 0

    def fetch_events(
        self,
        tickers: list[str],
        lookback_days: int = 90,
        as_of: dt.date | None = None,
    ) -> list[InsiderFlowEvent]:
        self.fetch_calls += 1
        return list(self._events)


class _RaisingAdapter(InsiderFlowAdapter):
    SOURCE_KEY = "test_raising"

    def fetch_events(self, *a: Any, **kw: Any) -> list[InsiderFlowEvent]:
        raise RuntimeError("boom")


def _make_feature_set(ticker: str = "NVDA") -> FeatureSet:
    return FeatureSet(
        security_id=uuid.uuid4(),
        ticker=ticker,
        as_of_timestamp=dt.datetime(2026, 4, 18, tzinfo=dt.timezone.utc),
    )


class TestFeatureEnrichmentInsiderFlow:
    def test_no_adapter_injected_keeps_defaults(self) -> None:
        svc = FeatureEnrichmentService(
            theme_engine=_StubThemeEngine(),
            macro_policy=_StubMacroPolicy(),
            news_intelligence=_StubNewsIntel(),
        )
        fs = _make_feature_set()
        out = svc.enrich_batch([fs])
        assert out[0].insider_flow_score == 0.0
        assert out[0].insider_flow_confidence == 0.0
        assert out[0].insider_flow_age_days is None

    def test_adapter_events_populate_overlay(self) -> None:
        today = dt.date(2026, 4, 18)
        adapter = _StaticInsiderFlowAdapter([
            InsiderFlowEvent(
                ticker="NVDA",
                actor_type="congress",
                actor_name="x",
                side="BUY",
                notional_usd=Decimal("100000"),
                trade_date=today - dt.timedelta(days=5),
                filing_date=today - dt.timedelta(days=2),
                source_key="test",
                confidence=0.9,
            )
        ])
        svc = FeatureEnrichmentService(
            theme_engine=_StubThemeEngine(),
            macro_policy=_StubMacroPolicy(),
            news_intelligence=_StubNewsIntel(),
            insider_flow_adapter=adapter,
        )
        fs = _make_feature_set("NVDA")
        out = svc.enrich_batch([fs])
        assert out[0].insider_flow_score == 1.0
        assert out[0].insider_flow_confidence == pytest.approx(0.9)
        # age_days is floatish — aggregate uses today vs filing_date
        assert out[0].insider_flow_age_days is not None
        assert adapter.fetch_calls == 1

    def test_batch_fetches_once_per_call(self) -> None:
        today = dt.date(2026, 4, 18)
        adapter = _StaticInsiderFlowAdapter([
            InsiderFlowEvent(
                ticker="AAPL",
                actor_type="congress",
                actor_name="x",
                side="BUY",
                notional_usd=Decimal("50000"),
                trade_date=today - dt.timedelta(days=1),
                filing_date=today,
                source_key="test",
                confidence=1.0,
            ),
        ])
        svc = FeatureEnrichmentService(
            theme_engine=_StubThemeEngine(),
            macro_policy=_StubMacroPolicy(),
            news_intelligence=_StubNewsIntel(),
            insider_flow_adapter=adapter,
        )
        batch = [_make_feature_set(t) for t in ("AAPL", "NVDA", "MSFT")]
        svc.enrich_batch(batch)
        # One adapter.fetch_events() call regardless of batch size
        assert adapter.fetch_calls == 1

    def test_raising_adapter_degrades_gracefully(self) -> None:
        svc = FeatureEnrichmentService(
            theme_engine=_StubThemeEngine(),
            macro_policy=_StubMacroPolicy(),
            news_intelligence=_StubNewsIntel(),
            insider_flow_adapter=_RaisingAdapter(),
        )
        fs = _make_feature_set()
        out = svc.enrich_batch([fs])
        # Overlay defaults unchanged, no exception propagated
        assert out[0].insider_flow_score == 0.0
        assert out[0].insider_flow_confidence == 0.0

    def test_enrich_single_path_also_uses_adapter(self) -> None:
        today = dt.date(2026, 4, 18)
        adapter = _StaticInsiderFlowAdapter([
            InsiderFlowEvent(
                ticker="AAPL",
                actor_type="insider_form4",
                actor_name="x",
                side="SELL",
                notional_usd=Decimal("250000"),
                trade_date=today - dt.timedelta(days=3),
                filing_date=today - dt.timedelta(days=1),
                source_key="test",
                confidence=1.0,
            )
        ])
        svc = FeatureEnrichmentService(
            theme_engine=_StubThemeEngine(),
            macro_policy=_StubMacroPolicy(),
            news_intelligence=_StubNewsIntel(),
            insider_flow_adapter=adapter,
        )
        fs = _make_feature_set("AAPL")
        out = svc.enrich(fs)
        assert out.insider_flow_score == -1.0
