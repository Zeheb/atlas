import enum
from dataclasses import dataclass
from datetime import datetime


class EvidenceSource(enum.Enum):
    BSE = "BSE"
    NSE = "NSE"
    MCA = "MCA"


class EvidenceKind(enum.Enum):
    # Primary research documents (DEFAULT acquisition profile)
    ANNUAL_REPORT = "annual_report"
    FINANCIAL_RESULTS = "financial_results"
    EARNINGS_TRANSCRIPT = "earnings_transcript"
    INVESTOR_PRESENTATION = "investor_presentation"
    # Corporate actions and governance
    DIVIDEND = "dividend"
    BUYBACK = "buyback"
    ACQUISITION = "acquisition"
    AGM_NOTICE = "agm_notice"
    BOARD_OUTCOME = "board_outcome"
    BRSR = "brsr"
    # Other document types
    CREDIT_RATING_REPORT = "credit_rating_report"
    REGULATORY_FILING = "regulatory_filing"
    SHAREHOLDING_PATTERN = "shareholding_pattern"
    CORPORATE_GOVERNANCE_REPORT = "corporate_governance_report"
    RESEARCH_REPORT = "research_report"
    NEWS = "news"
    DISCUSSION = "discussion"
    OTHER = "other"


@dataclass
class Evidence:
    """A unit of evidence Atlas has collected about a company.

    Source-agnostic: the same type represents exchange filings, transcripts,
    credit ratings, news, and any future collection target. Origin and kind
    are expressed through enums, not through type hierarchy.
    """

    evidence_id: str
    company_id: str
    source: EvidenceSource
    kind: EvidenceKind
    title: str
    source_date: datetime
    document_url: str | None
    file_size_bytes: int | None
    file_extension: str = "pdf"
