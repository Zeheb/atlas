import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from atlas.acquisition.acquisitions import AcquisitionReport
from atlas.acquisition.catalog import CatalogEntry, RepositoryCatalog
from atlas.acquisition.connectors.connector import Company, Connector
from atlas.acquisition.downloader import DownloadResult, download_evidence
from atlas.acquisition.profile import DEFAULT_PROFILE, AcquisitionProfile


def run_acquisition(
    repo_root: Path,
    connector: Connector,
    profile: AcquisitionProfile = DEFAULT_PROFILE,
    on_progress: Callable[[str], None] | None = None,
) -> AcquisitionReport:
    """Execute the acquisition workflow for a company repository.

    Steps: load company → discover → profile filter → compare →
           download → update catalog → return report.

    The connector owns all source-specific orchestration (identity resolution,
    endpoint selection, pagination). The workflow owns profile filtering and
    catalog persistence. The caller is responsible for persisting the report
    as an acquisition run record.
    """

    def _noop(_: str) -> None:
        pass

    _emit = on_progress if on_progress is not None else _noop
    started_at = datetime.now(timezone.utc)

    # Load company identity from repository
    company_json = repo_root / "company.json"
    company_data = json.loads(company_json.read_text(encoding="utf-8"))
    company = Company(
        id=company_data["id"],
        ticker=company_data["ticker"],
        exchange_identities=dict(company_data.get("exchange_identities", {})),
    )

    # Step 1 — Discover: connector owns all source-specific orchestration
    _emit(f"Discovering evidence for {company.ticker}...")
    discovery = connector.discover(company)
    all_evidence = discovery.evidence
    _emit(f"  Discovered: {len(all_evidence)} item(s)")
    for w in discovery.warnings:
        count = w.metadata.get("count", "?")
        subcat = w.metadata.get("subcategory", "unknown")
        _emit(f"  Warning: {count} occurrence(s) of unmapped subcategory {subcat!r}")

    # Persist any source identities the connector resolved during discovery
    company_data["exchange_identities"] = company.exchange_identities
    company_json.write_text(json.dumps(company_data, indent=2), encoding="utf-8")

    # Step 2 — Apply acquisition profile
    evidence_list = profile.select(all_evidence)
    skipped_by_profile = len(all_evidence) - len(evidence_list)
    _emit(
        f"  Profile '{profile.name}': {len(evidence_list)} selected"
        + (f", {skipped_by_profile} outside profile" if skipped_by_profile else "")
    )

    # Step 3 — Compare against catalog
    catalog = RepositoryCatalog(repo_root)
    known = catalog.known_ids()
    missing = [e for e in evidence_list if e.evidence_id not in known]
    already_acquired = len(evidence_list) - len(missing)
    _emit(f"  Already acquired: {already_acquired}  To download: {len(missing)}")

    # Step 4 — Download missing evidence
    results: list[DownloadResult] = []
    for i, ev in enumerate(missing, start=1):
        _emit(f"  [{i:2d}/{len(missing)}] {ev.title}")
        result = download_evidence(ev, repo_root, connector.fetch_bytes)
        if result.succeeded:
            mb = (result.file_size_bytes or 0) / 1_048_576
            _emit(f"        OK ({mb:.1f} MB)")
        else:
            _emit(f"        FAILED: {result.error}")
        results.append(result)

    # Step 5 — Update catalog
    for result in results:
        if result.succeeded and result.local_path is not None:
            catalog.add(CatalogEntry.from_evidence(result.evidence, result.local_path))
    catalog.save()

    return AcquisitionReport(
        ticker=company.ticker,
        company_id=company.id,
        profile=profile.name,
        started_at=started_at,
        completed_at=datetime.now(timezone.utc),
        discovered=len(all_evidence),
        selected=len(evidence_list),
        already_acquired=already_acquired,
        results=results,
        warnings=list(discovery.warnings),
    )
