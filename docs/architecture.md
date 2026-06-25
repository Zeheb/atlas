# Architecture

## Overview

Atlas is structured as a layered Python application. Each layer has a single, well-defined
responsibility and depends only on layers below it. No layer has knowledge of layers above it.

```
┌─────────────────────────────────────┐
│           research/                 │  Human-authored notes, memos, watchlists
├─────────────────────────────────────┤
│        atlas.knowledge              │  Entities, events, timelines, relationships
├─────────────────────────────────────┤
│        atlas.processing             │  PDF, OCR, tables, metadata, markdown
├─────────────────────────────────────┤
│        atlas.ingestion              │  Orchestration: scheduling, retry, dedup
├─────────────────────────────────────┤
│        atlas.connectors             │  External source adapters (one per source)
├─────────────────────────────────────┤
│  atlas.storage  │  atlas.models     │  Persistence abstractions and domain schemas
├─────────────────────────────────────┤
│        atlas.core                   │  Domain primitives, interfaces, exceptions
└─────────────────────────────────────┘
```

---

## Design Principles

**Immutable inputs.** Raw documents in the object store are never modified after ingestion.
All downstream products (processed text, extracted tables, knowledge records) are derived
and can be regenerated from source.

**Content-addressable storage.** Documents are stored by the hash of their content, not by
filename or source URL. This naturally deduplicates and makes storage reproducible.

**Explicit boundaries.** Each package exposes a narrow public interface. Internal
implementation details are private. Dependencies flow downward only.

**No framework lock-in.** The core domain logic (`atlas.core`, `atlas.models`,
`atlas.knowledge`) has no dependency on ingestion or processing infrastructure. It can be
reasoned about, tested, and evolved independently.

**Testability first.** Every module is testable in isolation. Integration tests are
explicit and live in `tests/integration/`. Nothing in `atlas.core` or `atlas.models`
requires a live connection.

---

## Package Responsibilities

| Package | Responsibility |
|---|---|
| `atlas.core` | Domain primitives, base interfaces, shared exceptions |
| `atlas.models` | Pydantic schemas for all domain objects |
| `atlas.storage` | Abstract interfaces for object store and database access |
| `atlas.connectors` | One adapter per external data source |
| `atlas.ingestion` | Orchestration: fetch → hash → deduplicate → store |
| `atlas.processing` | Transform raw objects into structured content |
| `atlas.knowledge` | Build and query the entity/event/relationship graph |
| `atlas.api` | Internal API layer (future) |
| `atlas.utils` | Logging, config loading, retry decorators, date helpers |

---

## Data Flow

```
External Source
     │
     ▼
atlas.connectors      ← fetches raw bytes
     │
     ▼
atlas.ingestion       ← hashes, deduplicates, writes to data/objects/
     │
     ▼
atlas.processing      ← reads from object store, extracts structured content
     │
     ▼
atlas.knowledge       ← reads processed content, builds entity/event graph
     │
     ▼
research/             ← researcher queries knowledge, writes memos and notes
```

---

## Key Decisions

See [`docs/adr/`](adr/) for Architecture Decision Records.
