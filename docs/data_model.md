# Data Model

## Overview

The Atlas data model is organized into four layers, each building on the one below it.

```
┌─────────────────────────────────────────────────────────┐
│  Layer 4 — Research    Thesis · Assumption · Note       │
│                        WatchlistEntry · ThesisRevision  │
├─────────────────────────────────────────────────────────┤
│  Layer 3 — Event       Event · Claim · Relationship     │
├─────────────────────────────────────────────────────────┤
│  Layer 2 — Entity      Company · Person · Role          │
│                        Industry · ProductSegment        │
├─────────────────────────────────────────────────────────┤
│  Layer 1 — Document    Document · DocumentEntity        │
│                        (bridge to the object store)     │
└─────────────────────────────────────────────────────────┘
```

Every object in layers 2–4 can be traced back to one or more Documents. Every
Document can be traced back to a content-addressed file in `data/objects/`. That
chain — from raw bytes to investor conviction — is the platform's core purpose.

---

## Guiding Principles

**Two clocks for every fact.**
Every object carries two timestamps: when the underlying thing happened in the world
(`occurred_at`, `event_date`, `published_at`, `stated_at`), and when it entered Atlas
(`ingested_at`, `created_at`). These must never be conflated. An earnings call from
Q3 2019 ingested in 2024 happened in 2019. Point-in-time integrity is what separates
a research platform from a document archive.

**Claims are what was said; Events are what happened.**
The gap between them is where judgment lives. A claim — "we expect 20% revenue growth"
— can be tracked against the event — "revenue grew 8%." Over years, this gap becomes
a systematic record of management credibility. The model keeps them separate.

**Theses, not notes, are the primary research artifact.**
Notes are ephemeral observations. A Thesis is a structured, revisable statement of
investment conviction with attached evidence, testable assumptions, and an append-only
revision log. It is what compounds in value over a decade of research.

**Assumptions are the unit of testable conviction.**
A thesis is too coarse to update surgically. Breaking it into specific, falsifiable
Assumptions lets you revise one piece of your view without discarding the whole. Over
time, the status of each Assumption becomes a record of how your thesis evolved and why.

**Company identity is stable across change.**
Tickers change. Names change. Companies merge, split, and delist. The model separates
stable identity (`isin`, `cusip`) from current presentation (`ticker`, `name`). A
research record from 2015 on a company that was later acquired remains linked to the
right entity.

---

## Layer 1 — Document

The Document is the bridge between the content-addressable object store and the
knowledge graph. It does not contain document content — that lives in `data/objects/`.
It carries provenance, classification, and temporal context so that every derived fact
can be traced to a source.

### Document

| Field               | Type              | Description                                              |
|---------------------|-------------------|----------------------------------------------------------|
| `id`                | UUID              | Stable database identifier                               |
| `object_hash`       | SHA-256 hex       | Pointer into the object store (`data/objects/`)          |
| `object_type`       | enum              | `pdf`, `markdown`, `table`, `summary`                    |
| `source_name`       | str               | Which connector produced this (e.g., `edgar`, `web`)     |
| `source_id`         | str               | Identifier within the source (e.g., SEC accession number)|
| `document_type`     | enum              | Classification of what the document is (see below)       |
| `title`             | str \| None       | Document title if available                              |
| `period_of_report`  | date \| None      | The period the content covers (e.g., fiscal year end)    |
| `published_at`      | date \| None      | When the document was filed or published                 |
| `ingested_at`       | datetime          | When it entered Atlas's object store                     |
| `page_count`        | int \| None       | For PDFs                                                 |
| `language`          | str               | ISO 639-1 code, default `en`                             |

**`document_type` values:**
`annual_report`, `quarterly_report`, `earnings_transcript`, `investor_presentation`,
`proxy_statement`, `press_release`, `news_article`, `analyst_report`,
`regulatory_filing`, `court_filing`, `patent`, `other`

**Design note:** `period_of_report` and `published_at` are separate because a 10-K
filed in March 2024 covers the fiscal year that ended December 2023. Queries about
"what was disclosed about FY2023" should filter on `period_of_report`, not
`published_at`.

---

### DocumentEntity

A link table that records which entities a document is primarily about versus merely
mentioning. This enables efficient entity-centric document retrieval without full-text
search on every query.

| Field           | Type   | Description                                                |
|-----------------|--------|------------------------------------------------------------|
| `document_id`   | UUID   | Reference to Document                                      |
| `entity_id`     | UUID   | Reference to any Entity subtype                            |
| `role`          | enum   | `primary_subject`, `mentioned`, `source_organization`      |

---

## Layer 2 — Entity

Entities are the actors in the research universe. They persist across documents, time,
and events. The base representation handles identity and aliasing; subtypes carry
domain-specific attributes.

### Entity (base)

All entity subtypes share these fields. Identity resolution — determining that "Apple
Inc." and "AAPL" and "Apple" are the same entity — is the hardest problem in the
knowledge layer. The alias list is the primary mechanism; entity resolution logic lives
in `atlas.knowledge.entities`.

| Field            | Type        | Description                                              |
|------------------|-------------|----------------------------------------------------------|
| `id`             | UUID        | Stable cross-time identifier                             |
| `entity_type`    | enum        | `company`, `person`, `industry`, `product_segment`       |
| `canonical_name` | str         | The authoritative display name                           |
| `aliases`        | list[str]   | Known alternate names, tickers, abbreviations            |
| `created_at`     | datetime    | When this entity record was created in Atlas             |
| `notes`          | str \| None | Researcher's notes on identity or disambiguation         |

---

### Company

The primary research target. Most research in Atlas orbits around Company records.

| Field                        | Type        | Description                                        |
|------------------------------|-------------|----------------------------------------------------|
| `ticker`                     | str \| None | Current primary ticker symbol                      |
| `exchange`                   | str \| None | Primary listing exchange                           |
| `isin`                       | str \| None | ISIN — stable across ticker and name changes       |
| `cusip`                      | str \| None | CUSIP — used for US equities                       |
| `country_of_incorporation`   | str \| None | ISO 3166-1 alpha-2                                 |
| `sector`                     | str \| None | GICS Level 1 or custom classification              |
| `industry`                   | str \| None | GICS Level 2/3 or custom classification            |
| `description`                | str \| None | Business description                               |
| `status`                     | enum        | `active`, `acquired`, `delisted`, `bankrupt`, `private`, `spun_off` |
| `founded_year`               | int \| None |                                                    |
| `headquarters_country`       | str \| None | ISO 3166-1 alpha-2                                 |

**Design note:** `isin` and `cusip` are the anchor for company identity across
corporate events. If a company changes its ticker from FOO to BAR, the ISIN stays the
same and all research records remain correctly linked.

---

### Person

Executives, board members, founders, and analysts. Person records are primarily used for
tracking management quality and attribution of claims.

| Field         | Type        | Description                                            |
|---------------|-------------|--------------------------------------------------------|
| `bio`         | str \| None | Brief background note                                  |
| `nationality` | str \| None | ISO 3166-1 alpha-2                                     |

---

### Role

A time-bounded association between a Person and a Company. Roles are facts, not just
tags, because management tenure, transitions, and overlap are research signals.

| Field                | Type        | Description                                        |
|----------------------|-------------|----------------------------------------------------|
| `person_id`          | UUID        |                                                    |
| `company_id`         | UUID        |                                                    |
| `title`              | str         | e.g., "Chief Executive Officer", "Independent Director" |
| `is_insider`         | bool        | Executive or board member (vs. external analyst)   |
| `started_at`         | date \| None|                                                    |
| `ended_at`           | date \| None| None means the role is current                     |
| `source_document_id` | UUID \| None| Document that confirms this role                   |

---

### Industry

A node in a classification hierarchy. Used for relative comparison and sector-level
research. Industries can be nested (e.g., Technology → Semiconductors → Fabless).

| Field                    | Type        | Description                          |
|--------------------------|-------------|--------------------------------------|
| `parent_industry_id`     | UUID \| None| For hierarchical classification      |
| `classification_scheme`  | str         | e.g., `GICS`, `SIC`, `custom`        |
| `code`                   | str \| None | Scheme-native code                   |

---

### ProductSegment

A named business unit or product line within a Company. Essential for researching
conglomerates and companies with material segment-level differences.

| Field          | Type        | Description                                        |
|----------------|-------------|----------------------------------------------------|
| `company_id`   | UUID        | The Company that owns this segment                 |
| `description`  | str \| None |                                                    |
| `is_active`    | bool        | Whether the segment is currently reported          |

---

## Layer 3 — Event

Events are what happened. Claims are what was said. Relationships are how entities
connect. Together they form the factual substrate that Theses and Assumptions are
built on.

### Event

A discrete, dated occurrence in the world that is relevant to investment research.
Events are the primary unit of the timeline.

| Field                  | Type          | Description                                        |
|------------------------|---------------|----------------------------------------------------|
| `id`                   | UUID          |                                                    |
| `title`                | str           | One-line description                               |
| `description`          | str           | Fuller narrative of what happened                  |
| `event_date`           | date          | When this happened in the world                    |
| `event_date_precision` | enum          | `exact`, `month`, `quarter`, `year`                |
| `category`             | enum          | See below                                          |
| `significance`         | enum          | `low`, `medium`, `high`, `critical`                |
| `entity_ids`           | list[UUID]    | Companies and people involved                      |
| `source_document_ids`  | list[UUID]    | Documents that report this event                   |
| `origin`               | enum          | `extracted` (pipeline), `manual` (researcher)      |
| `created_at`           | datetime      | When this record was created in Atlas              |
| `notes`                | str \| None   | Researcher's context on the event                  |

**`category` values:**
`earnings_result`, `guidance_issued`, `management_change`, `capital_allocation`,
`m_and_a`, `product_launch`, `product_discontinuation`, `competitive_action`,
`regulatory_action`, `litigation`, `macro_event`, `analyst_action`, `other`

**Design note:** `event_date` is when the thing happened; `created_at` is when Atlas
learned about it. A merger that closed in 2017 and was ingested in 2024 has
`event_date = 2017-06-15` and `created_at = 2024-…`. Never infer one from the other.

---

### Claim

A factual or forward-looking assertion made in a specific document by a specific
speaker. Claims are the atomic unit of evidence for building and testing Theses.

| Field                | Type        | Description                                          |
|----------------------|-------------|------------------------------------------------------|
| `id`                 | UUID        |                                                      |
| `body`               | str         | The claim verbatim or faithfully paraphrased         |
| `claim_type`         | enum        | `factual_disclosure`, `guidance`, `analyst_assertion`, `researcher_note` |
| `source_document_id` | UUID        | Document containing this claim                       |
| `source_page`        | int \| None | Page number in source document                       |
| `speaker_id`         | UUID \| None| Person who made this claim (for transcripts)         |
| `company_id`         | UUID \| None| Which company this claim is about                    |
| `refers_to_period`   | date \| None| The time period the claim addresses (e.g., FY2025)   |
| `stated_at`          | date        | When this claim was made (document's publication date)|
| `tags`               | list[str]   |                                                      |

**Claims vs Events — the key distinction:**
A Claim is what someone said in a document. An Event is what actually happened. Tracking
the distance between them — guidance issued vs. result reported, prediction made vs.
outcome observed — is how management credibility is built up over years. They must remain
separate records even when one directly contradicts the other.

---

### Relationship

A time-bounded, typed connection between two Entities. Relationships change: a company
that was a competitor in 2015 may have been acquired in 2019. The temporal bounds make
this history queryable.

| Field                  | Type          | Description                                      |
|------------------------|---------------|--------------------------------------------------|
| `id`                   | UUID          |                                                  |
| `from_entity_id`       | UUID          |                                                  |
| `to_entity_id`         | UUID          |                                                  |
| `relationship_type`    | enum          | See below                                        |
| `valid_from`           | date \| None  | When this relationship began                     |
| `valid_to`             | date \| None  | When it ended; None means it is current          |
| `notes`                | str \| None   |                                                  |
| `source_document_ids`  | list[UUID]    | Documents that evidence this relationship        |

**`relationship_type` values:**
`subsidiary_of`, `acquired`, `spun_off_from`, `merged_with`, `competed_with`,
`supplies_to`, `customer_of`, `invested_in`, `founded_by`, `joint_venture_with`,
`board_member_of`, `analyst_covers`

---

## Layer 4 — Research

The research layer is the investor's intellectual work. It is the only layer that
Atlas cannot regenerate from source documents — it represents original judgment.
It must be durable, revisable, and auditable.

### Thesis

A structured, evolving statement of investment conviction on a specific entity.
The Thesis is the primary research artifact in Atlas. Everything else either
feeds into it or supports understanding it.

| Field               | Type        | Description                                          |
|---------------------|-------------|------------------------------------------------------|
| `id`                | UUID        |                                                      |
| `subject_entity_id` | UUID        | Usually a Company; occasionally an Industry          |
| `title`             | str         | e.g., "Compounding returns through operational leverage" |
| `direction`         | enum        | `long`, `short`, `watch`, `pass`                     |
| `conviction`        | enum        | `low`, `medium`, `high`                              |
| `status`            | enum        | `active`, `monitoring`, `closed`, `abandoned`        |
| `opened_at`         | date        | When research formally began                         |
| `closed_at`         | date \| None| When the thesis was formally concluded               |
| `close_reason`      | str \| None | Why closed: thesis played out, proven wrong, etc.    |
| `summary`           | str         | Current state of the thesis in plain prose           |
| `key_questions`     | list[str]   | 3–5 questions that, if answered, resolve the thesis  |

---

### ThesisRevision

An append-only log of every time a Thesis was meaningfully updated. This is what
makes long-term research self-evaluable. You cannot delete or edit a ThesisRevision —
only add new ones.

| Field                      | Type        | Description                                  |
|----------------------------|-------------|----------------------------------------------|
| `id`                       | UUID        |                                              |
| `thesis_id`                | UUID        |                                              |
| `revised_at`               | datetime    | When the revision was written                |
| `previous_conviction`      | enum        |                                              |
| `new_conviction`           | enum        |                                              |
| `previous_direction`       | enum \| None|                                              |
| `new_direction`            | enum \| None|                                              |
| `rationale`                | str         | Why the thesis changed                       |
| `triggering_event_id`      | UUID \| None| The Event that prompted this revision        |
| `triggering_document_id`   | UUID \| None| The Document that prompted this revision     |

**Design note:** The revision log answers the question "When I read the Q2 2022
earnings call, did I update my view? Why?" Over a decade this becomes a systematic
record of how good a researcher's judgment is under uncertainty.

---

### Assumption

A specific, falsifiable claim embedded in a Thesis. Assumptions decompose conviction
into pieces that can be individually confirmed, refuted, or superseded as evidence
accumulates.

| Field              | Type        | Description                                          |
|--------------------|-------------|------------------------------------------------------|
| `id`               | UUID        |                                                      |
| `thesis_id`        | UUID        |                                                      |
| `body`             | str         | The assumption stated as a falsifiable claim         |
| `importance`       | enum        | `low`, `medium`, `high`, `critical`                  |
| `status`           | enum        | `pending`, `confirmed`, `partially_confirmed`, `refuted`, `superseded`, `irrelevant` |
| `created_at`       | datetime    |                                                      |
| `resolved_at`      | date \| None| When the assumption's status was determined          |
| `resolution_notes` | str \| None | What evidence resolved it                            |

**Example assumptions for a long thesis:**
- "Management will continue to allocate capital to organic growth over M&A" → status: `confirmed` (2024)
- "European regulatory exposure remains manageable through 2026" → status: `pending`
- "The gross margin profile holds above 60% as volume scales" → status: `refuted` (Q3 2023)

---

### AssumptionEvidence

Links an Assumption to the Events and Claims that support or contradict it. This makes
the evidence chain from raw document to thesis conviction fully traceable.

| Field           | Type   | Description                                              |
|-----------------|--------|----------------------------------------------------------|
| `assumption_id` | UUID   |                                                          |
| `evidence_type` | enum   | `event`, `claim`, `document`                             |
| `evidence_id`   | UUID   | ID of the referenced Event, Claim, or Document           |
| `stance`        | enum   | `supports`, `refutes`, `neutral`                         |
| `notes`         | str \| None |                                                     |

---

### Note

An atomic researcher observation. Notes are quick to create and broadly linkable.
They are not the primary research artifact (that is Thesis), but they are the primary
input to thesis revision — they capture the observation before the judgment.

| Field          | Type        | Description                                          |
|----------------|-------------|------------------------------------------------------|
| `id`           | UUID        |                                                      |
| `body`         | str         | Markdown free text                                   |
| `note_type`    | enum        | `observation`, `question`, `decision`, `reference`, `reminder` |
| `written_at`   | datetime    | Researcher's timestamp — may be backdated            |
| `entity_ids`   | list[UUID]  | Entities this note is about                          |
| `event_ids`    | list[UUID]  | Events this note references                          |
| `thesis_id`    | UUID \| None| Thesis this note belongs to                          |
| `document_ids` | list[UUID]  | Documents this note references                       |
| `tags`         | list[str]   |                                                      |

---

### WatchlistEntry

The researcher's active monitoring queue. Every company being researched exists in
the watchlist with a stated reason and a status. The status represents where in the
research lifecycle the company sits.

| Field               | Type        | Description                                        |
|---------------------|-------------|----------------------------------------------------|
| `id`                | UUID        |                                                    |
| `entity_id`         | UUID        | The Company being monitored                        |
| `status`            | enum        | `monitoring`, `researching`, `thesis_active`, `passed`, `exited` |
| `added_at`          | date        | When it was added to the watchlist                 |
| `status_updated_at` | datetime    | When the status last changed                       |
| `reason`            | str         | Why this company is being watched                  |
| `priority`          | enum        | `low`, `medium`, `high`                            |
| `next_review_date`  | date \| None| When to revisit                                    |

**Status lifecycle:**
```
monitoring → researching → thesis_active → [exited / passed]
     └─────────────────────────────────→ passed
```

`passed` means "considered and decided not to invest." This is as important to record
as an active thesis — it prevents re-doing the same analysis.

---

## Relationship Map

```
Document ──────────────────────────────────────────────────────┐
  │                                                            │
  │ DocumentEntity                                             │
  ▼                                                            │
Entity (Company / Person / Industry / ProductSegment)          │
  │                                                            │
  ├── Role ──────────────────────────── Person                 │
  │                                                            │
  ├── Relationship ─────────────────── Entity                  │
  │    (time-bounded, typed)                                   │
  │                                                            │
  ├── Event ──────── entity_ids: Entity[]                      │
  │         └─────── source_document_ids: Document[]◄──────────┘
  │
  ├── Claim ──────── company_id: Company                       │
  │         ├─────── speaker_id: Person                        │
  │         └─────── source_document_id: Document ◄────────────┘
  │
  └── (via Thesis.subject_entity_id)
        │
        ▼
      Thesis ──── ThesisRevision (append-only log)
        │
        └── Assumption ── AssumptionEvidence ──► Event
              │                              └──► Claim
              │                              └──► Document
              └── [resolved_at, resolution_notes]


WatchlistEntry ──► Company (entity_id)

Note ──► entity_ids: Entity[]
     ──► event_ids: Event[]
     ──► thesis_id: Thesis
     ──► document_ids: Document[]
```

---

## Domain Rules and Invariants

**R1 — Immutability of source records.**
Documents, Claims, and Events once written are never deleted. They may be
superseded (via an `is_superseded_by` pointer) but the original record persists.
This mirrors the object store's immutability.

**R2 — Temporal ordering.**
`event_date` must be ≤ the `published_at` date of any source document that reports
the event. An event cannot be documented before it occurs.

**R3 — ThesisRevision is append-only.**
No revision record is ever deleted or edited. A correction to a past revision creates
a new revision with a `rationale` explaining the correction. The log must reflect what
the researcher actually thought at each point in time, not a post-hoc cleaned-up version.

**R4 — Assumption status is monotonic.**
An Assumption moves through status changes in one direction. Once `resolved_at` is set,
the Assumption may only be `superseded` (to be replaced by a more precise one), not
reverted to `pending`.

**R5 — WatchlistEntry.passed is permanent.**
Once a company is marked `passed`, the record is retained indefinitely. Re-opening
research on the same company creates a new WatchlistEntry with a reference to the prior
one, not a status reversal. This preserves the historical decision record.

**R6 — Entity aliases are additive.**
Aliases are only ever added to an entity record, never removed. A resolved alias
might be flagged as `deprecated` but the resolution link is preserved for traceability.

---

## Design Decisions

**D1 — No financial statement storage.**
The model does not include structured financial data (income statement, balance sheet,
cash flow). Financial statement analysis lives in spreadsheets or exported tables.
Atlas stores the documents that contain financials and the Claims and Events extracted
from them; it does not replicate the financial data store.

**D2 — Conviction not price target.**
`Thesis.conviction` is a qualitative enum, not a price target or expected return.
Atlas is a fundamental research platform, not a valuation engine. Price targets change
with market prices; conviction is a function of research quality.

**D3 — Single entity type hierarchy.**
Rather than separate tables for Company, Person, etc. with no shared identity,
all entities share a base record. This allows polymorphic linking from Events,
Claims, Notes, and Relationships to any entity type without separate foreign key
columns for each type.

**D4 — Claims include researcher notes.**
The `claim_type` value `researcher_note` allows a researcher to enter a first-person
observation as a Claim, linking it to a document and period. This unifies the note-
taking workflow: structured claims (extracted from documents) and free-form
observations (written by the researcher) live in the same collection with the same
temporal metadata, making them co-queryable on a timeline.

**D5 — No position or portfolio tracking.**
`WatchlistEntry.status` stops at `thesis_active`. There is no `position_size`,
`entry_price`, `exit_price`, or portfolio-level aggregation. That data lives in a
brokerage account. Atlas tracks conviction and evidence, not capital allocation.

---

## What This Model Is Not

- **A financial database.** No OHLCV data, no earnings estimates, no consensus.
- **A portfolio manager.** No positions, no returns, no risk attribution.
- **A quantitative model.** No factor scores, no signals, no backtests.
- **A collaboration tool.** No user accounts, permissions, or shared workspaces in scope.
- **A CRM.** Person records track research-relevant roles; they are not contact management.

The model is optimized for one purpose: accumulating structured evidence about companies
over long time horizons, and building an auditable record of the investment reasoning
that evidence produced.
