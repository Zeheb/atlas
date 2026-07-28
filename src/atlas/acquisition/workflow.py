import json
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from atlas.acquisition.acquisitions import AcquisitionReport
from atlas.acquisition.catalog import CatalogEntry, RepositoryCatalog
from atlas.acquisition.classifier import ClassificationResult, classify
from atlas.acquisition.connectors.connector import Company, Connector
from atlas.acquisition.downloader import DownloadResult, download_evidence
from atlas.acquisition.evidence import EvidenceKind
from atlas.acquisition.multi_source import resolve_multi_source
from atlas.acquisition.profile import DEFAULT_PROFILE, AcquisitionProfile
from atlas.knowledge.base import KnowledgeBase


@dataclass
class DocumentOutcome:
    """What happened to one document across the full acquisition pipeline —
    download, parse (incl. OCR fallback), and content classification.

    This is the record that makes the pipeline's quality measurable without
    a separate audit pass: ocr_used and classification are populated inline,
    during acquisition, not backfilled by a repair script afterward.
    """

    download: DownloadResult
    ocr_used: bool = False
    classification: ClassificationResult | None = None


def run_acquisition(
    repo_root: Path,
    connector: Connector,
    profile: AcquisitionProfile = DEFAULT_PROFILE,
    on_progress: Callable[[str], None] | None = None,
    additional_connectors: Sequence[Connector] = (),
    kb: KnowledgeBase | None = None,
) -> AcquisitionReport:
    """Execute the acquisition workflow for a company repository.

    Pipeline: discover (every connector) -> deduplicate across sources ->
    profile filter -> compare against catalog -> download -> validate ->
    parse (OCR falls back automatically inside KnowledgeBase.parse()) ->
    classify -> catalog under the classifier's resolved kind, not the
    source's raw label.

    Classification and OCR happen inline, per document, as part of this one
    call — there is no separate repair pass to remember to run afterward.
    A document whose download or parse fails is still cataloged under its
    connector-assigned kind (there's no parsed text to classify), exactly
    as before this pipeline existed; classification only ever *improves* on
    the connector's label, never blocks on its absence.

    `connector` remains required and positional for backward compatibility
    with every existing caller (a single BSE connector, today). NSE or any
    future source is added via `additional_connectors` — discovery runs
    against every connector supplied, and resolve_multi_source() dedupes
    across all of them uniformly; with only `connector` given (the default),
    this is a proven no-op (see multi_source.py's test suite), so a
    single-connector call behaves exactly as it always has.
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

    # Step 1 — Discover from every connector, and remember which connector
    # found which evidence_id, so the right one is used to fetch its bytes
    # later (a document surviving deduplication is still one of the
    # original Evidence objects a specific connector produced).
    all_connectors = [connector, *additional_connectors]
    discoveries = []
    connector_by_evidence_id: dict[str, Connector] = {}
    for conn in all_connectors:
        _emit(f"Discovering evidence for {company.ticker}...")
        discovery = conn.discover(company)
        discoveries.append(discovery)
        for ev in discovery.evidence:
            connector_by_evidence_id[ev.evidence_id] = conn
        _emit(f"  Discovered: {len(discovery.evidence)} item(s)")
        for w in discovery.warnings:
            count = w.metadata.get("count", "?")
            subcat = w.metadata.get("subcategory", "unknown")
            _emit(
                f"  Warning: {count} occurrence(s) of unmapped subcategory {subcat!r}"
            )

    # Step 2 — Deduplicate across sources (a no-op with one connector)
    merged = resolve_multi_source(discoveries)
    all_evidence = merged.evidence
    dedup_warnings = [
        w for w in merged.warnings if w.code == "duplicate_across_exchanges"
    ]
    if dedup_warnings:
        _emit(
            f"  Deduplication: suppressed {len(dedup_warnings)} cross-source duplicate(s)"
        )

    # Persist any source identities the connector(s) resolved during discovery
    company_data["exchange_identities"] = company.exchange_identities
    company_json.write_text(json.dumps(company_data, indent=2), encoding="utf-8")

    # Step 3 — Apply acquisition profile
    evidence_list = profile.select(all_evidence)
    skipped_by_profile = len(all_evidence) - len(evidence_list)
    _emit(
        f"  Profile '{profile.name}': {len(evidence_list)} selected"
        + (f", {skipped_by_profile} outside profile" if skipped_by_profile else "")
    )

    # Step 4 — Compare against catalog
    catalog = RepositoryCatalog(repo_root)
    known = catalog.known_ids()
    missing = [e for e in evidence_list if e.evidence_id not in known]
    already_acquired = len(evidence_list) - len(missing)
    _emit(f"  Already acquired: {already_acquired}  To download: {len(missing)}")

    # Step 5 — Download, validate, parse (OCR as needed), classify
    kb = kb if kb is not None else KnowledgeBase(repo_root)
    outcomes: list[DocumentOutcome] = []
    for i, ev in enumerate(missing, start=1):
        _emit(f"  [{i:2d}/{len(missing)}] {ev.title}")
        fetch = connector_by_evidence_id.get(ev.evidence_id, connector).fetch_bytes
        dl_result = download_evidence(ev, repo_root, fetch)
        if not dl_result.succeeded:
            _emit(f"        FAILED: {dl_result.error}")
            outcomes.append(DocumentOutcome(download=dl_result))
            continue

        mb = (dl_result.file_size_bytes or 0) / 1_048_576
        _emit(f"        downloaded ({mb:.1f} MB)")

        # download_evidence()'s own invariant: local_path is None only on a
        # failed result (see acquisition/downloader.py), already ruled out above.
        assert dl_result.local_path is not None
        provisional_entry = CatalogEntry.from_evidence(ev, dl_result.local_path)
        parsed = kb.parse(provisional_entry)
        ocr_used = parsed.ocr_attempted
        classification: ClassificationResult | None = None

        if parsed.status == "ok":
            text = kb.get_content(ev.evidence_id) or ""
            classification = classify(ev.kind.value, text, parsed.page_count)
            if classification.was_reclassified:
                _emit(
                    f"        reclassified: {classification.original_kind} -> {classification.resolved_kind}"
                )
                reclassified_entry = replace(
                    provisional_entry, kind=classification.resolved_kind
                )
                kb.parse(
                    reclassified_entry
                )  # keep ParsedDocument.kind in sync with the catalog
                resolved_kind_enum = EvidenceKind(classification.resolved_kind)
                dl_result = replace(
                    dl_result, evidence=replace(ev, kind=resolved_kind_enum)
                )

        outcomes.append(
            DocumentOutcome(
                download=dl_result, ocr_used=ocr_used, classification=classification
            )
        )

    # Step 6 — Update catalog with the (possibly classification-corrected) results
    for outcome in outcomes:
        result = outcome.download
        if result.succeeded and result.local_path is not None:
            catalog.add(
                CatalogEntry.from_evidence(
                    result.evidence, result.local_path, checksum=result.checksum
                )
            )
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
        results=[o.download for o in outcomes],
        warnings=list(merged.warnings),
        document_outcomes=outcomes,
    )
