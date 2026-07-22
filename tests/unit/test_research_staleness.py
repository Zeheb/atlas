"""Deterministic staleness checking (M2.4 commit 4).

The architectural test here matters as much as the behavioral ones: the
import-boundary test proves staleness.py never imports research.memory at
module level, which is what lets the two evolve independently.
"""
from __future__ import annotations

import ast
import inspect

from atlas.acquisition.catalog import CatalogEntry, RepositoryCatalog
from atlas.acquisition.evidence import EvidenceKind, EvidenceSource
from atlas.knowledge.base import KnowledgeBase
from atlas.reasoning.contracts import RecalledClaim, RecalledView, SubjectRef
from atlas.research import staleness as staleness_mod
from atlas.research.staleness import StalenessPolicy, check_staleness, sweep_staleness

SUBJECT = SubjectRef(subject_id="TCS", display="TCS")


def _entry(evidence_id: str, source_date: str, acquired_at: str = "2026-04-01T00:00:00+00:00") -> CatalogEntry:
    return CatalogEntry(
        evidence_id=evidence_id, source=EvidenceSource.BSE.value,
        kind=EvidenceKind.FINANCIAL_RESULTS.value, title="Test filing",
        source_date=source_date, document_url=None,
        local_path=f"{evidence_id}.txt", file_size_bytes=None, acquired_at=acquired_at,
    )


def _seed_catalog_and_kb(base, entries: list[CatalogEntry]) -> None:
    repo_root = base / "TCS"
    repo_root.mkdir(parents=True, exist_ok=True)
    catalog = RepositoryCatalog(repo_root)
    kb = KnowledgeBase(repo_root)
    for entry in entries:
        catalog.add(entry)
        (repo_root / entry.local_path).write_text("Some parsed content here.", encoding="utf-8")
        kb.parse(entry)
    catalog.save()


def _view(*evidence_ids: str, as_of: str = "2026-06-01T00:00:00+00:00", view_id: str = "view-1") -> RecalledView:
    ids = evidence_ids or ("bse-ev-1",)
    return RecalledView(
        view_id=view_id, subject_ref=SUBJECT, question="Should I invest in TCS?",
        claims=(RecalledClaim(
            statement="Margins are durable.", evidence_ids=frozenset(ids), confidence="medium",
        ),),
        as_of=as_of,
    )


# --- The architectural property: independence from the store ------------------------
def test_staleness_never_imports_memory_at_module_level() -> None:
    """AST scan, not a substring grep: the module docstring legitimately
    names research.memory when explaining the layering, and a boundary test
    a comment could break is worse than none."""
    tree = ast.parse(inspect.getsource(staleness_mod))
    module_level_imports: set[str] = set()
    for node in tree.body:  # tree.body only -- NOT ast.walk -- excludes function bodies
        if isinstance(node, ast.ImportFrom) and node.module:
            module_level_imports.add(node.module)
        elif isinstance(node, ast.Import):
            module_level_imports.update(alias.name for alias in node.names)

    assert "atlas.research.memory" not in module_level_imports


def test_sweep_staleness_is_the_one_function_that_imports_memory() -> None:
    """The composition point exists, deliberately, one level down."""
    source = inspect.getsource(staleness_mod.sweep_staleness)
    assert "from atlas.research.memory import ThesisStore" in source


# --- Hard staleness: cited evidence no longer resolves --------------------------------
def test_no_repository_at_all_reports_hard_stale(tmp_path) -> None:
    """A view whose subject has no knowledge.db/catalog.json yet -- every
    cited id is trivially missing."""
    report = check_staleness(_view("bse-ev-1"), tmp_path / "TCS")
    assert report.hard_stale
    assert report.missing_evidence == ("bse-ev-1",)


def test_cited_evidence_still_resolving_is_not_hard_stale(tmp_path) -> None:
    _seed_catalog_and_kb(tmp_path, [_entry("bse-ev-1", "2026-01-01T00:00:00+00:00")])
    report = check_staleness(_view("bse-ev-1"), tmp_path / "TCS")

    assert not report.hard_stale
    assert report.missing_evidence == ()


def test_cited_evidence_no_longer_resolving_is_hard_stale(tmp_path) -> None:
    _seed_catalog_and_kb(tmp_path, [_entry("bse-ev-1", "2026-01-01T00:00:00+00:00")])
    report = check_staleness(_view("bse-ev-1", "ev-GONE"), tmp_path / "TCS")

    assert report.hard_stale
    assert report.missing_evidence == ("ev-GONE",)


def test_view_id_is_carried_onto_the_report(tmp_path) -> None:
    _seed_catalog_and_kb(tmp_path, [_entry("bse-ev-1", "2026-01-01T00:00:00+00:00")])
    report = check_staleness(_view("bse-ev-1", view_id="my-view"), tmp_path / "TCS")
    assert report.view_id == "my-view"


# --- New evidence since (advisory) ----------------------------------------------------
def test_new_evidence_after_as_of_is_reported(tmp_path) -> None:
    _seed_catalog_and_kb(tmp_path, [
        _entry("bse-ev-1", "2026-01-01T00:00:00+00:00"),
        _entry("bse-ev-2-new", "2026-07-01T00:00:00+00:00"),
    ])
    report = check_staleness(_view("bse-ev-1", as_of="2026-06-01T00:00:00+00:00"), tmp_path / "TCS")

    assert "bse-ev-2-new" in report.new_evidence_since


def test_no_new_evidence_is_an_empty_tuple(tmp_path) -> None:
    _seed_catalog_and_kb(tmp_path, [_entry("bse-ev-1", "2026-01-01T00:00:00+00:00")])
    report = check_staleness(_view("bse-ev-1", as_of="2026-06-01T00:00:00+00:00"), tmp_path / "TCS")

    assert report.new_evidence_since == ()


def test_new_evidence_does_not_make_it_hard_stale(tmp_path) -> None:
    """Advisory, not blocking -- new evidence existing is not itself an
    error, even though it is worth surfacing."""
    _seed_catalog_and_kb(tmp_path, [
        _entry("bse-ev-1", "2026-01-01T00:00:00+00:00"),
        _entry("bse-ev-2-new", "2026-07-01T00:00:00+00:00"),
    ])
    report = check_staleness(_view("bse-ev-1", as_of="2026-06-01T00:00:00+00:00"), tmp_path / "TCS")

    assert not report.hard_stale


def test_policy_kinds_filter_restricts_new_evidence(tmp_path) -> None:
    _seed_catalog_and_kb(tmp_path, [
        _entry("bse-ev-1", "2026-01-01T00:00:00+00:00"),
        _entry("bse-ev-2-new", "2026-07-01T00:00:00+00:00"),
    ])
    policy = StalenessPolicy(kinds=("board_outcome",))  # excludes financial_results
    report = check_staleness(
        _view("bse-ev-1", as_of="2026-06-01T00:00:00+00:00"), tmp_path / "TCS", policy,
    )
    assert report.new_evidence_since == ()


def test_default_policy_counts_every_kind(tmp_path) -> None:
    assert StalenessPolicy().kinds is None


# --- No LLM, no I/O beyond the repository ------------------------------------------------
def test_check_staleness_is_pure_no_llm_import() -> None:
    source = inspect.getsource(staleness_mod)
    assert "atlas.reasoning.llm" not in source
    assert "atlas.reasoning.ask" not in source


# --- sweep_staleness composition -------------------------------------------------------
def test_sweep_staleness_returns_empty_for_a_subject_with_no_stored_views(tmp_path) -> None:
    assert sweep_staleness(tmp_path, "TCS") == ()


def test_sweep_staleness_checks_every_stored_view(tmp_path) -> None:
    import json

    from atlas.reasoning.contracts import Claim, EvidenceReference
    from atlas.research.investigate import InvestigationResult, InvestigationRun
    from atlas.research.citations import Finding
    from atlas.research.memory import ThesisStore
    from atlas.research.plan import Investigation, ResearchPlan
    from atlas.research.thesis import synthesize

    _seed_catalog_and_kb(tmp_path, [_entry("bse-ev-1", "2026-01-01T00:00:00+00:00")])

    def _semantic(statement, eid):
        from atlas.reasoning.contracts import Finding as SemanticFinding

        return SemanticFinding(
            statement=statement, assertability="judgment", confidence="high",
            supporting_claims=(Claim(
                subject_ref=SUBJECT, statement=statement, assertability="fact",
                confidence="high", evidence=[EvidenceReference(evidence_id=eid)],
            ),),
        )

    investigation = Investigation(
        dimension="business_quality", question="What does business quality show?",
        subjects=("TCS",), rationale="a required dimension", priority=5,
    )
    run = InvestigationRun(
        plan=ResearchPlan(
            raw_question="Should I invest in TCS?", intent="invest_decision",
            subjects=("TCS",), investigations=(investigation,),
        ),
        results=(InvestigationResult(
            investigation=investigation,
            finding=Finding(text="Fine.", evidence_ids=["bse-ev-1"]),
            semantic_findings=(_semantic("Fine.", "bse-ev-1"),),
        ),),
    )

    class _Fake:
        def complete(self, *, system: str, user: str) -> str:
            return json.dumps({
                "refused": False, "overall_confidence": "medium",
                "findings": [{
                    "statement": "Durable business.", "assertability": "judgment",
                    "confidence": "medium", "supporting_evidence_ids": ["bse-ev-1"],
                    "known_unknowns": [],
                }],
            })

    thesis = synthesize(run, _Fake())
    ThesisStore(tmp_path / "TCS" / "theses.json", "TCS").save(thesis)

    reports = sweep_staleness(tmp_path, "TCS")
    assert len(reports) == 1
    assert reports[0].view_id == thesis.view_id
    assert not reports[0].hard_stale
