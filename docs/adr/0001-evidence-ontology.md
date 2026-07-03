# ADR-0001 — Evidence Ontology: Three-Layer Classification with First-Class Provenance

**Date:** 2026-06-25
**Status:** Accepted

---

## Context

Atlas acquires evidence from external sources and catalogs it for research.
The first acquisition source was BSE, which returns announcements classified
by a proprietary field called `SUBCATNAME` — values like "Financial Results",
"Annual Report", "Analyst / Investor Meet", "AGM/EGM Notice".

The original implementation mapped these BSE subcategory strings directly to
a flat `EvidenceKind` enum:

```python
class EvidenceKind(str, enum.Enum):
    ANNUAL_REPORT = "annual_report"
    FINANCIAL_RESULTS = "financial_results"
    EARNINGS_TRANSCRIPT = "earnings_transcript"
    INVESTOR_PRESENTATION = "investor_presentation"
    AGM_NOTICE = "agm_notice"
    BOARD_OUTCOME = "board_outcome"
    DIVIDEND = "dividend"
    BUYBACK = "buyback"
    ACQUISITION = "acquisition"
    CREDIT_RATING_REPORT = "credit_rating_report"
    NEWS = "news"
    BRSR = "brsr"
    REGULATORY_FILING = "regulatory_filing"
    OTHER = "other"
    ...
```

This model had four structural problems that would compound as Atlas added
evidence sources beyond BSE.

**Problem 1 — BSE semantics leaked into the domain model.**
`EvidenceKind.NEWS` was derived from BSE's "Press Release / Media Release"
subcategory. `EvidenceKind.BOARD_OUTCOME` was derived from BSE's "Outcome of
Board Meeting". These are BSE-specific labels, not source-agnostic concepts.
When NSE, MCA, or a company's IR website produces the same document type using
different labels, there is no principled way to map them to the existing Kinds.

**Problem 2 — A single dimension conflated three orthogonal concepts.**
`EvidenceKind` mixed together:
- The business domain (what world does this come from?)
- The content type (what is it about?)
- The format (how is it encoded?)

An annual report and an earnings call transcript are fundamentally different
evidence formats even though both discuss the same company performance. The
flat enum could not express that they shared a business concept while differing
in format, making it impossible to query "all earnings disclosures regardless
of format."

**Problem 3 — `EvidenceKind.OTHER` was a silent failure mode.**
Unmapped BSE subcategories fell through to `EvidenceKind.OTHER` with no
visibility. As BSE introduces new filing subcategories, Atlas would silently
misclassify evidence without any signal to the operator. An analyst querying
for investor presentations could silently miss records that BSE started calling
"Analyst Webinar" instead of "Analyst / Investor Meet".

(The observability problem was partially addressed in Sprint 2 through
`DiscoveryWarning` and a counter on `BSEParser`. But the underlying
classification model remained flat and BSE-coupled.)

**Problem 4 — Provenance was a three-value enum.**
`EvidenceSource` had three values: BSE, NSE, MCA. This could not represent
the diversity of sources Atlas will eventually integrate: rating agencies,
company IR websites, Reddit, ValuePickr, DGFT, courts, patent offices. It also
could not capture whether a source was authoritative (exchange filing) vs.
recognized third-party (brokerage) vs. community-generated (Reddit).

---

## Decision

We adopt a **three-layer evidence ontology** with **first-class provenance**.

Every evidence item is classified along four dimensions:

```
category   : EvidenceCategory   (6 values)
kind       : EvidenceKind       (21 values)
format     : EvidenceFormat     (9 values)
provenance : Provenance         (structured, not an enum)
```

### Why three dimensions instead of one

**Category** answers: which business domain is this? (CORPORATE_REPORTING,
REGULATORY, MARKET_DATA, THIRD_PARTY, ALTERNATIVE, PUBLIC_RECORDS)

**Kind** answers: what type of business disclosure or record is this?
(ANNUAL_REVIEW, PERIODIC_EARNINGS_DISCLOSURE, OWNERSHIP_DISCLOSURE, …)

**Format** answers: how is it encoded? (NARRATIVE_DOCUMENT, TRANSCRIPT,
STRUCTURED_DATASET, DISCLOSURE_NOTICE, …)

These dimensions are fully independent. An earnings result appears as a
DISCLOSURE_NOTICE (the brief exchange announcement), a NARRATIVE_DOCUMENT
(the full PDF results), a TRANSCRIPT (the earnings call), and an AUDIO_VISUAL
(the recording). All four share Category=CORPORATE_REPORTING and
Kind=PERIODIC_EARNINGS_DISCLOSURE. The Format field distinguishes them.
The flat enum could not represent this.

### Why Kind describes business concepts, not document types

An earlier proposal considered making Kind a topic-based layer: Financial
Performance, Governance, Capital Allocation. This was rejected because:

1. Most corporate documents are multi-topic. An annual report discusses
   financial performance, governance, capital allocation, sustainability, and
   strategy simultaneously. A single-valued Kind cannot express this without
   either arbitrary primary-topic selection or a many-to-many relationship.

2. Topic assignment requires reading the document. At acquisition time, Atlas
   knows the document type before it has analyzed the content. Kind must be
   assignable from metadata and source labels alone.

Topics are what Atlas extracts from evidence at the ingestion/analysis stage.
They are not part of the acquisition ontology.

### Why Provenance is a structured dataclass, not an enum

The `Provenance` dataclass has three fields:

- `source_id: str` — a free-form identifier for the specific source ("bse",
  "crisil", "reddit"). Not an enum because sources are open-ended.

- `source_kind: SourceKind` — the type of entity operating the source
  (EXCHANGE, REGULATOR, GOVERNMENT, COMPANY, FINANCIAL_INSTITUTION, MEDIA,
  COMMUNITY, DATA_PROVIDER). An enum because entity types are stable.

- `authority: Authority` — OFFICIAL, RECOGNIZED, or COMMUNITY. Drives
  downstream deduplication and evidence weighting.

The same credit rating action arrives through multiple provenance paths: a
DISCLOSURE_NOTICE from BSE (source_kind=EXCHANGE, authority=OFFICIAL) and a
full NARRATIVE_DOCUMENT from CRISIL's website (source_kind=FINANCIAL_INSTITUTION,
authority=RECOGNIZED). These are distinct evidence items. Provenance preserves
both.

### The Kind governance rule

Undisciplined addition of Kinds would recreate the flat-enum problem at scale.
The rule: **a new Kind should only be introduced when an analyst would
specifically filter for it, and an existing Kind would silently omit evidence
they expected to see.**

Three gate questions before adding any new Kind:
1. Does it represent a genuinely different business disclosure or record — not
   a variant, not a different frequency, not a different format?
2. Would an analyst write a query specifically for this Kind and expect distinct
   results from existing Kinds?
3. Can it be expressed as an existing Kind with a different Format or Category?

If any answer is no, the answer is no new Kind. The target ceiling is 25 Kinds.

### The Event layer reservation

Many evidence items describe the same real-world event (the Q3 FY26 earnings
event produces a results PDF, a transcript, an audio recording, news coverage,
and community discussion). Grouping evidence into Events requires content
understanding and belongs to the Knowledge layer, not the acquisition layer.

The schema reservation: `Evidence` carries `event_id: str | None = None`,
always `None` at acquisition time, populated by the Knowledge layer later.
This avoids a schema migration when Events are introduced.

### Implementation timing

This ontology is adopted as the **frozen design target**. The implementation
refactor — replacing the flat `EvidenceKind` enum with the three-layer model
and replacing `EvidenceSource` with `Provenance` — is **deferred**.

The refactor will be performed once, after Atlas has ingested a wider variety
of evidence types. Performing the refactor now would:
- Impose migration cost before the ontology has been validated against real
  multi-source ingestion
- Slow acquisition capability expansion during the period when Atlas most needs
  more evidence flowing through it
- Risk performing a second structural refactor if real usage reveals gaps in
  the design

Until the refactor is performed, the current flat `EvidenceKind` enum serves
as an interim model. Changes to the interim model should be minimal and should
not introduce new BSE-specific concepts.

---

## Consequences

**Positive:**
- The ontology is source-agnostic. NSE, MCA, Reddit, DGFT, and any future
  source can be classified using the same dimensions without creating
  source-specific Kind values.
- Category + Kind supports natural analyst queries that cut across formats
  ("give me all earnings disclosures for TCS regardless of whether they are
  transcripts, PDFs, or audio").
- Format separation allows ingestion logic to be driven by Format without
  coupling it to business meaning.
- Provenance makes authority hierarchies explicit and supports deduplication
  across overlapping sources.
- The governance rule prevents Kind from becoming a per-document dumping
  ground of 120+ values.
- The Event reservation allows Knowledge-layer grouping without a breaking
  schema change when that layer is built.

**Negative / Trade-offs:**
- The refactor is a non-trivial schema migration. Every model that touches
  `EvidenceKind` or `EvidenceSource` — the parser, connector, catalog, profile,
  downloader, and all their tests — changes simultaneously.
- Until the refactor is performed, the codebase carries two models: the
  interim flat enum and this documented target. Code written against the interim
  model will need to be updated at migration time.
- The 21-Kind target requires discipline. Every new evidence type will tempt
  a new Kind; the governance rule must be applied consistently.

**Risks:**
- Real-world ingestion of investor presentations, shareholding patterns, and
  earnings transcripts may reveal gaps in the ontology before the refactor is
  complete. If so, the ontology document should be updated; the interim code
  should not be updated to match unless the gap is critical.
- The deferred refactor may be deprioritized indefinitely. To mitigate: the
  refactor should be scheduled once Atlas has ingested evidence from at least
  four distinct evidence types across at least two acquisition sources.

---

## Alternatives Considered

| Option | Reason rejected |
|---|---|
| Keep the flat `EvidenceKind` enum, extend as needed | Recreates the BSE-coupling problem for every new source. A new source with different label conventions either forces new Kinds or requires lossy mapping. Not viable at scale. |
| Topic-based second layer (Financial Performance, Governance, Capital Allocation) | Topics require document content analysis, which is not available at acquisition time. Most documents are multi-topic, making a single-valued Kind field incoherent. Topics belong in the analysis layer. |
| Three layers + implement now | Correct ontology, wrong timing. Implementing the refactor before Atlas has real multi-source evidence risks over-engineering for hypothetical cases and imposes migration cost that should be paid once. |
| Defer the ontology design until the refactor is needed | By the time the refactor is needed, the interim model will have proliferated BSE-specific concepts into more places, making migration harder. Freezing the design now limits that damage. |

---

## References

- [`docs/architecture/evidence_ontology.md`](../architecture/evidence_ontology.md) — Full ontology reference with classification table
- [`docs/data_model.md`](../data_model.md) — Knowledge layer data model (Document, Entity, Event, Claim)
- [`src/atlas/acquisition/evidence.py`](../../src/atlas/acquisition/evidence.py) — Current interim implementation
