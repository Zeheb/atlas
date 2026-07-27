"""Unit tests for atlas.research — the reusable citation-formatting toolkit
for research reports.

Synthetic Repository/CompanyProfile via a stub — no real PDFs needed since
this module only ever reads CatalogEntry metadata + citation resolution,
both already covered by test_citation.py.
"""

from __future__ import annotations

from atlas.acquisition.catalog import CatalogEntry
from atlas.company.model import CompanyProfile, FinancialSnapshot, FinancialTimeSeries
from atlas.research import Finding, render_finding, render_report


class _StubRepo:
    """Minimal Repository stand-in: only .get() is used by research.py."""

    def __init__(self, entries: dict[str, CatalogEntry]) -> None:
        self._entries = entries

    def get(self, evidence_id: str) -> CatalogEntry | None:
        return self._entries.get(evidence_id)


def _entry(evidence_id: str, kind: str, source_date: str) -> CatalogEntry:
    return CatalogEntry(
        evidence_id=evidence_id,
        source="BSE",
        kind=kind,
        title="x",
        source_date=source_date,
        document_url=None,
        local_path="x.pdf",
        file_size_bytes=None,
        acquired_at=source_date,
    )


def _fsnap(period, sources) -> FinancialSnapshot:
    return FinancialSnapshot(
        period=period,
        period_type="annual",
        basis="consolidated",
        facts={},
        sources=sources,
    )


class TestRenderFindingSingleSource:
    def _setup(self):
        repo = _StubRepo(
            {"e1": _entry("e1", "annual_report", "2026-05-15T00:00:00+00:00")}
        )
        profile = CompanyProfile(company_id="TCS")
        profile.financial = FinancialTimeSeries(
            snapshots=[_fsnap("2026-03-31", ["e1"])]
        )
        return repo, profile

    def test_uses_source_singular_label(self):
        repo, profile = self._setup()
        finding = Finding(text="Claim text.", evidence_ids=["e1"])
        out = render_finding(finding, "TCS", repo, profile)
        assert "Source:" in out
        assert "Supporting evidence" not in out

    def test_includes_citation_full(self):
        repo, profile = self._setup()
        finding = Finding(text="Claim text.", evidence_ids=["e1"])
        out = render_finding(finding, "TCS", repo, profile)
        assert "TCS FY2026 Annual Report" in out
        assert "Published: May 2026" in out

    def test_section_included_for_single_source(self):
        repo, profile = self._setup()
        finding = Finding(
            text="Claim.", evidence_ids=["e1"], section="Business Outlook"
        )
        out = render_finding(finding, "TCS", repo, profile)
        assert "Section: Business Outlook" in out

    def test_page_included_for_single_source(self):
        repo, profile = self._setup()
        finding = Finding(
            text="Claim.", evidence_ids=["e1"], section="Business Outlook", page=143
        )
        out = render_finding(finding, "TCS", repo, profile)
        assert "Page 143" in out

    def test_page_never_fabricated(self):
        repo, profile = self._setup()
        finding = Finding(text="Claim.", evidence_ids=["e1"])
        out = render_finding(finding, "TCS", repo, profile)
        assert "Page" not in out

    def test_claim_text_present(self):
        repo, profile = self._setup()
        finding = Finding(text="A specific, checkable claim.", evidence_ids=["e1"])
        out = render_finding(finding, "TCS", repo, profile)
        assert "A specific, checkable claim." in out


class TestRenderFindingMultipleSources:
    def _setup(self):
        repo = _StubRepo(
            {
                "e1": _entry("e1", "earnings_transcript", "2026-04-14T00:00:00+00:00"),
                "e2": _entry(
                    "e2", "investor_presentation", "2025-12-17T00:00:00+00:00"
                ),
            }
        )
        profile = CompanyProfile(company_id="TCS")
        profile.financial = FinancialTimeSeries(
            snapshots=[
                _fsnap("2026-03-31", ["e1"]),
                _fsnap("2021-03-31", ["e2"]),
                _fsnap("2025-03-31", ["e2"]),
            ]
        )
        return repo, profile

    def test_uses_supporting_evidence_label(self):
        repo, profile = self._setup()
        finding = Finding(text="A well-corroborated claim.", evidence_ids=["e1", "e2"])
        out = render_finding(finding, "TCS", repo, profile)
        assert "Supporting evidence:" in out
        assert "Source:" not in out

    def test_lists_each_citation_as_bullet(self):
        repo, profile = self._setup()
        finding = Finding(text="Claim.", evidence_ids=["e1", "e2"])
        out = render_finding(finding, "TCS", repo, profile)
        assert "- TCS Q4 FY2026 Earnings Call Transcript" in out
        # e2 spans two periods -> falls back to filing-date naming, per
        # citation.py's multi-period-reference-document rule.
        assert "- TCS Investor Presentation - Dec 2025" in out

    def test_section_and_page_ignored_for_multi_source(self):
        # Attaching one page number to a claim backed by several
        # independent documents wouldn't mean anything — no single page
        # applies to all of them.
        repo, profile = self._setup()
        finding = Finding(text="Claim.", evidence_ids=["e1", "e2"], section="X", page=5)
        out = render_finding(finding, "TCS", repo, profile)
        assert "Page 5" not in out
        assert "Section: X" not in out


class TestRenderFindingMissingEvidence:
    def test_unresolvable_evidence_id_reports_unavailable(self):
        repo = _StubRepo({})
        finding = Finding(text="Claim.", evidence_ids=["nonexistent"])
        out = render_finding(finding, "TCS", repo, None)
        assert "Source: (evidence unavailable)" in out

    def test_no_evidence_ids_reports_unavailable(self):
        repo = _StubRepo({})
        finding = Finding(text="Claim with no citation at all.")
        out = render_finding(finding, "TCS", repo, None)
        assert "Source: (evidence unavailable)" in out

    def test_partial_resolution_shows_only_resolved(self):
        repo = _StubRepo(
            {"e1": _entry("e1", "board_outcome", "2026-04-09T00:00:00+00:00")}
        )
        finding = Finding(text="Claim.", evidence_ids=["e1", "missing"])
        out = render_finding(finding, "TCS", repo, None)
        # Only one resolves -> single-source "Source:" framing, not "Supporting evidence"
        assert "Source:" in out
        assert "TCS Board Outcome - Apr 2026" in out


class TestRenderReport:
    def test_includes_title_and_all_findings(self):
        repo = _StubRepo(
            {"e1": _entry("e1", "board_outcome", "2026-04-09T00:00:00+00:00")}
        )
        findings = [
            Finding(text="First claim.", evidence_ids=["e1"]),
            Finding(text="Second claim.", evidence_ids=["e1"]),
        ]
        out = render_report("Test Report", findings, "TCS", repo, None)
        assert "Test Report" in out
        assert "First claim." in out
        assert "Second claim." in out

    def test_title_underline_matches_length(self):
        repo = _StubRepo({})
        out = render_report("Short", [], "TCS", repo, None)
        lines = out.split("\n")
        assert lines[1] == "=" * len("Short")

    def test_empty_findings_still_renders_title(self):
        repo = _StubRepo({})
        out = render_report("Empty Report", [], "TCS", repo, None)
        assert "Empty Report" in out
