# Atlas — Project Specification

## Purpose

Atlas is a private, long-term investment research platform. Its goal is to systematically
collect, process, and structure financial information about companies and markets into a
persistent knowledge base that compounds in value over time.

The platform is designed around the research process of a fundamental, long-term investor:
reading deeply, tracking companies across time, connecting events to outcomes, and building
conviction through structured evidence — not quantitative signals.

---

## Target User

A single researcher or a small team conducting fundamental equity research with a long
time horizon. The user reads a large volume of primary source documents (filings, transcripts,
reports), forms hypotheses, and tracks how they evolve.

---

## Core Capabilities

### Ingestion
- Ingest documents from structured and unstructured sources
- Store documents in a content-addressable local object store
- Deduplicate by content hash

### Processing
- Extract structured content from PDFs, scanned documents, and web pages
- Parse tables into structured formats
- Extract metadata (dates, entities, document type)
- Run OCR on image-based documents

### Knowledge
- Identify and link entities (companies, people, markets, products)
- Extract events from documents and place them on a timeline
- Model relationships between entities
- Surface connections across documents and time

### Research
- Maintain investment memos, hypotheses, and watchlists
- Link research notes to source documents and knowledge entities
- Track how a thesis evolves over time

---

## Non-Goals

- Real-time market data or trading signals
- Portfolio management or position tracking
- Quantitative factor models or backtesting
- Multi-user collaboration (at this stage)
- Public-facing web interface

---

## Constraints

- All data is stored locally; no cloud data dependencies
- Python 3.14+
- No proprietary data sources initially; public filings and documents only
- System must remain operable indefinitely without external service dependencies

---

## Open Questions

- [ ] Which database engine for the knowledge graph? (SQLite, DuckDB, or embedded graph DB)
- [ ] What is the deduplication and versioning strategy for the object store?
- [ ] How are entities resolved across documents? (rule-based vs. model-based)
- [ ] What is the interface for research notes — plain Markdown files or structured records?
