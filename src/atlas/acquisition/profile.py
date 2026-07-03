from typing import Protocol, Sequence, runtime_checkable

from atlas.acquisition.evidence import Evidence, EvidenceKind


@runtime_checkable
class AcquisitionProfile(Protocol):
    """Selects which discovered evidence an acquisition run should download.

    Implementations own the selection logic; the workflow owns scheduling
    and persistence. New profiles (date-range filters, size caps, compound
    rules) can be introduced without touching the workflow.
    """

    @property
    def name(self) -> str: ...

    @property
    def kinds(self) -> frozenset[EvidenceKind]: ...

    def select(self, evidence: Sequence[Evidence]) -> list[Evidence]: ...


class KindFilterProfile:
    """Selects evidence whose kind is in a fixed allowed set."""

    def __init__(self, name: str, kinds: frozenset[EvidenceKind]) -> None:
        self._name = name
        self._kinds = kinds

    @property
    def name(self) -> str:
        return self._name

    @property
    def kinds(self) -> frozenset[EvidenceKind]:
        return self._kinds

    def select(self, evidence: Sequence[Evidence]) -> list[Evidence]:
        return [e for e in evidence if e.kind in self._kinds]


DEFAULT_PROFILE = KindFilterProfile(
    name="default",
    kinds=frozenset(
        {
            EvidenceKind.ANNUAL_REPORT,
            EvidenceKind.FINANCIAL_RESULTS,
            EvidenceKind.EARNINGS_TRANSCRIPT,
            EvidenceKind.INVESTOR_PRESENTATION,
        }
    ),
)

COMPREHENSIVE_PROFILE = KindFilterProfile(
    name="comprehensive",
    kinds=frozenset(
        {
            # Primary research (superset of DEFAULT_PROFILE)
            EvidenceKind.ANNUAL_REPORT,
            EvidenceKind.FINANCIAL_RESULTS,
            EvidenceKind.EARNINGS_TRANSCRIPT,
            EvidenceKind.INVESTOR_PRESENTATION,
            # Governance
            EvidenceKind.BOARD_OUTCOME,
            EvidenceKind.BRSR,
            EvidenceKind.AGM_NOTICE,
            # Corporate actions
            EvidenceKind.DIVIDEND,
            EvidenceKind.BUYBACK,
            EvidenceKind.ACQUISITION,
            # Regulatory
            EvidenceKind.CREDIT_RATING_REPORT,
            EvidenceKind.REGULATORY_FILING,
            EvidenceKind.SHAREHOLDING_PATTERN,
            EvidenceKind.CORPORATE_GOVERNANCE_REPORT,
        }
    ),
)
