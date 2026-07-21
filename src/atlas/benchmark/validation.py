"""Machine-checked provenance validation (M1.8.5 commit 4, ADR-0005).

A case's provenance is a CLAIM ("this scenario is real, here is why"); this
module is what turns the claim into a checked fact rather than an assertion
someone wrote once and never revisited:

- ``corpus_derived`` -- every evidence id the case's provenance or retrieval
  label names must actually resolve in that SUBJECT's ``KnowledgeBase``, and
  if a label declares ``relevant_kinds``, each named id's real kind must be
  among them. A label naming a document that doesn't exist, or mislabeling
  its kind, fails.
- ``corpus_validated_negative`` -- the INVERTED check: actually run
  retrieval (the real ``build_context_with_diagnostics`` / ``plan_retrieval``
  production path, not a reimplementation) over the subject's candidate pool
  and assert NOTHING clears the accept bar. "Verified absent" is a test
  result here, not a one-time assertion -- if the corpus later grows to
  contain the answer (M1.8.6), this fails loudly and the case must be
  reclassified, which is exactly the behavior wanted.

Read-only, no LLM, no mutation of any case or corpus. Depends on
``reasoning`` and ``knowledge`` like the rest of this package, plus
``company.store`` to load a profile -- not on ``atlas.eval`` (see
``coverage.py``'s ``CaseLike`` for the same structural-Protocol pattern).
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from atlas.benchmark.provenance import CaseProvenance, RetrievalLabel
from atlas.company.store import CompanyStore
from atlas.knowledge.base import KnowledgeBase
from atlas.reasoning.context import build_context_with_diagnostics
from atlas.reasoning.contracts import SubjectRef
from atlas.reasoning.planner import plan_retrieval


class ValidatableCase(Protocol):
    """The minimal shape validation needs from a case -- structural, not
    ``eval.cases.EvalCase`` itself (this package has no dependency on
    ``atlas.eval``).
    """

    id: str
    subject: str
    question: str
    difficulty: str | None
    provenance: CaseProvenance | None
    retrieval_label: RetrievalLabel | None


@dataclass(frozen=True)
class ValidationIssue:
    case_id: str
    kind: str
    detail: str


@dataclass(frozen=True)
class ValidationReport:
    total_cases: int
    issues: tuple[ValidationIssue, ...]

    @property
    def passed(self) -> bool:
        return not self.issues


def _validate_corpus_derived(
    case: ValidatableCase, kb: KnowledgeBase, provenance: CaseProvenance,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    all_ids: set[str] = set(provenance.supporting_evidence_ids)
    label = case.retrieval_label
    if label is not None:
        all_ids |= set(label.relevant_evidence_ids)

    metadata = kb.get_many(sorted(all_ids)) if all_ids else {}
    for evidence_id in sorted(all_ids - set(metadata)):
        issues.append(ValidationIssue(
            case.id, "missing_evidence",
            f"evidence_id {evidence_id!r} does not resolve in {case.subject}'s KnowledgeBase",
        ))

    if label is not None and label.relevant_kinds:
        for evidence_id in label.relevant_evidence_ids:
            doc = metadata.get(evidence_id)
            if doc is not None and doc.kind not in label.relevant_kinds:
                issues.append(ValidationIssue(
                    case.id, "kind_mismatch",
                    f"evidence_id {evidence_id!r} has kind {doc.kind!r}, "
                    f"not in declared relevant_kinds {label.relevant_kinds}",
                ))
    return issues


def _validate_negative(case: ValidatableCase, kb: KnowledgeBase, repo_root: Path) -> list[ValidationIssue]:
    profile_path = repo_root / case.subject / "profile.json"
    if not profile_path.exists():
        return [ValidationIssue(
            case.id, "missing_profile", f"no profile.json for subject {case.subject!r}",
        )]
    profile = CompanyStore(profile_path, case.subject).load()
    subject_ref = SubjectRef(subject_id=case.subject, display=case.subject)
    plan = plan_retrieval(case.question)
    build_result = build_context_with_diagnostics(
        profile, subject_ref, kb=kb, question=case.question, plan=plan,
    )
    if build_result.retrieval is not None and build_result.retrieval.matches:
        return [ValidationIssue(
            case.id, "negative_not_absent",
            f"question retrieved {len(build_result.retrieval.matches)} match(es); "
            "no longer verifiably absent",
        )]
    return []


def validate_cases(cases: Sequence[ValidatableCase], repo_root: Path) -> ValidationReport:
    """Machine-check every case's provenance claim. See module docstring for
    what "checked" means per origin.
    """
    issues: list[ValidationIssue] = []
    kb_cache: dict[str, KnowledgeBase | None] = {}

    def _kb_for(subject: str) -> KnowledgeBase | None:
        if subject not in kb_cache:
            root = repo_root / subject
            kb_cache[subject] = KnowledgeBase(root) if (root / "knowledge.db").exists() else None
        return kb_cache[subject]

    for case in cases:
        if case.difficulty == "difficult":
            if case.provenance is None:
                issues.append(ValidationIssue(
                    case.id, "missing_provenance", "difficult case has no provenance",
                ))
                continue
            if case.provenance.origin != "corpus_validated_negative" and case.retrieval_label is None:
                issues.append(ValidationIssue(
                    case.id, "missing_label",
                    "non-negative difficult case has no retrieval_label",
                ))

        provenance = case.provenance
        if provenance is None:
            continue

        kb = _kb_for(case.subject)
        if kb is None:
            issues.append(ValidationIssue(
                case.id, "missing_kb", f"no KnowledgeBase for subject {case.subject!r}",
            ))
            continue

        if provenance.origin == "corpus_derived":
            issues.extend(_validate_corpus_derived(case, kb, provenance))
        elif provenance.origin == "corpus_validated_negative":
            issues.extend(_validate_negative(case, kb, repo_root))

    return ValidationReport(total_cases=len(cases), issues=tuple(issues))
