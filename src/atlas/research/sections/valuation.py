"""Valuation — is this cheap or expensive?

Every real investment memo answers this question. Atlas categorically
cannot: there is no market price, share count-to-market-cap link, or
trading multiple anywhere in Evidence, Fact, or CompanyProfile — Atlas's
ontology is built entirely from regulatory filings and corporate
disclosures, none of which carry a live or historical market price.

This section exists to say so directly, not to leave the question
silently unanswered. A reader who doesn't see a Valuation section at all
might reasonably assume Atlas forgot to ask; seeing this section states
plainly what would be needed to close the gap, rather than pretending
fundamentals alone answer a pricing question.
"""
from __future__ import annotations

from atlas.acquisition.repository import Repository
from atlas.company.model import CompanyProfile
from atlas.research.model import ReportSection


def build(profile: CompanyProfile, repo: Repository | None, ticker: str) -> ReportSection:
    return ReportSection(
        key="valuation",
        title="Valuation",
        notes=[
            "Out of scope for this report: Atlas has no market price, share count, or trading "
            "multiple data anywhere in its ontology — only regulatory filings and corporate "
            "disclosures. Answering \"is this cheap or expensive\" requires a market data feed "
            "this system does not have. Everything else in this report is fundamental evidence; "
            "pairing it with a price is left to the reader.",
        ],
    )
