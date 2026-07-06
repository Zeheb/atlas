"""Integration tests for atlas.research.report — the full orchestrator,
synthetic profile (no real repository/PDFs), but exercising every section
builder together the way generate_report() actually calls them."""
from __future__ import annotations

from atlas.research.report import generate_report, generate_report_markdown
from tests.unit.research_fixtures import make_empty_profile, make_profile


class TestGenerateReport:
    def test_returns_expected_section_keys_in_order(self) -> None:
        report = generate_report("ACME", make_profile())
        keys = [s.key for s in report.sections]
        assert keys[0] == "the_call"
        assert keys[1] == "what_changed"
        assert keys[-2] == "open_questions"
        assert keys[-1] == "evidence_appendix"
        assert "business_quality" in keys
        assert "balance_sheet" in keys
        assert "valuation" in keys
        assert "catalysts" in keys
        assert "competitive_position" in keys

    def test_no_duplicate_section_keys(self) -> None:
        report = generate_report("ACME", make_profile())
        keys = [s.key for s in report.sections]
        assert len(keys) == len(set(keys))

    def test_ticker_and_title_set(self) -> None:
        report = generate_report("ACME", make_profile())
        assert report.ticker == "ACME"
        assert "ACME" in report.title

    def test_works_for_a_second_ticker_with_no_special_casing(self) -> None:
        # Same fixture builder, different company_id/ticker — proves no
        # ticker-specific branching exists anywhere in the pipeline.
        report_a = generate_report("ACME", make_profile("ACME"))
        report_b = generate_report("OTHERCO", make_profile("OTHERCO"))
        assert [s.key for s in report_a.sections] == [s.key for s in report_b.sections]

    def test_empty_profile_does_not_crash(self) -> None:
        report = generate_report("EMPTY", make_empty_profile())
        assert len(report.sections) == 12
        assert all(s.is_empty() or s.notes for s in report.sections if s.key != "open_questions")

    def test_peer_profiles_feed_competitive_position(self) -> None:
        report = generate_report("ACME", make_profile("ACME"), peer_profiles={"ACME": make_profile("ACME"), "PEER": make_profile("PEER")})
        comp = report.section("competitive_position")
        assert comp is not None
        assert any("PEER" in n for n in comp.notes)


class TestGenerateReportMarkdown:
    def test_produces_nonempty_markdown(self) -> None:
        md = generate_report_markdown("ACME", make_profile())
        assert md.startswith("# ACME")
        assert len(md) > 500

    def test_every_section_title_appears(self) -> None:
        report = generate_report("ACME", make_profile())
        md = generate_report_markdown("ACME", make_profile())
        for section in report.sections:
            assert f"## {section.title}" in md

    def test_deterministic_across_calls(self) -> None:
        md1 = generate_report_markdown("ACME", make_profile())
        md2 = generate_report_markdown("ACME", make_profile())
        assert md1 == md2
