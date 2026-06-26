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
    except (ValueError, TypeError):
        return None
