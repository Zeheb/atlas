"""Analyzer registry — single authoritative dispatch from evidence kind → analyzer.

Usage
-----
    from atlas.analysis.registry import analyze, supported_kinds

    result = analyze(evidence_id, kb)           # kind resolved from KB entry
    print(supported_kinds())                    # list registered kinds

Individual analyzer modules remain importable for focused unit testing.
"""

from __future__ import annotations

from atlas.analysis.base import AnalysisResult
from atlas.knowledge.base import KnowledgeBase

# ---------------------------------------------------------------------------
# Static registry — add a new entry here when a new analyzer is implemented.
# Key: entry.kind value from the catalog / KnowledgeBase.
# Value: the analyze(evidence_id, kb) -> AnalysisResult callable.
# ---------------------------------------------------------------------------

from atlas.analysis.financial_results import analyze as _financial_results
from atlas.analysis.acquisition import analyze as _acquisition
from atlas.analysis.board_outcome import analyze as _board_outcome
from atlas.analysis.buyback import analyze as _buyback
from atlas.analysis.shareholding_pattern import analyze as _shareholding_pattern
from atlas.analysis.credit_rating import analyze as _credit_rating
from atlas.analysis.earnings_transcript import analyze as _earnings_transcript
from atlas.analysis.investor_presentation import analyze as _investor_presentation
from atlas.analysis.agm_notice import analyze as _agm_notice
from atlas.analysis.brsr import analyze as _brsr
from atlas.analysis.annual_report import analyze as _annual_report

_REGISTRY: dict[str, object] = {
    "financial_results": _financial_results,
    "acquisition": _acquisition,
    "board_outcome": _board_outcome,
    "buyback": _buyback,
    "shareholding_pattern": _shareholding_pattern,
    "credit_rating_report": _credit_rating,
    "earnings_transcript": _earnings_transcript,
    "investor_presentation": _investor_presentation,
    "agm_notice": _agm_notice,
    "brsr": _brsr,
    "annual_report": _annual_report,
}


def analyze(evidence_id: str, kb: KnowledgeBase) -> AnalysisResult:
    """Dispatch to the appropriate analyzer based on the document's evidence kind.

    Raises ValueError when the evidence_id is not in the knowledge base or
    when no analyzer is registered for the document's kind.
    """
    entry = kb.get(evidence_id)
    if entry is None:
        raise ValueError(
            f"cannot analyze evidence_id={evidence_id!r}: not in knowledge base"
        )
    kind = entry.kind
    fn = _REGISTRY.get(kind)
    if fn is None:
        raise ValueError(
            f"no analyzer registered for kind={kind!r}; "
            f"supported kinds: {sorted(_REGISTRY)}"
        )
    return fn(evidence_id, kb)  # type: ignore[call-arg]


def supported_kinds() -> list[str]:
    """Return all evidence kinds with registered analyzers, sorted alphabetically."""
    return sorted(_REGISTRY.keys())
