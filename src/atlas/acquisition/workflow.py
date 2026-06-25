import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from atlas.acquisition.catalog import CatalogEntry, RepositoryCatalog
from atlas.acquisition.connectors.connector import Company, Connector, DiscoveryWarning
from atlas.acquisition.downloader import DownloadResult, download_evidence
from atlas.acquisition.profile import AcquisitionProfile, kinds_for_profile


@dataclass
class AcquisitionReport:
    ticker: str
    company_id: str
    profile: AcquisitionProfile
    started_at: datetime
    completed_at: datetime
    discovered: int  # total evidence returned by the connector
    profile_selected: int  # evidence matching the acquisition profile
    already_acquired: int  # already present in the catalog (of profile_selected)
    results: list[DownloadResult] = field(default_factory=list)
    warnings: list[DiscoveryWarning] = field(default_factory=list)

    @property
    def succeeded(self) -> int:
        return sum(1 for r in self.results if r.succeeded)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if not r.succeeded)

    @property
    def duration_seconds(self) -> float:
        return (self.completed_at - self.started_at).total_seconds()


def run_acquisition(
    repo_root: Path,
    connector: Connector,
    profile: AcquisitionProfile = AcquisitionProfile.DEFAULT,
    on_progress: Callable[[str], None] | None = None,
) -> AcquisitionReport:
    """Execute the acquisition workflow for a company repository.

    Steps: load company → discover → filter by profile → compare →
           download → update catalog → report.

    The connector owns all source-specific orchestration (identity resolution,
    endpoint selection, pagination). The workflow owns policy (profile filtering)
    and persistence (catalog, company identity cache).
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

    # Step 2 — Apply acquisition profile (workflow policy)
    allowed_kinds = kinds_for_profile(profile)
    evidence_list = [e for e in all_evidence if e.kind in allowed_kinds]
    skipped = len(all_evidence) - len(evidence_list)
    _emit(
        f"  Profile '{profile.value}': {len(evidence_list)} selected"
        + (f", {skipped} skipped" if skipped else "")
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
        profile=profile,
        started_at=started_at,
        completed_at=datetime.now(timezone.utc),
        discovered=len(all_evidence),
        profile_selected=len(evidence_list),
        already_acquired=already_acquired,
        results=results,
        warnings=discovery.warnings,
    )
