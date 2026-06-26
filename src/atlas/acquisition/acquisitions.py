import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from atlas.acquisition.connectors.connector import DiscoveryWarning


@dataclass
class DownloadFailure:
    evidence_id: str
    title: str
    error: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "title": self.title,
            "error": self.error,
        }


@dataclass
class AcquisitionRecord:
    """Summary of one acquisition run — held in memory and persisted to disk."""

    run_id: str
    ticker: str
    company_id: str
    policy_name: str
    started_at: datetime
    completed_at: datetime
    discovered: int
    selected: int
    already_acquired: int
    downloaded: int
    failures: list[DownloadFailure]
    warnings: list[DiscoveryWarning]
    record_path: Path | None = field(default=None, compare=False)

    @staticmethod
    def new_run_id() -> str:
        return uuid.uuid4().hex[:8]

    @property
    def new(self) -> int:
        return self.selected - self.already_acquired

    @property
    def failed(self) -> int:
        return len(self.failures)

    @property
    def duration_seconds(self) -> float:
        return (self.completed_at - self.started_at).total_seconds()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1",
            "run_id": self.run_id,
            "ticker": self.ticker,
            "company_id": self.company_id,
            "policy": self.policy_name,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
            "duration_seconds": round(self.duration_seconds, 3),
            "counts": {
                "discovered": self.discovered,
                "selected": self.selected,
                "already_acquired": self.already_acquired,
                "new": self.new,
                "downloaded": self.downloaded,
                "failed": self.failed,
            },
            "warnings": [
                {
                    "source": w.source.value,
                    "code": w.code,
                    "message": w.message,
                    "metadata": w.metadata,
                }
                for w in self.warnings
            ],
            "failures": [f.to_dict() for f in self.failures],
        }


def save_acquisition_record(record: AcquisitionRecord, repo_root: Path) -> Path:
    """Write the acquisition record to {repo_root}/acquisitions/ and return the path.

    Uses the same atomic write pattern as RepositoryCatalog.
    """
    acq_dir = repo_root / "acquisitions"
    acq_dir.mkdir(parents=True, exist_ok=True)

    ts = record.started_at.strftime("%Y%m%dT%H%M%SZ")
    path = acq_dir / f"{ts}_{record.run_id}.json"

    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(record.to_dict(), indent=2), encoding="utf-8")
    tmp.replace(path)

    return path
