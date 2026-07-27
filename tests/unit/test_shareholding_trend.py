"""Unit tests for atlas.analysis.shareholding_trend.

All tests use synthetic AnalysisResult objects — no file I/O or KB access.
The five-quarter TCS-like dataset covers Q4 FY25 through Q4 FY26 with
approximate real values, producing FPI decline, DII rise, and streak signals.
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone
from typing import Any

from atlas.analysis.base import (
    AnalysisFact,
    AnalysisResult,
    FactKind,
    FactUnit,
    Provenance,
)
from atlas.analysis.shareholding_trend import (
    HoldingDelta,
    HoldingPoint,
    TrendResult,
    analyze_trend,
    _SIGNAL_THRESHOLD,
    _STREAK_LENGTH,
    _TRACKED_KINDS,
)

# ---------------------------------------------------------------------------
# Test data — approximate TCS quarterly holdings (FPI declining, DII rising)
# ---------------------------------------------------------------------------

_QUARTERS: list[dict[str, Any]] = [
    {
        "evidence_id": "bse-shp-532540-q4fy25",
        "period": "2025-03-31",
        "promoter": 71.77,
        "public": 28.23,
        "fpi": 11.24,
        "dii": 12.54,
        "mf": 5.46,
        "insurance": 6.18,
        "nri": 0.24,
        "pledged": 0.0,
        "total_shares": 3_618_087_518,
    },
    {
        "evidence_id": "bse-shp-532540-q1fy26",
        "period": "2025-06-30",
        "promoter": 71.77,
        "public": 28.23,
        "fpi": 10.59,
        "dii": 12.98,
        "mf": 5.68,
        "insurance": 6.44,
        "nri": 0.25,
        "pledged": 0.0,
        "total_shares": 3_618_087_518,
    },
    {
        "evidence_id": "bse-shp-532540-q2fy26",
        "period": "2025-09-30",
        "promoter": 71.77,
        "public": 28.23,
        "fpi": 10.28,
        "dii": 13.09,
        "mf": 5.65,
        "insurance": 6.58,
        "nri": 0.27,
        "pledged": 0.0,
        "total_shares": 3_618_087_518,
    },
    {
        "evidence_id": "bse-shp-532540-q3fy26",
        "period": "2025-12-31",
        "promoter": 71.77,
        "public": 28.23,
        "fpi": 10.01,
        "dii": 13.27,
        "mf": 5.72,
        "insurance": 6.64,
        "nri": 0.26,
        "pledged": 0.0,
        "total_shares": 3_618_087_518,
    },
    {
        "evidence_id": "bse-shp-532540-q4fy26",
        "period": "2026-03-31",
        "promoter": 71.77,
        "public": 28.23,
        "fpi": 9.66,
        "dii": 13.41,
        "mf": 5.77,
        "insurance": 6.69,
        "nri": 0.24,
        "pledged": 0.0,
        "total_shares": 3_618_087_518,
    },
]

_KIND_MAP: dict[str, FactKind] = {
    "promoter": FactKind.OWNERSHIP_PROMOTER_PCT,
    "public": FactKind.OWNERSHIP_PUBLIC_PCT,
    "fpi": FactKind.OWNERSHIP_FPI_PCT,
    "dii": FactKind.OWNERSHIP_DII_PCT,
    "mf": FactKind.OWNERSHIP_MF_PCT,
    "insurance": FactKind.OWNERSHIP_INSURANCE_PCT,
    "nri": FactKind.OWNERSHIP_NRI_PCT,
    "pledged": FactKind.OWNERSHIP_PROMOTER_PLEDGED_PCT,
    "total_shares": FactKind.OWNERSHIP_TOTAL_SHARES,
}

_UNIT_MAP: dict[str, FactUnit] = {
    "total_shares": FactUnit.COUNT,
}


def _make_result(q: dict[str, Any]) -> AnalysisResult:
    """Build a synthetic AnalysisResult for one quarter."""
    period = q["period"]
    result = AnalysisResult(
        evidence_id=q["evidence_id"],
        kind="shareholding_pattern",
        analyzer_version="1.0",
        confidence="high",
        source_date=datetime.fromisoformat(period + "T00:00:00+00:00"),
    )
    for key, kind in _KIND_MAP.items():
        if key not in q:
            continue
        unit = _UNIT_MAP.get(key, FactUnit.PERCENT)
        result.facts.append(
            AnalysisFact(
                kind=kind,
                value=q[key],
                unit=unit,
                period=period,
                confidence="high",
                provenance=Provenance(section="test"),
            )
        )
    return result


# Pre-built results for 5 quarters (earliest → latest)
_R = [_make_result(q) for q in _QUARTERS]


def _qoq(trend: TrendResult, kind: FactKind) -> list[HoldingDelta]:
    return [d for d in trend.qoq_deltas if d.kind == kind]


def _yoy(trend: TrendResult, kind: FactKind) -> list[HoldingDelta]:
    return [d for d in trend.yoy_deltas if d.kind == kind]


# ---------------------------------------------------------------------------
# Empty and degenerate cases
# ---------------------------------------------------------------------------


class TestEmpty:
    def test_no_input_returns_empty_trend(self):
        t = analyze_trend([])
        assert t.points == []
        assert t.qoq_deltas == []
        assert t.yoy_deltas == []
        assert t.signals == []
        assert t.warnings == []

    def test_single_result_no_deltas(self):
        t = analyze_trend([_R[0]])
        assert len(t.points) == 1
        assert t.qoq_deltas == []
        assert t.yoy_deltas == []

    def test_single_result_no_signals(self):
        assert analyze_trend([_R[0]]).signals == []

    def test_all_wrong_kind_returns_empty_with_warning(self):
        bad = AnalysisResult(
            evidence_id="x",
            kind="financial_results",
            analyzer_version="1.0",
            confidence="high",
            source_date=datetime.now(timezone.utc),
        )
        t = analyze_trend([bad])
        assert t.points == []
        assert len(t.warnings) == 1

    def test_mixed_kind_filters_non_shp(self):
        bad = AnalysisResult(
            evidence_id="x",
            kind="financial_results",
            analyzer_version="1.0",
            confidence="high",
            source_date=datetime.now(timezone.utc),
        )
        t = analyze_trend([_R[0], bad])
        assert len(t.points) == 1
        assert any("skipped" in w for w in t.warnings)


# ---------------------------------------------------------------------------
# HoldingPoint extraction and sorting
# ---------------------------------------------------------------------------


class TestHoldingPoints:
    def test_points_sorted_ascending(self):
        t = analyze_trend(list(reversed(_R)))
        periods = [p.period for p in t.points]
        assert periods == sorted(periods)

    def test_point_count_matches_input(self):
        t = analyze_trend(_R)
        assert len(t.points) == 5

    def test_point_period_set(self):
        t = analyze_trend(_R)
        assert t.points[0].period == "2025-03-31"
        assert t.points[-1].period == "2026-03-31"

    def test_point_evidence_id_preserved(self):
        t = analyze_trend(_R[:2])
        eids = {p.evidence_id for p in t.points}
        assert "bse-shp-532540-q4fy25" in eids

    def test_point_facts_extracted(self):
        t = analyze_trend([_R[0]])
        p = t.points[0]
        assert FactKind.OWNERSHIP_PROMOTER_PCT in p.facts
        assert FactKind.OWNERSHIP_FPI_PCT in p.facts
        assert FactKind.OWNERSHIP_TOTAL_SHARES in p.facts

    def test_duplicate_period_deduped(self):
        dup = _make_result(_QUARTERS[0])
        t = analyze_trend([_R[0], dup])
        assert len(t.points) == 1
        assert any("Duplicate" in w for w in t.warnings)

    def test_result_without_period_in_facts_skipped(self):
        result = AnalysisResult(
            evidence_id="no-period",
            kind="shareholding_pattern",
            analyzer_version="1.0",
            confidence="high",
            source_date=datetime.now(timezone.utc),
        )
        t = analyze_trend([result, _R[0]])
        assert len(t.points) == 1
        assert any("Period not found" in w for w in t.warnings)


# ---------------------------------------------------------------------------
# QoQ deltas
# ---------------------------------------------------------------------------


class TestQoQDeltas:
    @pytest.fixture(autouse=True)
    def trend(self):
        self.t = analyze_trend(_R)

    def test_qoq_count_is_n_minus_one_times_kinds(self):
        n_periods = 5
        n_kinds = len(
            [k for k in _TRACKED_KINDS if any(k in p.facts for p in self.t.points)]
        )
        assert len(self.t.qoq_deltas) == (n_periods - 1) * n_kinds

    def test_fpi_qoq_all_negative(self):
        deltas = _qoq(self.t, FactKind.OWNERSHIP_FPI_PCT)
        assert all(d.delta < 0 for d in deltas)

    def test_dii_qoq_all_positive(self):
        deltas = _qoq(self.t, FactKind.OWNERSHIP_DII_PCT)
        assert all(d.delta > 0 for d in deltas)

    def test_promoter_qoq_all_zero(self):
        deltas = _qoq(self.t, FactKind.OWNERSHIP_PROMOTER_PCT)
        assert all(d.delta == 0.0 for d in deltas)

    def test_first_fpi_delta_value(self):
        d = _qoq(self.t, FactKind.OWNERSHIP_FPI_PCT)[0]
        assert d.delta == pytest.approx(-0.65, abs=1e-3)
        assert d.from_period == "2025-03-31"
        assert d.to_period == "2025-06-30"

    def test_first_fpi_delta_from_to_values(self):
        d = _qoq(self.t, FactKind.OWNERSHIP_FPI_PCT)[0]
        assert d.from_value == pytest.approx(11.24, abs=1e-4)
        assert d.to_value == pytest.approx(10.59, abs=1e-4)

    def test_delta_period_continuity(self):
        fpi_deltas = _qoq(self.t, FactKind.OWNERSHIP_FPI_PCT)
        for i in range(len(fpi_deltas) - 1):
            assert fpi_deltas[i].to_period == fpi_deltas[i + 1].from_period

    def test_total_shares_delta_zero(self):
        deltas = _qoq(self.t, FactKind.OWNERSHIP_TOTAL_SHARES)
        assert all(d.delta == 0 for d in deltas)

    def test_two_quarter_scenario(self):
        t = analyze_trend(_R[:2])
        fpi_deltas = _qoq(t, FactKind.OWNERSHIP_FPI_PCT)
        assert len(fpi_deltas) == 1
        assert fpi_deltas[0].delta == pytest.approx(-0.65, abs=1e-3)


# ---------------------------------------------------------------------------
# YoY deltas
# ---------------------------------------------------------------------------


class TestYoYDeltas:
    @pytest.fixture(autouse=True)
    def trend(self):
        self.t = analyze_trend(_R)

    def test_yoy_produced_for_q4fy26(self):
        yoy = _yoy(self.t, FactKind.OWNERSHIP_FPI_PCT)
        assert any(d.to_period == "2026-03-31" for d in yoy)

    def test_fpi_yoy_q4_vs_q4(self):
        yoy = [
            d
            for d in _yoy(self.t, FactKind.OWNERSHIP_FPI_PCT)
            if d.to_period == "2026-03-31"
        ]
        assert len(yoy) == 1
        assert yoy[0].from_period == "2025-03-31"
        assert yoy[0].delta == pytest.approx(9.66 - 11.24, abs=1e-3)

    def test_dii_yoy_q4_positive(self):
        yoy = [
            d
            for d in _yoy(self.t, FactKind.OWNERSHIP_DII_PCT)
            if d.to_period == "2026-03-31"
        ]
        assert len(yoy) == 1
        assert yoy[0].delta > 0

    def test_no_yoy_for_first_four_quarters(self):
        # Only Q4 FY26 has a same-quarter match one year prior (Q4 FY25)
        t = analyze_trend(_R)
        periods_with_yoy = {d.to_period for d in t.yoy_deltas}
        # Q1/Q2/Q3 FY26 have no prior-year equivalent in our 5-quarter window
        for p in ("2025-06-30", "2025-09-30", "2025-12-31"):
            assert p not in periods_with_yoy

    def test_yoy_needs_at_least_5_quarters(self):
        t_4q = analyze_trend(_R[1:])  # Q1-Q4 FY26 only (no same-quarter prior year)
        assert t_4q.yoy_deltas == []


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------


class TestSignals:
    @pytest.fixture(autouse=True)
    def trend(self):
        self.t = analyze_trend(_R)
        self.sigs = "\n".join(self.t.signals)

    def test_signals_non_empty(self):
        assert len(self.t.signals) > 0

    def test_fpi_notable_decline_first_quarter(self):
        # Q4FY25 → Q1FY26: -0.65pp exceeds threshold 0.50
        assert any(
            "fpi pct" in s and "decreased" in s and "0.65pp" in s
            for s in self.t.signals
        )

    def test_fpi_streak_signal(self):
        assert any(
            "fpi pct" in s and "falling" in s and "3+" in s for s in self.t.signals
        )

    def test_dii_streak_signal(self):
        assert any(
            "dii pct" in s and "rising" in s and "3+" in s for s in self.t.signals
        )

    def test_insurance_streak_signal(self):
        assert any(
            "insurance pct" in s and "rising" in s and "3+" in s for s in self.t.signals
        )

    def test_promoter_stable_no_signal(self):
        assert not any("promoter pct" in s for s in self.t.signals)

    def test_no_pledging_signal_when_always_zero(self):
        assert not any("pledged" in s for s in self.t.signals)

    def test_single_period_signal_includes_arrow(self):
        # Signals include "X% → Y%" format
        assert any("→" in s for s in self.t.signals)

    def test_streak_signal_includes_period_range(self):
        fpi_streak = [s for s in self.t.signals if "fpi pct" in s and "falling" in s]
        assert len(fpi_streak) == 1
        assert "2025-03-31 → " in fpi_streak[0]

    def test_no_duplicate_streak_signal_per_kind(self):
        fpi_streaks = [s for s in self.t.signals if "fpi pct" in s and "falling" in s]
        assert len(fpi_streaks) == 1

    def test_two_quarters_no_streak(self):
        t = analyze_trend(_R[:2])
        assert not any("3+" in s for s in t.signals)


# ---------------------------------------------------------------------------
# Pledging transitions
# ---------------------------------------------------------------------------


class TestPledging:
    def _make_pledging(self, period: str, pledged: float) -> AnalysisResult:
        q = {
            "evidence_id": f"shp-{period}",
            "period": period,
            "promoter": 71.77,
            "public": 28.23,
            "fpi": 10.0,
            "dii": 13.0,
            "mf": 5.5,
            "insurance": 6.5,
            "nri": 0.25,
            "pledged": pledged,
            "total_shares": 3_618_087_518,
        }
        return _make_result(q)

    def test_pledging_appears(self):
        r1 = self._make_pledging("2025-03-31", 0.0)
        r2 = self._make_pledging("2025-06-30", 1.5)
        t = analyze_trend([r1, r2])
        assert any("appeared" in s and "1.50%" in s for s in t.signals)

    def test_pledging_cleared(self):
        r1 = self._make_pledging("2025-03-31", 2.3)
        r2 = self._make_pledging("2025-06-30", 0.0)
        t = analyze_trend([r1, r2])
        assert any("cleared" in s and "2.30%" in s for s in t.signals)

    def test_no_signal_when_pledging_unchanged_nonzero(self):
        r1 = self._make_pledging("2025-03-31", 1.5)
        r2 = self._make_pledging("2025-06-30", 1.5)
        t = analyze_trend([r1, r2])
        assert not any("pledged" in s for s in t.signals)

    def test_no_signal_when_always_zero(self):
        r1 = self._make_pledging("2025-03-31", 0.0)
        r2 = self._make_pledging("2025-06-30", 0.0)
        t = analyze_trend([r1, r2])
        assert not any("pledged" in s for s in t.signals)


# ---------------------------------------------------------------------------
# TrendResult shape
# ---------------------------------------------------------------------------


class TestTrendResultShape:
    def test_result_is_trend_result(self):
        assert isinstance(analyze_trend(_R), TrendResult)

    def test_holding_points_are_holding_point(self):
        t = analyze_trend(_R)
        assert all(isinstance(p, HoldingPoint) for p in t.points)

    def test_qoq_deltas_are_holding_delta(self):
        t = analyze_trend(_R)
        assert all(isinstance(d, HoldingDelta) for d in t.qoq_deltas)

    def test_signals_are_strings(self):
        t = analyze_trend(_R)
        assert all(isinstance(s, str) for s in t.signals)

    def test_warnings_are_strings(self):
        t = analyze_trend(_R)
        assert all(isinstance(w, str) for w in t.warnings)

    def test_clean_run_no_warnings(self):
        t = analyze_trend(_R)
        assert t.warnings == []
