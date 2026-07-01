"""Longitudinal analysis of shareholding pattern changes across quarters.

Consumes a sequence of AnalysisResult objects — one per quarter, each produced
by the shareholding_pattern analyzer — and computes:

  HoldingPoint   Per-quarter snapshot of all extracted OWNERSHIP_* values.

  HoldingDelta   Signed change in one ownership metric between two periods.
                 Produced for every consecutive quarter pair (QoQ) and for
                 same-quarter pairs one year apart (YoY).

  TrendResult    Container for the above plus notable signals detected from
                 the series.

The public function ``analyze_trend`` works purely from AnalysisResult
objects. No knowledge-base access or document re-reading is required.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Sequence

from atlas.analysis.base import AnalysisResult, FactKind

# ---------------------------------------------------------------------------
# Output types
# ---------------------------------------------------------------------------

@dataclass
class HoldingPoint:
    """Ownership snapshot extracted from one AnalysisResult."""

    evidence_id: str
    period: str                          # ISO quarter-end date, e.g. "2026-03-31"
    facts: dict[FactKind, float | int]   # kind → value (% on 0-100 scale, or count)


@dataclass
class HoldingDelta:
    """Signed change in one ownership metric between two periods."""

    from_period: str
    to_period: str
    kind: FactKind
    delta: float          # to_value - from_value; positive = metric increased
    from_value: float
    to_value: float


@dataclass
class TrendResult:
    """Longitudinal ownership analysis across multiple quarters."""

    points: list[HoldingPoint] = field(default_factory=list)
    """Sorted by period ascending (earliest first)."""

    qoq_deltas: list[HoldingDelta] = field(default_factory=list)
    """Quarter-over-quarter changes for every consecutive period pair."""

    yoy_deltas: list[HoldingDelta] = field(default_factory=list)
    """Year-over-year changes matched to same-calendar-quarter periods."""

    signals: list[str] = field(default_factory=list)
    """Notable changes worth surfacing to an analyst."""

    warnings: list[str] = field(default_factory=list)
    """Non-fatal issues encountered during analysis."""


# ---------------------------------------------------------------------------
# Internal constants
# ---------------------------------------------------------------------------

# The FactKinds we track in the time-series (excludes non-ownership facts
# that can appear in the same result).
_TRACKED_KINDS: tuple[FactKind, ...] = (
    FactKind.OWNERSHIP_PROMOTER_PCT,
    FactKind.OWNERSHIP_PROMOTER_PLEDGED_PCT,
    FactKind.OWNERSHIP_PUBLIC_PCT,
    FactKind.OWNERSHIP_FPI_PCT,
    FactKind.OWNERSHIP_DII_PCT,
    FactKind.OWNERSHIP_MF_PCT,
    FactKind.OWNERSHIP_INSURANCE_PCT,
    FactKind.OWNERSHIP_NRI_PCT,
    FactKind.OWNERSHIP_TOTAL_SHARES,
)

# Minimum absolute change (in percentage points) to generate a single-period signal.
# Share count is excluded (it rarely changes; share splits/buybacks are a different signal).
_SIGNAL_THRESHOLD: dict[FactKind, float] = {
    FactKind.OWNERSHIP_FPI_PCT:              0.50,
    FactKind.OWNERSHIP_DII_PCT:              0.50,
    FactKind.OWNERSHIP_MF_PCT:               0.30,
    FactKind.OWNERSHIP_INSURANCE_PCT:        0.30,
    FactKind.OWNERSHIP_PROMOTER_PCT:         0.05,
    FactKind.OWNERSHIP_PROMOTER_PLEDGED_PCT: 0.001,  # any pledging change is notable
}

_STREAK_LENGTH = 3   # N consecutive same-direction moves triggers a trend signal
_YOY_WINDOW_DAYS = 45  # match same-quarter YoY within this tolerance


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze_trend(results: Sequence[AnalysisResult]) -> TrendResult:
    """Compute longitudinal ownership trends from a sequence of AnalysisResults.

    All results must have ``kind = "shareholding_pattern"``. Results in any
    order are accepted; the function sorts them by the quarter-end period of
    their facts.

    Returns a TrendResult with empty deltas and signals when fewer than two
    valid results are provided (single-point series has no change to measure).
    """
    out = TrendResult()

    if not results:
        return out

    # Filter to expected kind
    valid = [r for r in results if r.kind == "shareholding_pattern"]
    skipped = len(results) - len(valid)
    if skipped:
        out.warnings.append(
            f"{skipped} result(s) skipped: kind != 'shareholding_pattern'"
        )
    if not valid:
        return out

    # Build HoldingPoints
    for result in valid:
        period = _extract_period(result)
        if period is None:
            out.warnings.append(
                f"Period not found in facts for {result.evidence_id!r} — skipping"
            )
            continue
        facts: dict[FactKind, float | int] = {
            f.kind: f.value
            for f in result.facts
            if f.kind in _TRACKED_KINDS
        }
        out.points.append(HoldingPoint(
            evidence_id=result.evidence_id,
            period=period,
            facts=facts,
        ))

    out.points.sort(key=lambda p: p.period)
    _dedup_points(out.points, out.warnings)

    if len(out.points) < 2:
        return out

    # QoQ deltas (every consecutive pair)
    for prev, curr in zip(out.points, out.points[1:]):
        for kind in _TRACKED_KINDS:
            v0 = prev.facts.get(kind)
            v1 = curr.facts.get(kind)
            if v0 is not None and v1 is not None:
                out.qoq_deltas.append(HoldingDelta(
                    from_period=prev.period,
                    to_period=curr.period,
                    kind=kind,
                    delta=round(float(v1) - float(v0), 4),
                    from_value=float(v0),
                    to_value=float(v1),
                ))

    # YoY deltas (same-calendar-quarter, ≈1 year apart)
    _compute_yoy(out.points, out.yoy_deltas)

    # Signals
    out.signals = _detect_signals(out.points, out.qoq_deltas)

    return out


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _extract_period(result: AnalysisResult) -> str | None:
    """Return the quarter-end date from facts in an SHP AnalysisResult."""
    for f in result.facts:
        if f.kind in _TRACKED_KINDS and f.period:
            return f.period
    return None


def _dedup_points(points: list[HoldingPoint], warnings: list[str]) -> None:
    """Remove duplicate periods, keeping the point with more extracted facts."""
    seen: dict[str, int] = {}
    drop: set[int] = set()
    for i, p in enumerate(points):
        if p.period in seen:
            j = seen[p.period]
            if len(p.facts) >= len(points[j].facts):
                drop.add(j)
                seen[p.period] = i
            else:
                drop.add(i)
            warnings.append(
                f"Duplicate period {p.period} in inputs — kept the richer result"
            )
        else:
            seen[p.period] = i
    for i in sorted(drop, reverse=True):
        points.pop(i)


def _compute_yoy(
    points: list[HoldingPoint],
    yoy_deltas: list[HoldingDelta],
) -> None:
    """Append YoY deltas for same-calendar-quarter pairs ≈1 year apart."""
    for i, curr in enumerate(points):
        curr_date = date.fromisoformat(curr.period)
        try:
            target = curr_date.replace(year=curr_date.year - 1)
        except ValueError:
            # leap-day edge case (Feb 29 → Feb 28)
            target = curr_date.replace(year=curr_date.year - 1, day=28)

        best: HoldingPoint | None = None
        best_gap = timedelta(days=_YOY_WINDOW_DAYS + 1)
        for prev in points[:i]:
            gap = abs(date.fromisoformat(prev.period) - target)
            if gap < best_gap:
                best_gap = gap
                best = prev

        if best is None or best_gap.days > _YOY_WINDOW_DAYS:
            continue

        for kind in _TRACKED_KINDS:
            v0 = best.facts.get(kind)
            v1 = curr.facts.get(kind)
            if v0 is not None and v1 is not None:
                yoy_deltas.append(HoldingDelta(
                    from_period=best.period,
                    to_period=curr.period,
                    kind=kind,
                    delta=round(float(v1) - float(v0), 4),
                    from_value=float(v0),
                    to_value=float(v1),
                ))


def _label(kind: FactKind) -> str:
    return kind.value.removeprefix("ownership_").replace("_", " ")


def _detect_signals(
    points: list[HoldingPoint],
    qoq_deltas: list[HoldingDelta],
) -> list[str]:
    signals: list[str] = []

    # Single-period notable moves
    for d in qoq_deltas:
        threshold = _SIGNAL_THRESHOLD.get(d.kind)
        if threshold and abs(d.delta) >= threshold:
            direction = "increased" if d.delta > 0 else "decreased"
            signals.append(
                f"{_label(d.kind)} {direction} {abs(d.delta):.2f}pp "
                f"({d.from_value:.2f}% → {d.to_value:.2f}%) "
                f"{d.from_period} → {d.to_period}"
            )

    # Consecutive-streak signals (N+ same-direction moves)
    by_kind: dict[FactKind, list[HoldingDelta]] = defaultdict(list)
    for d in qoq_deltas:
        by_kind[d.kind].append(d)

    for kind, deltas in by_kind.items():
        n = len(deltas)
        if n < _STREAK_LENGTH:
            continue
        emitted_up = emitted_dn = False
        for i in range(_STREAK_LENGTH - 1, n):
            window = deltas[i - _STREAK_LENGTH + 1 : i + 1]
            all_up = all(w.delta > 0 for w in window)
            all_dn = all(w.delta < 0 for w in window)
            if all_up and not emitted_up:
                signals.append(
                    f"{_label(kind)} rising for {_STREAK_LENGTH}+ consecutive quarters "
                    f"({window[0].from_period} → {window[-1].to_period})"
                )
                emitted_up = True
            elif all_dn and not emitted_dn:
                signals.append(
                    f"{_label(kind)} falling for {_STREAK_LENGTH}+ consecutive quarters "
                    f"({window[0].from_period} → {window[-1].to_period})"
                )
                emitted_dn = True

    # Pledging transitions
    pledge = [
        (p.period, p.facts.get(FactKind.OWNERSHIP_PROMOTER_PLEDGED_PCT))
        for p in points
    ]
    for (p0, v0), (p1, v1) in zip(pledge, pledge[1:]):
        if v0 is not None and v1 is not None:
            if v0 == 0.0 and v1 > 0.0:
                signals.append(
                    f"promoter pledged pct appeared: {v1:.2f}% as of {p1}"
                )
            elif v0 > 0.0 and v1 == 0.0:
                signals.append(
                    f"promoter pledged pct cleared: was {v0:.2f}% as of {p0}"
                )

    return signals
