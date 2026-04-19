"""
SEC EDGAR Form 4 insider-flow adapter (Phase 57 Part 2 — DEC-024 / 2026-04-18).

Supplementary free-tier provider pulling insider (officer / director / 10 %
owner) transactions from the SEC's public filings.  Normalises Form 4
disclosures into ``InsiderFlowEvent`` objects the enrichment pipeline can
aggregate.

SEC requirements (see https://www.sec.gov/os/accessing-edgar-data):
    * Every request must include a descriptive ``User-Agent`` with a contact
      email, e.g. ``"APIS Auto-Trade-Bot aaron@example.com"``.
    * Programmatic access is hard-capped at ~10 req/sec; we target ≤ 5 req/sec
      and apply exponential backoff on 429.

We use the per-ticker submissions JSON endpoint as the cheapest index
path (one request per ticker to discover recent Form 4 accession numbers)
then pull the per-filing Form 4 XML only when a filing falls inside the
lookback window.

Safety rules (from ``InsiderFlowAdapter`` contract):
    - NEVER raise on empty result sets → return []
    - NEVER raise on row / XML parse failures → log WARNING + skip
    - Return events with filing_date <= as_of (default: today UTC)

Default-OFF: the factory only wires this adapter when the provider is
selected AND ``sec_edgar_user_agent`` is set.  Missing User-Agent falls back
to ``NullInsiderFlowAdapter`` with a WARNING — never a crash.
"""
from __future__ import annotations

import datetime as dt
import logging
import random
import re
import time
from decimal import Decimal, InvalidOperation
from typing import Any
from xml.etree import ElementTree as ET

from services.data_ingestion.adapters.insider_flow_adapter import (
    InsiderFlowAdapter,
    InsiderFlowEvent,
)

logger = logging.getLogger(__name__)

SOURCE_KEY = "sec_edgar_form4"

DEFAULT_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
DEFAULT_FILING_INDEX_URL = (
    "https://www.sec.gov/cgi-bin/browse-edgar"
    "?action=getcompany&CIK={cik}&type=4&dateb=&owner=include&count=40"
)
DEFAULT_TIMEOUT_S = 10.0
DEFAULT_MIN_INTERVAL_S = 0.25  # 4 req/s — under SEC's 10 req/s cap
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_BASE_S = 1.0

# Form 4 "A" = acquired (BUY), "D" = disposed (SELL).  Other codes exist
# (e.g. gifts, option exercises) but they are noisy and non-directional; we
# treat only explicit A/D as flow-bearing.
_ACQUIRED_CODES = {"A"}
_DISPOSED_CODES = {"D"}

_NS = {"ns": "http://www.sec.gov/edgar/thirteenffiler"}  # unused; kept for docs


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        import math
        if isinstance(value, float) and math.isnan(value):
            return None
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _parse_iso_date(value: Any) -> dt.date | None:
    if value is None:
        return None
    if isinstance(value, dt.date):
        return value
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


class SECEdgarFormFourAdapter(InsiderFlowAdapter):
    """Pulls Form 4 insider transactions from SEC EDGAR.

    Args:
        user_agent: SEC-compliant UA string, e.g.
            ``"APIS Auto-Trade-Bot ops@example.com"``.  REQUIRED.
        ticker_to_cik: dict mapping upper-case ticker → 10-digit zero-padded
            CIK.  Injected so the adapter itself stays I/O-free for CIK
            resolution (the warehouse ``Security`` table already stores CIKs).
            Tickers missing from the map are silently skipped.
        timeout_s: per-request HTTP timeout.
        min_interval_s: minimum seconds between outbound requests.
        max_retries: max retries on 429 / 5xx / network errors.
        submissions_url_template / filing_index_url_template / http_client:
            override hooks for tests.
    """

    SOURCE_KEY: str = SOURCE_KEY

    def __init__(
        self,
        *,
        user_agent: str,
        ticker_to_cik: dict[str, str] | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        min_interval_s: float = DEFAULT_MIN_INTERVAL_S,
        max_retries: int = DEFAULT_MAX_RETRIES,
        submissions_url_template: str = DEFAULT_SUBMISSIONS_URL,
        filing_index_url_template: str = DEFAULT_FILING_INDEX_URL,
        http_client: Any = None,
    ) -> None:
        if not user_agent:
            raise ValueError(
                "SECEdgarFormFourAdapter requires a non-empty user_agent; "
                "SEC rejects anonymous programmatic traffic."
            )
        self._user_agent = user_agent
        self._ticker_to_cik = {
            k.upper(): self._pad_cik(v) for k, v in (ticker_to_cik or {}).items()
            if v
        }
        self._timeout_s = timeout_s
        self._min_interval_s = min_interval_s
        self._max_retries = max_retries
        self._submissions_url_template = submissions_url_template
        self._filing_index_url_template = filing_index_url_template
        self._http_client = http_client
        self._last_request_at: float = 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch_events(
        self,
        tickers: list[str],
        lookback_days: int = 90,
        as_of: dt.date | None = None,
    ) -> list[InsiderFlowEvent]:
        if not tickers:
            return []

        as_of = as_of or dt.datetime.utcnow().date()
        cutoff = as_of - dt.timedelta(days=max(1, lookback_days))

        events: list[InsiderFlowEvent] = []
        skipped_no_cik = 0

        for ticker in tickers:
            ticker_up = ticker.upper()
            cik = self._ticker_to_cik.get(ticker_up)
            if not cik:
                skipped_no_cik += 1
                continue

            try:
                submissions = self._fetch_submissions_json(cik)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "edgar_submissions_failed ticker=%s cik=%s error=%s",
                    ticker_up, cik, exc,
                )
                continue

            recent = (submissions or {}).get("filings", {}).get("recent", {})
            forms = recent.get("form", []) or []
            filing_dates = recent.get("filingDate", []) or []
            accession_nums = recent.get("accessionNumber", []) or []
            primary_docs = recent.get("primaryDocument", []) or []

            for form, fdate, accn, pdoc in zip(
                forms, filing_dates, accession_nums, primary_docs
            ):
                if form != "4":
                    continue
                fdate_parsed = _parse_iso_date(fdate)
                if fdate_parsed is None:
                    continue
                if fdate_parsed > as_of or fdate_parsed < cutoff:
                    continue

                try:
                    doc_events = self._fetch_form4(
                        ticker=ticker_up,
                        cik=cik,
                        accession=accn,
                        primary_document=pdoc,
                        filing_date=fdate_parsed,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "edgar_form4_failed ticker=%s accn=%s error=%s",
                        ticker_up, accn, exc,
                    )
                    continue

                events.extend(doc_events)

        if skipped_no_cik:
            logger.info(
                "edgar_skipped_no_cik count=%d (resolve via Security table)",
                skipped_no_cik,
            )
        logger.info(
            "edgar_fetch_ok tickers=%d events=%d lookback_days=%d",
            len(tickers), len(events), lookback_days,
        )
        return events

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _pad_cik(cik: Any) -> str:
        s = str(cik).strip()
        # Strip any "CIK" prefix then zero-pad to 10 digits (SEC convention).
        s = re.sub(r"^CIK", "", s, flags=re.IGNORECASE)
        try:
            return f"{int(s):010d}"
        except (ValueError, TypeError):
            return ""

    def _fetch_submissions_json(self, cik: str) -> dict[str, Any] | None:
        url = self._submissions_url_template.format(cik=cik)
        return self._http_json_get(url)

    def _fetch_form4(
        self,
        *,
        ticker: str,
        cik: str,
        accession: str,
        primary_document: str,
        filing_date: dt.date,
    ) -> list[InsiderFlowEvent]:
        """Pull one Form 4 XML doc and parse its non-derivative transactions."""
        # Accession format in JSON: "0001234567-23-000123" → strip dashes for path.
        accn_nodash = accession.replace("-", "")
        cik_int = int(cik)
        base = (
            f"https://www.sec.gov/Archives/edgar/data/"
            f"{cik_int}/{accn_nodash}/{primary_document}"
        )
        xml_text = self._http_text_get(base)
        if not xml_text:
            return []

        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as exc:
            logger.warning(
                "edgar_form4_xml_parse_failed ticker=%s accn=%s error=%s",
                ticker, accession, exc,
            )
            return []

        out: list[InsiderFlowEvent] = []
        reporter_name = self._xml_first_text(
            root, [".//rptOwnerName", ".//reportingOwnerId/rptOwnerName"]
        ) or "unknown"

        # Non-derivative transactions — the common open-market buy/sell case.
        for txn in root.findall(".//nonDerivativeTransaction"):
            side = self._classify_txn_code(
                self._xml_first_text(txn, [".//transactionCode"])
            )
            if side is None:
                continue

            shares = _to_decimal(
                self._xml_first_text(txn, [".//transactionShares/value"])
            )
            price = _to_decimal(
                self._xml_first_text(txn, [".//transactionPricePerShare/value"])
            )
            if shares is None or price is None:
                continue
            notional = (shares * price).copy_abs()
            if notional <= 0:
                continue

            tdate = _parse_iso_date(
                self._xml_first_text(txn, [".//transactionDate/value"])
            ) or filing_date

            out.append(
                InsiderFlowEvent(
                    ticker=ticker,
                    actor_type="insider_form4",
                    actor_name=reporter_name,
                    side=side,
                    notional_usd=notional,
                    trade_date=tdate,
                    filing_date=filing_date,
                    source_key=SOURCE_KEY,
                    confidence=1.0,  # SEC filings are authoritative
                    raw={
                        "accession": accession,
                        "cik": cik,
                        "primary_document": primary_document,
                    },
                )
            )
        return out

    @staticmethod
    def _classify_txn_code(code: str | None) -> str | None:
        if not code:
            return None
        c = code.strip().upper()
        if c in _ACQUIRED_CODES:
            return "BUY"
        if c in _DISPOSED_CODES:
            return "SELL"
        return None

    @staticmethod
    def _xml_first_text(node: ET.Element, paths: list[str]) -> str | None:
        for p in paths:
            found = node.find(p)
            if found is not None and found.text:
                return found.text.strip()
        return None

    # -- HTTP --------------------------------------------------------

    def _http_json_get(self, url: str) -> dict[str, Any] | None:
        resp_text = self._http_text_get(url)
        if not resp_text:
            return None
        try:
            import json
            return json.loads(resp_text)
        except Exception as exc:  # noqa: BLE001
            logger.warning("edgar_bad_json url=%s error=%s", url, exc)
            return None

    def _http_text_get(self, url: str) -> str | None:
        import httpx  # lazy

        headers = {
            "User-Agent": self._user_agent,
            "Accept-Encoding": "gzip, deflate",
            "Host": url.split("/", 3)[2] if "://" in url else "",
        }

        client = self._http_client
        owns_client = False
        if client is None:
            client = httpx.Client(timeout=self._timeout_s)
            owns_client = True

        try:
            for attempt in range(self._max_retries + 1):
                self._respect_rate_limit()
                try:
                    resp = client.get(url, headers=headers)
                except Exception as exc:  # noqa: BLE001
                    if attempt >= self._max_retries:
                        logger.warning(
                            "edgar_network_error url=%s attempts=%d error=%s",
                            url, attempt + 1, exc,
                        )
                        return None
                    self._backoff(attempt)
                    continue

                status = getattr(resp, "status_code", 0)
                if status == 200:
                    return getattr(resp, "text", "") or ""
                if status == 404:
                    return None
                if status == 429 or 500 <= status < 600:
                    if attempt >= self._max_retries:
                        logger.warning(
                            "edgar_retry_exhausted url=%s status=%d",
                            url, status,
                        )
                        return None
                    self._backoff(attempt)
                    continue
                logger.warning("edgar_bad_status url=%s status=%d", url, status)
                return None
            return None
        finally:
            if owns_client:
                try:
                    client.close()
                except Exception:  # noqa: BLE001
                    pass

    def _respect_rate_limit(self) -> None:
        now = time.monotonic()
        wait = self._min_interval_s - (now - self._last_request_at)
        if wait > 0:
            time.sleep(wait)
        self._last_request_at = time.monotonic()

    @staticmethod
    def _backoff(attempt: int) -> None:
        delay = DEFAULT_BACKOFF_BASE_S * (2 ** attempt)
        delay = random.uniform(0, delay)
        time.sleep(delay)
