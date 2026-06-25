from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from atlas.acquisition.evidence import Evidence, EvidenceKind

_KIND_TO_SUBDIR: dict[EvidenceKind, str] = {
    EvidenceKind.ANNUAL_REPORT: "annual_reports",
    EvidenceKind.FINANCIAL_RESULTS: "financial_results",
    EvidenceKind.EARNINGS_TRANSCRIPT: "earnings_transcripts",
    EvidenceKind.INVESTOR_PRESENTATION: "investor_presentations",
    EvidenceKind.CREDIT_RATING_REPORT: "credit_ratings",
    EvidenceKind.BRSR: "brsr",
    EvidenceKind.AGM_NOTICE: "agm_notices",
    EvidenceKind.BOARD_OUTCOME: "board_outcomes",
    EvidenceKind.DIVIDEND: "corporate_actions",
    EvidenceKind.BUYBACK: "corporate_actions",
    EvidenceKind.ACQUISITION: "corporate_actions",
    EvidenceKind.REGULATORY_FILING: "regulatory_filings",
    EvidenceKind.NEWS: "press_releases",
}

_DEFAULT_SUBDIR = "other"


@dataclass
class DownloadResult:
    evidence: Evidence
    local_path: str | None
    file_size_bytes: int | None
    error: str | None

    @property
    def succeeded(self) -> bool:
        return self.error is None


def _subdir_for(kind: EvidenceKind) -> str:
    return _KIND_TO_SUBDIR.get(kind, _DEFAULT_SUBDIR)


def download_evidence(
    evidence: Evidence,
    repo_root: Path,
    fetch: Callable[[str], bytes],
) -> DownloadResult:
    """Download one Evidence document and save to the repository.

    `fetch` accepts a URL and returns raw bytes. Any exception from `fetch`
    or from disk I/O is caught and surfaced as a failed DownloadResult.
    The target subdirectory is created on demand.
    """
    if not evidence.document_url:
        return DownloadResult(
            evidence=evidence,
            local_path=None,
            file_size_bytes=None,
            error="no document URL",
        )

    subdir = _subdir_for(evidence.kind)
    filename = f"{evidence.evidence_id}.pdf"
    relative_path = f"{subdir}/{filename}"
    destination = repo_root / subdir / filename

    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        content = fetch(evidence.document_url)
        destination.write_bytes(content)
        return DownloadResult(
            evidence=evidence,
            local_path=relative_path,
            file_size_bytes=len(content),
            error=None,
        )
    except Exception as exc:  # noqa: BLE001
        return DownloadResult(
            evidence=evidence,
            local_path=None,
            file_size_bytes=None,
            error=str(exc),
        )
