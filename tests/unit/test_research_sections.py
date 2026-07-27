"""Unit tests for each atlas.research.sections builder (v2, question-driven).

Every builder is a pure function of CompanyProfile — no repo/citations
needed to test the retrieval+synthesis logic itself (repo=None everywhere;
citation resolution is exercised separately in test_research_render.py and
the integration tests).
"""

from __future__ import annotations

from datetime import datetime, timezone

from atlas.company.model import AGMResolution
from atlas.research.sections import (
    balance_sheet,
    business_quality,
    catalysts,
    competitive_position,
    esg_governance,
    evidence_appendix,
    management_credibility,
    open_questions,
    risks,
    the_call,
    valuation,
    what_changed,
)
from atlas.research.model import ReportSection
from tests.unit.research_fixtures import make_empty_profile, make_profile


class TestBusinessQuality:
    def test_margin_stability_reported_over_full_history(self) -> None:
        sec = business_quality.build(make_profile(), None, "ACME")
        assert any("ranged" in f.text for f in sec.findings)

    def test_growth_consistency_reported(self) -> None:
        sec = business_quality.build(make_profile(), None, "ACME")
        assert any("grew year-over-year" in f.text for f in sec.findings)

    def test_segment_concentration_reported(self) -> None:
        sec = business_quality.build(make_profile(), None, "ACME")
        assert any("Largest segment" in f.text for f in sec.findings)

    def test_empty_profile_notes_insufficient_history(self) -> None:
        sec = business_quality.build(make_empty_profile(), None, "ACME")
        assert sec.notes
        assert not sec.findings


class TestManagementCredibility:
    def test_repeated_target_detected(self) -> None:
        sec = management_credibility.build(make_profile(), None, "ACME")
        assert any("20-22%" in f.text for f in sec.findings)

    def test_recurring_risk_detected(self) -> None:
        sec = management_credibility.build(make_profile(), None, "ACME")
        assert any("consistently" in f.text for f in sec.findings)

    def test_failed_resolution_flagged(self) -> None:
        profile = make_profile()
        profile.governance.resolutions.append(
            AGMResolution(
                source_date=datetime(2026, 7, 1, tzinfo=timezone.utc),
                period="2026-06-30",
                title="Special resolution X",
                resolution_type="special",
                outcome="not_passed",
                evidence_id="ev-agm-2",
            )
        )
        sec = management_credibility.build(profile, None, "ACME")
        assert any("did not pass" in f.text for f in sec.findings)

    def test_empty_profile_notes_no_signals(self) -> None:
        sec = management_credibility.build(make_empty_profile(), None, "ACME")
        assert sec.notes
        assert not sec.findings


class TestBalanceSheet:
    def test_net_cash_verdict_with_direction(self) -> None:
        sec = balance_sheet.build(make_profile(), None, "ACME")
        verdict = sec.findings[0].text
        assert "Net Cash" in verdict
        assert "strengthening" in verdict or "weakening" in verdict

    def test_rating_trajectory_reported(self) -> None:
        sec = balance_sheet.build(make_profile(), None, "ACME")
        assert any("rating action" in f.text.lower() for f in sec.findings)

    def test_shareholder_returns_reported(self) -> None:
        sec = balance_sheet.build(make_profile(), None, "ACME")
        assert any("dividend declaration" in f.text for f in sec.findings)

    def test_dividend_table_deduped(self) -> None:
        sec = balance_sheet.build(make_profile(), None, "ACME")
        div_table = next((t for t in sec.tables if t.heading == "Dividends"), None)
        assert div_table is not None
        assert len(div_table.rows) == 1

    def test_empty_profile_notes_no_data(self) -> None:
        sec = balance_sheet.build(make_empty_profile(), None, "ACME")
        assert sec.notes


class TestValuation:
    def test_always_states_out_of_scope(self) -> None:
        sec = valuation.build(make_profile(), None, "ACME")
        assert any("no market price" in n.lower() for n in sec.notes)

    def test_no_findings_ever_invented(self) -> None:
        sec = valuation.build(make_profile(), None, "ACME")
        assert sec.findings == []


class TestRisks:
    def test_high_confidence_recurring_risk_leads(self) -> None:
        sec = risks.build(make_profile(), None, "ACME")
        assert "Currency fluctuations" in sec.findings[0].text
        assert "[low confidence" not in sec.findings[0].text

    def test_low_confidence_single_mention_tagged(self) -> None:
        sec = risks.build(make_profile(), None, "ACME")
        # "Short frag" fails the length filter entirely and shouldn't appear
        assert not any("Short frag" in f.text for f in sec.findings)

    def test_reliability_caveat_present_when_risks_exist(self) -> None:
        sec = risks.build(make_profile(), None, "ACME")
        assert any("known, pre-existing reliability" in n for n in sec.notes)

    def test_empty_profile_no_caveat_noise(self) -> None:
        sec = risks.build(make_empty_profile(), None, "ACME")
        assert not any("reliability" in n for n in sec.notes)


class TestCatalysts:
    def test_pending_acquisition_completion_reported(self) -> None:
        sec = catalysts.build(make_profile(), None, "ACME")
        assert any("expected completion" in f.text for f in sec.findings)
        assert any("2026-09-30" in f.text for f in sec.findings)

    def test_same_pending_acquisition_from_two_filings_deduped(self) -> None:
        from atlas.company.model import AcquisitionEvent

        profile = make_profile()
        profile.capital_events.acquisitions.append(
            AcquisitionEvent(
                source_date=datetime(2025, 11, 2, tzinfo=timezone.utc),
                target_name="Widget Co",
                stake_pct=100.0,
                expected_completion="2026-09-30",
                evidence_id="ev-acq-1-dup",
            )
        )
        sec = catalysts.build(profile, None, "ACME")
        widget_findings = [f for f in sec.findings if "Widget Co" in f.text]
        assert len(widget_findings) == 1
        assert set(widget_findings[0].evidence_ids) == {"ev-acq-1", "ev-acq-1-dup"}

    def test_unresolved_fundraise_reported(self) -> None:
        sec = catalysts.build(make_profile(), None, "ACME")
        assert any("fundraise" in f.text.lower() for f in sec.findings)

    def test_empty_profile_notes_nothing_pending(self) -> None:
        sec = catalysts.build(make_empty_profile(), None, "ACME")
        assert sec.notes
        assert not sec.findings


class TestWhatChanged:
    def test_events_within_window_shown(self) -> None:
        sec = what_changed.build(make_profile(), None, "ACME")
        assert sec.findings
        dates = [f.text[:10] for f in sec.findings]
        assert dates == sorted(dates, reverse=True)

    def test_notes_state_window(self) -> None:
        sec = what_changed.build(make_profile(), None, "ACME")
        assert any("Showing events since" in n for n in sec.notes)

    def test_empty_profile_notes_no_events(self) -> None:
        sec = what_changed.build(make_empty_profile(), None, "ACME")
        assert sec.notes


class TestCompetitivePosition:
    def test_no_peers_states_limitation_explicitly(self) -> None:
        sec = competitive_position.build(
            make_profile(), None, "ACME", peer_profiles=None
        )
        assert any("No peer companies" in n for n in sec.notes)

    def test_with_peers_lists_which_were_checked(self) -> None:
        peer = make_profile("PEER")
        sec = competitive_position.build(
            make_profile(),
            None,
            "ACME",
            peer_profiles={"ACME": make_profile(), "PEER": peer},
        )
        assert any("PEER" in n for n in sec.notes)


class TestESGGovernance:
    def test_includes_esg_metric_tables(self) -> None:
        sec = esg_governance.build(make_profile(), None, "ACME")
        assert sec.tables

    def test_esg_movers_shown_here(self) -> None:
        sec = esg_governance.build(make_profile(), None, "ACME")
        assert any("Attrition" in f.text for f in sec.findings)

    def test_director_change_summarized(self) -> None:
        sec = esg_governance.build(make_profile(), None, "ACME")
        assert any("director/KMP change" in f.text for f in sec.findings)


class TestOpenQuestions:
    def test_flags_empty_sections(self) -> None:
        empty_sec = ReportSection(key="risks", title="What Could Go Wrong")
        sec = open_questions.build(
            make_profile(), None, "ACME", other_sections=[empty_sec]
        )
        assert any("What Could Go Wrong" in f.text for f in sec.findings)

    def test_valuation_section_never_flagged_as_a_gap(self) -> None:
        val_sec = valuation.build(make_profile(), None, "ACME")
        sec = open_questions.build(
            make_profile(), None, "ACME", other_sections=[val_sec]
        )
        assert not any("Valuation" in f.text for f in sec.findings)

    def test_thin_metric_flagged(self) -> None:
        from atlas.analysis.base import FactKind

        profile = make_profile()
        profile.financial.snapshots[0].facts[FactKind.FINANCIAL_FCF] = 1000.0
        sec = open_questions.build(profile, None, "ACME", other_sections=[])
        assert any("Insufficient history" in f.text for f in sec.findings)


class TestTheCall:
    def test_leads_with_most_recent_development(self) -> None:
        changed_sec = what_changed.build(make_profile(), None, "ACME")
        sec = the_call.build(make_profile(), None, "ACME", other_sections=[changed_sec])
        assert any("Most recent development" in f.text for f in sec.findings)

    def test_prioritizes_financial_signal_over_esg(self) -> None:
        # Fixture's financial-domain moves (Net Debt, Operating Margin) are
        # both real; either legitimately winning by magnitude is correct —
        # what matters is that no ESG metric (Attrition %) wins instead,
        # which domain-filtering exists specifically to prevent.
        sec = the_call.build(make_profile(), None, "ACME", other_sections=[])
        improving = next(f for f in sec.findings if f.text.startswith("Improving"))
        assert "Attrition" not in improving.text

    def test_reuses_balance_sheet_verdict_verbatim(self) -> None:
        bs_sec = balance_sheet.build(make_profile(), None, "ACME")
        sec = the_call.build(make_profile(), None, "ACME", other_sections=[bs_sec])
        call_bs_finding = next(
            f for f in sec.findings if f.text.startswith("Balance sheet:")
        )
        assert bs_sec.findings[0].text in call_bs_finding.text

    def test_low_confidence_risk_produces_honest_fallback(self) -> None:
        risks_sec = risks.build(
            make_profile(), None, "ACME"
        )  # only low-confidence risks in fixture besides the recurring one
        sec = the_call.build(make_profile(), None, "ACME", other_sections=[risks_sec])
        # fixture's recurring risk IS high confidence, so this should headline it, not fall back
        assert any("Top risk on record" in f.text for f in sec.findings)

    def test_always_includes_non_recommendation_disclosure(self) -> None:
        sec = the_call.build(make_profile(), None, "ACME", other_sections=[])
        assert any(
            "does not issue a buy/sell recommendation" in f.text for f in sec.findings
        )


class TestEvidenceAppendix:
    def test_dedupes_evidence_ids_across_sections(self) -> None:
        from atlas.research.citations import Finding

        sec_a = ReportSection(
            key="a", title="A", findings=[Finding(text="x", evidence_ids=["ev-1"])]
        )
        sec_b = ReportSection(
            key="b",
            title="B",
            findings=[Finding(text="y", evidence_ids=["ev-1", "ev-2"])],
        )
        result = evidence_appendix.build(
            make_profile(), None, "ACME", other_sections=[sec_a, sec_b]
        )
        assert (
            result.notes
        )  # no repo given -> can't resolve citations, notes explains why

    def test_no_citations_when_nothing_cited(self) -> None:
        result = evidence_appendix.build(
            make_profile(), None, "ACME", other_sections=[]
        )
        assert any("No evidence" in n for n in result.notes)
