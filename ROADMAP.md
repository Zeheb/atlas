# Atlas — Roadmap

Phases are sequential. Each phase produces a usable, testable layer before the next begins.

---

## Phase 1 — Foundation
**Goal:** A clean, well-structured codebase with working configuration, logging, and storage primitives.

- [ ] Finalize package structure and dependency setup
- [ ] Implement configuration loading (per-environment YAML)
- [ ] Set up structured logging
- [ ] Define and implement content-addressable object store interface
- [ ] Write tests for storage primitives
- [ ] Set up CI (lint, type-check, test)

---

## Phase 2 — Ingestion
**Goal:** Reliably bring documents into the object store from primary sources.

- [ ] Define connector interface (abstract base class)
- [ ] Implement first connector (SEC EDGAR or equivalent)
- [ ] Implement ingestion orchestration (scheduling, retry, deduplication)
- [ ] Store raw documents in `data/objects/` by type
- [ ] Write integration tests for ingestion flow

---

## Phase 3 — Processing
**Goal:** Extract structured content from raw documents.

- [ ] PDF text extraction
- [ ] OCR for image-based documents
- [ ] Table extraction and normalization
- [ ] Metadata extraction (document type, date, source, issuer)
- [ ] Markdown normalization for web-sourced content
- [ ] Store processed outputs alongside source objects

---

## Phase 4 — Knowledge
**Goal:** Build a structured, queryable knowledge layer over processed content.

- [ ] Define entity model (companies, people, geographies, products)
- [ ] Define event model and timeline structure
- [ ] Define relationship model
- [ ] Implement entity extraction pipeline
- [ ] Implement event extraction pipeline
- [ ] Link extracted knowledge back to source documents

---

## Phase 5 — Research Interface
**Goal:** A usable interface for conducting and recording investment research.

- [ ] Investment memo format and storage
- [ ] Hypothesis tracking with evidence links
- [ ] Watchlist management
- [ ] Search across documents, entities, and notes
- [ ] Timeline view for a given company or sector

---

## Future Considerations

- Multi-source entity resolution and deduplication
- Versioning and diffing of company metrics over time
- Export to structured formats (CSV, JSON, Parquet)
- Read-only internal API for programmatic access
