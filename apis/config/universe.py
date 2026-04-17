"""
APIS trading universe configuration.

Defines the default paper-trading universe. Expanded 2026-04-15 from 62 to
~500 US large-cap equities (S&P 500 constituents, approximate as of early
2026) with explicit AI/tech theme granularity on top. Further expanded
2026-04-16 with 5 high-conviction non-S&P AI names (CRWV, CLS, TLN, NVT, BE)
and cross-listed 4 INDUSTRIALS names (PWR, TT, HUBB, CARR) into AI buckets.

Any service that needs the ticker list should import `get_universe_tickers()`.

Notes on expansion:
- Existing AI/tech theme buckets (AI_INFRASTRUCTURE, AI_NETWORKING, etc.) are
  preserved first so that the TICKER_THEME mapping assigns the most specific
  theme to AI-adjacent names even when those names also appear in the broader
  S&P 500 sector buckets below.
- BRK-B uses dash format to match the existing code convention / broker tick.
- Where a ticker belongs to multiple buckets, the first segment encountered in
  `_build_universe()` wins for ordering; TICKER_THEME applies the most
  specific theme tag regardless of order.
"""
from __future__ import annotations

from typing import Final

# ---------------------------------------------------------------------------
# AI / thematic buckets (kept narrow so TICKER_THEME assigns specific themes)
# ---------------------------------------------------------------------------
MEGA_CAP_TECH: Final[list[str]] = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "GOOG", "AMZN", "META", "TSLA", "AVGO",
]

AI_INFRASTRUCTURE: Final[list[str]] = [
    "NVDA", "AMD", "INTC", "ARM", "MRVL", "SMCI", "DELL", "HPE",
    "CRWV",   # CoreWeave — pure-play AI cloud infrastructure (added 2026-04-16)
    "CLS",    # Celestica — Google TPU assembler, liquid-cooled rack integrator
]

SEMICONDUCTORS: Final[list[str]] = [
    "TSM", "ASML", "QCOM", "TXN", "MU", "NXPI", "ON", "LRCX", "KLAC", "AMAT",
    "ADI", "MCHP", "MPWR", "SWKS", "TER", "ENPH", "FSLR", "WDC", "STX", "GFS",
]

CLOUD_SOFTWARE: Final[list[str]] = [
    "MSFT", "AMZN", "GOOGL", "CRM", "NOW", "SNOW", "DDOG", "MDB", "ORCL",
    "ADBE", "INTU", "WDAY", "TEAM", "PANW", "ZS", "CRWD", "OKTA", "NET",
    "FTNT", "CHKP", "GEN", "ZM", "DOCU", "HUBS", "ANSS", "CDNS", "SNPS",
    "ADSK", "CRM", "PAYC", "PCTY", "MANH", "PTC", "TYL", "VRSN", "AKAM",
    "FFIV", "JKHY", "FIS", "FISV", "GPN", "CTSH", "IT", "EPAM", "ACN",
]

AI_NETWORKING: Final[list[str]] = [
    "ANET", "CIEN", "CSCO", "JNPR", "NTAP", "COHR",
]

AI_POWER_UTILITIES: Final[list[str]] = [
    "CEG", "VST", "ETN", "VRT", "NEE", "DUK", "SO", "AEP", "EXC", "XEL",
    "SRE", "D", "PCG", "ED", "EIX", "PPL", "CMS", "DTE", "WEC", "AEE",
    "ATO", "ES", "FE", "LNT", "NI", "EVRG", "PNW", "AES", "CNP", "NRG",
    "TLN",    # Talen Energy — nuclear fleet for AI data centres (added 2026-04-16)
    "NVT",    # nVent Electric — liquid cooling specialist, 65% order surge
    "BE",     # Bloom Energy — onsite fuel-cell power for AI data centres
    "PWR",    # Quanta Services — $44B backlog, full electrical path (cross-listed from INDUSTRIALS)
    "TT",     # Trane Technologies — AI data centre cooling/HVAC (cross-listed)
    "HUBB",   # Hubbell — power infrastructure for data centres (cross-listed)
    "CARR",   # Carrier — data centre cooling systems (cross-listed)
]

AI_CYBERSECURITY: Final[list[str]] = [
    "PANW", "CRWD", "FTNT", "ZS", "OKTA", "NET", "CHKP", "GEN",
]

AI_SOFTWARE: Final[list[str]] = [
    "PLTR", "AI",
]

DATA_CENTER_REITS: Final[list[str]] = [
    "EQIX", "DLR",
]

EDA_CHIP_DESIGN: Final[list[str]] = [
    "CDNS", "SNPS",
]

# ---------------------------------------------------------------------------
# S&P 500 sector buckets (approximate constituents, early 2026)
# ---------------------------------------------------------------------------
HEALTHCARE: Final[list[str]] = [
    "LLY", "UNH", "JNJ", "ABBV", "MRK", "PFE", "TMO", "ABT", "DHR", "BMY",
    "AMGN", "GILD", "CVS", "MDT", "ELV", "ISRG", "SYK", "REGN", "VRTX",
    "ZTS", "CI", "BSX", "HCA", "IDXX", "BDX", "EW", "HUM", "BIIB", "ILMN",
    "IQV", "MCK", "COR", "DXCM", "A", "MTD", "RMD", "ALGN", "WST", "PKI",
    "STE", "INCY", "HOLX", "ZBH", "CAH", "WAT", "VTRS", "MRNA", "MOH",
    "CNC", "BAX", "UHS", "CTLT", "PODD", "TFX", "TECH", "DGX", "LH",
    "CRL", "HSIC", "DVA", "ORGN",
]

FINANCIALS: Final[list[str]] = [
    "JPM", "BAC", "GS", "MS", "V", "MA", "BRK-B", "WFC", "C", "AXP",
    "SCHW", "BLK", "SPGI", "MMC", "PGR", "CB", "ICE", "CME", "AON",
    "MCO", "USB", "PNC", "TFC", "COF", "BK", "STT", "TRV", "AIG", "AFL",
    "MET", "PRU", "ALL", "HIG", "WTW", "AJG", "BRO", "AMP", "FITB", "KEY",
    "RF", "HBAN", "CFG", "MTB", "CINF", "L", "PFG", "GL", "WRB", "RJF",
    "NTRS", "NDAQ", "CBOE", "IVZ", "MKTX", "BEN", "TROW", "FDS", "MSCI",
    "DFS", "SYF", "COF", "FIS", "FISV",
]

ENERGY: Final[list[str]] = [
    "XOM", "CVX", "COP", "SLB", "EOG", "PXD", "MPC", "PSX", "VLO", "OXY",
    "HES", "WMB", "KMI", "OKE", "BKR", "HAL", "DVN", "FANG", "MRO", "APA",
    "CTRA", "EQT", "TRGP", "LNG",
]

CONSUMER_DISCRETIONARY: Final[list[str]] = [
    "AMZN", "TSLA", "HD", "MCD", "NKE", "LOW", "SBUX", "BKNG", "TJX",
    "CMG", "MAR", "HLT", "ORLY", "AZO", "GM", "F", "LULU", "ROST", "YUM",
    "DHI", "LEN", "PHM", "NVR", "EBAY", "DPZ", "POOL", "ULTA", "DECK",
    "TSCO", "GPC", "BBY", "LVS", "WYNN", "CZR", "RL", "TPR", "LKQ",
    "WHR", "HAS", "MHK", "APTV", "BWA", "NCLH", "CCL", "RCL", "EXPE",
    "ABNB", "DRI", "GRMN", "MGM", "KMX", "BBWI", "VFC", "ETSY", "DLTR",
    "DG", "TGT",
]

CONSUMER_STAPLES: Final[list[str]] = [
    "WMT", "COST", "PG", "KO", "PEP", "PM", "MDLZ", "MO", "CL", "KMB",
    "GIS", "SYY", "KHC", "STZ", "KR", "ADM", "HSY", "MNST", "KDP", "TSN",
    "CHD", "CAG", "CPB", "SJM", "HRL", "K", "MKC", "CLX", "EL", "BG",
    "LW", "TAP", "BF-B",
]

INDUSTRIALS: Final[list[str]] = [
    "GE", "CAT", "HON", "UPS", "RTX", "BA", "LMT", "DE", "UNP", "ADP",
    "NOC", "MMM", "ITW", "CSX", "WM", "GD", "EMR", "FDX", "NSC", "PH",
    "CMI", "TT", "CARR", "OTIS", "PCAR", "ROK", "JCI", "LHX", "TDG",
    "FAST", "PAYX", "AME", "URI", "CTAS", "IR", "DOV", "XYL", "LUV",
    "DAL", "UAL", "AAL", "ALK", "CPRT", "EFX", "RSG", "WAB", "CHRW",
    "J", "PNR", "SWK", "NDSN", "SNA", "ODFL", "GWW", "FTV", "AOS",
    "ROL", "LDOS", "MAS", "ALLE", "JBHT", "EXPD", "WCN", "HEI", "TXT",
    "HUBB", "AXON", "HWM", "BLDR", "PWR", "URI", "VRSK",
]

MATERIALS: Final[list[str]] = [
    "LIN", "SHW", "APD", "ECL", "FCX", "NEM", "DOW", "DD", "CTVA", "PPG",
    "MLM", "VMC", "NUE", "STLD", "CF", "MOS", "LYB", "IFF", "ALB", "EMN",
    "CE", "PKG", "IP", "WRK", "AMCR", "BALL", "AVY", "SEE", "FMC",
]

REAL_ESTATE: Final[list[str]] = [
    "PLD", "AMT", "EQIX", "CCI", "PSA", "WELL", "DLR", "O", "SPG", "VICI",
    "EXR", "AVB", "EQR", "INVH", "MAA", "ESS", "UDR", "ARE", "WY", "SBAC",
    "VTR", "BXP", "KIM", "REG", "FRT", "HST", "CPT", "DOC", "IRM",
]

COMMUNICATION_SERVICES: Final[list[str]] = [
    "GOOGL", "GOOG", "META", "NFLX", "DIS", "CMCSA", "VZ", "T", "TMUS",
    "CHTR", "EA", "TTWO", "WBD", "PARA", "FOX", "FOXA", "OMC", "IPG",
    "NWS", "NWSA", "LYV", "MTCH", "DASH",
]

UTILITIES: Final[list[str]] = [
    "NEE", "DUK", "SO", "AEP", "EXC", "XEL", "SRE", "D", "PCG", "ED",
    "EIX", "PPL", "CMS", "DTE", "WEC", "AEE", "ATO", "ES", "FE", "LNT",
    "NI", "EVRG", "PNW", "AES", "CNP", "NRG", "AWK",
]

# ---------------------------------------------------------------------------
# Full universe — deduplicated, preserving order of first appearance
# ---------------------------------------------------------------------------
def _build_universe() -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for segment in [
        # AI/tech specific first so "most specific theme" wins downstream
        MEGA_CAP_TECH,
        AI_INFRASTRUCTURE,
        SEMICONDUCTORS,
        CLOUD_SOFTWARE,
        AI_NETWORKING,
        AI_POWER_UTILITIES,
        AI_CYBERSECURITY,
        AI_SOFTWARE,
        DATA_CENTER_REITS,
        EDA_CHIP_DESIGN,
        # Broad S&P 500 sector buckets
        HEALTHCARE,
        FINANCIALS,
        ENERGY,
        CONSUMER_DISCRETIONARY,
        CONSUMER_STAPLES,
        INDUSTRIALS,
        MATERIALS,
        REAL_ESTATE,
        COMMUNICATION_SERVICES,
        UTILITIES,
    ]:
        for ticker in segment:
            if ticker not in seen:
                seen.add(ticker)
                result.append(ticker)
    return result


UNIVERSE_TICKERS: Final[list[str]] = _build_universe()

# Back-compat alias: older code/tests expect a "CONSUMER" bucket.
CONSUMER: Final[list[str]] = CONSUMER_DISCRETIONARY + CONSUMER_STAPLES

# ---------------------------------------------------------------------------
# Sector mapping (used by ranking_engine / source reliability tags)
# ---------------------------------------------------------------------------
# NOTE: dict merge is last-wins for duplicate keys.  Since AI_POWER_UTILITIES
# now cross-lists PWR/TT/HUBB/CARR (originally INDUSTRIALS), their sector tag
# would flip to "utilities".  We override those back to "industrials" after the
# merge via _SECTOR_OVERRIDES so the sector concentration check uses the
# correct GICS sector, while the *theme* mapping (below) still assigns them
# the AI "power_infrastructure" theme they deserve.
_SECTOR_OVERRIDES: Final[dict[str, str]] = {
    "PWR": "industrials",
    "TT": "industrials",
    "HUBB": "industrials",
    "CARR": "industrials",
    # New non-S&P names: assign the most accurate GICS sector
    "CRWV": "technology",
    "CLS": "technology",
    "TLN": "utilities",
    "NVT": "industrials",
    "BE": "industrials",
}

TICKER_SECTOR: Final[dict[str, str]] = (
    dict.fromkeys(MEGA_CAP_TECH, "technology")
    | dict.fromkeys(AI_INFRASTRUCTURE, "technology")
    | dict.fromkeys(SEMICONDUCTORS, "technology")
    | dict.fromkeys(CLOUD_SOFTWARE, "technology")
    | dict.fromkeys(AI_NETWORKING, "technology")
    | dict.fromkeys(AI_CYBERSECURITY, "technology")
    | dict.fromkeys(AI_SOFTWARE, "technology")
    | dict.fromkeys(EDA_CHIP_DESIGN, "technology")
    | dict.fromkeys(DATA_CENTER_REITS, "real_estate")
    | dict.fromkeys(AI_POWER_UTILITIES, "utilities")
    | dict.fromkeys(HEALTHCARE, "healthcare")
    | dict.fromkeys(FINANCIALS, "financials")
    | dict.fromkeys(ENERGY, "energy")
    | dict.fromkeys(CONSUMER_DISCRETIONARY, "consumer_discretionary")
    | dict.fromkeys(CONSUMER_STAPLES, "consumer_staples")
    | dict.fromkeys(INDUSTRIALS, "industrials")
    | dict.fromkeys(MATERIALS, "materials")
    | dict.fromkeys(REAL_ESTATE, "real_estate")
    | dict.fromkeys(COMMUNICATION_SERVICES, "communication_services")
    | dict.fromkeys(UTILITIES, "utilities")
    | _SECTOR_OVERRIDES
)


# ---------------------------------------------------------------------------
# Theme mapping (used for thematic concentration checks).
# Most specific theme wins.  Earlier assignments win on collision because we
# build the dict with AI/tech themes first, then broader sectors, and use
# setdefault-equivalent ordering.
# ---------------------------------------------------------------------------
def _build_ticker_theme() -> dict[str, str]:
    theme: dict[str, str] = {}
    # Most specific AI/tech themes first
    for t in AI_INFRASTRUCTURE:
        theme.setdefault(t, "ai_infrastructure")
    for t in EDA_CHIP_DESIGN:
        theme.setdefault(t, "semiconductors")
    for t in SEMICONDUCTORS:
        theme.setdefault(t, "semiconductors")
    for t in AI_NETWORKING:
        theme.setdefault(t, "networking")
    for t in AI_CYBERSECURITY:
        theme.setdefault(t, "cybersecurity")
    for t in AI_SOFTWARE:
        theme.setdefault(t, "ai_applications")
    for t in DATA_CENTER_REITS:
        theme.setdefault(t, "data_centres")
    for t in AI_POWER_UTILITIES:
        theme.setdefault(t, "power_infrastructure")
    for t in CLOUD_SOFTWARE:
        theme.setdefault(t, "cloud_software")
    for t in MEGA_CAP_TECH:
        theme.setdefault(t, "mega_cap_tech")
    # Broader sector themes
    for t in HEALTHCARE:
        theme.setdefault(t, "healthcare")
    for t in FINANCIALS:
        theme.setdefault(t, "financials")
    for t in ENERGY:
        theme.setdefault(t, "energy")
    for t in CONSUMER_DISCRETIONARY:
        theme.setdefault(t, "consumer_discretionary")
    for t in CONSUMER_STAPLES:
        theme.setdefault(t, "consumer_staples")
    for t in INDUSTRIALS:
        theme.setdefault(t, "industrials")
    for t in MATERIALS:
        theme.setdefault(t, "materials")
    for t in REAL_ESTATE:
        theme.setdefault(t, "real_estate")
    for t in COMMUNICATION_SERVICES:
        theme.setdefault(t, "communication_services")
    for t in UTILITIES:
        theme.setdefault(t, "utilities")
    return theme


TICKER_THEME: Final[dict[str, str]] = _build_ticker_theme()


def get_universe_tickers(segment: str | None = None) -> list[str]:
    """Return the full universe ticker list, or a named segment subset."""
    segments: dict[str, list[str]] = {
        "mega_cap_tech": MEGA_CAP_TECH,
        "ai_infrastructure": AI_INFRASTRUCTURE,
        "semiconductors": SEMICONDUCTORS,
        "cloud_software": CLOUD_SOFTWARE,
        "ai_networking": AI_NETWORKING,
        "ai_power_utilities": AI_POWER_UTILITIES,
        "ai_cybersecurity": AI_CYBERSECURITY,
        "ai_software": AI_SOFTWARE,
        "data_center_reits": DATA_CENTER_REITS,
        "eda_chip_design": EDA_CHIP_DESIGN,
        "healthcare": HEALTHCARE,
        "financials": FINANCIALS,
        "energy": ENERGY,
        "consumer": CONSUMER,
        "consumer_discretionary": CONSUMER_DISCRETIONARY,
        "consumer_staples": CONSUMER_STAPLES,
        "industrials": INDUSTRIALS,
        "materials": MATERIALS,
        "real_estate": REAL_ESTATE,
        "communication_services": COMMUNICATION_SERVICES,
        "utilities": UTILITIES,
    }
    if segment is not None:
        return list(segments[segment])
    return list(UNIVERSE_TICKERS)
