"""Unit tests for atlas.research.render — the only module that emits
Markdown syntax."""
from __future__ import annotations

from atlas.query.engine import TableSection
from atlas.research.citations import Finding
from atlas.research.model import ReportData, ReportSection
from atlas.research.render import render_markdown


class TestRenderMarkdown:
    def test_title_rendered_as_h1(self) -> None:
        report = ReportData(ticker="X", title="X — Briefing", sections=[])
        md = render_markdown(report)
        assert md.startswith("# X — Briefing")

    def test_section_rendered_as_h2(self) -> None:
        report = ReportData(ticker="X", title="T", sections=[ReportSection(key="risks", title="Risks", findings=[Finding(text="a risk")])])
        md = render_markdown(report)
        assert "## Risks" in md

    def test_synthesis_finding_tagged(self) -> None:
        sec = ReportSection(key="k", title="K", findings=[Finding(text="claim", kind="synthesis")])
        md = render_markdown(ReportData(ticker="X", title="T", sections=[sec]))
        assert "_[synthesis]_" in md

    def test_fact_finding_not_tagged(self) -> None:
        sec = ReportSection(key="k", title="K", findings=[Finding(text="claim", kind="fact")])
        md = render_markdown(ReportData(ticker="X", title="T", sections=[sec]))
        assert "[synthesis]" not in md

    def test_table_rendered_as_markdown_table(self) -> None:
        table = TableSection(heading="H", columns=["A", "B"], rows=[["1", "2"]])
        sec = ReportSection(key="k", title="K", tables=[table])
        md = render_markdown(ReportData(ticker="X", title="T", sections=[sec]))
        assert "| A | B |" in md
        assert "| 1 | 2 |" in md

    def test_embedded_newline_in_cell_does_not_break_table(self) -> None:
        # Real case found in Tata Steel's data: an acquisition target name
        # extracted from a PDF carried an embedded newline, which would
        # otherwise split one logical row across multiple broken lines.
        table = TableSection(heading="H", columns=["Target"], rows=[["Widget Co\n\nWidget Co"]])
        sec = ReportSection(key="k", title="K", tables=[table])
        md = render_markdown(ReportData(ticker="X", title="T", sections=[sec]))
        assert "| Widget Co Widget Co |" in md

    def test_pipe_character_in_cell_escaped(self) -> None:
        table = TableSection(heading="H", columns=["Name"], rows=[["A | B Corp"]])
        sec = ReportSection(key="k", title="K", tables=[table])
        md = render_markdown(ReportData(ticker="X", title="T", sections=[sec]))
        assert "A \\| B Corp" in md

    def test_notes_rendered_as_blockquote(self) -> None:
        sec = ReportSection(key="k", title="K", notes=["a caveat"])
        md = render_markdown(ReportData(ticker="X", title="T", sections=[sec]))
        assert "> a caveat" in md

    def test_empty_section_states_no_evidence(self) -> None:
        sec = ReportSection(key="k", title="K")
        md = render_markdown(ReportData(ticker="X", title="T", sections=[sec]))
        assert "No evidence available" in md

    def test_no_source_line_when_finding_has_no_evidence_ids(self) -> None:
        sec = ReportSection(key="k", title="K", findings=[Finding(text="claim", evidence_ids=[])])
        md = render_markdown(ReportData(ticker="X", title="T", sections=[sec]), repo=None)
        assert "Source:" not in md

    def test_no_raw_evidence_id_ever_shown_without_repo(self) -> None:
        sec = ReportSection(key="k", title="K", findings=[Finding(text="claim", evidence_ids=["bse-news-abc123"])])
        md = render_markdown(ReportData(ticker="X", title="T", sections=[sec]), repo=None)
        assert "bse-news-abc123" not in md
