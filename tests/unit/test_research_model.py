"""Unit tests for atlas.research.model — ReportSection/ReportData."""
from __future__ import annotations

from atlas.query.engine import TableSection
from atlas.research.citations import Finding
from atlas.research.model import ReportData, ReportSection


class TestReportSectionIsEmpty:
    def test_empty_with_nothing(self) -> None:
        assert ReportSection(key="k", title="T").is_empty() is True

    def test_not_empty_with_findings(self) -> None:
        sec = ReportSection(key="k", title="T", findings=[Finding(text="x")])
        assert sec.is_empty() is False

    def test_not_empty_with_table_rows(self) -> None:
        sec = ReportSection(key="k", title="T", tables=[TableSection(heading="H", columns=["A"], rows=[["1"]])])
        assert sec.is_empty() is False

    def test_empty_with_table_but_no_rows(self) -> None:
        sec = ReportSection(key="k", title="T", tables=[TableSection(heading="H", columns=["A"], rows=[])])
        assert sec.is_empty() is True

    def test_not_empty_with_notes_only(self) -> None:
        sec = ReportSection(key="k", title="T", notes=["no data"])
        assert sec.is_empty() is False


class TestReportDataSection:
    def test_finds_section_by_key(self) -> None:
        sec = ReportSection(key="risks", title="Risks")
        report = ReportData(ticker="X", title="T", sections=[sec])
        assert report.section("risks") is sec

    def test_returns_none_for_missing_key(self) -> None:
        report = ReportData(ticker="X", title="T", sections=[])
        assert report.section("missing") is None
