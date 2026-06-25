# Storage

## Design

Atlas uses a **content-addressable object store** for all raw and processed documents.
Objects are stored by the SHA-256 hash of their content. This guarantees:

- **Deduplication** — the same document ingested twice produces one stored object.
- **Immutability** — an object's path is derived from its content; it cannot be silently modified.
- **Reproducibility** — re-running any pipeline over the same object produces the same output.

---

## Directory Layout

```
data/
└── objects/
    ├── pdf/          Raw PDF files (binary, as ingested)
    ├── markdown/     Markdown-normalized text extracted from PDFs and web pages
    ├── metadata/     JSON metadata records (source, date, document type, entity hints)
    ├── summaries/    Generated summaries (keyed to source object hash)
    └── tables/       Extracted tables in structured format (JSON or Parquet)
```

Each object is stored under a path derived from its content hash:

```
data/objects/pdf/ab/cd1234...
                ^^
                First two hex chars (bucket prefix to avoid large flat directories)
```

---

## Object Types

| Type | Format | Description |
|---|---|---|
| `pdf` | Binary | Raw PDF as downloaded or provided |
| `markdown` | UTF-8 text | Normalized text representation of a document |
| `metadata` | JSON | Structured metadata: source, date, type, issuer, hash |
| `summaries` | UTF-8 text | Model-generated or human-authored summaries |
| `tables` | JSON / Parquet | Tabular data extracted from documents |

---

## Cache and Exports

```
data/
├── cache/    Temporary files: API responses, intermediate computation artifacts
└── exports/  Generated outputs: CSVs, reports, snapshots for external use
```

Both directories are **gitignored**. They are ephemeral and must be regeneratable
from the object store at any time.

---

## Retention Policy

- `data/objects/` — permanent. Never delete an ingested object.
- `data/cache/` — ephemeral. Safe to clear at any time.
- `data/exports/` — ephemeral. Treat as generated artifacts.

---

## Open Questions

- [ ] Should objects be compressed at rest? (gzip, zstd)
- [ ] What is the strategy for very large objects (e.g., multi-hundred-page PDFs)?
- [ ] Should the object store support metadata indexing, or is a separate database sufficient?
