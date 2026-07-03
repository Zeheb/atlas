"""Cross-company screening — the one query capability with no single-company
precedent in this codebase: every other query (including timeline/compare in
engine.py) operates on one CompanyProfile. Screening needs several at once.

Deliberately kept separate from engine.py rather than folded in: it depends
on CompanyStore for discovery, which the rest of engine.py has no reason to
import (every other query is a pure function of an already-loaded profile).
Both this module and engine.py depend on query.metrics; neither depends on
the other.

No CompanyProfile/CompanyStore change was needed — discover_companies() is
a thin loop over the existing, unmodified CompanyStore.load() API.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from atlas.company.model import CompanyProfile
from atlas.company.store import CompanyStore
from atlas.query import metrics
from atlas.query.engine import QueryResult, TableSection, _fmt_date

_OPS: dict[str, Callable[[float, float], bool]] = {
    ">":  lambda v, t: v > t,
    "<":  lambda v, t: v < t,
    ">=": lambda v, t: v >= t,
    "<=": lambda v, t: v <= t,
    "==": lambda v, t: v == t,
}


def discover_companies(repository_base_path: Path) -> dict[str, CompanyProfile]:
    """Load every company under repository_base_path that has a saved profile.json.

    Silently skips a company whose profile fails to load (e.g. stale
    store_version) rather than failing the whole screen — one bad profile
    shouldn't block screening every other company.
    """
    profiles: dict[str, CompanyProfile] = {}
    if not repository_base_path.exists():
        return profiles
    for child in sorted(repository_base_path.iterdir()):
        if not child.is_dir():
            continue
        profile_path = child / "profile.json"
        if not profile_path.exists():
            continue
        store = CompanyStore(profile_path, child.name)
        try:
            profiles[child.name] = store.load()
        except Exception:
            continue
    return profiles


def screen(
    profiles: dict[str, CompanyProfile],
    metric: str,
    op: str | None = None,
    threshold: float | None = None,
    basis: str = "consolidated",
    period_type: str | None = None,
) -> QueryResult:
    """Rank every company's latest value of *metric*; optionally filter by op+threshold.

    "Latest" means the most recent period (by basis/period_type, for
    financial-domain metrics) that actually has a value for this metric —
    not necessarily the same period across companies, since filing cadence
    and extraction coverage differ (e.g. TCS's FY26 transcript-sourced TCV
    vs. Tata Steel having none at all).

    Sort direction defaults to the metric's higher_is_better hint (best
    first); metrics with no directional hint (None) also sort descending,
    since "rank" implies an order and descending-by-value is the least
    surprising default.

    Raises ValueError for an unregistered metric or unknown operator.
    """
    spec = metrics.get_metric(metric)
    if op is not None and op not in _OPS:
        raise ValueError(f"Unknown operator {op!r}. Available: {sorted(_OPS)}")

    found: list[tuple[str, str, float]] = []
    for company_id, profile in sorted(profiles.items()):
        snaps = metrics.domain_snapshots(profile, spec.domain)
        if spec.domain == "financial":
            snaps = [
                s for s in snaps
                if s.basis == basis and (period_type is None or s.period_type == period_type)
            ]
        snaps = sorted(snaps, key=lambda s: s.period)
        for snap in reversed(snaps):
            value = metrics.snapshot_value(spec, snap)
            if value is not None:
                found.append((company_id, snap.period, value))
                break

    matched = found
    if op is not None and threshold is not None:
        matched = [(cid, period, v) for cid, period, v in found if _OPS[op](v, threshold)]

    reverse = spec.higher_is_better is not False
    matched = sorted(matched, key=lambda r: r[2], reverse=reverse)

    rows = [[cid, _fmt_date(period), metrics.format_value(v, spec.unit)] for cid, period, v in matched]

    notes = [f"{len(found)}/{len(profiles)} companies had data for {spec.label!r}."]
    if op is not None:
        notes.append(f"{len(matched)} matched filter: {metric} {op} {threshold}.")

    title = f"Screen: {spec.label}"
    if op is not None:
        title += f" {op} {threshold}"

    return QueryResult(
        query="screen",
        company_id="ALL",
        title=title,
        sections=[TableSection(
            heading="Ranked Companies",
            columns=["Company", "Latest Period", spec.label],
            rows=rows,
        )],
        notes=notes,
    )
