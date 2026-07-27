"""C7 findings preserved through investigate.py (M2.3 commit 3).

Before M2.3 the reasoning layer computed assertability, confidence and
known_unknowns on every investigation, and investigate.py discarded all of it
at the research boundary -- keeping only flattened prose plus evidence ids.
Synthesis needs the discarded structure, so these tests pin that it survives,
that it is stored unmodified, and that dimension is read from the
Investigation rather than copied onto the contract type (ADR-0009).
"""

from __future__ import annotations

import json

from atlas.acquisition.catalog import CatalogEntry
from atlas.acquisition.evidence import EvidenceKind, EvidenceSource
from atlas.analysis.base import FactKind
from atlas.company.model import CompanyProfile, FinancialSnapshot, FinancialTimeSeries
from atlas.company.store import CompanyStore
from atlas.knowledge.base import KnowledgeBase
from atlas.research.investigate import InvestigationResult, run_investigation, run_plan
from atlas.research.plan import Investigation
from atlas.research.planner import plan_research

_CONTENT = (
    "Operating margin stood at 24.2% in FY26, driven by continued cost discipline "
    "across major markets, with steady improvement over prior quarters."
)


def _inv(dimension: str = "business_quality") -> Investigation:
    return Investigation(
        dimension=dimension,
        question="What do margins show about business quality?",
        subjects=("TCS",),
        rationale="margins are the cheapest available test of business durability",
        priority=5,
    )


def _seed(base) -> None:
    profile = CompanyProfile(
        company_id="TCS",
        financial=FinancialTimeSeries(
            snapshots=[
                FinancialSnapshot(
                    period="2026-03-31",
                    period_type="annual",
                    basis="consolidated",
                    facts={FactKind.FINANCIAL_OPERATING_MARGIN: 24.2},
                    sources=["ev-1"],
                )
            ]
        ),
    )
    repo_root = base / "TCS"
    repo_root.mkdir(parents=True, exist_ok=True)
    CompanyStore(repo_root / "profile.json", "TCS").save(profile)

    rel = "ev-1.txt"
    (repo_root / rel).write_text(_CONTENT, encoding="utf-8")
    entry = CatalogEntry(
        evidence_id="ev-1",
        source=EvidenceSource.BSE.value,
        kind=EvidenceKind.FINANCIAL_RESULTS.value,
        title="Test filing",
        source_date="2026-03-31T00:00:00+00:00",
        document_url=None,
        local_path=rel,
        file_size_bytes=None,
        acquired_at="2026-04-01T00:00:00+00:00",
    )
    KnowledgeBase(repo_root).parse(entry)


class _RichFake:
    """Returns a finding carrying every field the flattened view loses."""

    def complete(self, *, system: str, user: str) -> str:
        return json.dumps(
            {
                "refused": False,
                "overall_confidence": "medium",
                "findings": [
                    {
                        "statement": "Operating margin ~24%.",
                        "assertability": "judgment",
                        "confidence": "medium",
                        "supporting_evidence_ids": ["ev-1"],
                        "known_unknowns": ["segment-level margin is not disclosed"],
                    }
                ],
            }
        )


class _RefusingFake:
    def complete(self, *, system: str, user: str) -> str:
        return json.dumps(
            {
                "refused": True,
                "overall_confidence": "low",
                "refusal_reason": "no evidence supports this",
                "findings": [],
            }
        )


# --- The metadata survives ------------------------------------------------------------
def test_semantic_findings_are_preserved(tmp_path) -> None:
    _seed(tmp_path)
    result = run_investigation(_inv(), tmp_path, _RichFake())

    assert result.semantic_findings, "C7 findings must not be discarded"
    sf = result.semantic_findings[0]
    assert sf.statement == "Operating margin ~24%."
    assert sf.assertability == "judgment"
    assert sf.confidence == "medium"
    assert sf.known_unknowns == ("segment-level margin is not disclosed",)


def test_preserved_confidence_is_absent_from_the_flattened_view(tmp_path) -> None:
    """The reason this commit exists: the rendering view cannot represent
    per-finding confidence, so synthesis could not have read it."""
    _seed(tmp_path)
    result = run_investigation(_inv(), tmp_path, _RichFake())

    assert result.finding is not None
    assert not hasattr(result.finding, "confidence")
    assert result.semantic_findings[0].confidence == "medium"


def test_semantic_findings_carry_grounded_evidence(tmp_path) -> None:
    _seed(tmp_path)
    result = run_investigation(_inv(), tmp_path, _RichFake())

    assert result.semantic_findings[0].evidence_ids == frozenset({"ev-1"})


# --- Stored unmodified: no research vocabulary added to the contract type -------------
def test_c7_findings_are_stored_unmodified(tmp_path) -> None:
    """ADR-0009: a shared contract does not gain Research-specific fields."""
    _seed(tmp_path)
    result = run_investigation(_inv(), tmp_path, _RichFake())

    sf = result.semantic_findings[0]
    assert not hasattr(sf, "dimension")


def test_dimension_is_read_from_the_investigation_not_duplicated(tmp_path) -> None:
    _seed(tmp_path)
    result = run_investigation(_inv("risks"), tmp_path, _RichFake())

    assert result.dimension == "risks"
    assert result.dimension == result.investigation.dimension


# --- Additive: unresolved paths and defaults unchanged ---------------------------------
def test_unresolved_results_have_no_semantic_findings(tmp_path) -> None:
    _seed(tmp_path)
    result = run_investigation(_inv(), tmp_path, _RefusingFake())

    assert not result.resolved
    assert result.semantic_findings == ()


def test_field_defaults_to_empty_so_pre_m23_construction_still_works() -> None:
    from atlas.research.citations import Finding

    result = InvestigationResult(
        investigation=_inv(),
        finding=Finding(text="x", evidence_ids=["ev-1"]),
    )
    assert result.semantic_findings == ()


def test_whole_run_preserves_semantic_findings(tmp_path) -> None:
    _seed(tmp_path)
    plan = plan_research("Should I invest in TCS?", ("TCS",))
    run = run_plan(plan, tmp_path, _RichFake())

    assert all(r.semantic_findings for r in run.results if r.resolved)
