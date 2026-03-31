"""theme_engine registry utilities.

Contains the static curated ticker → theme mapping registry for all
tickers in the APIS trading universe.  Covers the 12 canonical themes
defined in ThemeEngineConfig and the APIS Master Spec §7.4.
"""
from __future__ import annotations

from services.theme_engine.models import BeneficiaryOrder, ThemeMapping

# ---------------------------------------------------------------------------
# Static theme registry  — list[ThemeMapping] per ticker
# Curated to the 50-ticker APIS universe (config/universe.py)
# ---------------------------------------------------------------------------

TICKER_THEME_REGISTRY: dict[str, list[ThemeMapping]] = {
    # ── Mega-cap tech ────────────────────────────────────────────────────────
    "AAPL": [
        ThemeMapping("AAPL", "ai_applications", BeneficiaryOrder.SECOND_ORDER, 0.65,
                     "Apple Silicon and on-device AI (Core ML / NPU)"),
    ],
    "MSFT": [
        ThemeMapping("MSFT", "ai_applications", BeneficiaryOrder.DIRECT, 0.90,
                     "Azure OpenAI, Copilot, GitHub Copilot"),
        ThemeMapping("MSFT", "cloud_computing", BeneficiaryOrder.DIRECT, 0.95,
                     "Azure — No. 2 cloud platform"),
    ],
    "NVDA": [
        ThemeMapping("NVDA", "ai_infrastructure", BeneficiaryOrder.DIRECT, 0.99,
                     "H100/H200 GPUs are the dominant AI training accelerators"),
        ThemeMapping("NVDA", "semiconductor", BeneficiaryOrder.DIRECT, 0.95,
                     "Fabless semiconductor designer"),
        ThemeMapping("NVDA", "data_centres", BeneficiaryOrder.DIRECT, 0.85,
                     "Largest GPU supplier to hyperscaler data centres"),
    ],
    "GOOGL": [
        ThemeMapping("GOOGL", "ai_applications", BeneficiaryOrder.DIRECT, 0.90,
                     "Gemini LLM, DeepMind, AI Search"),
        ThemeMapping("GOOGL", "cloud_computing", BeneficiaryOrder.DIRECT, 0.85,
                     "Google Cloud Platform — No. 3 cloud"),
    ],
    "AMZN": [
        ThemeMapping("AMZN", "cloud_computing", BeneficiaryOrder.DIRECT, 0.98,
                     "AWS — No. 1 cloud platform by revenue"),
        ThemeMapping("AMZN", "ai_infrastructure", BeneficiaryOrder.SECOND_ORDER, 0.70,
                     "Trainium/Inferentia custom AI chips"),
    ],
    "META": [
        ThemeMapping("META", "ai_applications", BeneficiaryOrder.DIRECT, 0.85,
                     "Llama open-source LLM, AI ad targeting, Meta AI"),
        ThemeMapping("META", "ai_infrastructure", BeneficiaryOrder.SECOND_ORDER, 0.60,
                     "Massive GPU cluster capex"),
    ],
    "TSLA": [
        ThemeMapping("TSLA", "ai_applications", BeneficiaryOrder.DIRECT, 0.75,
                     "Full Self-Driving (FSD) neural net autonomy"),
        ThemeMapping("TSLA", "clean_energy", BeneficiaryOrder.DIRECT, 0.70,
                     "EV manufacturer and energy storage"),
    ],
    "AVGO": [
        ThemeMapping("AVGO", "semiconductor", BeneficiaryOrder.DIRECT, 0.90,
                     "ASICs, networking chips, RF semiconductors"),
        ThemeMapping("AVGO", "networking", BeneficiaryOrder.DIRECT, 0.85,
                     "Data-center networking silicon"),
        ThemeMapping("AVGO", "ai_infrastructure", BeneficiaryOrder.SECOND_ORDER, 0.70,
                     "Custom AI accelerators for hyperscalers"),
    ],
    # ── AI infrastructure ────────────────────────────────────────────────────
    "AMD": [
        ThemeMapping("AMD", "ai_infrastructure", BeneficiaryOrder.DIRECT, 0.82,
                     "MI300X GPU competing with NVIDIA for AI training"),
        ThemeMapping("AMD", "semiconductor", BeneficiaryOrder.DIRECT, 0.90,
                     "x86 CPUs (EPYC) and GPU (Instinct)"),
    ],
    "INTC": [
        ThemeMapping("INTC", "semiconductor", BeneficiaryOrder.DIRECT, 0.85,
                     "x86 CPUs, foundry (IFS), Gaudi AI accelerator"),
        ThemeMapping("INTC", "ai_infrastructure", BeneficiaryOrder.INDIRECT, 0.45,
                     "Gaudi AI chips still gaining market share"),
    ],
    "ARM": [
        ThemeMapping("ARM", "semiconductor", BeneficiaryOrder.DIRECT, 0.95,
                     "ISA licensor — almost all mobile and edge AI chips use ARM"),
        ThemeMapping("ARM", "ai_infrastructure", BeneficiaryOrder.DIRECT, 0.75,
                     "ARM Neoverse in cloud; on-device AI via NPU IP"),
    ],
    "MRVL": [
        ThemeMapping("MRVL", "semiconductor", BeneficiaryOrder.DIRECT, 0.85,
                     "Custom AI ASICs, data-center networking"),
        ThemeMapping("MRVL", "networking", BeneficiaryOrder.DIRECT, 0.80,
                     "Ethernet switching and custom silicon"),
        ThemeMapping("MRVL", "ai_infrastructure", BeneficiaryOrder.DIRECT, 0.75,
                     "Custom AI silicon for hyperscalers"),
    ],
    "SMCI": [
        ThemeMapping("SMCI", "ai_infrastructure", BeneficiaryOrder.DIRECT, 0.90,
                     "GPU server OEM — primary rack supplier for NVIDIA H-series"),
        ThemeMapping("SMCI", "data_centres", BeneficiaryOrder.DIRECT, 0.80,
                     "Complete AI server and rack systems"),
    ],
    "DELL": [
        ThemeMapping("DELL", "ai_infrastructure", BeneficiaryOrder.SECOND_ORDER, 0.70,
                     "PowerEdge AI servers; GPU server sales momentum"),
        ThemeMapping("DELL", "data_centres", BeneficiaryOrder.SECOND_ORDER, 0.65,
                     "Data center hardware infrastructure"),
    ],
    "HPE": [
        ThemeMapping("HPE", "ai_infrastructure", BeneficiaryOrder.SECOND_ORDER, 0.60,
                     "ProLiant AI servers; Cray supercomputing"),
    ],
    # ── Semiconductors ───────────────────────────────────────────────────────
    "TSM": [
        ThemeMapping("TSM", "semiconductor", BeneficiaryOrder.DIRECT, 0.99,
                     "World's largest contract chip fab (N3/N2)"),
        ThemeMapping("TSM", "ai_infrastructure", BeneficiaryOrder.DIRECT, 0.80,
                     "Manufactures all Nvidia H-series and AMD MI-series GPUs"),
    ],
    "ASML": [
        ThemeMapping("ASML", "semiconductor", BeneficiaryOrder.DIRECT, 0.99,
                     "Only EUV lithography equipment supplier — monopoly"),
    ],
    "QCOM": [
        ThemeMapping("QCOM", "semiconductor", BeneficiaryOrder.DIRECT, 0.90,
                     "Snapdragon SoC with on-device NPU for AI"),
        ThemeMapping("QCOM", "ai_applications", BeneficiaryOrder.SECOND_ORDER, 0.60,
                     "Edge AI inference via Snapdragon AI model"),
    ],
    "TXN": [
        ThemeMapping("TXN", "semiconductor", BeneficiaryOrder.DIRECT, 0.80,
                     "Analog and embedded semiconductors"),
    ],
    "MU": [
        ThemeMapping("MU", "semiconductor", BeneficiaryOrder.DIRECT, 0.88,
                     "DRAM and NAND memory"),
        ThemeMapping("MU", "ai_infrastructure", BeneficiaryOrder.DIRECT, 0.75,
                     "HBM3E memory critical for AI training"),
    ],
    "NXPI": [
        ThemeMapping("NXPI", "semiconductor", BeneficiaryOrder.DIRECT, 0.80,
                     "Automotive and industrial semiconductors"),
    ],
    "ON": [
        ThemeMapping("ON", "semiconductor", BeneficiaryOrder.DIRECT, 0.78,
                     "Power management and analog ICs"),
        ThemeMapping("ON", "clean_energy", BeneficiaryOrder.SECOND_ORDER, 0.55,
                     "SiC and GaN chips for EV powertrains"),
    ],
    # ── Cloud software ───────────────────────────────────────────────────────
    "CRM": [
        ThemeMapping("CRM", "cloud_computing", BeneficiaryOrder.DIRECT, 0.85,
                     "Salesforce CRM SaaS platform"),
        ThemeMapping("CRM", "ai_applications", BeneficiaryOrder.SECOND_ORDER, 0.65,
                     "Einstein AI CRM"),
    ],
    "NOW": [
        ThemeMapping("NOW", "cloud_computing", BeneficiaryOrder.DIRECT, 0.88,
                     "ServiceNow enterprise workflow SaaS"),
        ThemeMapping("NOW", "ai_applications", BeneficiaryOrder.SECOND_ORDER, 0.70,
                     "Now Assist AI agents"),
    ],
    "SNOW": [
        ThemeMapping("SNOW", "cloud_computing", BeneficiaryOrder.DIRECT, 0.90,
                     "Snowflake cloud data platform"),
        ThemeMapping("SNOW", "ai_applications", BeneficiaryOrder.SECOND_ORDER, 0.65,
                     "Cortex AI / Snowpark ML"),
    ],
    "DDOG": [
        ThemeMapping("DDOG", "cloud_computing", BeneficiaryOrder.DIRECT, 0.85,
                     "Datadog observability SaaS"),
        ThemeMapping("DDOG", "cybersecurity", BeneficiaryOrder.SECOND_ORDER, 0.55,
                     "Cloud security and CSPM"),
    ],
    "MDB": [
        ThemeMapping("MDB", "cloud_computing", BeneficiaryOrder.DIRECT, 0.82,
                     "MongoDB Atlas cloud database"),
    ],
    # ── Healthcare / biotech ─────────────────────────────────────────────────
    "LLY": [
        ThemeMapping("LLY", "biotech", BeneficiaryOrder.DIRECT, 0.90,
                     "GLP-1 obesity/diabetes drugs (Mounjaro, Zepbound)"),
    ],
    "UNH": [
        ThemeMapping("UNH", "biotech", BeneficiaryOrder.INDIRECT, 0.40,
                     "Managed care — health insurance, not drug innovation"),
    ],
    "JNJ": [
        ThemeMapping("JNJ", "biotech", BeneficiaryOrder.DIRECT, 0.75,
                     "Pharmaceutical plus medical devices"),
    ],
    "ABBV": [
        ThemeMapping("ABBV", "biotech", BeneficiaryOrder.DIRECT, 0.85,
                     "Humira successor pipeline (Skyrizi, Rinvoq)"),
    ],
    "MRK": [
        ThemeMapping("MRK", "biotech", BeneficiaryOrder.DIRECT, 0.82,
                     "Keytruda oncology franchise"),
    ],
    "PFE": [
        ThemeMapping("PFE", "biotech", BeneficiaryOrder.DIRECT, 0.70,
                     "Large pharma pipeline rebuilding post-COVID"),
    ],
    "TMO": [
        ThemeMapping("TMO", "biotech", BeneficiaryOrder.DIRECT, 0.80,
                     "Life science tools — enables drug development"),
    ],
    # ── Financials ───────────────────────────────────────────────────────────
    "JPM": [
        ThemeMapping("JPM", "fintech", BeneficiaryOrder.SECOND_ORDER, 0.60,
                     "Largest US bank with digital payments leadership"),
    ],
    "BAC": [
        ThemeMapping("BAC", "fintech", BeneficiaryOrder.SECOND_ORDER, 0.50,
                     "Digital banking platform"),
    ],
    "GS": [
        ThemeMapping("GS", "fintech", BeneficiaryOrder.INDIRECT, 0.40,
                     "Investment bank with select fintech exposure"),
    ],
    "MS": [
        ThemeMapping("MS", "fintech", BeneficiaryOrder.INDIRECT, 0.40,
                     "Wealth management and capital markets"),
    ],
    "V": [
        ThemeMapping("V", "fintech", BeneficiaryOrder.DIRECT, 0.90,
                     "Global payments network — benefits from digital payments shift"),
    ],
    "MA": [
        ThemeMapping("MA", "fintech", BeneficiaryOrder.DIRECT, 0.90,
                     "Global payments network — cross-border and digital wallet growth"),
    ],
    "BRK-B": [],  # Conglomerate — no single primary theme
    # ── Energy ──────────────────────────────────────────────────────────────
    "XOM": [
        ThemeMapping("XOM", "clean_energy", BeneficiaryOrder.INDIRECT, 0.35,
                     "Big Oil transitioning to LNG and carbon capture"),
    ],
    "CVX": [
        ThemeMapping("CVX", "clean_energy", BeneficiaryOrder.INDIRECT, 0.38,
                     "LNG growth and renewable investments"),
    ],
    "COP": [],
    "SLB": [
        ThemeMapping("SLB", "power_infrastructure", BeneficiaryOrder.INDIRECT, 0.40,
                     "Oilfield services benefit from energy infrastructure demand"),
    ],
    # ── Consumer ────────────────────────────────────────────────────────────
    "WMT": [],
    "COST": [],
    "HD": [],
    "NKE": [],
    "SBUX": [],
}


def get_ticker_mappings(ticker: str) -> list[ThemeMapping]:
    """Return curated ThemeMapping list for *ticker* from the static registry."""
    return list(TICKER_THEME_REGISTRY.get(ticker.upper(), []))


def get_theme_members_from_registry(
    theme: str, min_score: float = 0.0
) -> list[ThemeMapping]:
    """Return all ThemeMappings across all tickers for a given theme."""
    results: list[ThemeMapping] = []
    for mappings in TICKER_THEME_REGISTRY.values():
        for m in mappings:
            if m.theme == theme and m.thematic_score >= min_score:
                results.append(m)
    # Sort by score descending
    return sorted(results, key=lambda m: m.thematic_score, reverse=True)

