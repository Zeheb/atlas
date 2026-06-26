import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from atlas.acquisition.acquisitions import (
    AcquisitionRecord,
    DownloadFailure,
    save_acquisition_record,
)
from atlas.acquisition.catalog import CatalogEntry, RepositoryCatalog
from atlas.acquisition.connectors.connector import Company, Connector
from atlas.acquisition.downloader import DownloadResult, download_evidence
from atlas.acquisition.policy import DEFAULT_POLICY, AcquisitionPolicy


def run_acquisition(
    repo_root: Path,
    connector: Connector,
    policy: AcquisitionPolicy = DEFAULT_POLICY,
    on_progress: Callable[[str], None] | None = None,
) -> AcquisitionRecord:
    """Execute the acquisition workflow for a company repository.

    Steps: load company → discover → policy filter → compare →
           download → update catalog → save record → return.

    The connector owns all source-specific orchestration (identity resolution,
    endpoint selection, pagination). The workflow owns policy (selection) and
    persistence (catalog, acquisition record).
    """

    def _noop(_: str) -> None:
        pass

    _emit = on_progress if on_progress is not None else _noop
    run_id = AcquisitionRecord.new_run_id()
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

    # Step 2 — Apply acquisition policy
    evidence_list = policy.select(all_evidence)
    skipped_by_policy = len(all_evidence) - len(evidence_list)
    _emit(
        f"  Policy '{policy.name}': {len(evidence_list)} selected"
        + (f", {skipped_by_policy} outside policy" if skipped_by_policy else "")
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

    # Step 6 — Build and save acquisition record
    record = AcquisitionRecord(
        run_id=run_id,
        ticker=company.ticker,
        company_id=company.id,
        policy_name=policy.name,
        started_at=started_at,
        completed_at=datetime.now(timezone.utc),
        discovered=len(all_evidence),
        selected=len(evidence_list),
        already_acquired=already_acquired,
        downloaded=sum(1 for r in results if r.succeeded),
        failures=[
            DownloadFailure(
                evidence_id=r.evidence.evidence_id,
                title=r.evidence.title,
                error=r.error or "",
            )
            for r in results
            if not r.succeeded
        ],
        warnings=list(discovery.warnings),
    )
    record.record_path = save_acquisition_record(record, repo_root)

    return record
