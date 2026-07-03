"""Atlas query engine — deterministic, rule-based investor queries over CompanyProfile."""
from atlas.query.engine import (
    QueryResult,
    TableSection,
    acquisitions,
    capital_allocation,
    credit_ratings,
    leverage,
    ownership,
    revenue,
    risks,
    run_query,
    strategy,
)

__all__ = [
    "QueryResult",
    "TableSection",
    "acquisitions",
    "capital_allocation",
    "credit_ratings",
    "leverage",
    "ownership",
    "revenue",
    "risks",
    "run_query",
    "strategy",
]
