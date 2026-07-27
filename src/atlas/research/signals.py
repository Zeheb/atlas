"""Generic metric-move classification — the one new decision engine in
Atlas Research v1.

Deliberately driven entirely by query.metrics' registry, not by any
company- or sector-specific list. Every metric with a `higher_is_better`
hint is eligible; a company from a fourth sector needs zero code changes
here — whatever metrics that company happens to have data for drive the
result.

What "improving" / "deteriorating" means
-----------------------------------------
Compare the two most recent periods with data for one metric. If the
direction of change agrees with the metric's higher_is_better hint,
classify "improving"; if it disagrees, "deteriorating". A metric with
higher_is_better=None (context-dependent, e.g. promoter ownership — good
for a control thesis, bad for a free-float thesis) is never classified
either way — Atlas doesn't have a basis to call a direction good or bad,
so it doesn't guess.

A move below the noise threshold is classified "stable", not flagged as
either — this prevents a rounding-level wiggle in a metric from reading as
a headline finding.
"""

from __future__ import annotations

from dataclasses import dataclass

from atlas.company.model import CompanyProfile
from atlas.query import metrics as metrics_mod

# Percent-unit metrics: a change below this many percentage points is noise.
_PP_NOISE_FLOOR = 0.3
# Non-percent metrics: a relative change below this fraction is noise.
_RELATIVE_NOISE_FLOOR = 0.02

Direction = str  # "improving" | "deteriorating" | "stable"


@dataclass(frozen=True)
class MetricSignal:
    """One metric's latest period-over-period move.

    magnitude is always a positive number: percentage points for PERCENT-unit
    metrics, relative fraction (0.05 = 5%) otherwise — comparable across
    metrics of the same unit family for ranking "biggest movers", not
    intended to be compared across unit families.
    """

    metric_key: str
    label: str
    direction: Direction
    latest_period: str
    prior_period: str
    latest_value: float
    prior_value: float
    magnitude: float
    sources: list[str]


def _direction(
    spec: metrics_mod.MetricSpec, delta: float, magnitude: float
) -> Direction:
    if spec.unit == metrics_mod.FactUnit.PERCENT:
        if magnitude < _PP_NOISE_FLOOR:
            return "stable"
    else:
        if magnitude < _RELATIVE_NOISE_FLOOR:
            return "stable"
    moved_up = delta > 0
    return "improving" if moved_up == bool(spec.higher_is_better) else "deteriorating"


def classify_metric_moves(
    profile: CompanyProfile,
    basis: str = "consolidated",
    period_type: str = "annual",
    domains: tuple[str, ...] = ("financial", "esg", "ownership"),
) -> list[MetricSignal]:
    """One MetricSignal per registered metric with >=2 datapoints and a
    directional hint, restricted to *domains*.

    domains defaults to all three, but callers building a domain-specific
    section (business_quality.py, balance_sheet.py, esg_governance.py)
    should restrict it — found during validation that an unfiltered call
    let an ESG metric (Waste Recovery %) outrank Operating Margin purely
    because its raw percentage-point swing was larger, which is a domain
    mismatch dressed up as a magnitude ranking, not a real prioritization.

    financial-domain metrics are filtered to *basis*/*period_type* — the
    same filter timeline()/compare() apply — so a quarterly and an annual
    snapshot of the same FactKind are never compared against each other.
    esg/ownership snapshots carry no such distinction and are used as-is.
    """
    signals: list[MetricSignal] = []
    for spec in metrics_mod.METRICS.values():
        if spec.higher_is_better is None or spec.domain not in domains:
            continue
        snaps = metrics_mod.domain_snapshots(profile, spec.domain)
        if spec.domain == "financial":
            snaps = [
                s for s in snaps if s.basis == basis and s.period_type == period_type
            ]
        snaps = sorted(snaps, key=lambda s: s.period)

        points = [
            (s.period, v, s.sources)
            for s in snaps
            if (v := metrics_mod.snapshot_value(spec, s)) is not None
        ]
        if len(points) < 2:
            continue

        (prior_period, prior_value, _), (latest_period, latest_value, sources) = points[
            -2:
        ]
        delta = latest_value - prior_value
        magnitude = (
            abs(delta)
            if spec.unit == metrics_mod.FactUnit.PERCENT
            else (abs(delta) / abs(prior_value) if prior_value else 0.0)
        )
        signals.append(
            MetricSignal(
                metric_key=spec.key,
                label=spec.label,
                direction=_direction(spec, delta, magnitude),
                latest_period=latest_period,
                prior_period=prior_period,
                latest_value=latest_value,
                prior_value=prior_value,
                magnitude=magnitude,
                sources=list(sources),
            )
        )
    return signals


def top_movers(
    signals: list[MetricSignal], direction: Direction, n: int = 3
) -> list[MetricSignal]:
    """The N largest-magnitude signals of one direction, biggest first."""
    matching = [s for s in signals if s.direction == direction]
    return sorted(matching, key=lambda s: s.magnitude, reverse=True)[:n]
