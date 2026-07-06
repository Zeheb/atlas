"""Unit tests for atlas.query.metrics — the metric registry.

Covers: every registered metric resolves to a real FactKind or derive_fn,
get_metric()/metrics_by_domain() behave correctly, domain_snapshots()/
snapshot_value()/format_value() read profiles correctly for each domain.
"""
from __future__ import annotations

import pytest

from atlas.analysis.base import FactKind, FactUnit
from atlas.company.model import (
    CompanyProfile,
    ESGSnapshot,
    ESGTimeSeries,
    FinancialSnapshot,
    FinancialTimeSeries,
    OwnershipSnapshot,
    OwnershipTimeSeries,
)
from atlas.query import metrics


class TestRegistryIntegrity:
    def test_every_metric_has_exactly_one_source(self) -> None:
        for spec in metrics.METRICS.values():
            has_kind = spec.fact_kind is not None
            has_fn = spec.derive_fn is not None
            assert has_kind != has_fn, f"{spec.key} must set exactly one of fact_kind/derive_fn"

    def test_every_fact_kind_metric_resolves(self) -> None:
        for spec in metrics.METRICS.values():
            if spec.fact_kind is not None:
                assert isinstance(spec.fact_kind, FactKind)

    def test_domain_is_valid(self) -> None:
        for spec in metrics.METRICS.values():
            assert spec.domain in ("financial", "esg", "ownership")

    def test_derive_fn_metrics_are_financial_domain(self) -> None:
        # derived.py only operates on FinancialSnapshot
        for spec in metrics.METRICS.values():
            if spec.derive_fn is not None:
                assert spec.domain == "financial"

    def test_no_duplicate_keys(self) -> None:
        keys = [spec.key for spec in metrics._SPECS]
        assert len(keys) == len(set(keys))

    def test_registry_size_reflects_ontology_audit(self) -> None:
        # Not an exact pin — just guards against silently losing most of the
        # registry in a future refactor (the whole point of this module is
        # that ~70 previously-dark FactKinds became queryable through it).
        assert len(metrics.METRICS) >= 65


class TestGetMetric:
    def test_known_key_returns_spec(self) -> None:
        spec = metrics.get_metric("revenue")
        assert spec.fact_kind == FactKind.FINANCIAL_REVENUE

    def test_unknown_key_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown metric"):
            metrics.get_metric("not_a_real_metric")

    def test_banking_ratio_registered(self) -> None:
        # The audit's headline finding: banking ratios had zero query access.
        spec = metrics.get_metric("gross_npa_ratio")
        assert spec.fact_kind == FactKind.FINANCIAL_GROSS_NPA_RATIO
        assert spec.domain == "financial"

    def test_esg_metric_registered(self) -> None:
        spec = metrics.get_metric("ghg_scope1")
        assert spec.fact_kind == FactKind.ESG_GHG_SCOPE1
        assert spec.domain == "esg"

    def test_derived_metric_registered(self) -> None:
        spec = metrics.get_metric("ebitda_margin")
        assert spec.derive_fn is not None
        assert spec.fact_kind is None


class TestMetricsByDomain:
    def test_partitions_all_metrics(self) -> None:
        by_domain = metrics.metrics_by_domain()
        total = sum(len(v) for v in by_domain.values())
        assert total == len(metrics.METRICS)

    def test_each_domain_sorted_by_key(self) -> None:
        by_domain = metrics.metrics_by_domain()
        for specs in by_domain.values():
            keys = [s.key for s in specs]
            assert keys == sorted(keys)


class TestDomainSnapshots:
    def _profile(self) -> CompanyProfile:
        p = CompanyProfile(company_id="TEST")
        p.financial = FinancialTimeSeries(snapshots=[
            FinancialSnapshot(period="2026-03-31", period_type="annual", basis="consolidated", facts={}, sources=[]),
        ])
        p.esg = ESGTimeSeries(snapshots=[
            ESGSnapshot(period="2026-03-31", facts={}, sources=[]),
        ])
        p.ownership = OwnershipTimeSeries(snapshots=[
            OwnershipSnapshot(period="2026-03-31", facts={}, sources=[]),
        ])
        return p

    def test_financial_domain(self) -> None:
        p = self._profile()
        assert metrics.domain_snapshots(p, "financial") is p.financial.snapshots

    def test_esg_domain(self) -> None:
        p = self._profile()
        assert metrics.domain_snapshots(p, "esg") is p.esg.snapshots

    def test_ownership_domain(self) -> None:
        p = self._profile()
        assert metrics.domain_snapshots(p, "ownership") is p.ownership.snapshots

    def test_unknown_domain_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown metric domain"):
            metrics.domain_snapshots(self._profile(), "bogus")


class TestSnapshotValue:
    def test_fact_kind_metric_reads_facts_dict(self) -> None:
        spec = metrics.get_metric("gross_npa_ratio")
        snap = FinancialSnapshot(
            period="2026-03-31", period_type="quarterly", basis="consolidated",
            facts={FactKind.FINANCIAL_GROSS_NPA_RATIO: 1.73}, sources=[],
        )
        assert metrics.snapshot_value(spec, snap) == 1.73

    def test_fact_kind_metric_missing_returns_none(self) -> None:
        spec = metrics.get_metric("gross_npa_ratio")
        snap = FinancialSnapshot(period="2026-03-31", period_type="quarterly", basis="consolidated", facts={}, sources=[])
        assert metrics.snapshot_value(spec, snap) is None

    def test_derived_metric_computes_from_snapshot(self) -> None:
        spec = metrics.get_metric("net_debt")
        snap = FinancialSnapshot(
            period="2026-03-31", period_type="annual", basis="consolidated",
            facts={FactKind.FINANCIAL_TOTAL_DEBT: 1000.0, FactKind.FINANCIAL_CASH_AND_EQUIVALENTS: 300.0},
            sources=[],
        )
        assert metrics.snapshot_value(spec, snap) == 700.0

    def test_derived_metric_missing_inputs_returns_none(self) -> None:
        spec = metrics.get_metric("net_debt")
        snap = FinancialSnapshot(period="2026-03-31", period_type="annual", basis="consolidated", facts={}, sources=[])
        assert metrics.snapshot_value(spec, snap) is None


class TestFormatValue:
    def test_crore_inr(self) -> None:
        assert metrics.format_value(70698.0, FactUnit.CRORE_INR) == "70,698 cr"

    def test_percent(self) -> None:
        assert metrics.format_value(25.3, FactUnit.PERCENT) == "25.30%"

    def test_usd_billion(self) -> None:
        assert metrics.format_value(12.0, FactUnit.USD_BILLION) == "$12.00B"

    def test_count(self) -> None:
        assert metrics.format_value(617437.0, FactUnit.COUNT) == "617,437"

    def test_tco2e(self) -> None:
        assert metrics.format_value(22631.0, FactUnit.TCO2E) == "22,631 tCO2e"

    def test_none_unit_falls_back_to_generic(self) -> None:
        # 3 decimals, not 2 — a small-magnitude ratio like LTIFR needs the
        # extra precision to remain distinguishable from a neighboring
        # period's value (0.025 vs 0.028 both round to "0.03" at 2dp).
        assert metrics.format_value(0.028, None) == "0.028"
