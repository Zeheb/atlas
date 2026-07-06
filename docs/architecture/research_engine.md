# Atlas Research v2 — Architecture

## What this is not

Not an LLM wrapper. Every section is a deterministic function of
`CompanyProfile` (plus the acquisition-layer `Repository` for citations).
Given the same profile, the report is byte-identical every time.

## v1 → v2: from a reporting engine to a question-driven briefing

v1 organized sections around what data Atlas *has* (Business Overview,
Financial Performance, ESG/Governance) — a reporting-engine structure, not
an analyst one. Studying how real investment memos are built — hedge fund
long/short pitches, quality-compounder letters, activist campaign letters,
high-quality sell-side notes — surfaces the same handful of underlying
questions in every genre, despite very different surface formats:

1. What is this, and why does it matter right now?
2. What changed since the last look? (every genre leads with the delta —
   nobody re-reads the whole company each time)
3. Is the underlying business good? (moat, margin durability, returns on
   capital — a quality question, not a "here are last quarter's numbers"
   question)
4. Is management credible? (do they repeat the same numbers, and does
   reality track them — not just "N guidance statements exist")
5. Is the balance sheet resilient? (a verdict, not a table)
6. What's priced in — cheap or expensive? (every real memo answers this;
   Atlas has no market price data and categorically cannot)
7. What could go wrong, prioritized? (not everything ever mentioned in 14
   years of annual reports)
8. What's the catalyst — what happens next, and when?
9. What would change our mind?
10. Bottom line: does this deserve another hour? — must be answerable from
    the first page, not buried after ten sections of data dump

v2 organizes sections around these questions. Where Atlas can answer one
deterministically, it does. Where it can't (valuation), it says so
explicitly rather than omitting the question silently — a reader should
never have to guess whether Atlas forgot to ask something or is honestly
unable to answer it.

## Module layout

```
src/atlas/research/
  __init__.py / citations.py / signals.py / model.py / render.py / report.py
                       (unchanged from v1 — see below)
  sections/
    the_call.py              Q10 — worth another hour? (built LAST, read FIRST)
    what_changed.py           Q2  — prioritized recent delta
    business_quality.py       Q3  — multi-year margin/growth stability
    management_credibility.py Q4  — guidance repetition, risk consistency,
                                     rating trajectory, AGM outcomes
    balance_sheet.py          Q5  — net cash/debt trend + rating + payouts,
                                     as a verdict
    valuation.py               Q6  — honest out-of-scope statement
    risks.py                  Q7  — top-N prioritized, not a full dump
    catalysts.py               Q8  — forward-dated pending items
    open_questions.py          Q9  — data gaps / what to watch
    competitive_position.py    (unchanged from v1)
    esg_governance.py          (unchanged from v1, read later — rarely the
                                deciding factor for "another hour" outside
                                ESG-mandated funds)
    evidence_appendix.py       (unchanged from v1, built LAST)
```

`signals.py`, `citations.py`, `model.py`, `render.py`, `_shared.py` are
unchanged — the retrieval/rendering separation and the metric-move
classifier were sound; what changed is which *sections* exist and what
each is asking, not the plumbing underneath.

## What was removed, and where it went

| v1 section | v2 fate |
|---|---|
| `executive_summary.py` | replaced by `the_call.py` — was a list of pointers to other sections ("N risks — see Risks"); a reader needing to visit five other sections to know if this is interesting is exactly the failure mode being fixed |
| `timeline.py` | replaced by `what_changed.py` — was a flat, undeduplicated dump of every event ever recorded, positioned last; the delta is what every analyst genre reads first |
| `business_overview.py` + half of `financial_performance.py` | merged into `business_quality.py` — was a single latest-period snapshot; a quality question needs multiple years to show whether a margin level is durable or a one-off |
| the other half of `financial_performance.py` + `capital_allocation.py` | merged into `balance_sheet.py` — was two separate raw-data sections; a resilience question needs one verdict, not a leverage table in one place and a dividend table in another |
| `guidance_outlook.py` | folded into `management_credibility.py` (the ledger, now with repetition detection) and `catalysts.py` (anything forward-dated) |

## Section detail

### The Call

Built last (needs every other section's output), rendered first. Not a
second, independent source of claims — every line here restates a finding
that already exists, with its own citation, elsewhere. Contains: a
one-line identity, the single most material recent change, the biggest
improving/deteriorating signal, a one-line balance sheet verdict, a
one-line credibility verdict, the single most severe open risk, and an
explicit disclosure: *Atlas does not issue a recommendation or have market
price data — this is an evidence briefing, not a rating.*

### What Changed

`_shared.collect_dated_events()` (unchanged) still collects everything,
but this section shows only the most recent N months/events by default,
explicitly labeled as a window — "since [date]" — not "here is all
history," which lives in the Appendix-adjacent full listing if a reader
wants it.

### Business Quality

Margin *stability* over the full available history (a level held for 8
years is a different fact than a level hit once), not just latest-vs-prior.
Segment concentration (how much of revenue/EBIT sits in the largest
segment) as a structural fact, not a UI table.

### Management Credibility

The one section with genuinely new logic this round:
`_shared.detect_repeated_targets()` finds literal numeric patterns (e.g.
"26-28%", "35-40 MTPA") that recur across two or more dated guidance
entries — a real, deterministic, general signal (regex over a % or
unit-quantity pattern, not NLP) that management is either consistently
reiterating a target or has been saying the same thing without updating it,
either of which is a legitimate credibility-relevant fact a reader can
judge for themselves once shown the dates.

### Balance Sheet & Capital Position

A verdict sentence (net cash vs. net debt, direction of travel, rating
trajectory) followed by the supporting tables — not tables with no
top-line synthesis above them.

### Valuation

No market price data exists anywhere in Atlas's ontology. Rather than
silently have no "valuation" section (which a reader might mistake for an
oversight), this section states the gap directly and names what data would
be needed to close it.

### What Could Go Wrong

Same underlying risk-factor data and reliability caveat as v1's `risks.py`,
re-cut: the most recent + most-recurring N risks lead, with the remainder
still present but visually and positionally secondary — a reader gets the
prioritized view first without losing access to the rest.

### Catalysts

New: scans `CapitalEventLedger` for forward-dated fields
(`AcquisitionEvent.expected_completion`) and any fundraise authorization
without a corresponding completed raise, surfacing what's pending rather
than only what already happened.

## Where determinism has real limits (unchanged from v1, still true)

Guidance-vs-delivery still isn't asserted (no structured link from free-text
guidance to a target FactKind). Competitive Position is still honest about
needing same-sector peers it doesn't yet have. Confidence is still a
source-count proxy, not `AnalysisFact.confidence` threaded through.
Valuation is new to this list: out of scope, stated explicitly, not a
silent gap.

## Testability

Unchanged principle: every section builder is a pure function of
`CompanyProfile`, unit-testable with a synthetic profile, no PDF or
KnowledgeBase involved. Golden test snapshots the full v2 Markdown shape.
