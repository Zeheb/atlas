import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass
class CompanyRecord:
    """Persisted identity record for a company, written to company.json."""

    id: str
    ticker: str
    created_at: datetime
    atlas_version: str

    @staticmethod
    def new_id() -> str:
        """Generate a stable, prefixed identifier for a new company record."""
        return f"cmp_{uuid.uuid4().hex}"

    def to_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "ticker": self.ticker,
            "created_at": self.created_at.isoformat(),
            "atlas_version": self.atlas_version,
        }


@dataclass
class Catalog:
    """Minimal catalog record written to catalog.json.

    The schema is intentionally sparse. Future tasks will extend it
    once the indexing requirements are understood.
    """

    schema_version: str = "1"

    def to_dict(self) -> dict[str, str]:
        return {"schema_version": self.schema_version}
