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

## References

- `src/atlas/analysis/financial_results.py` — `_extract_balance_sheet_facts`,
  the extended function; `_last_match_before`, `_positive` (new helpers)
- `src/atlas/analysis/base.py` — the four new FactKind members
- `src/atlas/query/metrics.py` — registration (`inventories`,
  `trade_receivables`, `trade_payables`, `unbilled_revenue`)
- Atlas Evaluation Matrix — Part II Phase 3, M-P3.0 (extraction-risk gate),
  M-P3.1 (this milestone)
- `docs/adr/0009-orthogonal-concerns.md` — the compose-don't-merge discipline
  informing the Billed/Unbilled non-overlap resolution
