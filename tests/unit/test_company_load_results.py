"""Routing a profile build through the configured source (M3, #25).

Two paths that must hand ``build_profile`` the same kind of input: re-run the
analyzers over evidence, or reconstruct results from the assertion store. The
swap is only reversible if neither path is special, so the tests check both
against the same expectations, including the failure accounting -- a profile
built from three documents out of ninety must not look like a healthy one.

``builder.py`` is not touched by any of this, which is the property that makes
the whole milestone safe to abandon if the equivalence gate goes red.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from atlas.acquisition.catalog import CatalogEntry, RepositoryCatalog
from atlas.analysis.base import AnalysisResult
from atlas.assertions.store import AssertionStore
from atlas.assertions.writer import write_result
from atlas.company.store import load_results
from atlas.knowledge.base import KnowledgeBase, ParsedDocument
from atlas.provenance import current_fingerprint
from tests.support.roundtrip import fact_multiset, make_result

_EVIDENCE = "bse-news-e1"
_KIND = "financial_results"


def _seed_evidence(
    root: Path, *, kind: str = _KIND, evidence_id: str = _EVIDENCE, parsed: bool = True
) -> None:
    local_path = f"other/{evidence_id}.pdf"
    document = root / local_path
    document.parent.mkdir(parents=True, exist_ok=True)
    document.write_bytes(b"%PDF-1.4 stub")

    catalog = RepositoryCatalog(root)
    catalog.add(
        CatalogEntry(
            evidence_id=evidence_id,
            source="bse",
            kind=kind,
            title="Quarterly Results",
            source_date="2026-04-09T00:00:00+00:00",
            document_url=None,
            local_path=local_path,
            file_size_bytes=13,
            acquired_at="2026-04-10T00:00:00+00:00",
        )
    )
    catalog.save()

    KnowledgeBase(root)._upsert(
        ParsedDocument(
            evidence_id=evidence_id,
            kind=kind,
            title="Quarterly Results",
            source_date="2026-04-09T00:00:00+00:00",
            local_path=local_path,
            parsed_at=datetime.now(timezone.utc),
            parser_version="test",
            status="ok" if parsed else "failed",
            char_count=10,
        ),
        "some extracted text",
    )


@pytest.fixture
def stub_analyzer(monkeypatch: pytest.MonkeyPatch) -> AnalysisResult:
    """Stand in for the eleven analyzers; the routing is what is under test."""
    result = make_result(_KIND)
    result.evidence_id = _EVIDENCE
    monkeypatch.setattr(
        "atlas.analysis.registry.analyze", lambda evidence_id, kb: result
    )
    monkeypatch.setattr(
        "atlas.knowledge.base.KnowledgeBase.parse",
        lambda self, entry: self.get(entry.evidence_id),
    )
    return result


# ---------------------------------------------------------------------------
# The analyzers path
# ---------------------------------------------------------------------------


def test_analyzers_path_returns_analyzed_results(
    tmp_path: Path, stub_analyzer: AnalysisResult
) -> None:
    _seed_evidence(tmp_path)

    report = load_results(tmp_path, source="analyzers")

    assert report.source == "analyzers"
    assert [result.evidence_id for result in report.results] == [_EVIDENCE]
    assert report.parsed == 1


def test_unsupported_kinds_are_counted_not_analyzed(
    tmp_path: Path, stub_analyzer: AnalysisResult
) -> None:
    _seed_evidence(tmp_path, kind="press_clipping")

    report = load_results(tmp_path, source="analyzers")

    assert report.results == []
    assert report.skipped_kind == 1


def test_an_unparsed_document_is_counted_not_dropped_silently(
    tmp_path: Path, stub_analyzer: AnalysisResult
) -> None:
    """Silence here is how a profile built from a fraction of a repository
    looks exactly like a healthy one."""
    _seed_evidence(tmp_path, parsed=False)

    report = load_results(tmp_path, source="analyzers")

    assert report.results == []
    assert report.failed_parse == 1


def test_one_failing_analyzer_does_not_abort_the_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_evidence(tmp_path)
    monkeypatch.setattr(
        "atlas.knowledge.base.KnowledgeBase.parse",
        lambda self, entry: self.get(entry.evidence_id),
    )

    def _explode(evidence_id: str, kb: KnowledgeBase) -> AnalysisResult:
        raise RuntimeError("no tables found")

    monkeypatch.setattr("atlas.analysis.registry.analyze", _explode)
    notes: list[str] = []

    report = load_results(tmp_path, source="analyzers", on_error=notes.append)

    assert report.failed_analyze == 1
    assert notes and "no tables found" in notes[0]


# ---------------------------------------------------------------------------
# The assertions path
# ---------------------------------------------------------------------------


def test_assertions_path_reads_the_store(tmp_path: Path) -> None:
    store = AssertionStore(tmp_path)
    original = make_result(_KIND)
    write_result(store, original, fingerprint=current_fingerprint().digest())

    report = load_results(tmp_path, source="assertions")

    assert report.source == "assertions"
    assert [result.evidence_id for result in report.results] == [original.evidence_id]


def test_assertions_path_never_touches_the_knowledge_base(tmp_path: Path) -> None:
    """The point of Tier 1: rebuilding a profile without re-reading a document.

    No catalog, no parsed documents, no PDFs on disk -- only the store.
    """
    store = AssertionStore(tmp_path)
    write_result(store, make_result(_KIND), fingerprint=current_fingerprint().digest())

    report = load_results(tmp_path, source="assertions")

    assert len(report.results) == 1
    assert not (tmp_path / "knowledge.db").exists()


def test_both_paths_yield_the_same_facts(
    tmp_path: Path, stub_analyzer: AnalysisResult
) -> None:
    """The claim the equivalence gate will make in full; here in miniature."""
    _seed_evidence(tmp_path)
    from_analyzers = load_results(tmp_path, source="analyzers")
    store = AssertionStore(tmp_path)
    for result in from_analyzers.results:
        write_result(store, result, fingerprint=current_fingerprint().digest())

    from_assertions = load_results(tmp_path, source="assertions")

    assert fact_multiset(
        [fact for result in from_assertions.results for fact in result.facts]
    ) == fact_multiset(
        [fact for result in from_analyzers.results for fact in result.facts]
    )


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def test_the_default_source_comes_from_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Since M4's cutover (#35) the default is the store, not the analyzers."""
    store = AssertionStore(tmp_path)
    write_result(store, make_result(_KIND), fingerprint=current_fingerprint().digest())
    monkeypatch.delenv("ATLAS_PROFILE_SOURCE", raising=False)

    assert load_results(tmp_path).source == "assertions"


def test_the_setting_can_select_the_analyzer_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_analyzer: AnalysisResult
) -> None:
    """The rollback path, which must keep working for a full milestone."""
    _seed_evidence(tmp_path)
    monkeypatch.setenv("ATLAS_PROFILE_SOURCE", "analyzers")

    assert load_results(tmp_path).source == "analyzers"


def test_an_explicit_source_overrides_the_setting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_analyzer: AnalysisResult
) -> None:
    """What lets the equivalence test build both ways in one process."""
    _seed_evidence(tmp_path)
    monkeypatch.setenv("ATLAS_PROFILE_SOURCE", "assertions")

    assert load_results(tmp_path, source="analyzers").source == "analyzers"
