"""Company-level domain model.

Assembles facts from multiple AnalysisResult objects into structured time-series
and event ledgers for a single company.  Sits one layer above the Analysis layer:
it consumes AnalysisResult objects and organises them by domain.

Design rules
------------
- FinancialSnapshot.facts uses FactKind enum keys (not strings) for type safety.
- Absence of a key means the data was not extracted — never zero.
- All numeric values are in their natural FactUnit (CRORE_INR, PERCENT, etc.).
- Categorical / textual facts (AUDIT_OPINION, RISK_FACTOR) are excluded.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from atlas.analysis.base import FactKind, FactUnit


# ---------------------------------------------------------------------------
# Financial time-series
# ---------------------------------------------------------------------------


@dataclass
class FinancialSnapshot:
    """P&L, balance sheet, and cash flow data for a single (period, basis) pair.

    period:      ISO date string — the period-end date ("2025-03-31").
    period_type: "quarterly" | "annual".
    basis:       "consolidated" | "standalone".
    facts:       FactKind → extracted numeric value in the fact's natural unit.
    sources:     Evidence IDs that contributed facts to this snapshot.
    """

    period: str
    period_type: str
    basis: str
    facts: dict[FactKind, float] = field(default_factory=dict)
    sources: list[str] = field(default_factory=list)


@dataclass
class FinancialTimeSeries:
    """Ordered collection of FinancialSnapshots, sorted ASC by (period, basis)."""

    snapshots: list[FinancialSnapshot] = field(default_factory=list)


# ---------------------------------------------------------------------------
# ESG time-series
# ---------------------------------------------------------------------------


@dataclass
class ESGSnapshot:
    """One fiscal year's sustainability metrics from a BRSR filing.

    period: Fiscal year end ISO date ("2025-03-31").
    """

    period: str
    facts: dict[FactKind, float] = field(default_factory=dict)
    sources: list[str] = field(default_factory=list)


@dataclass
class ESGTimeSeries:
    """Ordered collection of ESGSnapshots, sorted ASC by period."""

    snapshots: list[ESGSnapshot] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Capital event ledger
# ---------------------------------------------------------------------------


@dataclass
class DividendEvent:
    """A single dividend declaration from a board resolution or financial filing."""

    source_date: datetime
    per_share: float                        # RUPEES_PER_SHARE
    dividend_type: str                      # "interim" | "final" | "special"
    record_date: str | None = None          # ISO date
    payment_date: str | None = None         # ISO date
    evidence_id: str = ""


@dataclass
class BuybackEvent:
    """A single buyback program document (announcement, extinguishment, etc.)."""

    source_date: datetime
    sub_type: str                           # "announcement"|"extinguishment"|"schedule"|"unknown"
    amount: float | None = None             # CRORE_INR
    price_per_share: float | None = None    # RUPEES_PER_SHARE
    shares_offered: int | None = None       # max shares targeted
    shares_bought: int | None = None        # shares actually extinguished
    record_date: str | None = None          # ISO date
    evidence_id: str = ""


@dataclass
class AcquisitionEvent:
    """A single M&A or subsidiary formation event."""

    source_date: datetime
    target_name: str
    consideration_type: str | None = None   # "cash" | "share_swap" | "subscription"
    enterprise_value: float | None = None
    enterprise_value_unit: FactUnit | None = None
    stake_pct: float | None = None
    expected_completion: str | None = None  # ISO date
    evidence_id: str = ""


@dataclass
class InvestmentEvent:
    """A subsidiary capital injection or external investment commitment."""

    source_date: datetime
    target_name: str
    amount: float | None = None
    amount_unit: FactUnit | None = None
    evidence_id: str = ""


@dataclass
class CapitalEventLedger:
    """All capital allocation events, each list sorted ASC by source_date."""

    dividends: list[DividendEvent] = field(default_factory=list)
    buybacks: list[BuybackEvent] = field(default_factory=list)
    acquisitions: list[AcquisitionEvent] = field(default_factory=list)
    investments: list[InvestmentEvent] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Credit history
# ---------------------------------------------------------------------------


@dataclass
class CreditRatingEntry:
    """One credit or ESG rating action.

    For debt ratings: one entry per rated instrument per document.
    For ESG ratings: one entry per document (instrument = "ESG").
    """

    source_date: datetime
    agency: str
    instrument: str | None = None           # "Long-term Bank Facilities" | "ESG" | …
    rating: str | None = None               # "AAA" | "A1+" | "73" | …
    outlook: str | None = None              # "stable" | "leader" | …
    action: str | None = None               # "reaffirmed" | "upgraded" | …
    amount: float | None = None             # CRORE_INR — rated ceiling; absent for ESG
    evidence_id: str = ""


@dataclass
class CreditHistory:
    """All credit and ESG rating entries, sorted ASC by source_date."""

    entries: list[CreditRatingEntry] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Ownership time-series
# ---------------------------------------------------------------------------


@dataclass
class OwnershipSnapshot:
    """Shareholding pattern at one quarter-end."""

    period: str                             # ISO date (quarter end)
    facts: dict[FactKind, float] = field(default_factory=dict)
    evidence_id: str = ""


@dataclass
class OwnershipTimeSeries:
    """Ordered collection of OwnershipSnapshots, sorted ASC by period."""

    snapshots: list[OwnershipSnapshot] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Segment time-series
# ---------------------------------------------------------------------------


@dataclass
class SegmentEntry:
    """Revenue and EBIT for one named business segment at one period."""

    period: str
    name: str
    revenue: float | None = None            # CRORE_INR
    ebit: float | None = None               # CRORE_INR
    evidence_id: str = ""


@dataclass
class SegmentTimeSeries:
    """Ordered collection of SegmentEntries, sorted ASC by (period, name)."""

    entries: list[SegmentEntry] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Top-level company profile
# ---------------------------------------------------------------------------


@dataclass
class CompanyProfile:
    """Assembled knowledge graph for a single company.

    Built by builder.build_profile() from a collection of AnalysisResult objects.
    All sub-collections are sorted ASC (oldest first) after construction.
    """

    company_id: str
    financial: FinancialTimeSeries = field(default_factory=FinancialTimeSeries)
    esg: ESGTimeSeries = field(default_factory=ESGTimeSeries)
    capital_events: CapitalEventLedger = field(default_factory=CapitalEventLedger)
    credit_history: CreditHistory = field(default_factory=CreditHistory)
    ownership: OwnershipTimeSeries = field(default_factory=OwnershipTimeSeries)
    segments: SegmentTimeSeries = field(default_factory=SegmentTimeSeries)
