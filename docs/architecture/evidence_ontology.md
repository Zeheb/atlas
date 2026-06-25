# Evidence Ontology

Atlas classifies every piece of evidence along four orthogonal dimensions:
**Category**, **Kind**, **Format**, and **Provenance**. A fifth concept —
**Event** — is reserved for the Knowledge layer and documented here for
architectural continuity.

The ontology is designed to remain stable across 10–20 years of evidence
ingestion from sources that do not yet exist.

---

## Overview

```
Evidence
├── category   : EvidenceCategory   — which business domain
├── kind       : EvidenceKind       — what type of disclosure or record
├── format     : EvidenceFormat     — how the information is encoded
└── provenance : Provenance         — where it came from and how authoritative
```

Category and Kind describe **what** the evidence is.
Format describes **how** it is encoded.
Provenance describes **where** it originated and how much to trust the source.

These dimensions are fully independent. The same business concept (e.g., a
quarterly earnings result) can appear as a PDF narrative document filed through
BSE, an audio recording on the company's IR website, and a transcript
published by a third-party service. All three share the same Category and Kind;
they differ in Format and Provenance.

---

## Category

Category is the broadest classification. It describes the **domain** from which
the evidence originates — not the specific document or business event. Category
values must remain valid regardless of the specific evidence type or its source.

| Value | Description |
|---|---|
| `CORPORATE_REPORTING` | Documents the company authors and publishes about itself: performance, strategy, sustainability, investor communications |
| `REGULATORY` | Disclosures the company is required to file with exchanges or financial regulators, plus actions those regulators take |
| `MARKET_DATA` | Quantitative trading, pricing, and market microstructure data |
| `THIRD_PARTY` | Analysis, ratings, and assessments produced by credentialed external parties |
| `ALTERNATIVE` | Non-official, non-traditional sources: media coverage, social discussion, geospatial data, trade records |
| `PUBLIC_RECORDS` | Government datasets, court records, and administrative filings outside the securities regulatory sphere |

**Distinguishing CORPORATE_REPORTING from REGULATORY:** CORPORATE_REPORTING is
what the company *chooses to say* about itself. REGULATORY is what the company
is *required to report* in a specified format. An annual report is
CORPORATE_REPORTING. A shareholding pattern is REGULATORY. Both may be filed
with an exchange; the category reflects the nature of the disclosure, not the
filing channel.

**Distinguishing REGULATORY from PUBLIC_RECORDS:** REGULATORY covers the
securities and financial regulatory domain — exchange-mandated filings, SEBI
disclosures, board outcomes, enforcement actions. PUBLIC_RECORDS covers
everything else government-issued: courts, MCA, DGFT, CCI, patent offices,
electoral bodies.

---

## Kind

Kind describes the **specific type of business disclosure or record** within a
category. It is source-agnostic — a quarterly earnings result is the same Kind
whether filed with BSE, discussed in a transcript, or reported in a press release.

Kind answers: *what is this evidence about, as a business concept?*

### Kinds by Category

**CORPORATE_REPORTING**

| Kind | Description | Examples |
|---|---|---|
| `ANNUAL_REVIEW` | Full-year performance narrative and financial statements | Annual Report, Integrated Report |
| `PERIODIC_EARNINGS_DISCLOSURE` | Interim or quarterly financial results | Q1/Q2/Q3/Q4 results, half-yearly results, earnings release |
| `INVESTOR_COMMUNICATION` | Management presentations for investors or analysts | Analyst day, investor presentation, roadshow deck |
| `SUSTAINABILITY_DISCLOSURE` | ESG, BRSR, CSR, environmental reporting | BRSR report, standalone ESG report, CSR annual report |
| `CORPORATE_COMMUNICATION` | Official company-authored public communication not filed with an exchange | Press release, IR website announcement |

**REGULATORY**

| Kind | Description | Examples |
|---|---|---|
| `CAPITAL_EVENT_DISCLOSURE` | Mandatory exchange filing of a capital structure decision | Dividend announcement, buyback announcement, rights issue announcement, merger announcement |
| `SECURITIES_FILING` | Offer documents and prospectuses filed with SEBI or an exchange | IPO red herring prospectus, rights issue prospectus, NCD offer document |
| `OWNERSHIP_DISCLOSURE` | Mandatory disclosure of ownership, pledging, or insider transactions | Shareholding pattern, promoter pledging, SAST insider trade filing |
| `GOVERNANCE_DISCLOSURE` | Required disclosure of governance decisions and proceedings | AGM notice, board meeting outcome, postal ballot result |
| `CREDIT_RATING_DISCLOSURE` | Exchange filing of a credit rating action | Rating action filed by company with BSE/NSE |
| `REGULATORY_ORDER` | Order or enforcement action issued by a financial regulator | SEBI enforcement order, SEBI circular, RBI penalty notice |

**MARKET_DATA**

| Kind | Description | Examples |
|---|---|---|
| `PRICE_DATA` | Historical or real-time price and volume data | OHLCV, bid-ask, adjusted close |
| `DERIVATIVES_DATA` | Options and futures market data | F&O chain, open interest, put-call ratio |
| `OWNERSHIP_CHANGE` | Market-reported ownership transactions | Block deal, bulk deal, off-market transfer |

**THIRD_PARTY**

| Kind | Description | Examples |
|---|---|---|
| `CREDIT_ASSESSMENT` | Rating agency report on debt instruments or creditworthiness | CRISIL rating report, ICRA outlook report, Moody's review |
| `EQUITY_RESEARCH` | Brokerage or analyst research on the company | Initiating coverage, earnings preview, sector report |
| `ESG_ASSESSMENT` | Third-party ESG or sustainability rating | MSCI ESG rating, Sustainalytics score, CDP disclosure |

**ALTERNATIVE**

| Kind | Description | Examples |
|---|---|---|
| `MEDIA_COVERAGE` | Journalistic or press reporting about the company | News article, investigative report, interview |
| `SOCIAL_DISCUSSION` | User-generated discussion about the company | Reddit thread, ValuePickr discussion, Twitter/X thread |
| `TRADE_RECORD` | Import, export, or supply chain transaction data | DGFT customs data, shipping manifest, Zauba trade record |
| `GEOSPATIAL` | Satellite or location-derived signals | Satellite imagery, foot traffic count, car park occupancy |

**PUBLIC_RECORDS**

| Kind | Description | Examples |
|---|---|---|
| `PATENT_FILING` | Patent applications and grants | Indian patent application, USPTO grant |
| `TRADEMARK_FILING` | Trademark registrations and renewals | IP India trademark record |
| `JUDICIAL_ORDER` | Court orders and judgments | High Court ruling, Supreme Court judgment, NCLT order |
| `GOVERNMENT_ORDER` | Administrative orders from non-judicial bodies | CCI merger approval, NCLT scheme sanction, SFIO investigation |
| `CORPORATE_FILING` | Statutory filings with the company registrar | MCA annual return, charge filing, director appointment |
| `GOVERNMENT_DATA` | Raw datasets published by government bodies | DGFT trade statistics, census data, ministry statistics |
| `POLITICAL_DISCLOSURE` | Political donation and electoral bond records | Electoral bond disclosure, Form 26 (ECI) |

---

## Format

Format describes **how the evidence is encoded**. It is entirely source-agnostic
and primarily drives ingestion logic: how Atlas extracts text, tables, metadata,
and structured data from the evidence.

| Format | Description | Typical ingestion path |
|---|---|---|
| `NARRATIVE_DOCUMENT` | Prose-heavy PDF or HTML | Text extraction, page segmentation, section detection |
| `PRESENTATION` | Slide deck — low text density, high visual content | Slide extraction, title/body separation, image capture |
| `TRANSCRIPT` | Verbatim text of spoken content | Speaker diarization, Q&A segmentation, turn detection |
| `STRUCTURED_DATASET` | Tabular or machine-queryable records (CSV, JSON, XML) | Schema detection, column mapping, type coercion |
| `DISCLOSURE_NOTICE` | Short-form official filing, typically one to five pages | Full-text extraction, key field detection |
| `DISCUSSION_THREAD` | Nested user-generated content | Thread parsing, post/reply separation, author metadata |
| `NEWS_ARTICLE` | Journalistic or press prose | Article extraction, byline/date detection, body parsing |
| `AUDIO_VISUAL` | Audio or video recording | Transcription, speaker identification |
| `IMAGE` | Photograph, satellite image, diagram | Visual analysis, georeferencing |

---

## Provenance

Provenance captures **where an evidence item originated** and **how authoritative
that origin is**. It is a first-class field on every Evidence record — not
optional metadata.

Provenance consists of three sub-fields:

### `source_id: str`

A stable, lowercase string identifying the specific source system or entity.
This is not an enum; the list of sources Atlas integrates will grow continuously.

Examples: `"bse"`, `"nse"`, `"mca"`, `"sebi"`, `"crisil"`, `"icra"`,
`"reddit"`, `"valuepickr"`, `"dgft"`, `"tcs.com"`, `"nseindia.com"`.

### `source_kind: SourceKind`

The type of entity that operates the source. This is an enum because the
categories of sources are stable even as individual sources change.

| SourceKind | Description | Examples |
|---|---|---|
| `EXCHANGE` | Securities exchange | BSE, NSE |
| `REGULATOR` | Financial or securities regulator | SEBI, RBI, IRDAI, MCA |
| `GOVERNMENT` | Other government body | DGFT, CCI, courts, patent offices, ECI |
| `COMPANY` | The subject company's own channels | Company IR website, direct company publication |
| `FINANCIAL_INSTITUTION` | Rating agencies, banks, brokerages | CRISIL, ICRA, Goldman Sachs, Nomura |
| `MEDIA` | News outlets and press agencies | Economic Times, Bloomberg, Reuters |
| `COMMUNITY` | Discussion platforms | Reddit, ValuePickr, Twitter/X |
| `DATA_PROVIDER` | Commercial aggregators of public or market data | Zauba, NSE data APIs, Bloomberg Terminal |

### `authority: Authority`

How authoritative the source is — a three-value scale that drives downstream
weighting and deduplication decisions.

| Authority | Meaning |
|---|---|
| `OFFICIAL` | Primary source or officially mandated channel: the company itself, an exchange, a regulator, a government body |
| `RECOGNIZED` | A credentialed third party: established, accountable, not official — rating agencies, brokerages, reputable press |
| `COMMUNITY` | User-generated, unvetted content: Reddit, forums, anonymous sources |

**Why Provenance matters at scale:** The same underlying fact will eventually
arrive through multiple provenance paths. A credit rating action exists as a
short DISCLOSURE_NOTICE filed by the company with BSE (source_kind: EXCHANGE,
authority: OFFICIAL), a full NARRATIVE_DOCUMENT from CRISIL's website
(source_kind: FINANCIAL_INSTITUTION, authority: RECOGNIZED), and a NEWS_ARTICLE
in the financial press (source_kind: MEDIA, authority: RECOGNIZED). These are
three distinct evidence items about the same rating action. Provenance lets
Atlas deduplicate by content while preserving the full provenance chain, and
lets the Knowledge layer weight evidence by authority.

---

## Event (Reserved — Knowledge Layer)

Many evidence items describe the same real-world event. The quarterly earnings
event for TCS Q3 FY26 may produce: a results PDF, an investor presentation, an
earnings call audio, a transcript, a company press release, news coverage, and
community discussion. These are not six independent records — they are six
pieces of evidence about one event.

**Atlas does not model Events at the acquisition layer.** Event grouping requires
understanding evidence content, which is a Knowledge layer concern.

The schema reservation is: `Evidence` carries `event_id: str | None = None`. This
field is always `None` at acquisition time and is populated by the Knowledge layer
when it groups evidence into Events. This means the Event entity can be introduced
without requiring a schema migration on existing Evidence records.

The Event entity itself — its schema, population logic, and relationship model —
will be designed when the Knowledge layer is built.

---

## Governance: When to Add a New Kind

The target is approximately 25 stable Kinds over Atlas's lifetime. Every addition
beyond that carries a maintenance cost and risks fragmentation.

**Three questions before adding a new Kind:**

**1. Does it represent a genuinely different business disclosure or record?**
Not a document variant, not a format variation, not a frequency variation, not a
source variation. A quarterly result and a half-yearly result are the same Kind.
A patent application and a patent grant are the same Kind. A dividend announcement
filed with BSE and a dividend press release from the company website are the same
Kind in different Formats from different Provenances.

**2. Would an analyst specifically filter for this Kind — and would excluding it
silently omit evidence they expected to see?**
"Give me all earnings disclosures" is a valid Kind-level query. "Give me all Q3
earnings disclosures" is a time filter, not a Kind distinction. "Give me all
disclosures about capital structure changes" is a Kind-level query that maps to
`CAPITAL_EVENT_DISCLOSURE`.

**3. Is there an existing Kind that covers it when combined with Category, Format,
or Provenance?**
If the proposed new Kind can be expressed as an existing Kind with a different
Format (e.g., audio vs. transcript of the same earnings call) or a different
Category (e.g., the same credit rating action as a REGULATORY filing vs. a
THIRD_PARTY report), the answer is no new Kind.

**The default answer is no.** A new Kind is only justified if all three questions
are answered affirmatively and the omission would constitute a genuine gap in an
analyst's query results.

---

## Classification Reference

A reference classification of 40 evidence types Atlas will eventually support.

| Evidence | Category | Kind | Format |
|---|---|---|---|
| Annual Report | CORPORATE_REPORTING | ANNUAL_REVIEW | NARRATIVE_DOCUMENT |
| Quarterly Financial Results (PDF) | CORPORATE_REPORTING | PERIODIC_EARNINGS_DISCLOSURE | NARRATIVE_DOCUMENT |
| Earnings Call Audio | CORPORATE_REPORTING | PERIODIC_EARNINGS_DISCLOSURE | AUDIO_VISUAL |
| Earnings Call Transcript | CORPORATE_REPORTING | PERIODIC_EARNINGS_DISCLOSURE | TRANSCRIPT |
| Investor Presentation (Analyst Day) | CORPORATE_REPORTING | INVESTOR_COMMUNICATION | PRESENTATION |
| Investor Roadshow Deck | CORPORATE_REPORTING | INVESTOR_COMMUNICATION | PRESENTATION |
| Company Press Release | CORPORATE_REPORTING | CORPORATE_COMMUNICATION | NEWS_ARTICLE |
| BRSR / ESG Report | CORPORATE_REPORTING | SUSTAINABILITY_DISCLOSURE | NARRATIVE_DOCUMENT |
| Dividend Announcement (exchange filing) | REGULATORY | CAPITAL_EVENT_DISCLOSURE | DISCLOSURE_NOTICE |
| Buyback Announcement | REGULATORY | CAPITAL_EVENT_DISCLOSURE | DISCLOSURE_NOTICE |
| Buyback Offer Document | REGULATORY | CAPITAL_EVENT_DISCLOSURE | NARRATIVE_DOCUMENT |
| Merger / Acquisition Announcement | REGULATORY | CAPITAL_EVENT_DISCLOSURE | DISCLOSURE_NOTICE |
| IPO Red Herring Prospectus | REGULATORY | SECURITIES_FILING | NARRATIVE_DOCUMENT |
| Rights Issue Prospectus | REGULATORY | SECURITIES_FILING | NARRATIVE_DOCUMENT |
| NCD Private Placement Notice | REGULATORY | SECURITIES_FILING | DISCLOSURE_NOTICE |
| Shareholding Pattern | REGULATORY | OWNERSHIP_DISCLOSURE | STRUCTURED_DATASET |
| Promoter Pledging Disclosure | REGULATORY | OWNERSHIP_DISCLOSURE | DISCLOSURE_NOTICE |
| Insider Trade Filing (SAST) | REGULATORY | OWNERSHIP_DISCLOSURE | DISCLOSURE_NOTICE |
| AGM Notice | REGULATORY | GOVERNANCE_DISCLOSURE | NARRATIVE_DOCUMENT |
| Board Meeting Outcome | REGULATORY | GOVERNANCE_DISCLOSURE | DISCLOSURE_NOTICE |
| Credit Rating Filing (exchange) | REGULATORY | CREDIT_RATING_DISCLOSURE | DISCLOSURE_NOTICE |
| SEBI Enforcement Order | REGULATORY | REGULATORY_ORDER | NARRATIVE_DOCUMENT |
| NSE / BSE Historical Price Data | MARKET_DATA | PRICE_DATA | STRUCTURED_DATASET |
| F&O Open Interest / Options Chain | MARKET_DATA | DERIVATIVES_DATA | STRUCTURED_DATASET |
| Block Deal / Bulk Deal | MARKET_DATA | OWNERSHIP_CHANGE | STRUCTURED_DATASET |
| CRISIL Credit Rating Report | THIRD_PARTY | CREDIT_ASSESSMENT | NARRATIVE_DOCUMENT |
| Brokerage Initiating Coverage | THIRD_PARTY | EQUITY_RESEARCH | NARRATIVE_DOCUMENT |
| ESG Rating (MSCI, Sustainalytics) | THIRD_PARTY | ESG_ASSESSMENT | STRUCTURED_DATASET |
| News Article About Company | ALTERNATIVE | MEDIA_COVERAGE | NEWS_ARTICLE |
| Reddit Discussion | ALTERNATIVE | SOCIAL_DISCUSSION | DISCUSSION_THREAD |
| ValuePickr Thread | ALTERNATIVE | SOCIAL_DISCUSSION | DISCUSSION_THREAD |
| DGFT Import/Export Data (via Zauba) | ALTERNATIVE | TRADE_RECORD | STRUCTURED_DATASET |
| Satellite Imagery | ALTERNATIVE | GEOSPATIAL | IMAGE |
| Patent Filing | PUBLIC_RECORDS | PATENT_FILING | NARRATIVE_DOCUMENT |
| Trademark Registration | PUBLIC_RECORDS | TRADEMARK_FILING | STRUCTURED_DATASET |
| Court Order / High Court Ruling | PUBLIC_RECORDS | JUDICIAL_ORDER | NARRATIVE_DOCUMENT |
| CCI Merger Approval Order | PUBLIC_RECORDS | GOVERNMENT_ORDER | NARRATIVE_DOCUMENT |
| MCA Annual Return | PUBLIC_RECORDS | CORPORATE_FILING | STRUCTURED_DATASET |
| DGFT Trade Statistics (direct) | PUBLIC_RECORDS | GOVERNMENT_DATA | STRUCTURED_DATASET |
| Political Donation Disclosure | PUBLIC_RECORDS | POLITICAL_DISCLOSURE | STRUCTURED_DATASET |

---

## Relationship to the Current Implementation

The current `EvidenceKind` flat enum (15 values) is an interim model used in the
BSE acquisition pipeline. It conflates Category, Kind, and Format into a single
dimension and contains BSE-specific concepts. It will be replaced by this ontology
in a future refactor.

The refactor will introduce: `EvidenceCategory` (6 values), a restructured
`EvidenceKind` (21 values), `EvidenceFormat` (9 values), and a `Provenance`
dataclass replacing the current `EvidenceSource` enum.

The refactor is deferred until Atlas has ingested a wider variety of evidence types
and real usage has pressure-tested the ontology. See ADR-0001.
