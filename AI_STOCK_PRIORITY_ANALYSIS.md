# APIS — AI Stock Priority Analysis
**Date:** 2026-03-30
**Purpose:** Identify and prioritize AI-related stocks across the full value chain for potential addition to the APIS trading universe.

---

## Current AI Coverage in APIS Universe (50 tickers)

The existing universe has solid coverage of **direct AI compute and cloud**, but significant gaps in the **physical infrastructure, power, cooling, networking, cybersecurity, and pure-play AI software** layers that the APIS Master Spec §2 and §7.4 explicitly call out.

| Layer | Current Tickers | Gap Assessment |
|-------|----------------|----------------|
| AI Chips (GPU/ASIC) | NVDA, AMD, AVGO, MRVL, ARM | **Strong** |
| Chip Manufacturing | TSM, ASML, INTC | **Strong** |
| Memory (HBM/DRAM) | MU | **Adequate** |
| AI Servers/Hardware | SMCI, DELL, HPE | **Strong** |
| Cloud Platforms | MSFT, AMZN, GOOGL | **Strong** |
| AI Applications/Models | META, MSFT, GOOGL | **Adequate** (missing pure-play AI software) |
| Data Center Networking | — | **MISSING** |
| Power & Utilities for AI | — | **MISSING** |
| Cooling Infrastructure | — | **MISSING** |
| AI Cybersecurity | — | **MISSING** |
| Data Center REITs | — | **MISSING** |
| EDA/Chip Design Tools | — | **MISSING** |
| Pure-Play AI Software | — | **MISSING** |

---

## Prioritized AI Stock Additions

### TIER 1 — Critical Value Chain Gaps (Highest Priority)

These fill the most glaring holes in APIS's AI coverage. The Master Spec explicitly calls out power, cooling, networking, and cybersecurity as themes APIS must reason about.

---

#### 1. Arista Networks (ANET) — Data Center Networking
- **Theme:** ai_infrastructure, networking
- **Beneficiary Order:** DIRECT
- **Why it matters:** Arista dominates high-performance Ethernet switching inside AI GPU clusters. Every hyperscaler AI buildout (Meta, Microsoft, Google) uses Arista switches. Revenue grew 28.6% YoY in FY2025 to $9B. Raised 2026 AI revenue target from $2.75B to $3.25B. Gross margins 62-64%, operating margins ~46%.
- **AI connection:** AI training clusters require ultra-low-latency, high-bandwidth east-west traffic between thousands of GPUs. Arista's 400G/800G switches are the standard.
- **APIS fit:** Fills the "networking" theme gap that the Master Spec §7.4 explicitly defines. No current ticker covers this.

#### 2. Vertiv Holdings (VRT) — Power & Cooling Infrastructure
- **Theme:** power_infrastructure, data_centres
- **Beneficiary Order:** DIRECT
- **Why it matters:** Vertiv sells the complete power and thermal management ecosystem for data centers — UPS systems, switchgear, and critically, liquid cooling (CDUs). Nvidia's Blackwell and Rubin GPUs require liquid-to-chip cooling. Projected 28% organic sales growth in 2026 to ~$13.5B revenue. 46% expected earnings growth.
- **AI connection:** The bottleneck has shifted from silicon to power and cooling. Every new AI data center needs Vertiv equipment. Called "the safest AI infrastructure stock" by multiple analysts.
- **APIS fit:** Fills both "power_infrastructure" and "data_centres" themes. No current ticker covers AI cooling.

#### 3. Constellation Energy (CEG) — Nuclear Power for AI
- **Theme:** power_infrastructure, clean_energy
- **Beneficiary Order:** DIRECT
- **Why it matters:** Largest U.S. nuclear fleet. Signed a landmark deal with Microsoft to restart Three Mile Island Unit 1. Signed 380MW deal with CyrusOne (total >1,100 MW to CyrusOne in Texas alone). Nuclear provides 24/7 carbon-free baseload power — exactly what AI data centers need.
- **AI connection:** AI data centers need massive, reliable, always-on power. Nuclear is the only scalable carbon-free baseload source. CEG is the dominant supplier.
- **APIS fit:** Fills the "power demand" and "utilities" gap that the Master Spec §2 calls out (power demand, utilities, nuclear, grid load growth).

#### 4. Palo Alto Networks (PANW) — AI Cybersecurity
- **Theme:** cybersecurity, ai_applications
- **Beneficiary Order:** DIRECT
- **Why it matters:** Leading next-gen cybersecurity platform. Prisma AIRS platform for securing AI assets saw 3x sequential customer growth in Q2 FY2026. Partnered with Nvidia to push AI-powered security into industrial systems. Cybersecurity market projected to reach $500B by 2030.
- **AI connection:** Dual beneficiary — uses AI to improve security AND secures AI infrastructure itself. As AI adoption expands, the attack surface grows.
- **APIS fit:** Fills the "cybersecurity" canonical theme. No current ticker covers this despite it being a defined theme in ThemeEngineConfig.

---

### TIER 2 — Important AI Ecosystem (High Priority)

These add depth to the AI thesis and capture second-order beneficiaries the spec emphasizes.

---

#### 5. CrowdStrike (CRWD) — AI-Native Endpoint Security
- **Theme:** cybersecurity
- **Beneficiary Order:** DIRECT
- **Why it matters:** Falcon platform secures AI at every layer — GPU foundations, AI factories, cloud, and AI applications. Cloud-native architecture with 97%+ gross retention rate. Growing TAM as AI agents and applications need securing.
- **AI connection:** As enterprises deploy AI agents, each agent becomes an attack surface. CrowdStrike's platform is designed to secure this new paradigm.
- **APIS fit:** Second cybersecurity play provides sector diversification. Strong growth profile complements PANW.

#### 6. Palantir Technologies (PLTR) — Pure-Play AI Software
- **Theme:** ai_applications
- **Beneficiary Order:** DIRECT
- **Why it matters:** AIP (Artificial Intelligence Platform) drove 70% revenue growth in Q4 2025. U.S. commercial revenue jumped 137%. Only pure-play enterprise AI software company at scale. Government + commercial dual revenue streams.
- **AI connection:** PLTR is arguably the purest public-market AI software play. AIP is being adopted across enterprises for real-world AI deployment.
- **APIS fit:** Fills the pure-play AI software gap. Current universe has no ticker whose primary thesis is AI software.

#### 7. Vistra Energy (VST) — Diversified Power for AI
- **Theme:** power_infrastructure
- **Beneficiary Order:** DIRECT
- **Why it matters:** Nuclear fleet + $4.7B Cogentrix acquisition (5,500 MW of gas-fired generation). Long-term nuclear agreement with Meta. Earnings expected to jump 49% in 2026. Provides both nuclear baseload and gas peaking power.
- **AI connection:** Diversified power portfolio positions Vistra to supply data centers with both baseload (nuclear) and flexible (gas) power.
- **APIS fit:** Complements CEG. While CEG is pure nuclear, VST offers diversified power generation exposure to the AI power theme.

#### 8. Eaton Corporation (ETN) — Electrical Infrastructure
- **Theme:** power_infrastructure, data_centres
- **Beneficiary Order:** DIRECT
- **Why it matters:** Supplies the electrical systems (switchgear, transformers, PDUs, busways) that deliver and manage power inside data centers. Scored highest overall grade (A) among power/cooling infrastructure stocks. Strong industrial franchise with secular AI tailwind.
- **AI connection:** Every data center needs Eaton's electrical distribution equipment. AI data centers draw 2-10x more power per rack than traditional ones.
- **APIS fit:** Fills the electrical infrastructure layer between the utility (CEG/VST) and the server (SMCI/DELL).

---

### TIER 3 — Broader AI Beneficiaries (Medium Priority)

These capture additional second-order effects and diversify the AI thesis.

---

#### 9. Equinix (EQIX) — Data Center REIT
- **Theme:** data_centres
- **Beneficiary Order:** DIRECT
- **Why it matters:** World's largest data center REIT with 260+ facilities globally. Interconnection revenue (high-margin) benefits from AI workload growth. Provides the physical space hyperscalers and enterprises lease for AI compute.
- **AI connection:** AI workloads need physical homes. Equinix provides premium colocation with the power density AI requires.
- **APIS fit:** Adds data center real estate exposure. Different risk/return profile than hardware/power plays.

#### 10. Ciena Corporation (CIEN) — Optical Networking
- **Theme:** networking, ai_infrastructure
- **Beneficiary Order:** DIRECT
- **Why it matters:** Global leader in high-speed optical/WAN connectivity. Record Q1 FY2026 revenue of $1.43B (+33% YoY). FY2026 revenue guidance $5.9-6.3B. Zacks Rank #1 (Strong Buy). Enables massive data transfer between AI data centers.
- **AI connection:** As AI clusters scale across multiple data centers, high-bandwidth optical interconnects become critical. Ciena's WaveLogic technology leads the market.
- **APIS fit:** Complements ANET (which covers intra-DC switching) with inter-DC optical networking.

#### 11. Cadence Design Systems (CDNS) — EDA for AI Chip Design
- **Theme:** semiconductor, ai_infrastructure
- **Beneficiary Order:** SECOND_ORDER
- **Why it matters:** Every AI chip (NVDA, AMD, AVGO custom ASICs, AMZN Trainium, GOOGL TPU) is designed using Cadence's EDA tools. Duopoly with Synopsys. High recurring revenue, strong margins.
- **AI connection:** The explosion of custom AI silicon (ASICs) directly drives demand for chip design tools. More chip designs = more Cadence licenses.
- **APIS fit:** Second-order AI beneficiary that the Master Spec §2 emphasizes (suppliers, infrastructure).

#### 12. Fortinet (FTNT) — Network Security + AI
- **Theme:** cybersecurity, networking
- **Beneficiary Order:** SECOND_ORDER
- **Why it matters:** 800,000+ firewall customers. SASE convergence of networking and security. Lower valuation than PANW/CRWD with strong growth.
- **AI connection:** AI-powered threat detection. Benefits from network security refresh driven by AI infrastructure buildouts.
- **APIS fit:** Third cybersecurity name adds depth. Different customer segment (SMB/mid-market) than PANW (enterprise) and CRWD (cloud-native).

---

## Summary: Recommended Priority Order for Universe Addition

| Priority | Ticker | Name | Primary AI Theme | Thematic Score |
|----------|--------|------|------------------|----------------|
| **1** | **ANET** | Arista Networks | Networking / AI Infrastructure | 0.95 |
| **2** | **VRT** | Vertiv Holdings | Power & Cooling / Data Centres | 0.92 |
| **3** | **CEG** | Constellation Energy | Power Infrastructure / Nuclear | 0.88 |
| **4** | **PANW** | Palo Alto Networks | Cybersecurity | 0.90 |
| **5** | **CRWD** | CrowdStrike | Cybersecurity | 0.85 |
| **6** | **PLTR** | Palantir Technologies | AI Applications | 0.88 |
| **7** | **VST** | Vistra Energy | Power Infrastructure | 0.82 |
| **8** | **ETN** | Eaton Corporation | Power Infrastructure / Data Centres | 0.80 |
| **9** | **EQIX** | Equinix | Data Centres | 0.78 |
| **10** | **CIEN** | Ciena Corporation | Networking / Optical | 0.80 |
| **11** | **CDNS** | Cadence Design Systems | Semiconductor / EDA | 0.75 |
| **12** | **FTNT** | Fortinet | Cybersecurity / Networking | 0.72 |

---

## How These Map to APIS Canonical Themes

| APIS Theme | Current Coverage | Additions |
|------------|-----------------|-----------|
| ai_infrastructure | NVDA, AMD, ARM, MRVL, SMCI, DELL, HPE | ANET, VRT, CIEN |
| cybersecurity | *(none)* | PANW, CRWD, FTNT |
| power_infrastructure | *(none)* | CEG, VST, ETN, VRT |
| data_centres | *(none)* | VRT, EQIX, ETN |
| networking | *(none)* | ANET, CIEN, FTNT |
| ai_applications | META, MSFT, GOOGL | PLTR |
| semiconductor | TSM, ASML, QCOM, TXN, MU, NXPI, ON, AVGO | CDNS |

---

## Implementation Notes

- Adding all 12 would bring the universe from 50 to 62 tickers (well within system capacity).
- The universe management system already supports operator overrides via `POST /api/v1/universe/tickers/{ticker}/override` with ADD action.
- Theme registry (`services/theme_engine/utils.py`) and universe config (`config/universe.py`) would need new entries.
- All existing risk controls (max 10 positions, sector caps, thematic caps, drawdown limits) remain unchanged.
- These additions align with the Master Spec's emphasis on second-order AI beneficiaries (§2, §7.4).
