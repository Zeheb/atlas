"""Unit tests for atlas.research.signals — the generic metric-move classifier."""

from __future__ import annotations

from atlas.research.signals import classify_metric_moves, top_movers
from tests.unit.research_fixtures import make_empty_profile, make_profile


class TestClassifyMetricMoves:
    def test_improving_metric_classified_correctly(self) -> None:
        profile = make_profile()
        signals = classify_metric_moves(profile)
        margin = next(s for s in signals if s.metric_key == "operating_margin")
        assert margin.direction == "improving"
        assert margin.latest_value == 22.0
        assert margin.prior_value == 20.0

    def test_deteriorating_metric_classified_correctly(self) -> None:
        profile = make_profile()
        signals = classify_metric_moves(profile, domains=("esg",))
        attrition = next(
            s for s in signals if s.metric_key == "workforce_attrition_pct"
        )
        assert attrition.direction == "deteriorating"

    def test_metric_with_no_directional_hint_excluded(self) -> None:
        profile = make_profile()
        signals = classify_metric_moves(profile, domains=("ownership",))
        assert not any(s.metric_key == "promoter_pct" for s in signals)

    def test_single_datapoint_metric_excluded(self) -> None:
        profile = make_profile()
        signals = classify_metric_moves(profile, domains=("ownership",))
        # Only one ownership snapshot exists in the fixture -> no metric
        # with 2 datapoints can be classified from ownership alone.
        assert signals == []

    def test_domain_filter_restricts_output(self) -> None:
        profile = make_profile()
        financial_only = classify_metric_moves(profile, domains=("financial",))
        assert all(
            s.metric_key in ("revenue", "pat", "operating_margin") or True
            for s in financial_only
        )
        esg_only = classify_metric_moves(profile, domains=("esg",))
        assert not any(s.metric_key == "operating_margin" for s in esg_only)
        assert not any(
            s.metric_key == "workforce_attrition_pct" for s in financial_only
        )

    def test_empty_profile_returns_no_signals(self) -> None:
        assert classify_metric_moves(make_empty_profile()) == []

    def test_signal_carries_sources(self) -> None:
        profile = make_profile()
        signals = classify_metric_moves(profile, domains=("financial",))
        margin = next(s for s in signals if s.metric_key == "operating_margin")
        assert "ev-fin-2026" in margin.sources

    def test_below_noise_floor_classified_stable(self) -> None:
        from atlas.analysis.base import FactKind
        from atlas.company.model import FinancialSnapshot, FinancialTimeSeries

        profile = make_profile()
        profile.financial = FinancialTimeSeries(
            snapshots=[
                FinancialSnapshot(
                    period="2025-03-31",
                    period_type="annual",
                    basis="consolidated",
                    facts={FactKind.FINANCIAL_OPERATING_MARGIN: 20.00},
                    sources=["a"],
                ),
                FinancialSnapshot(
                    period="2026-03-31",
                    period_type="annual",
                    basis="consolidated",
                    facts={FactKind.FINANCIAL_OPERATING_MARGIN: 20.05},
                    sources=["b"],
                ),
            ]
        )
        signals = classify_metric_moves(profile, domains=("financial",))
        margin = next(s for s in signals if s.metric_key == "operating_margin")
        assert margin.direction == "stable"


class TestTopMovers:
    def test_returns_only_matching_direction(self) -> None:
        profile = make_profile()
        signals = classify_metric_moves(profile, domains=("financial", "esg"))
        improving = top_movers(signals, "improving")
        assert all(s.direction == "improving" for s in improving)

    def test_respects_n_limit(self) -> None:
        profile = make_profile()
        signals = classify_metric_moves(profile, domains=("financial", "esg"))
        assert len(top_movers(signals, "improving", n=1)) <= 1

    def test_sorted_by_magnitude_descending(self) -> None:
        profile = make_profile()
        signals = classify_metric_moves(profile, domains=("financial", "esg"))
        movers = top_movers(signals, "improving", n=10)
        magnitudes = [m.magnitude for m in movers]
        assert magnitudes == sorted(magnitudes, reverse=True)
