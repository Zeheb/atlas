# Atlas

> A long-term investment research platform.

## Overview

Atlas is a knowledge platform for systematic investment research. It ingests, processes,
and structures financial documents and data — filings, reports, transcripts, memos — into
a queryable knowledge base that supports deep, longitudinal analysis of companies and markets.

## Status

Early-stage. Repository scaffolding in progress.

## Repository Layout

```
Atlas/
├── src/atlas/          # Core application package
│   ├── api/            # Internal API layer
│   ├── connectors/     # External data source adapters
│   ├── core/           # Domain logic and abstractions
│   ├── ingestion/      # Data collection orchestration
│   ├── knowledge/      # Entity, event, timeline, relationship models
│   ├── models/         # Pydantic schemas and domain objects
│   ├── processing/     # Document processing (PDF, OCR, tables, etc.)
│   ├── storage/        # Storage abstractions
│   └── utils/          # Shared utilities
├── tests/              # Unit, integration, and fixture data
├── docs/               # Technical documentation
├── research/           # Investment memos, notes, hypotheses, watchlists
├── knowledge/          # Reference material and domain knowledge
├── data/               # Local content-addressable object store
├── configs/            # Environment configuration files
└── scripts/            # Operational and migration utilities
```

## Documentation

| Document | Description |
|---|---|
| [PROJECT_SPEC.md](PROJECT_SPEC.md) | Full product specification |
| [ROADMAP.md](ROADMAP.md) | Phased milestone plan |
| [docs/architecture.md](docs/architecture.md) | System design and principles |
| [docs/storage.md](docs/storage.md) | Storage layer design |
| [docs/database.md](docs/database.md) | Database schema and entity model |
| [docs/connectors.md](docs/connectors.md) | External data connector specifications |
| [docs/development.md](docs/development.md) | Local setup and development guide |

## Getting Started

See [docs/development.md](docs/development.md) for prerequisites and setup instructions.
