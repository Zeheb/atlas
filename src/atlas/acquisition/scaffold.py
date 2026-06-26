import json
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

from atlas.acquisition.catalog import RepositoryCatalog
from atlas.acquisition.models import CompanyRecord
from atlas.app import Atlas

_SUBDIRECTORIES: tuple[str, ...] = (
    "acquisitions",
    "annual_reports",
    "financial_results",
    "earnings_transcripts",
    "investor_presentations",
    "logs",
)


class RepositoryAlreadyExistsError(Exception):
    """Raised when build_repository is called on an already-initialised repository."""

    def __init__(self, path: Path) -> None:
        self.path = path
        super().__init__(str(path))


def build_repository(atlas: Atlas, ticker: str) -> Path:
    """Create the on-disk repository structure for a company.

    Returns the path to the repository root on success.
    Raises RepositoryAlreadyExistsError if company.json is already present.
    The ticker is normalised to uppercase before any path is created.
    """
    ticker = ticker.upper()
    root = atlas.settings.repository_base_path / ticker
    company_file = root / "company.json"

    if company_file.exists():
        raise RepositoryAlreadyExistsError(root)

    root.mkdir(parents=True, exist_ok=True)
    for name in _SUBDIRECTORIES:
        (root / name).mkdir(exist_ok=True)

    record = CompanyRecord(
        id=CompanyRecord.new_id(),
        ticker=ticker,
        created_at=datetime.now(timezone.utc),
        atlas_version=version("atlas"),
    )
    company_file.write_text(json.dumps(record.to_dict(), indent=2), encoding="utf-8")

    RepositoryCatalog(root).save()

    return root
