from datetime import datetime
from pathlib import Path
from typing import Collection

from atlas.acquisition.catalog import CatalogEntry, RepositoryCatalog
from atlas.acquisition.evidence import EvidenceKind
from atlas.acquisition.profile import AcquisitionProfile
from atlas.acquisition.query import filter_entries


class Repository:
    """Read-only view of a single company's acquisition repository.

    Loads the catalog once at construction time; all methods operate on that
    snapshot. Create a new Repository instance after an acquisition run to
    reflect newly downloaded evidence.

    The Repository is the single interface downstream analysis should use.
    It provides named, high-level methods instead of exposing catalog
    internals, query functions, or raw filesystem paths.
    """

    def __init__(self, root: Path) -> None:
        self._root = root
        self._catalog = RepositoryCatalog(root)

    @property
    def root(self) -> Path:
        return self._root

    def list_evidence(
        self,
        *,
        kinds: Collection[EvidenceKind] | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        profile: AcquisitionProfile | None = None,
    ) -> list[CatalogEntry]:
        """Return catalog entries matching all supplied filters, sorted by source_date ascending.

        Filters are AND-combined. Raise ValueError if both 'kinds' and 'profile' are given.
        """
        return filter_entries(
            self._catalog.all_entries(),
            kinds=kinds,
            since=since,
            until=until,
            profile=profile,
        )

    def get(self, evidence_id: str) -> CatalogEntry | None:
        """Return the catalog entry for an evidence ID, or None if not found."""
        return self._catalog.get_entry(evidence_id)

    def open(self, evidence_id: str) -> Path:
        """Return the absolute local Path to a downloaded evidence file.

        Raise KeyError if the evidence ID is not in the catalog.
        Raise FileNotFoundError if the file has been removed from disk since acquisition.
        """
        entry = self._catalog.get_entry(evidence_id)
        if entry is None:
            raise KeyError(evidence_id)
        path = self._root / entry.local_path
        if not path.exists():
            raise FileNotFoundError(f"Local file missing: {path}")
        return path

    def exists(self, evidence_id: str) -> bool:
        """Return True if the evidence ID is present in the catalog."""
        return self._catalog.get_entry(evidence_id) is not None

    def latest(
        self,
        kind: EvidenceKind,
        *,
        since: datetime | None = None,
    ) -> CatalogEntry | None:
        """Return the most recent catalog entry of the given kind, or None if none exists.

        'Most recent' means highest source_date. An optional 'since' bound excludes
        entries before that date.
        """
        entries = self.list_evidence(kinds={kind}, since=since)
        return entries[-1] if entries else None
