import json
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from atlas.acquisition.evidence import Evidence


@dataclass
class CatalogEntry:
    evidence_id: str
    source: str
    kind: str
    title: str
    source_date: str
    document_url: str | None
    local_path: str
    file_size_bytes: int | None
    acquired_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "source": self.source,
            "kind": self.kind,
            "title": self.title,
            "source_date": self.source_date,
            "document_url": self.document_url,
            "local_path": self.local_path,
            "file_size_bytes": self.file_size_bytes,
            "acquired_at": self.acquired_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CatalogEntry":
        return cls(
            evidence_id=d["evidence_id"],
            source=d["source"],
            kind=d["kind"],
            title=d["title"],
            source_date=d["source_date"],
            document_url=d.get("document_url"),
            local_path=d["local_path"],
            file_size_bytes=d.get("file_size_bytes"),
            acquired_at=d["acquired_at"],
        )

    @classmethod
    def from_evidence(cls, evidence: Evidence, local_path: str) -> "CatalogEntry":
        return cls(
            evidence_id=evidence.evidence_id,
            source=evidence.source.value,
            kind=evidence.kind.value,
            title=evidence.title,
            source_date=evidence.source_date.isoformat(),
            document_url=evidence.document_url,
            local_path=local_path,
            file_size_bytes=evidence.file_size_bytes,
            acquired_at=datetime.now(timezone.utc).isoformat(),
        )


class RepositoryCatalog:
    """Reads and writes catalog.json for a company repository."""

    _SCHEMA_VERSION = "1"

    def __init__(self, root: Path) -> None:
        self._path = root / "catalog.json"
        self._entries: dict[str, CatalogEntry] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        data = json.loads(self._path.read_text(encoding="utf-8"))
        migrated = False
        for item in data.get("items", []):
            entry = CatalogEntry.from_dict(item)
            # Migrate pre-prefix BSE entries: bare NEWSID (integer or UUID) stored
            # before evidence IDs were namespaced with "bse-news-".
            if entry.source == "BSE" and not entry.evidence_id.startswith("bse-"):
                entry = replace(entry, evidence_id=f"bse-news-{entry.evidence_id}")
                migrated = True
            self._entries[entry.evidence_id] = entry
        if migrated:
            self.save()

    def known_ids(self) -> frozenset[str]:
        return frozenset(self._entries.keys())

    def all_entries(self) -> list["CatalogEntry"]:
        return list(self._entries.values())

    def get_entry(self, evidence_id: str) -> "CatalogEntry | None":
        return self._entries.get(evidence_id)

    def add(self, entry: CatalogEntry) -> None:
        self._entries[entry.evidence_id] = entry

    def save(self) -> None:
        data: dict[str, Any] = {
            "schema_version": self._SCHEMA_VERSION,
            "items": [e.to_dict() for e in self._entries.values()],
        }
        # Write to a sibling temp file, then rename atomically so that a crash
        # between the two operations never corrupts catalog.json.
        #
        # A stale catalog.tmp left by a previous interrupted save is silently
        # overwritten here. We do not attempt to recover or promote it: the
        # file may be partial, and promoting it could replace a newer, valid
        # catalog.json with an older snapshot. Inert stale files are the
        # lesser risk.
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(self._path)
