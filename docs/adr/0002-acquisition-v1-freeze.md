# ADR-0002 — Acquisition Layer V1 Freeze

**Date:** 2026-07-04
**Status:** Accepted

---

## Context

Two prior sprints (the "evidence coverage audit" and the "acquisition-layer
architecture sprint") found and fixed three structural weaknesses in
acquisition: a dead CDN URL silently losing historical annual reports, BSE's
own document classification being trusted too literally, and no
architectural seam for a second exchange. This sprint ("final acquisition
hardening") closes the remaining gaps — classification now runs inline
during acquisition rather than as a standalone repair script, Evidence
metadata is populated wherever it can be determined deterministically, and
connector-independence is verified with real multi-connector integration
tests, not just claimed.

With those closed, the acquisition layer is being formally frozen as V1 so
Atlas's primary development effort can shift to research. This ADR records
what "V1" covers, what it explicitly does not cover, and what must remain
true for future connector work to stay additive rather than architectural.

This freeze operates *inside* the interim model ADR-0001 already
established: the flat `EvidenceKind`/`EvidenceSource` enums, not the
three-layer Category/Kind/Format/Provenance ontology ADR-0001 defers until
Atlas has ingested evidence from a second real acquisition source. Nothing
in this ADR brings that refactor forward — V1 is the interim model, hardened
and production-ready, not a replacement for the frozen design target.

---

## Decision

**Acquisition V1 is complete.** Future acquisition work should add sources
(a real NSE connector, a company-website connector) without touching the
pipeline architecture described below.

### Supported document types

14 `EvidenceKind` values have real, acquired evidence across the three
reference companies (TCS, Tata Steel, SBI): `annual_report`,
`financial_results`, `earnings_transcript`, `investor_presentation`,
`dividend`, `buyback`, `acquisition`, `agm_notice`, `board_outcome`, `brsr`,
`credit_rating_report`, `regulatory_filing`, `shareholding_pattern`,
`corporate_governance_report`. 11 of these have registered analyzers;
`agm_notice`, `dividend`, `regulatory_filing` are cataloged and classified
but have no analyzer yet (by design — they were out of scope for the
analyzer sprints, not a gap in acquisition).

### Supported exchanges

BSE is the only live connector (`BSEConnector`). NSE and MCA exist as
`EvidenceSource` enum values and as a `_default_quality_preference` tiebreak
case in `multi_source.py`, but no NSE or MCA connector is implemented — this
was explicitly out of scope for every sprint so far ("do not implement an
NSE connector yet"). The multi-connector orchestration path (discovery →
`resolve_multi_source` → profile filter → download → classify → catalog) is
proven correct against synthetic and mock multi-connector scenarios (28
tests across `test_multi_source.py` and `test_workflow.py`'s
`TestMultiConnectorOrchestration`), not yet against a second real source,
because none exists.

### Known limitations

- **Pre-2016 `financial_results` filings return 404.** Discovered this
  sprint while validating inline classification live: BSE's corpfiling
  archive (`AttachHis`) does not serve documents using the pre-2016
  company-name-based filename convention (e.g.
  `Tata_Consultancy_Services_Ltd_170413.pdf`), distinct from both filename
  generations the Stage 1 annual-report fix already handles. Same failure
  mode as the original annual-report bug (a dead archive path), but for a
  different kind and an older vintage. Not fixed this sprint — flagged as
  the top item for the next acquisition-adjacent sprint if pre-2016
  financial results become research-relevant.
- **`.zip`-packaged corporate governance reports have no extractor.** One
  Tata Steel entry (`bse-cg-500470-2025_2026-Q3`) is a ZIP archive rather
  than a PDF; `KnowledgeBase` has no ZIP extractor. Affects 1 of 334 Tata
  Steel entries.
- **One stale HTML-shell file predates the download-time validation
  guard.** One TCS entry downloaded before `_looks_like_html_shell()`
  existed still has HTML content on disk; the guard prevents this for every
  download since, but doesn't retroactively fix files acquired earlier.
  Affects 1 of 156 TCS entries.
- **`report_period` is populated for only 3 of 14 kinds** (`annual_report`,
  `shareholding_pattern`, `corporate_governance_report`) — the only ones
  where BSE's discovery API returns a structured period label before any
  parsing happens. For every other kind, period is intentionally left
  `None` at acquisition time and resolved later, at analysis time, via
  `Citation`'s existing lazy CompanyProfile back-link resolution — this is
  not a gap, it's the correct layer for that data given it isn't known any
  earlier.
- **`document_language` detection is a coarse script-ratio heuristic**, not
  real language identification — it distinguishes "predominantly Latin
  script" from "not," which is sufficient to flag an unexpected vernacular
  filing but cannot name which language it is. No vernacular filing has
  been observed in any of the three reference companies to date.

### Quality guarantees

- Every downloaded file is validated against being an HTML error page
  disguised as the expected format before being written to disk
  (`_looks_like_html_shell`) — the same failure mode that silently broke
  annual-report acquisition for years cannot recur undetected for any kind.
- Every successfully parsed document runs through deterministic content
  classification automatically, inline, during acquisition — not as a
  separate pass an operator must remember to run. `AcquisitionReport`
  exposes `classified`/`reclassified`/`ocr_used` as first-class counts on
  every run, not something requiring after-the-fact repository archaeology.
- Cross-source duplicates collapse to exactly one canonical Evidence object
  per real-world filing, matched on `(kind, filing date)` **and** requiring
  every candidate come from a distinct source — two genuine same-day,
  same-kind filings from one connector are never conflated with each other
  (a real bug found and fixed this sprint).
- A SHA-256 checksum is recorded for every downloaded file, giving a
  content-identity signal independent of size/date-based dedup heuristics.
- 2,318 tests pass (0 failures attributable to acquisition-layer code; 2 known
  pre-existing failures in unrelated query-engine tests).

### Architectural invariants

Future connector work must preserve these; violating any of them turns
"add a connector" back into an architecture change:

1. **No behavioral branch on `evidence.source` outside `acquisition/connectors/`.**
   Verified this sprint by grep audit across `acquisition/*.py` (excluding
   `connectors/`), `knowledge/*.py`, `analysis/*.py`, `company/*.py` — zero
   hits. The one BSE-specific conditional that exists
   (`catalog.py`'s bare-NEWSID migration) is a one-time historical-data
   migration, not live pipeline logic, and the one BSE-referencing default
   (`multi_source.py`'s tiebreak) is an overridable default, not a hardcoded
   behavior.
2. **A connector is anything satisfying the `Connector` Protocol** —
   `discover(company) -> DiscoveryResult`, `fetch_bytes(url) -> bytes`,
   `close()`, context manager. No base class, no required inheritance.
3. **Document normalization terminates at `Evidence`.** Every connector's
   parser module (the `bse_parser.py` pattern) is the *only* place that
   reads source-native field names; everything downstream — classifier,
   downloader, catalog, analyzers, CompanyProfile — reads only `Evidence`'s
   own fields.
4. **Deduplication keys on canonical Evidence fields, never a source-native
   identifier.** `resolve_multi_source`'s match key is
   `(evidence.kind.value, evidence.source_date.date())` — fields every
   connector must populate identically regardless of source, not a BSE
   NEWSID or an NSE-native ID.
5. **Adding a connector means writing one parser + one connector class and
   passing it to `additional_connectors`.** No change to `workflow.py`,
   `multi_source.py`, `classifier.py`, `downloader.py`, or `catalog.py` is
   required — proven this sprint by `TestMultiConnectorOrchestration`,
   which exercises this exact path with a synthetic second connector.

---

## Consequences

**Positive:**
- New sources are additive by construction, not by convention — the
  invariants above are enforced by tests, not just documentation.
- Classification and metadata quality no longer degrade over time between
  manual repair passes; they're inline pipeline steps.
- The acquisition layer's quality is now measurable per run
  (`AcquisitionReport.ocr_used/classified/reclassified`), not only
  discoverable via a separate audit script.

**Negative / Trade-offs:**
- The three known limitations above are accepted, not fixed, in this
  freeze — declaring V1 complete means treating them as follow-up work
  rather than blocking issues.
- `report_period` covers only 3 of 14 kinds; a future sprint wanting
  acquisition-time period metadata for `financial_results` or
  `earnings_transcript` will find no structured source for it (BSE's
  discovery API for those kinds carries no period field) and will have to
  continue relying on analysis-time extraction.

**Risks:**
- The BSE archive's pre-2016 404 pattern (discovered this sprint) suggests
  BSE's historical-document serving is not permanently stable at any given
  URL scheme — a future silent breakage of the *current* two-path
  resolution (legacy `/bseplus/` + `AttachHis`) is possible and would only
  be caught by the same download-time HTML-shell guard, not prevented
  outright.
- Every quality guarantee above has been validated against BSE only. The
  invariants are designed to generalize, but "designed to" is not the same
  claim as "validated against a second live source."

---

## Alternatives Considered

| Option | Reason rejected |
|---|---|
| Keep classification as a standalone repair script | Explicitly rejected by this sprint's brief ("no repair scripts, no manual post-processing") — inline classification means quality doesn't silently regress between manual passes. |
| Fix the pre-2016 `financial_results` 404s before freezing | Out of scope for this sprint's brief (metadata completeness, classifier productionization, connector-independence, freeze) — a genuinely separate acquisition-fix sprint, not architecture hardening. Documented as a known limitation instead. |
| Bump `report_period` coverage to every kind via title-text heuristics | Would reintroduce exactly the fragile-heuristic pattern Atlas has deliberately avoided elsewhere (e.g. `Citation` resolving period from CompanyProfile back-links rather than parsing titles). Left `None` where no structured source exists, by design. |
| Implement Connector v2's orchestrator as a separate module from `workflow.py` | The `additional_connectors` parameter accomplishes the same generalization with less new surface area, and it's proven by tests using the exact call path production code will use — no separate module needed until a second real connector exists to justify one. |

---

## References

- [ADR-0001 — Evidence Ontology](0001-evidence-ontology.md) — the frozen
  design target this freeze operates within, not against
- [`src/atlas/acquisition/workflow.py`](../../src/atlas/acquisition/workflow.py) — the pipeline this ADR documents
- [`src/atlas/acquisition/classifier.py`](../../src/atlas/acquisition/classifier.py) — inline content classification
- [`src/atlas/acquisition/multi_source.py`](../../src/atlas/acquisition/multi_source.py) — cross-source deduplication
- [`tests/unit/test_workflow.py`](../../tests/unit/test_workflow.py)'s `TestMultiConnectorOrchestration` — the connector-independence proof
