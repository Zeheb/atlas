"""Golden/snapshot test for atlas.research — catches unintended report-shape
regressions.

Uses the same synthetic fixture as the rest of the atlas.research unit
tests (not a real company) precisely so this test is stable regardless of
what happens to real repositories/*.json — a real company's report will
legitimately change as new filings arrive; this golden file should not.

If a change to a section builder is intentional, regenerate the golden
file with:

    python -c "
    import sys; sys.path.insert(0, 'src'); sys.path.insert(0, 'tests/unit')
    from research_fixtures import make_profile
    from atlas.research.report import generate_report_markdown
    open('tests/golden/research_acme_golden.md', 'w', encoding='utf-8').write(
        generate_report_markdown('ACME', make_profile()))
    "

and review the diff before committing it — a passing golden test after
regenerating proves nothing; the diff is what should be reviewed.
"""
from __future__ import annotations

from pathlib import Path

from atlas.research.report import generate_report_markdown
from tests.unit.research_fixtures import make_profile

_GOLDEN_PATH = Path(__file__).parent.parent / "golden" / "research_acme_golden.md"


class TestResearchGolden:
    def test_matches_golden_output_exactly(self) -> None:
        actual = generate_report_markdown("ACME", make_profile())
        expected = _GOLDEN_PATH.read_text(encoding="utf-8")
        assert actual == expected, (
            "Report output changed. If this is an intentional change to a "
            "section builder, regenerate tests/golden/research_acme_golden.md "
            "(see this test file's module docstring) and review the diff."
        )

    def test_golden_file_is_deterministic_regeneration(self) -> None:
        # Generating twice from the same fixture must be byte-identical —
        # this is the determinism guarantee the whole report engine rests on.
        first = generate_report_markdown("ACME", make_profile())
        second = generate_report_markdown("ACME", make_profile())
        assert first == second
