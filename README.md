# Atlas

Atlas is software for investment research.

The goal is to reduce the manual work involved in understanding a business by collecting information from many sources, organizing it, extracting useful information, and building a long-term knowledge base that improves over time.

It is designed around four stages.

## Stage 1 — Data Collection

Collect information from every relevant public source for a company.

Examples include:

* Annual reports
* Investor presentations
* Quarterly financial results
* Earnings call transcripts
* Exchange filings
* Shareholding patterns
* Credit rating reports
* Broker research
* Industry reports
* Government records
* News
* Community discussions

The objective is to acquire as much relevant information as possible while preserving where it came from.

Output:
A complete repository of raw evidence for a company.

---

## Stage 2 — Information Extraction

Read the collected evidence and extract structured information from it.

Examples include:

* Customers
* Suppliers
* Capex announcements
* Guidance
* Risks
* Management commentary
* Margin drivers
* Capacity additions
* Shareholding changes
* Key hires
* Product launches

The extracted information should be linked back to the evidence it came from.

Output:
A structured database of facts with supporting evidence.

---

## Stage 3 — Knowledge Repository

Connect information across documents, companies and time.

Examples:

* Track how management commentary changes over multiple years.
* Group documents relating to the same business event.
* Link facts mentioned across annual reports, presentations and conference calls.
* Keep a history of previous research and investment notes.
* Preserve evidence even as new information becomes available.

The repository should become more useful as more companies and more years of data are added.

Output:
A searchable knowledge base for long-term investment research.

---

## Stage 4 — Research

Use the knowledge repository to answer investment questions.

Examples:

* Who are the company's major customers?
* Has promoter ownership increased?
* Has management consistently met guidance?
* How have margins behaved over time?
* What risks keep recurring?
* What has changed since the last quarter?
* What did I conclude about this business two years ago?
* How does this company compare with its peers?

The aim is to bring together the relevant evidence so that an investor can make an informed decision.

---

## Current Status

Atlas has completed Stages 1 and 2, a working Stage 3 (`CompanyProfile` + `CompanyStore` + an OCR-hardened knowledge layer), and the beginning of Stage 4 (a deterministic query engine + CLI). Three companies are used as the reference set, chosen to span sectors: **TCS** (IT services), **Tata Steel** (manufacturing), **SBI** (banking).

---

### Stage 1 — Data Collection: Complete

* BSE integration: filing discovery, download, deduplication, verification
* Evidence catalog across TCS (156 documents), Tata Steel (334), and SBI (307), spanning 13+ filing types
* Acquisition pipeline: `AcquisitionPolicy`, per-run records, incremental updates
* Knowledge base: multi-stage PDF extraction — native text layer first, objective quality scoring (density + garbled-word coherence), automatic Tesseract OCR fallback below threshold. Validated against real filings: clean PDFs stay native, scanned/broken-encoding filings (common in older SBI filings) correctly trigger OCR, with zero false positives observed across 742 PDFs / 16,891 pages

Filing types in the TCS catalog:

| Filing type | Count |
|---|---|
| Investor presentations | 50 |
| Annual reports | 29 |
| AGM notices and voting results | 28 |
| Regulatory filings | 9 |
| Acquisitions (Reg 30) | 6 |
| Earnings transcripts | 6 |
| Dividend notices | 6 |
| Financial results (Reg 33) | 5 |
| Buyback filings | 5 |
| BRSR | 4 |
| Board outcomes (Reg 30) | 4 |
| Credit rating reports | 3 |
| Shareholding pattern (XBRL) | 1 |

---

### Stage 2 — Information Extraction: Complete

A typed fact ontology (`FactKind`) with 114 members and 13 units (`FactUnit`), spanning financial, capital allocation, ESG, governance, ownership, credit, strategy, and segment domains — including a banking-ratio family (NIM, NPA, PCR, CASA, credit cost, capital adequacy, slippage) and physical production/delivery volume for industrial companies.

Eleven analyzers, each implementing `analyze(evidence_id, kb) → AnalysisResult`:

| Analyzer | Document type | Notes |
|---|---|---|
| `financial_results` | Quarterly / annual Reg 33 | Full P&L, balance sheet, cash flow, segments, EPS, audit; dedicated Banking Regulation Act path for bank filings |
| `annual_report` | Annual report (Board's/Director's Report, MDA, auditor's report) | CSR spend, KAM titles, workforce attrition, risk factors |
| `brsr` | Business Responsibility & Sustainability Report | GHG, energy, water, waste, workforce, safety, SBTi targets |
| `agm_notice` | AGM voting results (Reg 44) | Resolution title, type, outcome, vote percentages |
| `investor_presentation` | Investor decks, press-release-style filings, IR schedules | **v2.0** — rebuilt around cross-sector concepts (forward guidance, ROE/FCF, a banking-ratio family, production/delivery volume, segment growth) rather than v1's TCS-specific slide titles, after v1 was found to extract nothing from the large majority of Tata Steel/SBI presentations. Validated against real TCS, Tata Steel, and SBI filings with dedicated regression tests for the layout quirks each surfaced (interleaved bar-chart pairing, ambiguous section headings, footnote markers, stray connector words) |
| `credit_rating` | ESG and debt rating rationales | Agency, instrument, amount, rating, outlook, action |
| `board_outcome` | Board meeting Reg 30 filings | Dividends, M&A events, subsidiary investments, fundraising, director changes |
| `acquisition` | Acquisition Reg 30 filings | Target, consideration type, enterprise value, stake, timeline |
| `buyback` | Buyback filings | Amount, price, shares offered/bought, record date |
| `shareholding_pattern` | BSE XBRL quarterly SHP | Promoter, FPI, DII, MF, insurance, retail, HNI, NRI holdings |
| `earnings_transcript` | Earnings call transcripts | Revenue, TCV, operating margin, net margin, period metadata |

A `shareholding_trend` module (`analyze_trend`) aggregates multiple SHP results into QoQ and YoY holding deltas and directional signals.

A golden corpus of real TCS documents with expected facts validates extraction quality on every test run. Total test suite: 2,150+ tests.

---

### Stage 3 — Knowledge Repository: Working

A `CompanyProfile` assembles `AnalysisResult` objects from multiple filings into a structured, time-ordered knowledge object:

```
CompanyProfile
├── FinancialTimeSeries     — quarterly and annual P&L, balance sheet, cash flow snapshots
├── ESGTimeSeries           — GHG, energy, water, waste, workforce snapshots
├── CapitalEventLedger      — dividends, buybacks, acquisitions, investments
├── CreditHistory           — rating entries sorted by date
├── OwnershipTimeSeries     — promoter, FPI, DII, retail holding snapshots
├── SegmentTimeSeries       — revenue and EBIT per business segment
├── StrategyProfile         — priorities, guidance, aspiration, CSAT
└── GovernanceProfile       — resolutions, director changes, audit KAMs, risk factors
```

A `derived` module computes net debt/cash, EBIT, EBITDA, margins (EBIT, EBITDA, PAT), capex intensity, GAAP FCF, and employee cost percentage from the snapshot facts.

`CompanyStore` persists a `CompanyProfile` to disk as JSON, with idempotent incremental merge (`store.merge(result)`) so a new filing updates the profile without a full rebuild from all historical results.

---

### Stage 4 — Research: Foundation started

A deterministic, rule-based query engine (`atlas.query.engine`) operates on `CompanyProfile` — no LLM calls, no raw document access — answering: `revenue`, `leverage`, `ownership` (with QoQ/streak signal detection), `capital` (allocation events), `acquisitions`, `ratings`, `risks`, `strategy`.

CLI: `atlas repository build <ticker>`, `atlas acquire <ticker>`, `atlas profile build <ticker>`, `atlas query <ticker> <query>` — the full pipeline from catalog to answered question.

---

### Next

* `corporate_governance_report` analyzer — SEBI LODR Reg. 27(2) board-composition filing, recommended as the next document type: fills the currently-reserved `GOVERNANCE_DIRECTOR` gap and has real volume (37+ filings for Tata Steel alone), though its table layout carries similar alignment risk to what was just fixed in `financial_results`' segment extraction and `investor_presentation`'s operating-volume rows
* Broaden the query engine and CLI beyond the current 8 queries as Stage 3 domain coverage grows (banking ratios, production/delivery volume, and segment growth are now in `CompanyProfile` but not yet surfaced by a query)
* `investor_presentation`'s STRATEGY_PRIORITY heading-anchor and STRATEGY_GUIDANCE keyword patterns are conservative by design (precision over recall) — worth revisiting with more cross-company sample filings as the repository grows
