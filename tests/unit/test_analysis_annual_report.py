"""Unit tests for atlas.analysis.annual_report.

Tests use synthetic annual report text rather than real PDFs so that:
- All paths match precisely (no TOC ambiguity)
- Section presence/absence is fully controlled
- Tests run offline with no large files

The synthetic text mimics the structure seen in real BSE-listed company annual
reports: a table of contents with page numbers, then real section bodies.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from unittest.mock import MagicMock

import pytest

from atlas.analysis.annual_report import (
    AnnualReportSummary,
    _compare,
    _extract_list_items,
    _extract_number,
    _extract_risks,
    _extract_section,
    _extract_segments,
    summarize,
)
from atlas.knowledge.base import KnowledgeBase, ParsedDocument


# ---------------------------------------------------------------------------
# Helpers — synthetic text corpus
# ---------------------------------------------------------------------------

def _make_doc(
    evidence_id: str = "test-001",
    status: Literal["ok", "failed"] = "ok",
    char_count: int | None = 10_000,
    title: str = "Annual Report FY2024",
    source_date: str = "2024-03-31",
    local_path: str = "annual_reports/test.pdf",
) -> ParsedDocument:
    return ParsedDocument(
        evidence_id=evidence_id,
        kind="annual_report",
        title=title,
        source_date=source_date,
        local_path=local_path,
        parsed_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
        parser_version="1.0",
        status=status,
        error=None,
        char_count=char_count,
    )


def _make_kb(
    doc: ParsedDocument,
    content: str | None = None,
) -> KnowledgeBase:
    """Return a KnowledgeBase stub backed by mocks."""
    kb = MagicMock(spec=KnowledgeBase)
    kb.get.return_value = doc
    kb.get_content.return_value = content
    return kb


# Synthetic text fragments used across multiple tests

_OVERVIEW_SECTION = (
    "Business Overview\n"
    "We are a global leader in IT services and consulting. "
    "Our solutions span cloud transformation, AI-enabled products, "
    "and enterprise integration across 19 industry verticals. "
    "Founded in 1968, we employ over 600,000 professionals worldwide. "
    "Our revenue reached ₹240,893 crore in FY2024.\n\n"
)

_MANAGEMENT_SECTION = (
    "Letter from the Chairman\n"
    "Dear Shareholders,\n"
    "FY2024 was a year of strong growth despite global macroeconomic headwinds. "
    "We continued to invest in our people, technology, and client relationships. "
    "We are confident in our long-term trajectory and will continue to deliver "
    "value to all stakeholders.\n\n"
)

_CAPITAL_SECTION = (
    "In keeping with our capital allocation policy, the Board has recommended "
    "a final dividend of ₹28 per share for FY2024. Additionally, we completed "
    "a share buyback programme worth ₹17,000 crore during the year.\n\n"
)

_RISK_SECTION_BULLETS = (
    "Key Risks\n"
    "1. Concentration risk in key geographies\n"
    "2. Cybersecurity and data privacy threats\n"
    "3. Talent attrition and availability\n"
    "4. Currency fluctuation risk\n"
    "5. Regulatory compliance risk\n"
    "The following section describes each risk in detail and the mitigation strategies adopted.\n\n"
)

_RISK_SECTION_HEADERS = (
    "Risk Management\n"
    "Geopolitical Risk\n"
    "Rapid shifts in geopolitical dynamics pose operational challenges.\n"
    "Technology Disruption Risk\n"
    "Emerging technologies can alter competitive dynamics.\n"
    "Talent Risk\n"
    "Attrition and skill shortages remain key concerns.\n\n"
)

_SEGMENT_PARAGRAPH = (
    "Among the Business Segments, Manufacturing grew 10.6%, "
    "Life Sciences and Healthcare grew 8.7%, Energy, Resources and Utilities grew 5.2%, "
    "and Communication and Media grew 3.1% in constant currency.\n\n"
)

_TOC_STUB = (
    "Table of Contents\n"
    "Business Overview ......................... 4\n"
    "Risk Management ........................... 30\n"
    "Key Risks ................................. 32\n\n"
)


def _build_full_report() -> str:
    return (
        "ANNUAL REPORT 2023-2024\n\n"
        + _TOC_STUB
        + _MANAGEMENT_SECTION
        + _OVERVIEW_SECTION
        + _SEGMENT_PARAGRAPH
        + _CAPITAL_SECTION
        + _RISK_SECTION_BULLETS
        + "x" * 5_000
    )


# ---------------------------------------------------------------------------
# _extract_section
# ---------------------------------------------------------------------------


class TestExtractSection:
    _PATTERN = re.compile(r"^Business Overview\s*$", re.IGNORECASE | re.MULTILINE)

    def test_returns_none_when_pattern_not_found(self) -> None:
        result = _extract_section("no matching text here", self._PATTERN)
        assert result is None

    def test_returns_excerpt_after_header(self) -> None:
        text = "Business Overview\n" + "A" * 500
        result = _extract_section(text, self._PATTERN)
        assert result is not None
        assert result.startswith("A")

    def test_excerpt_capped_at_4000_chars(self) -> None:
        text = "Business Overview\n" + "B" * 8_000
        result = _extract_section(text, self._PATTERN)
        assert result is not None
        assert len(result) <= 4_100  # slight slack for stripped whitespace

    def test_skips_toc_entry_with_only_page_number(self) -> None:
        # TOC entry: "Business Overview .... 4\n" followed by a page number only.
        # Real section appears later with substantial content.
        text = (
            "Business Overview .............. 4\n"
            "Other stuff on the TOC page\n\n"
            "Business Overview\n"
            + "C" * 600
        )
        result = _extract_section(text, self._PATTERN)
        assert result is not None
        assert len(result) >= 200

    def test_returns_none_when_all_matches_below_threshold(self) -> None:
        text = "Business Overview\n" + "X" * 50
        result = _extract_section(text, self._PATTERN)
        assert result is None

    def test_strips_leading_whitespace_from_excerpt(self) -> None:
        text = "Business Overview\n\n   \n" + "Content here " * 30
        result = _extract_section(text, self._PATTERN)
        assert result is not None
        assert not result.startswith(" ")


# ---------------------------------------------------------------------------
# _extract_list_items
# ---------------------------------------------------------------------------


class TestExtractListItems:
    def test_parses_numbered_list(self) -> None:
        text = "1. First item\n2. Second item\n3. Third item"
        items = _extract_list_items(text)
        assert items == ["First item", "Second item", "Third item"]

    def test_parses_bullet_list(self) -> None:
        text = "• Bullet one\n• Bullet two\n• Bullet three"
        items = _extract_list_items(text)
        assert len(items) == 3
        assert items[0] == "Bullet one"

    def test_parses_dash_list(self) -> None:
        text = "- Item A\n- Item B\n- Item C"
        items = _extract_list_items(text)
        assert items == ["Item A", "Item B", "Item C"]

    def test_ignores_non_list_lines(self) -> None:
        text = "This is a paragraph.\n1. An item\nAnother paragraph."
        items = _extract_list_items(text)
        assert items == ["An item"]

    def test_skips_items_shorter_than_5_chars(self) -> None:
        text = "1. Hi\n2. Valid item here"
        items = _extract_list_items(text)
        assert items == ["Valid item here"]

    def test_skips_items_longer_than_200_chars(self) -> None:
        long_item = "X" * 201
        text = f"1. {long_item}\n2. Short valid item"
        items = _extract_list_items(text)
        assert items == ["Short valid item"]

    def test_empty_string_returns_empty(self) -> None:
        assert _extract_list_items("") == []

    def test_parenthesis_numbered_list(self) -> None:
        text = "1) First\n2) Second"
        items = _extract_list_items(text)
        assert items == ["First", "Second"]


# ---------------------------------------------------------------------------
# _extract_segments
# ---------------------------------------------------------------------------


class TestExtractSegments:
    def test_parses_grew_paragraph(self) -> None:
        text = _SEGMENT_PARAGRAPH + "x" * 100
        segments = _extract_segments(text)
        assert len(segments) >= 2
        assert any("Manufacturing" in s for s in segments)

    def test_includes_life_sciences(self) -> None:
        text = _SEGMENT_PARAGRAPH + "x" * 100
        segments = _extract_segments(text)
        assert any("Life Sciences" in s for s in segments)

    def test_returns_empty_list_when_no_segment_text(self) -> None:
        assert _extract_segments("Nothing relevant here at all.") == []

    def test_falls_back_to_section_header_with_bullet_list(self) -> None:
        text = (
            "Business Segments\n"
            "1. Manufacturing\n"
            "2. Banking & Finance\n"
            "3. Energy\n"
            + "x" * 400
        )
        segments = _extract_segments(text)
        assert "Manufacturing" in segments
        assert "Banking & Finance" in segments

    def test_segment_names_do_not_contain_percentage(self) -> None:
        text = _SEGMENT_PARAGRAPH + "x" * 100
        segments = _extract_segments(text)
        for s in segments:
            assert "%" not in s


# ---------------------------------------------------------------------------
# _extract_risks
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
        assert _extract_risks("No risks here at all.") == []

    def test_caps_at_10_items(self) -> None:
        bullet_list = "".join(f"{i+1}. Risk item number {i+1} description\n" for i in range(20))
        text = "Key Risks\n" + bullet_list
        risks = _extract_risks(text)
        assert len(risks) <= 10

    def test_risk_management_header_recognized(self) -> None:
        text = (
            "Risk Management\n"
            "- Regulatory risk\n"
            "- Credit risk\n"
            "- Operational risk\n"
            + "x" * 300
        )
        risks = _extract_risks(text)
        assert len(risks) >= 1


# ---------------------------------------------------------------------------
# _extract_number
# ---------------------------------------------------------------------------


class TestExtractNumber:
    def test_extracts_plain_number(self) -> None:
        from atlas.analysis.annual_report import _RE_REVENUE
        text = "revenues of ₹240,893 crore"
        n = _extract_number(text, _RE_REVENUE)
        assert n == pytest.approx(240893.0)

    def test_extracts_decimal_number(self) -> None:
        from atlas.analysis.annual_report import _RE_REVENUE
        text = "revenue of 12,345.67 crore"
        n = _extract_number(text, _RE_REVENUE)
        assert n == pytest.approx(12345.67)

    def test_returns_none_when_no_match(self) -> None:
        from atlas.analysis.annual_report import _RE_REVENUE
        n = _extract_number("no financial data here", _RE_REVENUE)
        assert n is None


# ---------------------------------------------------------------------------
# _compare
# ---------------------------------------------------------------------------


class TestCompare:
    def test_detects_revenue_growth(self) -> None:
        curr = "revenues of ₹240,000 crore"
        prev = "revenues of ₹200,000 crore"
        changes = _compare(curr, prev)
        assert any("Revenue grew" in c for c in changes)

    def test_detects_revenue_decline(self) -> None:
        curr = "revenues of ₹180,000 crore"
        prev = "revenues of ₹200,000 crore"
        changes = _compare(curr, prev)
        assert any("Revenue declined" in c for c in changes)

    def test_includes_percentage(self) -> None:
        curr = "revenues of 300,000 crore"
        prev = "revenues of 250,000 crore"
        changes = _compare(curr, prev)
        assert any("20.0%" in c for c in changes)

    def test_returns_empty_when_no_metrics_found(self) -> None:
        changes = _compare("No numbers here.", "Also no numbers.")
        assert changes == []

    def test_includes_net_income_when_available(self) -> None:
        curr = "net profit of ₹50,000 crore\nrevenues of ₹240,000 crore"
        prev = "net profit of ₹40,000 crore\nrevenues of ₹200,000 crore"
        changes = _compare(curr, prev)
        assert any("Net income" in c for c in changes)


# ---------------------------------------------------------------------------
# summarize — happy path via mock KnowledgeBase
# ---------------------------------------------------------------------------


class TestSummarize:
    def test_returns_annual_report_summary(self) -> None:
        content = _build_full_report()
        doc = _make_doc(char_count=len(content))
        kb = _make_kb(doc, content)
        result = summarize("test-001", kb)
        assert isinstance(result, AnnualReportSummary)

    def test_evidence_id_passed_through(self) -> None:
        content = _build_full_report()
        doc = _make_doc(char_count=len(content))
        kb = _make_kb(doc, content)
        result = summarize("test-001", kb)
        assert result.evidence_id == "test-001"

    def test_title_passed_through(self) -> None:
        content = _build_full_report()
        doc = _make_doc(char_count=len(content))
        kb = _make_kb(doc, content)
        result = summarize("test-001", kb)
        assert result.title == "Annual Report FY2024"

    def test_finds_management_commentary(self) -> None:
        content = _build_full_report()
        doc = _make_doc(char_count=len(content))
        kb = _make_kb(doc, content)
        result = summarize("test-001", kb)
        assert result.management_commentary is not None
        assert len(result.management_commentary) >= 50

    def test_finds_business_overview(self) -> None:
        content = _build_full_report()
        doc = _make_doc(char_count=len(content))
        kb = _make_kb(doc, content)
        result = summarize("test-001", kb)
        assert result.business_overview is not None

    def test_finds_capital_allocation(self) -> None:
        content = _build_full_report()
        doc = _make_doc(char_count=len(content))
        kb = _make_kb(doc, content)
        result = summarize("test-001", kb)
        assert result.capital_allocation is not None
        assert "dividend" in result.capital_allocation.lower() or "capital" in result.capital_allocation.lower()

    def test_finds_segments(self) -> None:
        content = _build_full_report()
        doc = _make_doc(char_count=len(content))
        kb = _make_kb(doc, content)
        result = summarize("test-001", kb)
        assert len(result.segments) >= 2

    def test_finds_risks_from_bullet_list(self) -> None:
        content = _build_full_report()
        doc = _make_doc(char_count=len(content))
        kb = _make_kb(doc, content)
        result = summarize("test-001", kb)
        assert len(result.major_risks) >= 1

    def test_yoy_empty_when_no_previous_id(self) -> None:
        content = _build_full_report()
        doc = _make_doc(char_count=len(content))
        kb = _make_kb(doc, content)
        result = summarize("test-001", kb)
        assert result.year_on_year_changes == []

    def test_yoy_populated_when_previous_id_provided(self) -> None:
        content = "revenues of ₹240,000 crore\n" + "x" * 2000
        prev_content = "revenues of ₹200,000 crore\n" + "x" * 2000
        doc = _make_doc(char_count=len(content))
        kb = MagicMock(spec=KnowledgeBase)
        kb.get.return_value = doc
        kb.get_content.side_effect = lambda eid: content if eid == "test-001" else prev_content
        result = summarize("test-001", kb, previous_evidence_id="test-000")
        assert len(result.year_on_year_changes) >= 1

    def test_extracted_at_is_utc_datetime(self) -> None:
        content = _build_full_report()
        doc = _make_doc(char_count=len(content))
        kb = _make_kb(doc, content)
        result = summarize("test-001", kb)
        assert isinstance(result.extracted_at, datetime)
        assert result.extracted_at.tzinfo is not None

    def test_char_count_populated(self) -> None:
        content = _build_full_report()
        doc = _make_doc(char_count=len(content))
        kb = _make_kb(doc, content)
        result = summarize("test-001", kb)
        assert result.char_count == len(content)


# ---------------------------------------------------------------------------
# summarize — error cases
# ---------------------------------------------------------------------------


class TestSummarizeErrors:
    def test_raises_key_error_for_unknown_id(self) -> None:
        kb = MagicMock(spec=KnowledgeBase)
        kb.get.return_value = None
        with pytest.raises(KeyError):
            summarize("does-not-exist", kb)

    def test_raises_value_error_for_failed_document(self) -> None:
        doc = _make_doc(status="failed", char_count=None)
        kb = _make_kb(doc, None)
        with pytest.raises(ValueError, match="cannot summarize"):
            summarize("test-001", kb)

    def test_raises_value_error_when_content_unavailable(self) -> None:
        doc = _make_doc(status="ok", char_count=10_000)
        kb = _make_kb(doc, None)
        with pytest.raises(ValueError, match="content unavailable"):
            summarize("test-001", kb)


# ---------------------------------------------------------------------------
# Missing sections — graceful degradation
# ---------------------------------------------------------------------------


class TestMissingSections:
    def test_business_overview_is_none_when_absent(self) -> None:
        content = _MANAGEMENT_SECTION + "x" * 2000
        doc = _make_doc(char_count=len(content))
        kb = _make_kb(doc, content)
        result = summarize("test-001", kb)
        assert result.business_overview is None

    def test_segments_empty_when_absent(self) -> None:
        content = _MANAGEMENT_SECTION + _OVERVIEW_SECTION + "x" * 2000
        doc = _make_doc(char_count=len(content))
        kb = _make_kb(doc, content)
        result = summarize("test-001", kb)
        assert result.segments == []

    def test_risks_empty_when_absent(self) -> None:
        content = _MANAGEMENT_SECTION + _OVERVIEW_SECTION + "x" * 2000
        doc = _make_doc(char_count=len(content))
        kb = _make_kb(doc, content)
        result = summarize("test-001", kb)
        assert result.major_risks == []

    def test_capital_allocation_none_when_absent(self) -> None:
        content = _MANAGEMENT_SECTION + "x" * 2000
        doc = _make_doc(char_count=len(content))
        kb = _make_kb(doc, content)
        result = summarize("test-001", kb)
        assert result.capital_allocation is None
