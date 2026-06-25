# Database

## Philosophy

The object store holds documents. The database holds knowledge derived from those documents:
entities, events, relationships, and research records. These are two separate concerns with
separate storage backends.

The database is local, embedded, and schema-owned by this project. It has no external
service dependency at runtime.

---

## Entity Model (Draft)

The following is a preliminary model. It will be formalized in an ADR before implementation.

```
Company
  id            UUID
  name          str
  ticker        str | None
  exchange      str | None
  sector        str | None
  description   str | None
  created_at    datetime
  updated_at    datetime

Person
  id            UUID
  name          str
  role          str | None
  affiliated_companies  [Company.id]

Event
  id            UUID
  title         str
  date          date
  description   str
  entity_ids    [UUID]         ← companies or people involved
  source_hashes [str]          ← object store references
  tags          [str]

Relationship
  id            UUID
  from_entity   UUID
  to_entity     UUID
  type          str             ← e.g. "subsidiary_of", "competed_with", "acquired"
  valid_from    date | None
  valid_to      date | None
  source_hashes [str]
```

---

## Indexing Strategy

- Full-text search on entity names, event descriptions, and research notes
- Date-range queries on events and relationships
- Entity lookup by ticker, name, or alias

---

## Migration Strategy

- Schema changes are managed via migration scripts in `scripts/`
- Each migration is numbered and idempotent
- Migrations run forward only; rollback is handled by restoring from backup

---

## Open Questions

- [ ] SQLite vs. DuckDB vs. embedded graph database?
- [ ] ORM or raw SQL? (SQLModel, SQLAlchemy, or handwritten queries)
- [ ] How to handle entity aliases and name normalization?
- [ ] What is the backup and restore strategy for the local database?
