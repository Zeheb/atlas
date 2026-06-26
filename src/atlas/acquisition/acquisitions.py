import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from atlas.acquisition.connectors.connector import DiscoveryWarning
from atlas.acquisition.downloader import DownloadResult

if TYPE_CHECKING:
    pass


@dataclass
class AcquisitionReport:
    """Runtime result of one acquisition run — returned by run_acquisition().

    Holds rich objects (DownloadResult, DiscoveryWarning) for direct use by
    callers. Not responsible for serialisation or persistence.
    """

    ticker: str
    company_id: str
    profile: str
    started_at: datetime
    completed_at: datetime
    discovered: int
    selected: int
    already_acquired: int
    results: list[DownloadResult]
    warnings: list[DiscoveryWarning]

    @property
    def new(self) -> int:
        return self.selected - self.already_acquired

    @property
    def downloaded(self) -> int:
        return sum(1 for r in self.results if r.succeeded)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if not r.succeeded)

    @property
    def duration_seconds(self) -> float:
        return (self.completed_at - self.started_at).total_seconds()


@dataclass
class AcquisitionRun:
    """Persisted record of one acquisition run — written to acquisitions/.

    Holds only serialisable values. Created from an AcquisitionReport by
    save_acquisition_run(); callers are responsible for invoking that step.
    """

    run_id: str
    ticker: str
    company_id: str
    profile: str
    started_at: datetime
    completed_at: datetime
    discovered: int
    selected: int
    already_acquired: int
    downloaded: int
    failed: int
    warnings: list[dict[str, Any]]
    failures: list[dict[str, Any]]
    record_path: Path

    @property
    def new(self) -> int:
        return self.selected - self.already_acquired

    @property
    def duration_seconds(self) -> float:
        return (self.completed_at - self.started_at).total_seconds()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1",
            "run_id": self.run_id,
            "ticker": self.ticker,
            "company_id": self.company_id,
            "profile": self.profile,
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
            "warnings": self.warnings,
            "failures": self.failures,
        }


def save_acquisition_run(report: AcquisitionReport, repo_root: Path) -> AcquisitionRun:
    """Persist an AcquisitionReport as a timestamped JSON file under acquisitions/.

    Uses the same atomic write pattern as RepositoryCatalog.
    Returns the AcquisitionRun with record_path set.
    """
    run_id = uuid.uuid4().hex[:8]
    acq_dir = repo_root / "acquisitions"
    acq_dir.mkdir(parents=True, exist_ok=True)

    ts = report.started_at.strftime("%Y%m%dT%H%M%SZ")
    path = acq_dir / f"{ts}_{run_id}.json"

    run = AcquisitionRun(
        run_id=run_id,
        ticker=report.ticker,
        company_id=report.company_id,
        profile=report.profile,
        started_at=report.started_at,
        completed_at=report.completed_at,
        discovered=report.discovered,
        selected=report.selected,
        already_acquired=report.already_acquired,
        downloaded=report.downloaded,
        failed=report.failed,
        warnings=[
            {
                "source": w.source.value,
                "code": w.code,
                "message": w.message,
                "metadata": w.metadata,
            }
            for w in report.warnings
        ],
        failures=[
            {
                "evidence_id": r.evidence.evidence_id,
                "title": r.evidence.title,
                "error": r.error or "",
            }
            for r in report.results
            if not r.succeeded
        ],
        record_path=path,
    )

    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(run.to_dict(), indent=2), encoding="utf-8")
    tmp.replace(path)

    return run
