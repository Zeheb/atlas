import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from atlas.acquisition.connectors.connector import DiscoveryWarning
from atlas.acquisition.downloader import DownloadResult

if TYPE_CHECKING:
    from atlas.acquisition.workflow import DocumentOutcome


@dataclass
class AcquisitionReport:
    """Runtime result of one acquisition run — returned by run_acquisition().

    Holds rich objects (DownloadResult, DiscoveryWarning) for direct use by
    callers. Not responsible for serialisation or persistence.

    document_outcomes carries the per-document parse/OCR/classification
    detail the acquisition-hardening sprint made inline — it's what makes
    ocr_rate/classified/reclassified measurable from a single run's report,
    not from a separate audit pass over the finished repository.
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
    document_outcomes: "list[DocumentOutcome]" = field(default_factory=list)

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
    def ocr_used(self) -> int:
        return sum(1 for o in self.document_outcomes if o.ocr_used)

    @property
    def classified(self) -> int:
        return sum(1 for o in self.document_outcomes if o.classification is not None)

    @property
    def reclassified(self) -> int:
        return sum(1 for o in self.document_outcomes if o.classification is not None and o.classification.was_reclassified)

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
    ocr_used: int
    classified: int
    reclassified: int
    warnings: list[dict[str, Any]]
    failures: list[dict[str, Any]]
    reclassifications: list[dict[str, Any]]
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
                "ocr_used": self.ocr_used,
                "classified": self.classified,
                "reclassified": self.reclassified,
            },
            "warnings": self.warnings,
            "failures": self.failures,
            "reclassifications": self.reclassifications,
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
        ocr_used=report.ocr_used,
        classified=report.classified,
        reclassified=report.reclassified,
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
        reclassifications=[
            {
                "evidence_id": o.download.evidence.evidence_id,
                "from_kind": o.classification.original_kind,
                "to_kind": o.classification.resolved_kind,
                "reason": o.classification.reason,
            }
            for o in report.document_outcomes
            if o.classification is not None and o.classification.was_reclassified
        ],
        record_path=path,
    )

    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(run.to_dict(), indent=2), encoding="utf-8")
    tmp.replace(path)

    return run
