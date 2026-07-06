"""Unit tests for atlas.citation — the human-readable citation model.

Synthetic CompanyProfile/CatalogEntry fixtures. Regression tests are named
after the real bugs found while building this against actual TCS data:
a Q4 call losing its quarter number because period_type=="annual", and a
multi-year strategy deck being mislabelled as if it were one quarter's
earnings deck.
"""
from __future__ import annotations

from datetime import datetime, timezone

from atlas.acquisition.catalog import CatalogEntry
from atlas.citation import build_citation, resolve_agency, resolve_period
from atlas.company.model import (
    CompanyProfile,
    CreditHistory,
    CreditRatingEntry,
    ESGSnapshot,
    ESGTimeSeries,
    FinancialSnapshot,
    FinancialTimeSeries,
)

_DT = datetime(2026, 4, 14, tzinfo=timezone.utc)


def _entry(evidence_id: str, kind: str, source_date: str, title: str = "x") -> CatalogEntry:
    return CatalogEntry(
        evidence_id=evidence_id,
        source="BSE",
        kind=kind,
        title=title,
        source_date=source_date,
        document_url=None,
        local_path="x.pdf",
        file_size_bytes=None,
        acquired_at=source_date,
    )


def _fsnap(period, facts, period_type="quarterly", basis="consolidated", sources=None) -> FinancialSnapshot:
    return FinancialSnapshot(period=period, period_type=period_type, basis=basis, facts=facts, sources=sources or [])


# ---------------------------------------------------------------------------
# resolve_period
# ---------------------------------------------------------------------------


class TestResolvePeriod:
    def test_no_profile_returns_none(self):
        assert resolve_period("e1", None) == (None, None, False)

    def test_not_found_returns_none(self):
        p = CompanyProfile(company_id="TCS")
        assert resolve_period("e1", p) == (None, None, False)

    def test_found_in_financial_snapshot(self):
        p = CompanyProfile(company_id="TCS")
        p.financial = FinancialTimeSeries(snapshots=[_fsnap("2026-03-31", {}, sources=["e1"])])
        period, period_type, spans = resolve_period("e1", p)
        assert period == "2026-03-31"
        assert period_type == "quarterly"
        assert spans is False

    def test_prefers_latest_of_multiple_matches(self):
        # Regression: a document contributing to several periods (e.g. a
        # multi-year reference table) must resolve to the latest, not
        # whichever snapshot happens to be first in the sorted-ASC list.
        p = CompanyProfile(company_id="TCS")
        p.financial = FinancialTimeSeries(snapshots=[
            _fsnap("2021-03-31", {}, period_type="annual", sources=["deck-1"]),
            _fsnap("2023-03-31", {}, period_type="annual", sources=["deck-1"]),
            _fsnap("2025-03-31", {}, period_type="annual", sources=["deck-1"]),
        ])
        period, _, spans = resolve_period("deck-1", p)
        assert period == "2025-03-31"
        assert spans is True

    def test_single_match_not_flagged_as_spanning(self):
        p = CompanyProfile(company_id="TCS")
        p.financial = FinancialTimeSeries(snapshots=[_fsnap("2026-03-31", {}, sources=["e1"])])
        _, _, spans = resolve_period("e1", p)
        assert spans is False

    def test_esg_snapshot_match(self):
        p = CompanyProfile(company_id="TCS")
        p.esg = ESGTimeSeries(snapshots=[ESGSnapshot(period="2026-03-31", facts={}, sources=["e1"])])
        period, period_type, _ = resolve_period("e1", p)
        assert period == "2026-03-31"
        assert period_type is None


class TestResolveAgency:
    def test_found(self):
        p = CompanyProfile(company_id="TCS")
        p.credit_history = CreditHistory(debt_ratings=[
            CreditRatingEntry(source_date=_DT, agency="CRISIL", evidence_id="e1"),
        ])
        assert resolve_agency("e1", p) == "CRISIL"

    def test_not_found(self):
        assert resolve_agency("e1", CompanyProfile(company_id="TCS")) is None

    def test_checks_esg_ratings_too(self):
        p = CompanyProfile(company_id="TCS")
        p.credit_history = CreditHistory(esg_ratings=[
            CreditRatingEntry(source_date=_DT, agency="NSE Sustainability", evidence_id="e2"),
        ])
        assert resolve_agency("e2", p) == "NSE Sustainability"


# ---------------------------------------------------------------------------
# build_citation — per-kind display name templates
# ---------------------------------------------------------------------------


class TestDisplayNameTemplates:
    def _profile_with(self, evidence_id: str, period: str, period_type: str = "quarterly") -> CompanyProfile:
        p = CompanyProfile(company_id="TCS")
        p.financial = FinancialTimeSeries(snapshots=[_fsnap(period, {}, period_type=period_type, sources=[evidence_id])])
        return p

    def test_earnings_transcript_quarterly(self):
        entry = _entry("e1", "earnings_transcript", "2025-10-15T00:00:00+00:00")
        profile = self._profile_with("e1", "2025-09-30", "quarterly")
        c = build_citation(entry, "TCS", profile)
        assert c.display_name == "TCS Q2 FY2026 Earnings Call Transcript"

    def test_earnings_transcript_q4_keeps_quarter_despite_annual_period_type(self):
        # Regression: a Q4-and-full-year call is annual-scoped in
        # period_type but still happened in a specific quarter — must not
        # drop to a bare "FY2026" label.
        entry = _entry("e1", "earnings_transcript", "2026-04-14T00:00:00+00:00")
        profile = self._profile_with("e1", "2026-03-31", "annual")
        c = build_citation(entry, "TCS", profile)
        assert c.display_name == "TCS Q4 FY2026 Earnings Call Transcript"

    def test_financial_results_quarterly(self):
        entry = _entry("e1", "financial_results", "2026-04-09T00:00:00+00:00")
        profile = self._profile_with("e1", "2026-03-31", "annual")
        c = build_citation(entry, "TCS", profile)
        assert c.display_name == "TCS Q4 FY2026 Financial Results"

    def test_annual_report_fy_only(self):
        entry = _entry("e1", "annual_report", "2026-05-15T00:00:00+00:00")
        profile = self._profile_with("e1", "2026-03-31", "annual")
        # Annual reports route to ESG snapshots typically, but a financial
        # snapshot match works identically for period resolution.
        c = build_citation(entry, "TCS", profile)
        assert c.display_name == "TCS FY2026 Annual Report"

    def test_brsr_fy_only(self):
        entry = _entry("e1", "brsr", "2026-06-01T00:00:00+00:00")
        p = CompanyProfile(company_id="TATASTEEL")
        p.esg = ESGTimeSeries(snapshots=[ESGSnapshot(period="2026-03-31", facts={}, sources=["e1"])])
        c = build_citation(entry, "TATASTEEL", p)
        assert c.display_name == "TATASTEEL FY2026 BRSR"

    def test_multi_year_deck_falls_back_to_filing_date(self):
        # Regression: a strategy deck backing a 5-year ROE/FCF table must
        # not be labelled as if it were one specific quarter's earnings deck.
        entry = _entry("e1", "investor_presentation", "2025-12-17T00:00:00+00:00")
        p = CompanyProfile(company_id="TCS")
        p.financial = FinancialTimeSeries(snapshots=[
            _fsnap("2021-03-31", {}, period_type="annual", sources=["e1"]),
            _fsnap("2025-03-31", {}, period_type="annual", sources=["e1"]),
        ])
        c = build_citation(entry, "TCS", p)
        assert c.display_name == "TCS Investor Presentation - Dec 2025"

    def test_board_outcome_uses_month_year(self):
        entry = _entry("e1", "board_outcome", "2026-04-09T00:00:00+00:00")
        c = build_citation(entry, "TCS", None)
        assert c.display_name == "TCS Board Outcome - Apr 2026"

    def test_shareholding_pattern_uses_month_year(self):
        entry = _entry("e1", "shareholding_pattern", "2025-09-30T00:00:00+00:00")
        c = build_citation(entry, "SBI", None)
        assert c.display_name == "SBI Shareholding Pattern - Sep 2025"

    def test_credit_rating_includes_agency(self):
        entry = _entry("e1", "credit_rating_report", "2026-05-01T00:00:00+00:00")
        p = CompanyProfile(company_id="TCS")
        p.credit_history = CreditHistory(debt_ratings=[
            CreditRatingEntry(source_date=_DT, agency="CRISIL", evidence_id="e1"),
        ])
        c = build_citation(entry, "TCS", p)
        assert c.display_name == "TCS Credit Rating Report (CRISIL) - May 2026"

    def test_credit_rating_no_agency_omits_parens(self):
        entry = _entry("e1", "credit_rating_report", "2026-05-01T00:00:00+00:00")
        c = build_citation(entry, "TCS", None)
        assert c.display_name == "TCS Credit Rating Report - May 2026"

    def test_no_profile_falls_back_gracefully_for_quarter_covering_kind(self):
        entry = _entry("e1", "earnings_transcript", "2026-04-14T00:00:00+00:00")
        c = build_citation(entry, "TCS", None)
        assert c.display_name == "TCS Earnings Call Transcript - Apr 2026"

    def test_unmapped_kind_uses_title_cased_fallback(self):
        entry = _entry("e1", "research_report", "2026-04-14T00:00:00+00:00")
        c = build_citation(entry, "TCS", None)
        assert "Research Report" in c.display_name


# ---------------------------------------------------------------------------
# canonical_name
# ---------------------------------------------------------------------------


class TestCanonicalName:
    def test_uses_period_when_resolved(self):
        entry = _entry("e1", "earnings_transcript", "2026-04-14T00:00:00+00:00")
        p = CompanyProfile(company_id="TCS")
        p.financial = FinancialTimeSeries(snapshots=[_fsnap("2026-03-31", {}, sources=["e1"])])
        c = build_citation(entry, "TCS", p)
        assert c.canonical_name == "TCS/EARNINGS_TRANSCRIPT/2026-03-31"

    def test_falls_back_to_source_date(self):
        entry = _entry("e1", "board_outcome", "2026-04-09T00:00:00+00:00")
        c = build_citation(entry, "TCS", None)
        assert c.canonical_name == "TCS/BOARD_OUTCOME/2026-04-09"

    def test_evidence_id_unchanged(self):
        entry = _entry("bse-news-abc-123", "board_outcome", "2026-04-09T00:00:00+00:00")
        c = build_citation(entry, "TCS", None)
        assert c.evidence_id == "bse-news-abc-123"


# ---------------------------------------------------------------------------
# citation_short / citation_standard / citation_full
# ---------------------------------------------------------------------------


class TestCitationFormats:
    def _tcs_transcript_citation(self):
        entry = _entry("e1", "earnings_transcript", "2026-04-14T00:00:00+00:00")
        p = CompanyProfile(company_id="TCS")
        p.financial = FinancialTimeSeries(snapshots=[_fsnap("2026-03-31", {}, period_type="annual", sources=["e1"])])
        return build_citation(entry, "TCS", p)

    def test_citation_standard_equals_display_name(self):
        c = self._tcs_transcript_citation()
        assert c.citation_standard == c.display_name

    def test_citation_short_is_bracketed_and_compact(self):
        c = self._tcs_transcript_citation()
        assert c.citation_short == "[TCS Q4 FY26 Transcript]"

    def test_citation_full_without_section_or_page(self):
        c = self._tcs_transcript_citation()
        assert c.citation_full == "TCS Q4 FY2026 Earnings Call Transcript\nPublished: Apr 2026"

    def test_citation_full_with_section(self):
        entry = _entry("e1", "annual_report", "2026-05-15T00:00:00+00:00")
        c = build_citation(entry, "TCS", None, section="Business Outlook")
        assert "Section: Business Outlook" in c.citation_full

    def test_citation_full_never_fabricates_page(self):
        c = self._tcs_transcript_citation()
        assert "Page" not in c.citation_full
        assert c.page is None

    def test_citation_full_includes_page_when_given(self):
        entry = _entry("e1", "annual_report", "2026-05-15T00:00:00+00:00")
        c = build_citation(entry, "TCS", None, section="Business Outlook", page=143)
        assert "Page 143" in c.citation_full


# ---------------------------------------------------------------------------
# citation_for (catalog-lookup convenience)
# ---------------------------------------------------------------------------


class TestCitationFor:
    def test_missing_evidence_id_returns_none(self):
        from atlas.citation import citation_for
        assert citation_for("nope", {}, "TCS", None) is None

    def test_found_builds_citation(self):
        from atlas.citation import citation_for
        entry = _entry("e1", "board_outcome", "2026-04-09T00:00:00+00:00")
        c = citation_for("e1", {"e1": entry}, "TCS", None)
        assert c is not None
        assert c.display_name == "TCS Board Outcome - Apr 2026"
