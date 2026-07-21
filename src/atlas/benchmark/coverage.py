"""CoverageAnalyzer: the single implementation for benchmark coverage
analysis (M1.8.5 commit 3, ADR-0005).

Two surfaces share this implementation and never duplicate it: the
``atlas eval coverage`` CLI command (static analysis of the benchmark
itself — no LLM, no retrieval run) and the ``CoverageSnapshot`` embedded in
every ``atlas eval run`` report (``eval/report.py``). Both call
``analyze_suite``/``analyze`` directly; neither reimplements it.

Coverage measures the BENCHMARK, not any run's output — "does the suite
exercise every planner intent, rule, and retrieval scenario," not "how did
retrieval perform this time" (that question belongs to
``eval/comparison.py`` and ``eval/retrieval_quality.py``). Adds no retrieval
heuristics; changes no reasoning/retrieval behavior. Read-only against
``reasoning.planner.plan_retrieval`` (the REAL planner — coverage measures
what it actually does, never a reimplementation that could drift) and, for
corpus coverage, against a subject's real ``KnowledgeBase``.

Deliberately depends only on ``reasoning`` (planner, text) and ``knowledge``
(KnowledgeBase) — NOT on ``atlas.eval``. ``analyze_suite`` takes anything
shaped like ``CaseLike`` (a Protocol), so ``eval.cases.EvalCase`` satisfies it
structurally without this module importing ``eval`` at all. This keeps the
dependency direction the same one ``atlas.eval`` already has on this package,
never the reverse.
"""
from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, get_args

from atlas.benchmark.taxonomy import ALL_SCENARIO_IDS
from atlas.reasoning.plan import RetrievalIntent
from atlas.reasoning.planner import ALL_RULE_IDS, plan_retrieval
from atlas.reasoning.text import keywords as _keywords

_ALL_INTENTS: frozenset[str] = frozenset(get_args(RetrievalIntent))

# Every dimension's minimum-cases-per-slot floor (ADR-0005 acceptance
# criteria 1-3): below this, a slot counts as "underrepresented" even though
# it isn't literally empty.
_MIN_CASES_PER_SLOT = 3

# Question-similarity threshold above which two cases are flagged as
# near-duplicates during authoring (a benchmark-quality signal, not a
# correctness check).
_REDUNDANCY_THRESHOLD = 0.8


class CaseLike(Protocol):
    """The minimal shape ``analyze_suite`` needs from a case. Structural
    (PEP 544) — ``eval.cases.EvalCase`` satisfies this without either module
    importing the other's concrete type.
    """

    id: str
    category: str
    question: str
    subject: str
    scenario: str | None
    difficulty: str | None


@dataclass(frozen=True)
class DimensionCoverage:
    """Coverage of one categorical dimension (intent, rule, or scenario)
    against its full declared vocabulary.

    ``entropy`` is normalized Shannon entropy of the OBSERVED distribution
    (categories with count > 0), divided by log2(vocabulary size) — so it is
    0 when every case lands in one slot, and approaches 1 only when cases are
    spread evenly across the FULL declared vocabulary. A vocabulary with
    unused slots is thus penalized even though entropy is computed over the
    nonzero categories only; this is deliberate, not an approximation error.
    """

    counts: tuple[tuple[str, int], ...]
    missing: tuple[str, ...]
    underrepresented: tuple[str, ...]
    entropy: float


@dataclass(frozen=True)
class RedundancyReport:
    near_duplicate_pairs: tuple[tuple[str, str, float], ...]
    threshold: float


@dataclass(frozen=True)
class SuiteCoverage:
    """Static analysis of the case suite itself — no I/O beyond running the
    real planner over each question's text.
    """

    total_cases: int
    intent: DimensionCoverage
    rule: DimensionCoverage
    scenario: DimensionCoverage
    subject_counts: tuple[tuple[str, int], ...]
    difficulty_counts: tuple[tuple[str, int], ...]
    general_intent_share: float
    max_subject_share: float
    redundancy: RedundancyReport


@dataclass(frozen=True)
class CorpusCoverage:
    """Which EvidenceKinds are actually retrievable per subject (evidence
    backing profile claims, NOT the raw catalog — the same candidate-pool
    scope ``build_context``'s question-conditioned merge uses), and which
    doc-type kinds the planner's boost table declares but no subject can
    ever retrieve (structurally dead, not merely untested).
    """

    retrievable_kinds_by_subject: tuple[tuple[str, tuple[str, ...]], ...]
    structurally_dead_doc_types: tuple[str, ...]


@dataclass(frozen=True)
class BenchmarkCoverage:
    suite: SuiteCoverage
    corpus: CorpusCoverage | None = None


def _normalized_entropy(counts: dict[str, int], vocab_size: int) -> float:
    total = sum(counts.values())
    if total == 0 or vocab_size <= 1:
        return 0.0
    probs = [c / total for c in counts.values() if c > 0]
    h = -sum(p * math.log2(p) for p in probs)
    max_h = math.log2(vocab_size)
    return round(h / max_h, 3) if max_h > 0 else 0.0


def _dimension_coverage(
    counts: Counter[str], vocab: frozenset[str], floor: int = _MIN_CASES_PER_SLOT,
) -> DimensionCoverage:
    full = {v: counts.get(v, 0) for v in vocab}
    return DimensionCoverage(
        counts=tuple(sorted(full.items())),
        missing=tuple(sorted(v for v, c in full.items() if c == 0)),
        underrepresented=tuple(sorted(v for v, c in full.items() if 0 < c < floor)),
        entropy=_normalized_entropy(dict(counts), len(vocab)),
    )


def _redundancy(cases: Sequence[CaseLike]) -> RedundancyReport:
    """Pairwise Jaccard over each question's keyword set (the SAME tokenizer
    retrieve_passages/retrieve_with_plan use internally, via reasoning.text
    -- not a separate similarity notion invented for this module).
    """
    term_sets: dict[str, frozenset[str]] = {}
    for c in cases:
        words, numbers = _keywords(c.question)
        term_sets[c.id] = frozenset(words | numbers)

    ids = sorted(term_sets)
    pairs: list[tuple[str, str, float]] = []
    for i, a in enumerate(ids):
        for b in ids[i + 1 :]:
            sa, sb = term_sets[a], term_sets[b]
            union = sa | sb
            if not union:
                continue
            jaccard = len(sa & sb) / len(union)
            if jaccard > _REDUNDANCY_THRESHOLD:
                pairs.append((a, b, round(jaccard, 3)))
    return RedundancyReport(near_duplicate_pairs=tuple(pairs), threshold=_REDUNDANCY_THRESHOLD)


def analyze_suite(cases: Sequence[CaseLike]) -> SuiteCoverage:
    """Pure, no I/O beyond ``plan_retrieval`` (itself pure — see
    ``planner.py``'s own no-KB/LLM/network import boundary).
    """
    intent_counts: Counter[str] = Counter()
    rule_counts: Counter[str] = Counter()
    scenario_counts: Counter[str] = Counter()
    subject_counts: Counter[str] = Counter()
    difficulty_counts: Counter[str] = Counter()

    for c in cases:
        plan = plan_retrieval(c.question)
        intent_counts[plan.intent] += 1
        for decision in plan.decisions:
            rule_counts[decision.rule] += 1
        if c.scenario is not None:
            scenario_counts[c.scenario] += 1
        subject_counts[c.subject] += 1
        if c.difficulty is not None:
            difficulty_counts[c.difficulty] += 1

    total = len(cases)
    general_share = round(intent_counts.get("general", 0) / total, 3) if total else 0.0
    max_subject_share = (
        round(max(subject_counts.values()) / total, 3) if total and subject_counts else 0.0
    )

    return SuiteCoverage(
        total_cases=total,
        intent=_dimension_coverage(intent_counts, _ALL_INTENTS),
        rule=_dimension_coverage(rule_counts, ALL_RULE_IDS),
        scenario=_dimension_coverage(scenario_counts, ALL_SCENARIO_IDS),
        subject_counts=tuple(sorted(subject_counts.items())),
        difficulty_counts=tuple(sorted(difficulty_counts.items())),
        general_intent_share=general_share,
        max_subject_share=max_subject_share,
        redundancy=_redundancy(cases),
    )


def analyze_corpus(repo_root: Path, subjects: Sequence[str]) -> CorpusCoverage:
    """Which doc kinds are actually retrievable per subject, and which
    planner-declared doc-type kinds are retrievable nowhere.

    Reads ``_INTENT_DOC_TYPES`` directly from ``planner.py`` (an existing
    module-private symbol, read-only — this function does not modify
    ``planner.py`` in any way, keeping that file's diff against main empty).
    """
    from atlas.company.store import CompanyStore
    from atlas.knowledge.base import KnowledgeBase
    from atlas.reasoning.context import build_context
    from atlas.reasoning.contracts import SubjectRef
    from atlas.reasoning.planner import _INTENT_DOC_TYPES

    declared_kinds = frozenset(
        kind for entries in _INTENT_DOC_TYPES.values() for kind, _weight in entries
    )

    retrievable_by_subject: dict[str, frozenset[str]] = {}
    for subject in subjects:
        root = repo_root / subject
        profile_path = root / "profile.json"
        if not profile_path.exists() or not (root / "knowledge.db").exists():
            retrievable_by_subject[subject] = frozenset()
            continue
        profile = CompanyStore(profile_path, subject).load()
        kb = KnowledgeBase(root)
        ctx = build_context(profile, SubjectRef(subject_id=subject, display=subject))
        evidence_ids = sorted({eid for claim in ctx.claims for eid in claim.evidence_ids})
        if not evidence_ids:
            retrievable_by_subject[subject] = frozenset()
            continue
        metadata = kb.get_many(evidence_ids)
        retrievable_by_subject[subject] = frozenset(doc.kind for doc in metadata.values())

    all_retrievable: frozenset[str] = frozenset().union(*retrievable_by_subject.values()) \
        if retrievable_by_subject else frozenset()

    return CorpusCoverage(
        retrievable_kinds_by_subject=tuple(
            (subject, tuple(sorted(kinds))) for subject, kinds in sorted(retrievable_by_subject.items())
        ),
        structurally_dead_doc_types=tuple(sorted(declared_kinds - all_retrievable)),
    )


def analyze(
    cases: Sequence[CaseLike], repo_root: Path | None = None, subjects: Sequence[str] = (),
) -> BenchmarkCoverage:
    """Both analyses. ``corpus`` is ``None`` when no repo_root/subjects are
    given -- suite-only analysis needs neither.
    """
    corpus = analyze_corpus(repo_root, subjects) if repo_root is not None and subjects else None
    return BenchmarkCoverage(suite=analyze_suite(cases), corpus=corpus)
