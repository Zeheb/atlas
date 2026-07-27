"""Retrieval quality metrics from gold labels (M1.8.5 commit 7, ADR-0005).

Pure functions over a case's ``RetrievalCaseMetrics.selected`` (already
persisted by M1.8 -- see ``eval/report.py``) and its ``RetrievalLabel`` (the
gold target -- see ``benchmark/provenance.py``). Only meaningful for a
labelled case; an unlabelled case (most cases -- gold labels are opt-in, per
ADR-0005) scores ``None`` everywhere, not zero, since there is nothing to
score against.

This is what upgrades M1.8's own "the selection changed"
(``comparison.ranking_change``, which needs no label) into "the selection
got better." No new hard threshold enters ``recommendation.py``'s Phase-1
advisory verdict here -- these deltas are reported alongside it for history,
not enforced; promotion is Phase 2 (ADR-0004), once there is data.

``RetrievalQualityScore`` is defined in ``eval/report.py``, not here, purely
to avoid a cycle: this module needs ``RetrievalCaseMetrics`` from that one.
"""

from __future__ import annotations

from atlas.benchmark.provenance import RetrievalLabel
from atlas.eval.report import RetrievalCaseMetrics, RetrievalQualityScore


def score_retrieval_quality(
    metrics: RetrievalCaseMetrics | None,
    label: RetrievalLabel | None,
) -> RetrievalQualityScore | None:
    """Score one case's retrieval against its gold label.

    Returns ``None`` when either side is missing (no retrieval happened, or
    the case has no gold label -- most don't). ``precision_at_k``/
    ``recall_at_k``/``mrr`` are further ``None`` when the label declares
    only ``relevant_kinds`` (no ``relevant_evidence_ids``): this module has
    no doc_id-to-kind linkage (only aggregate ``doc_type_counts`` is
    persisted, not per-document kind), so id-level precision/recall/MRR
    cannot be computed against a kinds-only label -- only
    ``forbidden_retrieved`` (itself an id set) always can.
    """
    if metrics is None or label is None:
        return None

    selected_ids = [doc_id for doc_id, _char_offset, _score in metrics.selected]
    relevant_ids = set(label.relevant_evidence_ids)
    forbidden_ids = set(label.must_not_retrieve)
    forbidden_retrieved = tuple(
        doc_id for doc_id in selected_ids if doc_id in forbidden_ids
    )

    if not relevant_ids:
        return RetrievalQualityScore(
            precision_at_k=None,
            recall_at_k=None,
            mrr=None,
            forbidden_retrieved=forbidden_retrieved,
        )

    if not selected_ids:
        # Nothing retrieved but relevant docs were expected: zero, not None
        # -- there IS ground truth to score against, retrieval simply missed it.
        return RetrievalQualityScore(
            precision_at_k=0.0,
            recall_at_k=0.0,
            mrr=0.0,
            forbidden_retrieved=forbidden_retrieved,
        )

    hit_count = sum(1 for doc_id in selected_ids if doc_id in relevant_ids)
    precision = round(hit_count / len(selected_ids), 3)
    recall = round(len(relevant_ids & set(selected_ids)) / len(relevant_ids), 3)

    mrr = 0.0
    for rank, doc_id in enumerate(selected_ids, start=1):
        if doc_id in relevant_ids:
            mrr = round(1.0 / rank, 3)
            break

    return RetrievalQualityScore(
        precision_at_k=precision,
        recall_at_k=recall,
        mrr=mrr,
        forbidden_retrieved=forbidden_retrieved,
    )
