"""`atlas assertion explain <id> --company X`.

The command exists to answer one question -- "why is this number wrong" --
without six manual lookups. So the tests are about whether the whole chain
actually appears: the row, the analyzer version that produced it, the run, the
source document, and the text at the offset. A command that prints four of
those five is the manual trace again, just shorter.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from click.testing import CliRunner

from atlas.assertions.model import Assertion, AssertionRun
from atlas.assertions.store import AssertionStore
from atlas.cli import cli
from atlas.knowledge.base import KnowledgeBase, ParsedDocument

_TICKER = "TCS"
_EVIDENCE = "bse-news-e1"
_ID = "a1b2c3"
_CONTENT = "x" * 300 + "Revenue for the quarter was 64988 crore." + "y" * 300


@pytest.fixture
def repo_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("ATLAS_REPOSITORY_BASE_PATH", str(tmp_path))
    monkeypatch.setenv("ATLAS_ANTHROPIC_API_KEY", "sk-test")
    root = tmp_path / _TICKER
    root.mkdir()
    return root


def _assertion(*, char_offset: int | None = 300) -> Assertion:
    return Assertion(
        assertion_id=_ID,
        evidence_id=_EVIDENCE,
        kind="financial_revenue",
        value="64988",
        value_type="int",
        unit="crore_inr",
        period="2026-03-31",
        confidence="high",
        section="p_and_l",
        char_offset=char_offset,
        excerpt="Revenue for the quarter",
        analyzer_version="2.0",
        fingerprint="fp-abc",
        ordinal=0,
    )


def _run() -> AssertionRun:
    return AssertionRun(
        evidence_id=_EVIDENCE,
        kind="financial_results",
        analyzer_version="2.0",
        fingerprint="fp-abc",
        result_confidence="high",
        source_date=datetime(2026, 4, 9, tzinfo=timezone.utc),
        analyzed_at=datetime(2026, 7, 29, tzinfo=timezone.utc),
        warnings=("page 3 unreadable",),
        status="ok",
        error=None,
    )


def _seed(root: Path, *, char_offset: int | None = 300, with_document: bool = True):
    store = AssertionStore(root)
    store.write_run(_run(), [_assertion(char_offset=char_offset)])
    if with_document:
        KnowledgeBase(root)._upsert(
            ParsedDocument(
                evidence_id=_EVIDENCE,
                kind="financial_results",
                title="Q4 FY26 Results",
                source_date="2026-04-09T00:00:00+00:00",
                local_path="other/e1.pdf",
                parsed_at=datetime.now(timezone.utc),
                parser_version="test",
                status="ok",
                char_count=len(_CONTENT),
            ),
            _CONTENT,
        )
    return store


def _explain(assertion_id: str = _ID, ticker: str = _TICKER):
    return CliRunner().invoke(
        cli, ["assertion", "explain", assertion_id, "--company", ticker]
    )


def test_prints_the_stored_row(repo_root: Path) -> None:
    _seed(repo_root)

    result = _explain()

    assert result.exit_code == 0, result.output
    assert _ID in result.output
    assert "financial_revenue" in result.output
    assert "crore_inr" in result.output
    assert "2026-03-31" in result.output


def test_prints_the_analyzer_version_and_fingerprint(repo_root: Path) -> None:
    """Which code produced the row is half the answer to "why is it wrong"."""
    _seed(repo_root)

    result = _explain()

    assert "2.0" in result.output
    assert "fp-abc" in result.output


def test_prints_the_run_it_belonged_to(repo_root: Path) -> None:
    _seed(repo_root)

    result = _explain()

    assert _EVIDENCE in result.output
    assert "status:      ok" in result.output


def test_prints_the_source_document(repo_root: Path) -> None:
    _seed(repo_root)

    result = _explain()

    assert "Q4 FY26 Results" in result.output
    assert "other/e1.pdf" in result.output


def test_prints_the_text_around_the_offset(repo_root: Path) -> None:
    """The last link in the chain: the sentence the number came out of."""
    _seed(repo_root)

    result = _explain()

    assert "Revenue for the quarter was 64988 crore." in result.output


def test_value_type_is_shown_not_just_the_value(repo_root: Path) -> None:
    """5 and "5" print identically; the type is the only thing separating them."""
    _seed(repo_root)

    result = _explain()

    assert "(int)" in result.output


def test_missing_offset_is_stated_rather_than_left_blank(repo_root: Path) -> None:
    """Six analyzer sites emit char_offset=None; silence would look like a bug."""
    _seed(repo_root, char_offset=None)

    result = _explain()

    assert result.exit_code == 0
    assert "none recorded" in result.output


def test_missing_document_is_stated(repo_root: Path) -> None:
    """The store and the knowledge base are separate files; either can go."""
    _seed(repo_root, with_document=False)

    result = _explain()

    assert result.exit_code == 0
    assert "not in the knowledge base" in result.output


def test_unknown_id_reports_where_it_looked(repo_root: Path) -> None:
    _seed(repo_root)

    result = _explain(assertion_id="nosuchid")

    assert result.exit_code == 1
    assert "No assertion 'nosuchid'" in result.output
    assert "assertions.db" in result.output


def test_missing_repository_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ATLAS_REPOSITORY_BASE_PATH", str(tmp_path))
    monkeypatch.setenv("ATLAS_ANTHROPIC_API_KEY", "sk-test")

    result = _explain(ticker="NOSUCH")

    assert result.exit_code == 1
    assert "No repository for 'NOSUCH'" in result.output
