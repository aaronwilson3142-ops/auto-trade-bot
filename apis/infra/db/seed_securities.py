"""Seed the ``securities`` table from the APIS universe config.

Run once at worker startup (idempotent — skips tickers that already exist).
Also seeds the ``themes`` and ``security_themes`` join table so that
sector / thematic concentration checks have reference data.

Usage
-----
Called automatically by ``apps/worker/main.py`` at startup.
Can also be run standalone::

    python -m infra.db.seed_securities
"""
from __future__ import annotations

import logging

import sqlalchemy as sa
from sqlalchemy.orm import Session

from config.universe import (
    TICKER_SECTOR,
    TICKER_THEME,
    UNIVERSE_TICKERS,
)
from infra.db.models.reference import Security, SecurityTheme, Theme

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Ticker → human-readable company name (good enough for reference data)
# ---------------------------------------------------------------------------
_TICKER_NAMES: dict[str, str] = {
    "AAPL": "Apple Inc.",
    "ABBV": "AbbVie Inc.",
    "AMD": "Advanced Micro Devices Inc.",
    "AMZN": "Amazon.com Inc.",
    "ANET": "Arista Networks Inc.",
    "ARM": "Arm Holdings plc",
    "ASML": "ASML Holding N.V.",
    "AVGO": "Broadcom Inc.",
    "BAC": "Bank of America Corp.",
    "BRK-B": "Berkshire Hathaway Inc. (Class B)",
    "CDNS": "Cadence Design Systems Inc.",
    "CEG": "Constellation Energy Corp.",
    "CIEN": "Ciena Corp.",
    "COP": "ConocoPhillips",
    "COST": "Costco Wholesale Corp.",
    "CRM": "Salesforce Inc.",
    "CRWD": "CrowdStrike Holdings Inc.",
    "CVX": "Chevron Corp.",
    "DDOG": "Datadog Inc.",
    "DELL": "Dell Technologies Inc.",
    "EQIX": "Equinix Inc.",
    "ETN": "Eaton Corp. plc",
    "FTNT": "Fortinet Inc.",
    "GOOGL": "Alphabet Inc. (Class A)",
    "GS": "Goldman Sachs Group Inc.",
    "HD": "The Home Depot Inc.",
    "HPE": "Hewlett Packard Enterprise Co.",
    "INTC": "Intel Corp.",
    "JNJ": "Johnson & Johnson",
    "JPM": "JPMorgan Chase & Co.",
    "LLY": "Eli Lilly and Co.",
    "MA": "Mastercard Inc.",
    "MDB": "MongoDB Inc.",
    "MRK": "Merck & Co. Inc.",
    "MRVL": "Marvell Technology Inc.",
    "MS": "Morgan Stanley",
    "MSFT": "Microsoft Corp.",
    "META": "Meta Platforms Inc.",
    "MU": "Micron Technology Inc.",
    "NKE": "Nike Inc.",
    "NOW": "ServiceNow Inc.",
    "NVDA": "NVIDIA Corp.",
    "NXPI": "NXP Semiconductors N.V.",
    "ON": "ON Semiconductor Corp.",
    "PANW": "Palo Alto Networks Inc.",
    "PFE": "Pfizer Inc.",
    "PLTR": "Palantir Technologies Inc.",
    "QCOM": "Qualcomm Inc.",
    "SBUX": "Starbucks Corp.",
    "SLB": "Schlumberger N.V.",
    "SMCI": "Super Micro Computer Inc.",
    "SNOW": "Snowflake Inc.",
    "TMO": "Thermo Fisher Scientific Inc.",
    "TSLA": "Tesla Inc.",
    "TSM": "Taiwan Semiconductor Manufacturing Co.",
    "TXN": "Texas Instruments Inc.",
    "UNH": "UnitedHealth Group Inc.",
    "V": "Visa Inc.",
    "VRT": "Vertiv Holdings Co.",
    "VST": "Vistra Corp.",
    "WMT": "Walmart Inc.",
    "XOM": "Exxon Mobil Corp.",
}

# Theme key → human-readable label
_THEME_LABELS: dict[str, str] = {
    "ai_infrastructure": "AI Infrastructure",
    "semiconductors": "Semiconductors",
    "cloud_software": "Cloud Software",
    "mega_cap_tech": "Mega-Cap Technology",
    "healthcare": "Healthcare",
    "financials": "Financials",
    "energy": "Energy",
    "consumer": "Consumer",
    "networking": "AI Networking",
    "power_infrastructure": "Power Infrastructure",
    "cybersecurity": "Cybersecurity",
    "ai_applications": "AI Applications",
    "data_centres": "Data Centre REITs",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def seed_securities(session: Session) -> int:
    """Insert any missing universe tickers into the ``securities`` table.

    Returns the number of newly inserted rows.
    """
    existing = {
        row[0]
        for row in session.execute(
            sa.select(Security.ticker).where(Security.ticker.in_(UNIVERSE_TICKERS))
        ).all()
    }

    new_rows: list[Security] = []
    for ticker in UNIVERSE_TICKERS:
        if ticker in existing:
            continue
        new_rows.append(
            Security(
                ticker=ticker,
                name=_TICKER_NAMES.get(ticker, ticker),
                asset_type="equity",
                sector=TICKER_SECTOR.get(ticker),
                country="US",
                currency="USD",
                is_active=True,
            )
        )

    if new_rows:
        session.add_all(new_rows)
        session.flush()

    return len(new_rows)


def seed_themes(session: Session) -> int:
    """Insert any missing theme rows into the ``themes`` table.

    Returns the number of newly inserted rows.
    """
    unique_themes = set(TICKER_THEME.values())
    existing = {
        row[0]
        for row in session.execute(
            sa.select(Theme.theme_key).where(Theme.theme_key.in_(unique_themes))
        ).all()
    }

    new_rows: list[Theme] = []
    for theme_key in sorted(unique_themes):
        if theme_key in existing:
            continue
        new_rows.append(
            Theme(
                theme_key=theme_key,
                theme_name=_THEME_LABELS.get(theme_key, theme_key.replace("_", " ").title()),
            )
        )

    if new_rows:
        session.add_all(new_rows)
        session.flush()

    return len(new_rows)


def seed_security_themes(session: Session) -> int:
    """Link securities to themes via the ``security_themes`` join table.

    Returns the number of newly inserted rows.
    """
    # Load id maps
    sec_map: dict[str, object] = {
        row.ticker: row.id
        for row in session.execute(sa.select(Security.ticker, Security.id)).all()
    }
    theme_map: dict[str, object] = {
        row.theme_key: row.id
        for row in session.execute(sa.select(Theme.theme_key, Theme.id)).all()
    }

    # Load existing pairs to avoid duplicates
    existing_pairs: set[tuple[object, object]] = {
        (row.security_id, row.theme_id)
        for row in session.execute(
            sa.select(SecurityTheme.security_id, SecurityTheme.theme_id)
        ).all()
    }

    new_rows: list[SecurityTheme] = []
    for ticker, theme_key in TICKER_THEME.items():
        sec_id = sec_map.get(ticker)
        th_id = theme_map.get(theme_key)
        if sec_id is None or th_id is None:
            continue
        if (sec_id, th_id) in existing_pairs:
            continue
        new_rows.append(
            SecurityTheme(
                security_id=sec_id,
                theme_id=th_id,
                relationship_type="primary",
                source_method="universe_config",
            )
        )

    if new_rows:
        session.add_all(new_rows)
        session.flush()

    return len(new_rows)


def run_all_seeds(session: Session) -> dict[str, int]:
    """Run all seed functions in dependency order. Returns counts."""
    counts = {
        "securities": seed_securities(session),
        "themes": seed_themes(session),
        "security_themes": seed_security_themes(session),
    }
    return counts


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from infra.db.session import db_session

    with db_session() as session:
        counts = run_all_seeds(session)

    for table, count in counts.items():
        print(f"  {table}: {count} rows inserted")
    print("Done.")
