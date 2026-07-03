"""Unit tests for atlas.analysis.annual_report (v3.0).

Tests use synthetic annual report text rather than real PDFs so that:
- All paths match precisely (no TOC ambiguity, no Unicode apostrophe issues)
- Section presence/absence is fully controlled
- Tests run offline with no large files

Coverage mapping:
  TestFindSection          — _find_section TOC-skip and running-header logic
  TestExtractListItems     — _extract_list_items helper (unchanged behaviour)
  TestExtractRisks         — _extract_risks helper
  TestExtractCsrSpend      — _extract_csr_spend with rupee / backtick variants
  TestExtractKamTitles     — _extract_kam_titles
  TestExtractAttrition     — _extract_attrition
  TestAnalyze              — analyze() happy path via mock KnowledgeBase
  TestAnalyzeErrors        — analyze() error cases
  TestMissingSections      — graceful degradation when sections absent
  TestSummarizeAlias       — summarize() backward-compatible alias
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Literal
from unittest.mock import MagicMock

import pytest

from atlas.analysis.annual_report import (
    ANALYZER_VERSION,
    _extract_attrition,
    _extract_csr_spend,
    _extract_kam_titles,
    _extract_list_items,
    _extract_risks,
    _find_section,
    analyze,
    summarize,
)
from atlas.analysis.base import (
    AnalysisFact,
    AnalysisResult,
    FactKind,
    FactUnit,
    Provenance,
)
from atlas.knowledge.base import KnowledgeBase, ParsedDocument


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_doc(
    evidence_id: str = "test-001",
    status: Literal["ok", "failed"] = "ok",
    char_count: int | None = 10_000,
    title: str = "Integrated Annual Report FY2024",
    source_date: str = "2024-05-01",
    local_path: str = "annual_reports/test.pdf",
    kind: str = "annual_report",
) -> ParsedDocument:
    return ParsedDocument(
        evidence_id=evidence_id,
        kind=kind,
        title=title,
        source_date=source_date,
        local_path=local_path,
        parsed_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
        parser_version="1.0",
        status=status,
        error=None,
        char_count=char_count,
    )


def _make_kb(doc: ParsedDocument, content: str | None = None) -> KnowledgeBase:
    kb = MagicMock(spec=KnowledgeBase)
    kb.get.return_value = doc
    kb.get_content.return_value = content
    return kb


def _facts(result: AnalysisResult, kind: FactKind) -> list[AnalysisFact]:
    return [f for f in result.facts if f.kind == kind]


# ---------------------------------------------------------------------------
# Synthetic text fragments
# ---------------------------------------------------------------------------

# Simulates TOC entry then real section body
_TOC_AND_BOARDS_REPORT = (
    # TOC entry: header → page number → next section
    "65\n"
    "Board’s Report\n"
    "83\n"
    "Management Discussion and Analysis\n"
    "101\n"
    "Corporate Governance Report\n\n"
    # Real section body starting ~8000 chars later (simulated with padding)
    + "x" * 500
    + "Board’s Report\n"
    "65\n"
    "1.\tFinancial results\n"
    "The Directors present the annual report for FY 2024. "
    "Revenue from operations on a consolidated basis was ₹2,40,893 crore. "
    "Profit for the year attributable to shareholders was ₹45,908 crore.\n"
    "2.\tReturn of surplus funds to shareholders\n"
    "Three interim dividends of ₹9 per equity share each were declared.\n"
    + "x" * 400
)

_CSR_MANDATORY_DISCLOSURE = (
    "Annual Report on CSR Activities\n"
    "5.\n"
    "CSR obligation for FY 2024: ₹1,636 crore\n"
    "6.\n"
    "(a)\tAmount spent on CSR Projects (both Ongoing Project and other than "
    "Ongoing Project): ₹813 crore\n"
    "(b)\tAmount spent in Administrative Overheads: ₹14 crore\n"
    "(c)\tAmount spent on Impact Assessment: ₹5 crore\n"
)

_CSR_BACKTICK_VARIANT = (
    "(a)\tAmount spent on CSR Projects (both Ongoing Project and other than "
    "Ongoing Project): `949 crore\n"
)

_KAM_SECTION = (
    "Independent Auditor’s Report\n"
    "To the Members,\n"
    "Opinion\n"
    "We have audited the accompanying consolidated financial statements.\n"
    "Key Audit Matters\n"
    "Key audit matters are those matters that, in our professional judgment, "
    "were of most significance in our audit of the consolidated financial "
    "statements of the current period. These matters were addressed in the "
    "context of our audit of the consolidated financial statements as a whole, "
    "and in forming our opinion thereon, and we do not provide a separate "
    "opinion on these matters.\n"
    "Revenue recognition-Fixed price contracts where revenue is recognised "
    "using percentage of completion method\n"
    "See Note 5(a) and 12 to the consolidated financial statements\n"
    "The key audit matter\n"
    "How the matter was addressed in our audit\n"
    "Impairment of goodwill and other intangible assets\n"
    "See Note 3 to the consolidated financial statements\n"
    "Detailed audit procedures were performed.\n"
)

_MDA_WITH_ATTRITION = (
    "Management Discussion and Analysis\n"
    "Market and Industry Context\n"
    "The global economy grew at 3.1% in FY 2024.\n"
    "TCS’ Business Overview\n"
    "Revenue from operations was ₹2,40,893 crore.\n"
    "Human Capital\n"
    "Voluntary LTM attrition in IT Services was 12.5% for FY 2024, "
    "significantly lower than the peak of 21.3% seen in FY 2023.\n"
    "Risk Management\n"
    "1. Geopolitical risk\n"
    "2. Technology disruption risk\n"
    "3. Regulatory compliance risk\n"
    + "x" * 300
)

_RISK_SECTION_BULLETS = (
    "Key Risks\n"
    "1. Concentration risk in key geographies\n"
    "2. Cybersecurity and data privacy threats\n"
    "3. Talent attrition and availability\n"
    "4. Currency fluctuation risk\n"
    "5. Regulatory compliance risk\n"
    "These risks are described in detail in subsequent sections of this report "
    "along with the mitigation measures adopted by management.\n"
)

_RISK_SECTION_HEADERS = (
    "Risk Management\n"
    "Geopolitical Risk\n"
    "Rapid shifts in geopolitical dynamics pose significant operational and "
    "financial challenges for businesses with global exposure.\n"
    "Technology Disruption Risk\n"
    "Emerging technologies can alter competitive dynamics rapidly.\n"
    "Talent Risk\n"
    "Attrition and skill shortages in specialized areas remain key concerns.\n"
)


def _build_full_report() -> str:
    """Synthetic annual report with all major sections present."""
    return (
        "INTEGRATED ANNUAL REPORT 2023-2024\n\n"
        + _TOC_AND_BOARDS_REPORT
        + _CSR_MANDATORY_DISCLOSURE
        + _MDA_WITH_ATTRITION
        + _KAM_SECTION
        + "x" * 2_000
    )


# ---------------------------------------------------------------------------
# TestFindSection
# ---------------------------------------------------------------------------


class TestFindSection:
    _PAT = re.compile(r"Board[’']s\s+Report", re.IGNORECASE)

    def test_returns_none_when_pattern_not_found(self) -> None:
        result = _find_section("no matching text here", [self._PAT])
        assert result is None

    def test_returns_text_and_offset(self) -> None:
        text = "Board’s Report\n" + "A" * 500
        result = _find_section(text, [self._PAT])
        assert result is not None
        section_text, offset = result
        assert isinstance(section_text, str)
        assert isinstance(offset, int)
        assert offset == 0

    def test_skips_toc_entry_page_num_plus_next_section(self) -> None:
        # TOC: Board's Report → 65 → Management Discussion → 83 (→ more TOC)
        text = (
            "Board’s Report\n65\nManagement Discussion and Analysis\n83\n"
            "Corporate Governance\n\n"
            + "x" * 200
            + "Board’s Report\n"
            + "Actual section content follows here. " * 20
        )
        result = _find_section(text, [self._PAT])
        assert result is not None
        section_text, _offset = result
        assert "Actual section content" in section_text

    def test_accepts_running_header_with_page_then_prose(self) -> None:
        # Running header: Board's Report → page_num → prose (not TOC)
        text = (
            "Board’s Report\n"
            "65\n"
            "The Directors present the annual report.\n"
            "Revenue grew by 5% year-on-year.\n" * 10
        )
        result = _find_section(text, [self._PAT])
        assert result is not None
        section_text, _offset = result
        assert "Directors" in section_text

    def test_returns_none_when_insufficient_content(self) -> None:
        text = "Board’s Report\n" + "X" * 50
        result = _find_section(text, [self._PAT], min_content=200)
        assert result is None

    def test_tries_patterns_in_order(self) -> None:
        # Only Directors' Report is present
        dirs_pat = re.compile(r"Directors[’']\s+Report", re.IGNORECASE)
        text = (
            "Directors’ Report\n"
            "To the Members,\n"
            "The Directors present this report for FY 2024.\n" * 10
        )
        result = _find_section(text, [self._PAT, dirs_pat])
        assert result is not None
        assert "Directors" in result[0]

    def test_ascii_apostrophe_also_matched(self) -> None:
        text = "Board's Report\n" + "Prose content here.\n" * 15
        result = _find_section(text, [self._PAT])
        assert result is not None


# ---------------------------------------------------------------------------
# TestExtractListItems
# ---------------------------------------------------------------------------


class TestExtractListItems:
    def test_parses_numbered_list(self) -> None:
        text = "1. First item\n2. Second item\n3. Third item"
        items = _extract_list_items(text)
        assert items == ["First item", "Second item", "Third item"]

    def test_parses_bullet_list(self) -> None:
        items = _extract_list_items("• Bullet one\n• Bullet two\n• Bullet three")
        assert len(items) == 3
        assert items[0] == "Bullet one"

    def test_parses_dash_list(self) -> None:
        assert _extract_list_items("- Item A\n- Item B") == ["Item A", "Item B"]

    def test_ignores_non_list_lines(self) -> None:
        items = _extract_list_items("Paragraph.\n1. An item\nAnother paragraph.")
        assert items == ["An item"]

    def test_skips_short_items(self) -> None:
        items = _extract_list_items("1. Hi\n2. Valid item here")
        assert items == ["Valid item here"]

    def test_skips_long_items(self) -> None:
        items = _extract_list_items(f"1. {'X' * 201}\n2. Short valid item")
        assert items == ["Short valid item"]

    def test_empty_string_returns_empty(self) -> None:
        assert _extract_list_items("") == []


# ---------------------------------------------------------------------------
# TestExtractRisks
# ---------------------------------------------------------------------------


class TestExtractRisks:
    def test_parses_bullet_risks(self) -> None:
        risks = _extract_risks(_RISK_SECTION_BULLETS)
        assert len(risks) >= 3
        assert any("Concentration" in r for r in risks)

    def test_parses_header_style_risks(self) -> None:
        risks = _extract_risks(_RISK_SECTION_HEADERS)
        assert len(risks) >= 2

    def test_returns_empty_when_no_risk_section(self) -> None:
        assert _extract_risks("No risks discussed here.") == []

    def test_caps_at_10_items(self) -> None:
        bullets = "".join(f"{i+1}. Risk item {i+1} description\n" for i in range(20))
        risks = _extract_risks("Key Risks\n" + bullets)
        assert len(risks) <= 10

    def test_risk_management_header_recognised(self) -> None:
        text = "Risk Management\n- Regulatory risk\n- Credit risk\n" + "x" * 300
        risks = _extract_risks(text)
        assert len(risks) >= 1


# ---------------------------------------------------------------------------
# TestExtractCsrSpend
# ---------------------------------------------------------------------------


class TestExtractCsrSpend:
    def test_extracts_rupee_symbol(self) -> None:
        amount, offset, snip = _extract_csr_spend(_CSR_MANDATORY_DISCLOSURE)
        assert amount == 813.0
        assert offset is not None
        assert snip is not None

    def test_extracts_backtick_rupee(self) -> None:
        amount, offset, snip = _extract_csr_spend(_CSR_BACKTICK_VARIANT)
        assert amount == 949.0

    def test_handles_commas_in_number(self) -> None:
        text = "(a)\tAmount spent on CSR Projects (both): ₹1,009 crore\n"
        amount, _, _ = _extract_csr_spend(text)
        assert amount == 1009.0

    def test_returns_none_when_absent(self) -> None:
        amount, offset, snip = _extract_csr_spend("No CSR table here.")
        assert amount is None
        assert offset is None
        assert snip is None

    def test_case_insensitive(self) -> None:
        text = "(a)\tAmount Spent on CSR Projects (both): ₹500 crore\n"
        amount, _, _ = _extract_csr_spend(text)
        assert amount == 500.0

    def test_cr_abbreviation_accepted(self) -> None:
        text = "(a)\tAmount spent on CSR Projects (both): ₹820 Cr.\n"
        amount, _, _ = _extract_csr_spend(text)
        assert amount == 820.0


# ---------------------------------------------------------------------------
# TestExtractKamTitles
# ---------------------------------------------------------------------------


class TestExtractKamTitles:
    def test_extracts_one_kam_title(self) -> None:
        content = _KAM_SECTION
        entries = _extract_kam_titles(content, auditor_header_offset=0)
        titles = [t for t, _ in entries]
        assert any("Revenue recognition" in t for t in titles)

    def test_extracts_multiple_kam_titles(self) -> None:
        entries = _extract_kam_titles(_KAM_SECTION, auditor_header_offset=0)
        assert len(entries) >= 2

    def test_returns_offsets(self) -> None:
        entries = _extract_kam_titles(_KAM_SECTION, auditor_header_offset=0)
        for _title, offset in entries:
            assert isinstance(offset, int)
            assert offset >= 0

    def test_returns_empty_when_no_kam_header(self) -> None:
        text = "Independent Auditor's Report\nOpinion paragraph.\n" + "x" * 300
        entries = _extract_kam_titles(text, auditor_header_offset=0)
        assert entries == []

    def test_skips_lowercase_lines(self) -> None:
        # Lines starting with lowercase should not be treated as KAM titles
        text = (
            "Independent Auditor’s Report\n"
            "Key Audit Matters\n"
            "these are those matters that were of most significance.\n"
            "See Note 1 to the financial statements\n"
            "Real KAM Title Starting with Capital\n"
            "See Note 2 to the financial statements\n"
        )
        entries = _extract_kam_titles(text, auditor_header_offset=0)
        titles = [t for t, _ in entries]
        assert not any(t[0].islower() for t in titles)
        assert any("Real KAM Title" in t for t in titles)

    def test_auditor_offset_applied_correctly(self) -> None:
        padding = "x" * 5000
        content = padding + _KAM_SECTION
        entries = _extract_kam_titles(content, auditor_header_offset=5000)
        assert len(entries) >= 1
        # All returned offsets should be ≥ 5000
        for _title, offset in entries:
            assert offset >= 5000


# ---------------------------------------------------------------------------
# TestExtractAttrition
# ---------------------------------------------------------------------------


class TestExtractAttrition:
    def test_extracts_ltm_attrition(self) -> None:
        pct, offset, snip = _extract_attrition(_MDA_WITH_ATTRITION)
        assert pct == 12.5
        assert offset is not None

    def test_extracts_plain_attrition(self) -> None:
        text = "Company attrition rate was 14.7% during the year.\n"
        pct, _, _ = _extract_attrition(text)
        assert pct == 14.7

    def test_returns_none_when_absent(self) -> None:
        pct, offset, snip = _extract_attrition("No workforce data here.")
        assert pct is None
        assert offset is None
        assert snip is None

    def test_extracts_it_services_attrition(self) -> None:
        text = (
            "Voluntary LTM Attrition in IT Services was 13.7% in Q4 FY2026, "
            "reflecting improved retention.\n"
        )
        pct, _, _ = _extract_attrition(text)
        assert pct == 13.7


# ---------------------------------------------------------------------------
# TestAnalyze — happy path
# ---------------------------------------------------------------------------


class TestAnalyze:
    def test_returns_analysis_result(self) -> None:
        content = _build_full_report()
        doc = _make_doc(char_count=len(content))
        kb = _make_kb(doc, content)
        result = analyze("test-001", kb)
        assert isinstance(result, AnalysisResult)

    def test_evidence_id_passed_through(self) -> None:
        content = _build_full_report()
        doc = _make_doc(char_count=len(content))
        kb = _make_kb(doc, content)
        result = analyze("test-001", kb)
        assert result.evidence_id == "test-001"

    def test_kind_matches_document(self) -> None:
        content = _build_full_report()
        doc = _make_doc(char_count=len(content))
        kb = _make_kb(doc, content)
        result = analyze("test-001", kb)
        assert result.kind == "annual_report"

    def test_analyzer_version_is_current(self) -> None:
        content = _build_full_report()
        doc = _make_doc(char_count=len(content))
        kb = _make_kb(doc, content)
        result = analyze("test-001", kb)
        assert result.analyzer_version == ANALYZER_VERSION

    def test_analyzed_at_is_utc_datetime(self) -> None:
        content = _build_full_report()
        doc = _make_doc(char_count=len(content))
        kb = _make_kb(doc, content)
        result = analyze("test-001", kb)
        assert isinstance(result.analyzed_at, datetime)
        assert result.analyzed_at.tzinfo is not None

    def test_confidence_valid_literal(self) -> None:
        content = _build_full_report()
        doc = _make_doc(char_count=len(content))
        kb = _make_kb(doc, content)
        result = analyze("test-001", kb)
        assert result.confidence in ("high", "medium", "low")

    def test_warnings_is_list(self) -> None:
        content = _build_full_report()
        doc = _make_doc(char_count=len(content))
        kb = _make_kb(doc, content)
        result = analyze("test-001", kb)
        assert isinstance(result.warnings, list)

    def test_all_facts_are_analysis_fact_instances(self) -> None:
        content = _build_full_report()
        doc = _make_doc(char_count=len(content))
        kb = _make_kb(doc, content)
        result = analyze("test-001", kb)
        assert all(isinstance(f, AnalysisFact) for f in result.facts)

    # CSR spend
    def test_extracts_csr_spend_fact(self) -> None:
        content = _build_full_report()
        doc = _make_doc(char_count=len(content))
        kb = _make_kb(doc, content)
        result = analyze("test-001", kb)
        csr = _facts(result, FactKind.ESG_CSR_SPEND)
        assert len(csr) == 1
        assert csr[0].value == 813.0
        assert csr[0].unit == FactUnit.CRORE_INR
        assert csr[0].confidence == "high"

    def test_csr_fact_has_period(self) -> None:
        content = _build_full_report()
        doc = _make_doc(char_count=len(content), source_date="2024-05-01")
        kb = _make_kb(doc, content)
        result = analyze("test-001", kb)
        csr = _facts(result, FactKind.ESG_CSR_SPEND)
        assert csr[0].period == "2024-03-31"

    def test_csr_fact_has_provenance(self) -> None:
        content = _build_full_report()
        doc = _make_doc(char_count=len(content))
        kb = _make_kb(doc, content)
        result = analyze("test-001", kb)
        csr = _facts(result, FactKind.ESG_CSR_SPEND)
        assert isinstance(csr[0].provenance, Provenance)
        assert csr[0].provenance.section == "boards_report_csr"

    # KAM titles
    def test_extracts_kam_title_facts(self) -> None:
        content = _build_full_report()
        doc = _make_doc(char_count=len(content))
        kb = _make_kb(doc, content)
        result = analyze("test-001", kb)
        kams = _facts(result, FactKind.AUDIT_KAM_TITLE)
        assert len(kams) >= 1

    def test_kam_title_is_string(self) -> None:
        content = _build_full_report()
        doc = _make_doc(char_count=len(content))
        kb = _make_kb(doc, content)
        result = analyze("test-001", kb)
        kams = _facts(result, FactKind.AUDIT_KAM_TITLE)
        assert all(isinstance(f.value, str) for f in kams)

    def test_kam_fact_has_high_confidence(self) -> None:
        content = _build_full_report()
        doc = _make_doc(char_count=len(content))
        kb = _make_kb(doc, content)
        result = analyze("test-001", kb)
        kams = _facts(result, FactKind.AUDIT_KAM_TITLE)
        assert all(f.confidence == "high" for f in kams)

    def test_kam_fact_has_none_unit(self) -> None:
        content = _build_full_report()
        doc = _make_doc(char_count=len(content))
        kb = _make_kb(doc, content)
        result = analyze("test-001", kb)
        kams = _facts(result, FactKind.AUDIT_KAM_TITLE)
        assert all(f.unit is None for f in kams)

    def test_kam_contains_revenue_recognition(self) -> None:
        content = _build_full_report()
        doc = _make_doc(char_count=len(content))
        kb = _make_kb(doc, content)
        result = analyze("test-001", kb)
        kams = _facts(result, FactKind.AUDIT_KAM_TITLE)
        titles = [str(f.value) for f in kams]
        assert any("Revenue recognition" in t for t in titles)

    # Attrition
    def test_extracts_attrition_fact(self) -> None:
        content = _build_full_report()
        doc = _make_doc(char_count=len(content))
        kb = _make_kb(doc, content)
        result = analyze("test-001", kb)
        attr = _facts(result, FactKind.ESG_WORKFORCE_ATTRITION_PCT)
        assert len(attr) == 1
        assert attr[0].value == 12.5
        assert attr[0].unit == FactUnit.PERCENT

    def test_attrition_confidence_is_medium(self) -> None:
        content = _build_full_report()
        doc = _make_doc(char_count=len(content))
        kb = _make_kb(doc, content)
        result = analyze("test-001", kb)
        attr = _facts(result, FactKind.ESG_WORKFORCE_ATTRITION_PCT)
        assert attr[0].confidence == "medium"

    # Risk factors
    def test_extracts_risk_facts(self) -> None:
        content = _build_full_report()
        doc = _make_doc(char_count=len(content))
        kb = _make_kb(doc, content)
        result = analyze("test-001", kb)
        risks = _facts(result, FactKind.RISK_FACTOR)
        assert len(risks) >= 1

    def test_risk_facts_have_null_unit(self) -> None:
        content = _build_full_report()
        doc = _make_doc(char_count=len(content))
        kb = _make_kb(doc, content)
        result = analyze("test-001", kb)
        risks = _facts(result, FactKind.RISK_FACTOR)
        assert all(f.unit is None for f in risks)

    # Excerpts
    def test_boards_report_excerpt_present(self) -> None:
        content = _build_full_report()
        doc = _make_doc(char_count=len(content))
        kb = _make_kb(doc, content)
        result = analyze("test-001", kb)
        assert "boards_report" in result.excerpts

    def test_mda_excerpt_present(self) -> None:
        content = _build_full_report()
        doc = _make_doc(char_count=len(content))
        kb = _make_kb(doc, content)
        result = analyze("test-001", kb)
        assert "mda" in result.excerpts

    def test_key_audit_matters_excerpt_present(self) -> None:
        content = _build_full_report()
        doc = _make_doc(char_count=len(content))
        kb = _make_kb(doc, content)
        result = analyze("test-001", kb)
        assert "key_audit_matters" in result.excerpts

    def test_full_report_yields_high_confidence(self) -> None:
        content = _build_full_report()
        doc = _make_doc(char_count=len(content))
        kb = _make_kb(doc, content)
        result = analyze("test-001", kb)
        assert result.confidence in ("high", "medium")


# ---------------------------------------------------------------------------
# TestAnalyzeErrors
# ---------------------------------------------------------------------------


class TestAnalyzeErrors:
    def test_raises_key_error_for_unknown_id(self) -> None:
        kb = MagicMock(spec=KnowledgeBase)
        kb.get.return_value = None
        with pytest.raises(KeyError):
            analyze("does-not-exist", kb)

    def test_raises_value_error_for_failed_document(self) -> None:
        doc = _make_doc(status="failed", char_count=None)
        kb = _make_kb(doc, None)
        with pytest.raises(ValueError, match="cannot analyze"):
            analyze("test-001", kb)

    def test_raises_value_error_when_content_unavailable(self) -> None:
        doc = _make_doc(status="ok", char_count=10_000)
        kb = _make_kb(doc, None)
        with pytest.raises(ValueError, match="content unavailable"):
            analyze("test-001", kb)


# ---------------------------------------------------------------------------
# TestMissingSections — graceful degradation
# ---------------------------------------------------------------------------


class TestMissingSections:
    def test_csr_absent_adds_warning(self) -> None:
        content = _MDA_WITH_ATTRITION + _KAM_SECTION
        doc = _make_doc(char_count=len(content))
        kb = _make_kb(doc, content)
        result = analyze("test-001", kb)
        assert any("CSR" in w for w in result.warnings)

    def test_csr_absent_no_fact(self) -> None:
        content = _MDA_WITH_ATTRITION + _KAM_SECTION
        doc = _make_doc(char_count=len(content))
        kb = _make_kb(doc, content)
        result = analyze("test-001", kb)
        assert _facts(result, FactKind.ESG_CSR_SPEND) == []

    def test_auditor_absent_adds_warning(self) -> None:
        content = _CSR_MANDATORY_DISCLOSURE + _MDA_WITH_ATTRITION
        doc = _make_doc(char_count=len(content))
        kb = _make_kb(doc, content)
        result = analyze("test-001", kb)
        assert any("auditor" in w.lower() for w in result.warnings)

    def test_auditor_absent_no_kam_facts(self) -> None:
        content = _CSR_MANDATORY_DISCLOSURE + _MDA_WITH_ATTRITION
        doc = _make_doc(char_count=len(content))
        kb = _make_kb(doc, content)
        result = analyze("test-001", kb)
        assert _facts(result, FactKind.AUDIT_KAM_TITLE) == []

    def test_mda_absent_adds_warning(self) -> None:
        content = _CSR_MANDATORY_DISCLOSURE + _KAM_SECTION
        doc = _make_doc(char_count=len(content))
        kb = _make_kb(doc, content)
        result = analyze("test-001", kb)
        assert any("MDA" in w for w in result.warnings)

    def test_risk_absent_adds_warning(self) -> None:
        content = _CSR_MANDATORY_DISCLOSURE + _KAM_SECTION
        doc = _make_doc(char_count=len(content))
        kb = _make_kb(doc, content)
        result = analyze("test-001", kb)
        assert any("risk" in w.lower() for w in result.warnings)

    def test_empty_content_yields_low_confidence(self) -> None:
        content = "x" * 2000
        doc = _make_doc(char_count=len(content))
        kb = _make_kb(doc, content)
        result = analyze("test-001", kb)
        assert result.confidence == "low"

    def test_csr_only_yields_medium_confidence(self) -> None:
        content = _CSR_MANDATORY_DISCLOSURE + "x" * 2000
        doc = _make_doc(char_count=len(content))
        kb = _make_kb(doc, content)
        result = analyze("test-001", kb)
        assert result.confidence in ("medium", "low")

    def test_boards_report_excerpt_absent_when_not_found(self) -> None:
        content = _CSR_MANDATORY_DISCLOSURE + "x" * 2000
        doc = _make_doc(char_count=len(content))
        kb = _make_kb(doc, content)
        result = analyze("test-001", kb)
        assert "boards_report" not in result.excerpts

    def test_missing_sections_add_appropriate_warnings(self) -> None:
        content = "x" * 2000
        doc = _make_doc(char_count=len(content))
        kb = _make_kb(doc, content)
        result = analyze("test-001", kb)
        assert len(result.warnings) >= 3


# ---------------------------------------------------------------------------
# TestSummarizeAlias
# ---------------------------------------------------------------------------


class TestSummarizeAlias:
    def test_summarize_returns_same_result_as_analyze(self) -> None:
        content = _build_full_report()
        doc = _make_doc(char_count=len(content))
        kb = _make_kb(doc, content)
        r1 = analyze("test-001", kb)
        r2 = summarize("test-001", kb)
        assert r1.evidence_id == r2.evidence_id
        assert r1.kind == r2.kind
        assert r1.analyzer_version == r2.analyzer_version
        assert r1.confidence == r2.confidence
        assert len(r1.facts) == len(r2.facts)

    def test_summarize_raises_same_errors(self) -> None:
        kb = MagicMock(spec=KnowledgeBase)
        kb.get.return_value = None
        with pytest.raises(KeyError):
            summarize("does-not-exist", kb)
