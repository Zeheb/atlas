from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from atlas.acquisition.evidence import Evidence, EvidenceSource


@dataclass
class Company:
    """Source-agnostic company identity passed to connectors during discovery.

    A connector may read exchange_identities to find cached source-specific
    identifiers (e.g. BSE scrip code, NSE symbol, MCA CIN), and may write
    back newly resolved identifiers. The workflow persists any mutations to
    company.json after discovery completes.
    """

    id: str
    ticker: str
    exchange_identities: dict[str, Any] = field(default_factory=dict)


@dataclass
class DiscoveryWarning:
    """A structured warning emitted during evidence discovery.

    Carries observability data in machine-readable form until the CLI
    formats it for humans. Keeps the warning inspectable for future
    aggregation, API exposure, or trend detection across runs.
    """

    source: EvidenceSource
    code: str
    message: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DiscoveryResult:
    """The structured result of a connector's discover() call."""

    evidence: list[Evidence]
    warnings: list[DiscoveryWarning] = field(default_factory=list)


@runtime_checkable
class Connector(Protocol):
    """Source-agnostic interface for acquiring company evidence.

    A Connector owns all source-specific orchestration: identity resolution,
    endpoint selection, pagination, and deduplication. It returns every piece
    of evidence it can discover — profile filtering is the workflow's responsibility.
    """

    def discover(self, company: Company) -> DiscoveryResult:
        """Return all evidence available for this company from this source.

        May mutate company.exchange_identities to cache resolved source
        identifiers (e.g. scrip codes, symbols, CIN numbers). The caller is
        responsible for persisting those mutations.
        """
        ...

    def fetch_bytes(self, url: str) -> bytes:
        """Fetch raw bytes from a URL."""
        ...

    def close(self) -> None: ...

    def __enter__(self) -> "Connector": ...

    def __exit__(self, *args: object) -> None: ...
