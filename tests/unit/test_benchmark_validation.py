"""Machine-checked provenance validation (M1.8.5 commit 4, ADR-0005).

Hermetic fixtures throughout (a synthetic KnowledgeBase built via .parse(),
same pattern as test_reasoning_retrieval_plan.py) rather than the real
repositories -- deterministic and independent of what the real corpus
happens to contain. A manual exploratory check against the REAL TCS corpus
confirmed the inverted-negative check catches genuine overlap a human might
not anticipate (TCS's annual report has a glossary entry on quantum
computing/entanglement) -- proof the mechanism works, not reproduced here
since it depends on real, mutable corpus content.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from atlas.acquisition.catalog import CatalogEntry
from atlas.acquisition.evidence import EvidenceKind, EvidenceSource
from atlas.analysis.base import FactKind
from atlas.benchmark.provenance import CaseProvenance, RetrievalLabel
from atlas.benchmark.validation import validate_cases
from atlas.company.model import CompanyProfile, FinancialSnapshot, FinancialTimeSeries
from atlas.company.store import CompanyStore
from atlas.knowledge.base import KnowledgeBase

_CONTENT = (
    "Operating margin stood at 24.2% in FY26, driven by continued cost discipline "
    "across major markets, with steady improvement over prior quarters."
)


@dataclass(frozen=True)
class _Case:
    id: str
    subject: str
    question: str
    difficulty: str | None = None
    provenance: CaseProvenance | None = None
    retrieval_label: RetrievalLabel | None = None


def _seed(tmp_path: Path, subject: str = "TCS", kind: EvidenceKind = EvidenceKind.FINANCIAL_RESULTS) -> str:
    """Seeds one profile + one KB entry (evidence_id='ev-1'); returns the id."""
    root = tmp_path / subject
    profile = CompanyProfile(
        company_id=subject,
        financial=FinancialTimeSeries(snapshots=[FinancialSnapshot(
            period="2026-03-31", period_type="annual", basis="consolidated",
            facts={FactKind.FINANCIAL_OPERATING_MARGIN: 24.2}, sources=["ev-1"],
        )]),
    )
    CompanyStore(root / "profile.json", subject).save(profile)
    rel = "ev-1.txt"
    (root / rel).write_text(_CONTENT, encoding="utf-8")
    entry = CatalogEntry(
        evidence_id="ev-1", source=EvidenceSource.BSE.value, kind=kind.value,
        title="Test filing", source_date="2026-03-31T00:00:00+00:00", document_url=None,
        local_path=rel, file_size_bytes=None, acquired_at="2026-04-01T00:00:00+00:00",
    )
    KnowledgeBase(root).parse(entry)
    return "ev-1"


def _provenance(**overrides: object) -> CaseProvenance:
    defaults: dict[str, object] = dict(
        origin="corpus_derived", supporting_evidence_ids=("ev-1",),
        verification_method="manual", verified_at="2026-07-21", verified_by="z",
    )
    defaults.update(overrides)
    return CaseProvenance(**defaults)  # type: ignore[arg-type]


# --- corpus_derived: evidence must resolve -----------------------------------------
def test_corpus_derived_with_real_evidence_id_passes(tmp_path: Path) -> None:
    _seed(tmp_path)
    case = _Case(id="c1", subject="TCS", question="q", provenance=_provenance())
    report = validate_cases([case], tmp_path)
    assert report.passed


def test_corpus_derived_with_missing_evidence_id_fails(tmp_path: Path) -> None:
    _seed(tmp_path)
    case = _Case(id="c1", subject="TCS", question="q",
                 provenance=_provenance(supporting_evidence_ids=("ev-ghost",)))
    report = validate_cases([case], tmp_path)
    assert not report.passed
    assert report.issues[0].kind == "missing_evidence"
    assert report.issues[0].case_id == "c1"


# --- retrieval_label kind consistency ------------------------------------------------
def test_label_kind_matching_real_kind_passes(tmp_path: Path) -> None:
    _seed(tmp_path, kind=EvidenceKind.BRSR)
    case = _Case(
        id="c1", subject="TCS", question="q", provenance=_provenance(),
        retrieval_label=RetrievalLabel(relevant_evidence_ids=("ev-1",), relevant_kinds=("brsr",)),
    )
    report = validate_cases([case], tmp_path)
    assert report.passed


def test_label_kind_mismatch_detected(tmp_path: Path) -> None:
    _seed(tmp_path, kind=EvidenceKind.BRSR)
    case = _Case(
        id="c1", subject="TCS", question="q", provenance=_provenance(),
        retrieval_label=RetrievalLabel(relevant_evidence_ids=("ev-1",), relevant_kinds=("annual_report",)),
    )
    report = validate_cases([case], tmp_path)
    assert not report.passed
    assert report.issues[0].kind == "kind_mismatch"


def test_label_evidence_id_also_checked_for_existence(tmp_path: Path) -> None:
    _seed(tmp_path)
    case = _Case(
        id="c1", subject="TCS", question="q", provenance=_provenance(),
        retrieval_label=RetrievalLabel(relevant_evidence_ids=("ev-ghost",)),
    )
    report = validate_cases([case], tmp_path)
    assert not report.passed
    assert report.issues[0].kind == "missing_evidence"


# --- corpus_validated_negative: inverted check ---------------------------------------
def test_negative_case_with_no_overlap_passes(tmp_path: Path) -> None:
    _seed(tmp_path)
    case = _Case(
        id="c1", subject="TCS", question="xyzzyplugh wibbleflorp nonexistent gibberish term",
        provenance=CaseProvenance(
            origin="corpus_validated_negative", verification_method="ran retrieval, nothing matched",
            verified_at="2026-07-21", verified_by="z",
        ),
    )
    report = validate_cases([case], tmp_path)
    assert report.passed


def test_negative_case_with_real_overlap_fails(tmp_path: Path) -> None:
    _seed(tmp_path)
    # Deliberately asks about the exact content that was seeded -- the
    # inverted check must catch that this "negative" claim is false.
    case = _Case(
        id="c1", subject="TCS", question="What was the operating margin 24.2 percent in FY26?",
        provenance=CaseProvenance(
            origin="corpus_validated_negative", verification_method="claimed absent",
            verified_at="2026-07-21", verified_by="z",
        ),
    )
    report = validate_cases([case], tmp_path)
    assert not report.passed
    assert report.issues[0].kind == "negative_not_absent"


# --- difficult-case provenance requirements ------------------------------------------
def test_difficult_case_without_provenance_fails(tmp_path: Path) -> None:
    case = _Case(id="c1", subject="TCS", question="q", difficulty="difficult")
    report = validate_cases([case], tmp_path)
    assert not report.passed
    assert report.issues[0].kind == "missing_provenance"


def test_routine_case_without_provenance_is_fine(tmp_path: Path) -> None:
    case = _Case(id="c1", subject="TCS", question="q", difficulty="routine")
    report = validate_cases([case], tmp_path)
    assert report.passed


def test_difficult_corpus_derived_case_without_label_fails(tmp_path: Path) -> None:
    _seed(tmp_path)
    case = _Case(id="c1", subject="TCS", question="q", difficulty="difficult", provenance=_provenance())
    report = validate_cases([case], tmp_path)
    assert not report.passed
    assert report.issues[0].kind == "missing_label"


def test_difficult_negative_case_without_label_is_fine(tmp_path: Path) -> None:
    _seed(tmp_path)
    case = _Case(
        id="c1", subject="TCS", question="xyzzyplugh gibberish", difficulty="difficult",
        provenance=CaseProvenance(
            origin="corpus_validated_negative", verification_method="m",
            verified_at="2026-07-21", verified_by="z",
        ),
    )
    report = validate_cases([case], tmp_path)
    assert report.passed  # negatives don't need a retrieval_label


def test_difficult_case_with_both_provenance_and_label_passes(tmp_path: Path) -> None:
    _seed(tmp_path)
    case = _Case(
        id="c1", subject="TCS", question="q", difficulty="difficult", provenance=_provenance(),
        retrieval_label=RetrievalLabel(relevant_evidence_ids=("ev-1",)),
    )
    report = validate_cases([case], tmp_path)
    assert report.passed


# --- Missing subject / missing KB -----------------------------------------------------
def test_case_for_subject_with_no_kb_flagged(tmp_path: Path) -> None:
    case = _Case(id="c1", subject="NOKB", question="q", provenance=_provenance())
    report = validate_cases([case], tmp_path)
    assert not report.passed
    assert report.issues[0].kind == "missing_kb"


# --- Cases with no provenance at all are simply skipped -------------------------------
def test_case_without_provenance_or_difficulty_is_ignored(tmp_path: Path) -> None:
    case = _Case(id="c1", subject="TCS", question="q")
    report = validate_cases([case], tmp_path)
    assert report.passed


# --- Batch behavior --------------------------------------------------------------------
def test_kb_loaded_once_per_subject_not_per_case(tmp_path: Path) -> None:
    _seed(tmp_path)
    cases = [_Case(id=f"c{i}", subject="TCS", question="q", provenance=_provenance()) for i in range(5)]
    report = validate_cases(cases, tmp_path)
    assert report.passed
    assert report.total_cases == 5


def test_one_bad_case_does_not_suppress_others(tmp_path: Path) -> None:
    _seed(tmp_path)
    cases = [
        _Case(id="good", subject="TCS", question="q", provenance=_provenance()),
        _Case(id="bad", subject="TCS", question="q", provenance=_provenance(supporting_evidence_ids=("ghost",))),
    ]
    report = validate_cases(cases, tmp_path)
    assert len(report.issues) == 1
    assert report.issues[0].case_id == "bad"
