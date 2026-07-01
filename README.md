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

Atlas has completed Stages 1, 2, and the foundation of Stage 3. TCS is the reference company used throughout development.

---

### Stage 1 — Data Collection: Complete

* BSE integration: filing discovery, download, deduplication, verification
* Evidence catalog with 156 TCS documents across 13 filing types
* Acquisition pipeline: `AcquisitionPolicy`, per-run records, incremental updates
* Knowledge base: PDF → text parsing with page and character offsets preserved

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

A typed fact ontology (`FactKind`) with 98 members and 12 units (`FactUnit`), spanning financial, capital allocation, ESG, governance, ownership, credit, strategy, and segment domains.

Ten analyzers, each implementing `analyze(evidence_id, kb) → AnalysisResult`:

| Analyzer | Document type | FactKinds extracted | Tests |
|---|---|---|---|
| `financial_results` | Quarterly / annual Reg 33 | 26 (full P&L, balance sheet, cash flow, segments, EPS, audit) | 177 |
| `brsr` | Business Responsibility & Sustainability Report | 15 (GHG, energy, water, waste, workforce, safety, SBTi) | 154 |
| `agm_notice` | AGM voting results (Reg 44) | 5 (resolution title, type, outcome, vote percentages) | 85 |
| `investor_presentation` | Strategy decks and analyst day slides | 10 (strategy priorities, guidance, CSAT, segment growth, ROE, FCF) | 88 |
| `credit_rating` | ESG and debt rating rationales | 6 (agency, instrument, amount, rating, outlook, action) | 89 |
| `board_outcome` | Board meeting Reg 30 filings | 8 (dividends, M&A events, subsidiary investments) | 94 |
| `acquisition` | Acquisition Reg 30 filings | 5 (target, consideration type, enterprise value, stake, timeline) | 79 |
| `buyback` | Buyback filings | 5 (amount, price, shares offered/bought, record date) | 70 |
| `shareholding_pattern` | BSE XBRL quarterly SHP | 11 (promoter, FPI, DII, MF, insurance, retail, HNI, NRI holdings) | 66 |
| `earnings_transcript` | Earnings call transcripts | 6 (revenue, TCV, operating margin, net margin, period metadata) | 71 |

A `shareholding_trend` module (`analyze_trend`) aggregates multiple SHP results into QoQ and YoY holding deltas and directional signals (69 tests).

A golden corpus of 11 real TCS documents with expected facts validates extraction quality on every test run. Total test suite: 1,675+ tests, 92%+ line coverage.

---

### Stage 3 — Knowledge Repository: Foundation Complete

A `CompanyProfile` assembles `AnalysisResult` objects from multiple filings into a structured, time-ordered knowledge object:

```
CompanyProfile
├── FinancialTimeSeries     — quarterly and annual P&L, balance sheet, cash flow snapshots
├── ESGTimeSeries           — GHG, energy, water, waste, workforce snapshots
├── CapitalEventLedger      — dividends, buybacks, acquisitions, investments
├── CreditHistory           — rating entries sorted by date
├── OwnershipTimeSeries     — promoter, FPI, DII, retail holding snapshots
└── SegmentTimeSeries       — revenue and EBIT per business segment
```

A `derived` module computes net debt/cash, EBIT, EBITDA, margins (EBIT, EBITDA, PAT), capex intensity, GAAP FCF, and employee cost percentage from the snapshot facts.

---

### Next

* Wire `investor_presentation` and `agm_notice` results into `CompanyProfile` (Strategy and Governance sub-models)
* `CompanyStore`: serialize `CompanyProfile` to disk for incremental updates
* CLI: `atlas profile <company>` — end-to-end pipeline from catalog to profile
* Fix and register `annual_report` analyzer (currently partial; not in the registry)
