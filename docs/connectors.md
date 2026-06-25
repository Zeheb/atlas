# Connectors

## Overview

A connector is an adapter for a single external data source. Its only job is to fetch raw
content and return it as bytes with associated metadata. It has no knowledge of the object
store, the database, or any processing pipeline.

All connectors live in `src/atlas/connectors/`. Each source gets its own module.

---

## Connector Interface

Every connector must implement the following abstract interface (to be defined in `atlas.core`):

```
BaseConnector
  name: str                          ← unique identifier for this source
  fetch(identifier: str) → Document  ← fetches one document by source-native ID
  list(query: ConnectorQuery) → [str] ← lists available document identifiers
```

`Document` carries:
- `content: bytes` — raw bytes of the document
- `source: str` — connector name
- `source_id: str` — identifier within the source
- `content_type: str` — MIME type (e.g. `application/pdf`)
- `fetched_at: datetime`
- `metadata: dict` — source-specific metadata (URL, filing type, period, etc.)

---

## Planned Connectors

| Connector | Source | Document Types | Status |
|---|---|---|---|
| `edgar` | SEC EDGAR | 10-K, 10-Q, 8-K, DEF 14A | Planned |
| `pdf_local` | Local filesystem | PDF | Planned |
| `web` | Arbitrary URL | HTML → Markdown | Planned |

---

## Adding a New Connector

1. Create `src/atlas/connectors/<source_name>.py`
2. Implement `BaseConnector`
3. Register the connector in `src/atlas/connectors/__init__.py`
4. Write unit tests in `tests/unit/connectors/test_<source_name>.py`
5. Write integration tests (with a recorded fixture) in `tests/integration/`
6. Add an entry to the table above

---

## Conventions

- Connectors must not write to disk directly. Return a `Document`; let `atlas.ingestion` handle storage.
- Connectors must not retry indefinitely. Accept a configurable max-retry parameter.
- Connectors must raise typed exceptions defined in `atlas.core.exceptions`, not raw HTTP errors.
- Rate limiting and backoff belong in the connector, not in the ingestion layer.
