# ADR-0012 — FactKind Ontology Freeze: Formalization and a Narrow Working-Capital Exception

**Date:** 2026-07-27
**Status:** Accepted

---

## Context

The FactKind ontology was declared frozen after the V1 freeze (project memory,
never previously a numbered ADR): *"The ontology is now frozen. New FactKinds
may only be added when a new source document type is implemented."* Read
literally, that condition does not cover this case: M-P3.1 (working-capital
line items — Q2, Q11) needs new FactKinds sourced from `financial_results`, a
document kind the ontology already covers, not a new one.

Six rounds of architecture review preceded this ADR, each independently
re-verifying claims against live repository evidence rather than restated
assertion. That process:

- Confirmed a genuine, evidence-verified reuse opportunity: in the
  **deferred** balance-sheet layout (Tata Steel style), Inventories and Trade
  Receivables are already-computed values inside the existing Cash-extraction
  code path (`_extract_balance_sheet_facts` in `financial_results.py`),
  discarded past the index used for Cash. Verified by running the live code
  against four real Tata Steel `financial_results` filings.
- Found the **direct** layout (TCS style) needs new label regexes — cheap
  pattern-replication of the already-proven `_RE_BS_CASH`-style shape, not a
  new parser or new heuristic.
- Found and resolved a real double-occurrence risk: TCS's real filings report
  a second, non-current "Trade receivables / Billed / Unbilled" block (for
  long-duration contracts) ahead of the current-assets one. Verified directly
  against live TCS `financial_results` text. Resolved by anchoring extraction
  to the position immediately preceding the (reliably single-occurrence,
  current-assets-only) Cash match — the same anchor-to-Cash discipline the
  deferred layout already uses positionally.
- Considered and rejected removing `FINANCIAL_UNBILLED_REVENUE` as a
  single-company convention. Re-checked against the frozen roadmap's own
  text (`grep` confirmed M-P3.1's scope line names "unbilled" explicitly) and
  against the correct precedent — `FINANCIAL_TCV`, an already-accepted
  FactKind explicitly documented as *"IT-services specific — simply will not
  fire elsewhere"* — not the client-concentration-bands precedent (a
  voluntary, arbitrary disclosure format, not a standard accounting category).
  Unbilled revenue (a standard Ind AS 115 contract-asset distinction) is
  structurally analogous to TCV, not to concentration bands.
- Verified the Billed/Unbilled overlap resolves cleanly: `FINANCIAL_TRADE_
  RECEIVABLES` is defined as the Billed sub-line specifically when a split is
  disclosed (the natural result of "extract the value at this label," since
  "Trade receivables" is a bare header with no number of its own when a split
  exists), keeping it additive and non-overlapping with `FINANCIAL_UNBILLED_
  REVENUE`.
- Verified the MSME/non-MSME Trade Payables split — a Schedule III mandatory
  disclosure — directly against real `financial_results` text (not, as an
  earlier evidence-gathering pass mistakenly used, `annual_report` text — a
  different document kind this analyzer never reads). Real wording confirmed:
  *"Total outstanding dues of micro and small enterprises"* / *"...creditors
  other than micro and small enterprises"*.
- Found and confirmed as **pre-existing, unrelated technical debt** (not
  introduced by this milestone): (a) a `basis` defaulting assumption already
  documented for the shipped cash/debt/equity facts, inherited identically by
  the new facts; (b) an `UnboundLocalError` in the existing Cash/Equity/Debt
  extraction when a filing has no `Cash and cash equivalents` line (verified
  reproducing on the original, unmodified code against a real SBI filing,
  independent of any change in this ADR).

---

## Decision

**Formalize the freeze as a real ADR for the first time, and grant it one
narrow, explicitly-scoped exception — not a blanket relaxation.**

New FactKinds: `FINANCIAL_INVENTORIES`, `FINANCIAL_TRADE_RECEIVABLES`,
`FINANCIAL_TRADE_PAYABLES`, `FINANCIAL_UNBILLED_REVENUE`. Current-assets/
current-liabilities only; unit CRORE_INR; absence means not extracted, never
zero, matching every existing balance-sheet fact's convention.

**The exception test — three conditions, all required:**

1. The new FactKind is a genuinely **primary** disclosed fact, not derivable
   from any existing fact.
2. It is sourced from a section of an **already-parsed document kind**,
   extending that analyzer's existing extraction machinery (same file, same
   helper functions, same section-finding) — not a new parser or a new
   document kind.
3. It has passed an **independently verified evidence gate**: real
   extraction demonstrated across every structurally distinct extraction
   path the new fact touches (here: both the direct and deferred balance-
   sheet layouts) — not asserted, executed and checked against real filing
   text.

All four proposed FactKinds satisfy all three conditions, verified above.
This exception does **not** extend automatically to any other candidate
FactKind sourced from an existing document kind — each future case must
independently satisfy all three conditions, most pointedly condition 3. The
general freeze remains otherwise intact: `RISK_FACTOR`/RPT/contingent-
liability totals, evaluated during this same investigation, did **not**
pass condition 3 (narrative disclosure, no clean aggregate found) and remain
outside this exception.

**Plausibility floor.** Each new fact must be strictly positive to be
emitted; a value that is zero, negative, or otherwise fails this floor is
**dropped, not emitted** — never downgraded to a lower confidence and never
emitted with a warning. This matches the established under-emit convention
used throughout this codebase (the entity resolver's conservative merging,
the director-identity extractor's clean-adjacency-only rule): absence over
misattribution.

---

## Consequences

**Positive:**
- Two questions (Q2, Q11) gain the typed inputs they were entirely missing.
- The freeze is now a real, citable ADR rather than an informal memory note,
  with a concrete, reusable three-part test for any future exception request.
- The reuse of already-computed deferred-layout values, and the extension of
  the proven direct-layout pattern, add zero new architectural surface —
  same analyzer, same model, same builder, same store.

**Negative / Trade-offs:**
- Two extraction paths (direct/deferred) must each independently maintain
  correctness for these four facts, doubling the surface a future regression
  could touch, relative to a single unified extraction path.
- `FINANCIAL_UNBILLED_REVENUE` will populate for a minority of companies in
  most corpora (business-model-conditional), matching the accepted
  `FINANCIAL_TCV` precedent.

**Risks:**
- The basis-defaulting assumption (standalone/consolidated) is inherited,
  not introduced, and remains untested for companies reporting both under a
  single balance-sheet region. Documented below as known debt, not fixed
  here — fixing it is a change to the *existing* cash/debt/equity extraction,
  outside this ADR's scope.
- The pre-existing `UnboundLocalError` (Cash-absent filings) is inherited,
  reproduced independently of this change, and left unfixed for the same
  reason — it is a defect in already-shipped code this ADR's scope does not
  touch.

---

## Alternatives Considered

| Option | Reason rejected |
|---|---|
| Blanket amendment: any existing document kind may gain new FactKinds if evidence-verified | Silently lowers the bar for every future milestone able to produce *some* evidence; every prior deviation in this project was narrowly scoped and explicitly reasoned — a blanket rule breaks that pattern |
| Reinterpret "document type" to include a balance-sheet sub-kind | Does not hold up; `financial_results` is unambiguously the same already-implemented document type |
| Recast the four facts as derived, sidestepping the freeze | Not viable — they are primary disclosures, not computable from any existing fact |
| Remove `FINANCIAL_UNBILLED_REVENUE` as a single-company convention | Wrong precedent (client-concentration-bands is a voluntary format; this is a standard Ind AS 115 category); the correct precedent, `FINANCIAL_TCV`, was already accepted on identical grounds; the frozen roadmap names "unbilled" explicitly for this milestone |
| Fix the inherited basis-ambiguity or `UnboundLocalError` as part of this ADR | Both are defects in already-shipped cash/debt/equity extraction, unrelated to the four new FactKinds; fixing them is out of this milestone's scope and would be undisclosed scope creep |

---

## Amendment (M-P3.2)

Three further FactKinds independently satisfy the same three-part test and
are admitted under this exception, not a new one:

- `FINANCIAL_CASH_TAX_PAID` — primary (cash flow statement's own disclosed
  line); extends `_extract_cashflow_facts`, the already-parsed cash-flow
  region `FINANCIAL_OPERATING_CASH_FLOW`/`FINANCIAL_CAPEX` already use;
  evidence-verified at both TCS ("Taxes paid (net of refunds)") and Tata
  Steel ("Income taxes paid", a second real phrasing found and handled).
- `FINANCIAL_INTANGIBLE_ASSETS` — primary; extends
  `_extract_balance_sheet_facts`, the same already-parsed balance-sheet
  region; evidence-verified at TCS's direct layout only. **Condition 3 does
  not hold for the deferred layout** — tested directly against real Tata
  Steel text and no verified positional anchor exists for the non-current-
  assets block (unlike current assets, where Cash's fixed Schedule III
  position already anchors Inventories/Receivables). Deferred-layout
  intangibles are therefore absent, not guessed — the same under-emit floor
  this ADR already established, applied to a new case rather than relaxed.
- `FINANCIAL_GROSS_BLOCK` — primary; extends `annual_report.py`, not
  `financial_results.py` — the fact lives in the AR's financial-highlights
  table, a different already-parsed document kind than the other three, but
  condition 2 ("extends existing extraction machinery") holds at the
  analyzer/primitive level (the same `extract_n_values` helper, already
  shared via `patterns.py`), consistent with this ADR's own reading of that
  condition. Evidence-verified at TCS's highlights-table format only.
  **Condition 3 does not hold for Tata Steel's PP&E movement-schedule
  format** — tested directly: a "last value before the next row label"
  heuristic returned a wrong Total (a value from an adjacent unlabeled row),
  not a graceful failure. Rather than build an unverified header-column-
  counting mechanism, this format is deliberately not attempted — under-emit
  over shipping a heuristic already shown to produce a wrong number.

`FINANCIAL_TRADE_RECEIVABLES`/`FINANCIAL_TRADE_PAYABLES`/
`FINANCIAL_INVENTORIES`/`FINANCIAL_UNBILLED_REVENUE` (the original four) are
unchanged by this amendment. Contingent liabilities and RPT remain outside
this exception, re-confirmed with a properly note-anchored search this
round (narrative disclosure, still no clean aggregate found).

---

## Amendment (M-P3.3)

Two further FactKinds independently satisfy the same three-part test and are
admitted under this exception, not a new one — reversing the "RPT... still no
clean aggregate found" note above now that a clean aggregate has been located:

- `GOVERNANCE_RPT_BALANCE_AMOUNT` — primary (the notes-to-accounts "Loans to
  related parties" line, a period-end STOCK disclosure per Ind AS 24, never
  conflated with a period FLOW); extends `annual_report.py`'s existing
  extraction machinery (same file, same period/provenance conventions as
  `_extract_gross_block`). Evidence-verified at Tata Steel: 9/25 real
  filings, real varying multi-year values (0.0, 4816.15, 8601.65 (x2),
  52.01), including a correctly-handled disclosed-nil year. **Condition 3
  does not hold for TCS's format** — tested directly against the real wider
  table text: an open-ended, not-fully-observed category vocabulary, a
  variable value-count per row, and the same counterparty (Jaguar Land
  Rover) recurring under different categories in the same period, a genuine
  collision risk with no verified category-boundary mechanism. TCS's
  per-counterparty transaction table is therefore **not attempted** —
  under-emit over an untested generic table-row scanner, the same discipline
  already used for deferred-layout intangibles and Tata-Steel-format gross
  block above. `GOVERNANCE_RPT_TRANSACTION_AMOUNT` (the flow-side
  counterpart) and a counterparty FactKind are correspondingly **not added**
  in this milestone.
- `GOVERNANCE_RPT_CATEGORY` — the disclosed line's own label text, carried
  alongside the balance amount so a builder-level `RelatedPartyEntry` can be
  reconstructed without guessing at the category; sourced from the same
  regex match, same evidence gate as above.

Row identity for these two FactKinds is `provenance.section = "rpt_row_N"`,
reusing the existing `resolution_N`/`director_change_N` section-keying
discipline (see `src/atlas/company/builder.py`) — no new `Provenance` field
was introduced.

`GOVERNANCE_` (not `FINANCIAL_`) is the deliberate prefix choice: the
builder's `_FINANCIAL_SNAPSHOT_KINDS` frozenset does blanket
prefix-routing (`k.value.startswith("financial_")`) into a float-only,
one-value-per-kind-per-period dict — a `FINANCIAL_`-prefixed name would risk
being silently swept into the wrong snapshot rather than reaching the
dedicated `rpt_row_N` reconstruction code this milestone adds.

---

## Amendment (M-P3.4)

Three further FactKinds independently satisfy the same three-part test and
are admitted under this exception, not a new one:

- `FINANCIAL_COST_OF_MATERIALS` — primary (P&L's own disclosed "Cost of
  materials consumed" line); extends `_PL_ROWS`/`_extract_pl_facts`, the same
  already-parsed P&L region every other `FINANCIAL_*` P&L line already uses —
  a plain row addition, no new extraction function. Evidence-verified at Tata
  Steel: 5/7 real filings, real varying values (e.g. 11,764.27; 10,833.48;
  11,270.37), always positive. The two real-word variants observed —
  "materials" and an OCR-mangled "matenals" — are both matched by one regex.
  **Condition 3 does not hold at TCS** — confirmed absent in both TCS
  filings checked, expected: a service company has no cost-of-materials line
  by business model, the identical conditional-firing pattern already
  accepted for `FINANCIAL_TCV`/`FINANCIAL_UNBILLED_REVENUE`. Not a defect.
- `FINANCIAL_PURCHASES_STOCK_IN_TRADE` — primary ("Purchases of
  stock-in-trade"); same extension, same evidence gate, always positive in
  every verified filing.
- `FINANCIAL_CHANGE_IN_INVENTORIES` — primary ("Changes in inventories of
  finished and semi-finished goods, stock-in-trade and work-in-progress");
  same extension. **Genuinely signed, not floor-gated.** Real evidence shows
  both positive (559.40) and negative (-851.30) disclosed values across the
  same filing's comparative periods — an inventory drawdown is a real,
  correctly-disclosed negative contribution to cost of goods sold, not an
  extraction error. This is the one FactKind in the ontology where a
  negative value is accepted as-is.

**Why this needs no new floor-exception mechanism, and touches no existing
floor.** The `_positive()` plausibility floor (used by the M-P3.1/M-P3.2
balance-sheet and cash-flow extractions: `FINANCIAL_INVENTORIES`,
`FINANCIAL_TRADE_RECEIVABLES`, `FINANCIAL_TRADE_PAYABLES`,
`FINANCIAL_UNBILLED_REVENUE`, `FINANCIAL_INTANGIBLE_ASSETS`,
`FINANCIAL_CASH_TAX_PAID`) is implemented per-call-site in dedicated
extraction functions in `financial_results.py`, gating values where zero or
negative is implausible for a going concern (a balance-sheet asset
magnitude, a cash outflow). It was never part of `_extract_pl_facts` /
`_PL_ROWS` — the mechanism this amendment's three FactKinds reuse verbatim.
Every existing `_PL_ROWS` member (e.g. `FINANCIAL_PROFIT_BEFORE_TAX`, which
is legitimately negative in a loss-making period) already passes through
unfiltered by that same absence of a floor. Adding
`FINANCIAL_CHANGE_IN_INVENTORIES` to this mechanism therefore requires no
new exception to any floor — there is no floor at this call site to except
it from. `FINANCIAL_COST_OF_MATERIALS`/`FINANCIAL_PURCHASES_STOCK_IN_TRADE`
are empirically always-positive across every verified filing but are, like
every other `_PL_ROWS` member, not floor-enforced — consistent with, not a
deviation from, the existing per-call-site floor design (which the
M-P3.1/M-P3.2 extractions above remain unchanged and unaffected by this
amendment).

Row identity is not needed for these three: like every other `_PL_ROWS`
entry, each is one scalar value per period, not a repeated/multi-row
structure — no `provenance.section` row-keying, no builder change. All three
route into `FinancialSnapshot.facts` automatically via the existing
`_FINANCIAL_SNAPSHOT_KINDS` blanket `financial_`-prefix routing already
confirmed in the M-P3.3 amendment above — no store or builder change.

**Found and confirmed as pre-existing, unrelated technical debt (not
introduced by this milestone).** Verifying `FINANCIAL_COST_OF_MATERIALS`
against every real Tata Steel filing surfaced two defects already present in
`_extract_pl_facts` for **every** existing `_PL_ROWS` FactKind, reproduced
identically on already-shipped facts in the same filings, independent of this
amendment:

1. A dual-region ("labels-then-values") filing where one basis's region (here,
   `standalone`) contains only the label section with no proximate values —
   the existing per-pattern fallback ("keep the first match if none clears the
   >50-magnitude guard") then emits a garbage small value. Reproduced on the
   already-shipped `FINANCIAL_REVENUE` fact in the same filing
   (`bse-news-1145c1df...`-adjacent 2025-05-12 filing: `financial_revenue`
   extracted as `4.0` for `standalone`, not a plausible revenue figure).
2. An OCR-mangled multi-comma number (`"20,677 63"`-shaped) not fully
   corrected by `fix_ocr_numbers`, truncating to a fragment. Reproduced on the
   already-shipped `FINANCIAL_OTHER_EXPENSES` fact in the same filing
   (extracted as `73.35442`, not a plausible expense figure).

Both are defects in the pre-existing `_extract_pl_facts`/`fix_ocr_numbers`
machinery this amendment reuses verbatim, not in the three new FactKinds or
their regexes. Left unfixed for the same reason ADR-0012's original
`UnboundLocalError` and basis-defaulting debt were left unfixed: fixing
already-shipped extraction machinery is out of this milestone's scope and
would be undisclosed scope creep.

---

## References

- `src/atlas/analysis/financial_results.py` — `_extract_balance_sheet_facts`,
  `_extract_cashflow_facts`, the extended functions; `_last_match_before`,
  `_positive` (M-P3.1 helpers)
- `src/atlas/analysis/annual_report.py` — `_extract_gross_block` (M-P3.2),
  `_extract_rpt_balance` (M-P3.3)
- `src/atlas/analysis/financial_results.py` — `_PL_ROWS`/`_extract_pl_facts`,
  the reused generic row mechanism extended by `FINANCIAL_COST_OF_MATERIALS`/
  `FINANCIAL_PURCHASES_STOCK_IN_TRADE`/`FINANCIAL_CHANGE_IN_INVENTORIES` (M-P3.4)
- `src/atlas/company/model.py` — `AuditorEntry`, `GovernanceProfile.auditor_history` (M-P3.2);
  `RelatedPartyEntry`, `GovernanceProfile.related_parties` (M-P3.3)
- `src/atlas/analysis/base.py` — the twelve FactKind members this exception covers
- `src/atlas/query/metrics.py` — registration (`inventories`,
  `trade_receivables`, `trade_payables`, `unbilled_revenue`, `cash_tax_paid`,
  `intangible_assets`, `gross_block`, `cost_of_materials`,
  `purchases_stock_in_trade`, `change_in_inventories`)
- `src/atlas/query/engine.py` — `auditor_history()` query (M-P3.2);
  `related_party_disclosures()`, `rpt_resolutions()` queries (M-P3.3)
- Atlas Evaluation Matrix — Part II Phase 3, M-P3.0 (extraction-risk gate),
  M-P3.1, M-P3.2, M-P3.3, M-P3.4 (this amendment)
- `docs/adr/0009-orthogonal-concerns.md` — the compose-don't-merge discipline
  informing the Billed/Unbilled non-overlap resolution
