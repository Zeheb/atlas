from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Collection

from atlas.acquisition.catalog import CatalogEntry, RepositoryCatalog
from atlas.acquisition.evidence import EvidenceKind
from atlas.acquisition.profile import AcquisitionProfile


def filter_entries(
    entries: list[CatalogEntry],
    *,
    kinds: Collection[EvidenceKind] | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    profile: AcquisitionProfile | None = None,
) -> list[CatalogEntry]:
    """Filter and sort a list of CatalogEntry objects in memory.

    Filters are AND-combined:
    - kinds: only entries whose kind is in the set
    - since/until: inclusive bounds on source_date (must be timezone-aware)
    - profile: restrict to the kinds the profile covers

    Raise ValueError if both 'kinds' and 'profile' are given.
    Entries with unknown kind strings are excluded when a kind/profile filter is
    active; included otherwise. Entries with unparseable dates are excluded when
    a date filter is active; included otherwise.
    """
    if kinds is not None and profile is not None:
        raise ValueError("Specify at most one of 'kinds' and 'profile'.")

    allowed_kinds: frozenset[EvidenceKind] | None = None
    if profile is not None:
        allowed_kinds = profile.kinds
    elif kinds is not None:
        allowed_kinds = frozenset(kinds)

    result: list[CatalogEntry] = []
    for entry in entries:
        if allowed_kinds is not None:
            try:
                entry_kind = EvidenceKind(entry.kind)
            except ValueError:
                continue
            if entry_kind not in allowed_kinds:
                continue

        if since is not None or until is not None:
            sd = _parse_date(entry.source_date)
            if sd is None:
                continue
            if since is not None and sd < since:
                continue
            if until is not None and sd > until:
                continue

        result.append(entry)

    result.sort(key=lambda e: _parse_date(e.source_date) or _EPOCH)
    return result


def query_evidence(
    repo_root: Path,
    *,
    kinds: Collection[EvidenceKind] | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    profile: AcquisitionProfile | None = None,
) -> list[CatalogEntry]:
    """Load a repository catalog and return filtered, sorted entries.

    Convenience wrapper around filter_entries for callers who have a repo path
    rather than a pre-loaded entry list. A missing catalog.json returns [].
    """
    return filter_entries(
        RepositoryCatalog(repo_root).all_entries(),
        kinds=kinds,
        since=since,
        until=until,
        profile=profile,
    )


_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _parse_date(date_str: str) -> datetime | None:
    try:
        return datetime.fromisoformat(date_str)
    except ValueError, TypeError:
        return None


def _as_utc(dt: datetime) -> datetime:
    """Make a datetime timezone-aware (UTC) so mixed aware/naive catalog dates
    can be compared without raising. Naive dates are assumed UTC."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class HistoryDepth:
    """How far back a company's acquired evidence reaches — the measurement
    the M-P0.2 backfill is run against (Q33: "how did it manage a previous
    crisis, e.g. COVID"). Computed purely from catalog source dates; carries no
    judgment about whether the depth is sufficient — that is the caller's
    thesis-specific question, answered via ``reaches()``.
    """

    entry_count: int  # total catalog entries considered
    dated_count: int  # entries with a parseable source_date
    earliest: datetime | None  # oldest source_date (UTC), None if none dated
    latest: datetime | None  # newest source_date (UTC)
    earliest_by_kind: dict[str, datetime] = field(default_factory=dict)

    @property
    def span_days(self) -> int | None:
        if self.earliest is None or self.latest is None:
            return None
        return (self.latest - self.earliest).days

    @property
    def span_years(self) -> float | None:
        d = self.span_days
        return None if d is None else round(d / 365.25, 2)

    def reaches(self, cutoff: datetime) -> bool:
        """True when the catalog holds at least one document dated on or before
        *cutoff* — i.e. history reaches back that far."""
        return self.earliest is not None and self.earliest <= _as_utc(cutoff)


def history_depth(entries: Collection[CatalogEntry]) -> HistoryDepth:
    """Compute the per-company history depth from catalog entries.

    Entries with an unparseable source_date are counted in ``entry_count`` but
    excluded from date math (mirroring ``filter_entries``'s treatment of
    undated entries under a date filter).
    """
    earliest: datetime | None = None
    latest: datetime | None = None
    by_kind: dict[str, datetime] = {}
    dated = 0

    for entry in entries:
        raw = _parse_date(entry.source_date)
        if raw is None:
            continue
        dt = _as_utc(raw)
        dated += 1
        if earliest is None or dt < earliest:
            earliest = dt
        if latest is None or dt > latest:
            latest = dt
        prev = by_kind.get(entry.kind)
        if prev is None or dt < prev:
            by_kind[entry.kind] = dt

    return HistoryDepth(
        entry_count=len(entries),
        dated_count=dated,
        earliest=earliest,
        latest=latest,
        earliest_by_kind=by_kind,
    )


def repository_history_depth(repo_root: Path) -> HistoryDepth:
    """Load a repository catalog and report its history depth. A missing
    catalog.json yields an empty HistoryDepth (entry_count == 0)."""
    return history_depth(RepositoryCatalog(repo_root).all_entries())
