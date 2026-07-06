"""Small helpers shared by more than one section builder.

Not a general utility dumping ground — a function only belongs here once a
second section builder actually needs it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from atlas.company.model import CompanyProfile, RiskEntry
from atlas.query.engine import TableSection

# RISK_FACTOR extraction has a known, pre-existing reliability problem
# (documented against real TCS output before this sprint even started):
# it matches board-membership boilerplate and marketing headings, not just
# real risk-factor prose. Found again here, worse, across all three
# reference companies while building this report — Tata Steel's includes
# bare data-table fragments ("PE as at 31 March, 2015"), SBI's includes
# OCR-garbled vernacular-script noise ("soft aqg-| at mari sik 20 sage
# dhe"). This filter is a report-layer quality gate, not a fix to the
# analyzer (out of scope — "no new analyzers unless absolutely necessary",
# and the real fix belongs in annual_report.py's section-boundary
# detection). It catches the cleanly-classifiable garbage (too short,
# known boilerplate patterns, pure numeric); it does NOT reliably catch
# OCR noise that happens to be long enough and word-shaped — which is why
# risks.py and management_credibility.py both also emit an explicit
# reliability caveat regardless of how much this filter removes. A note is
# more honest than a filter that looks clean but still isn't.
_MIN_RISK_TEXT_LENGTH = 50

_BOILERPLATE_PATTERNS = (
    re.compile(r"https?://", re.IGNORECASE),
    re.compile(r"\bw\.e\.f\.?\b", re.IGNORECASE),
    re.compile(r"\bceased to be\b", re.IGNORECASE),
    re.compile(r"\bappointed as\b", re.IGNORECASE),
    re.compile(r"\bmember of the committee\b", re.IGNORECASE),
    re.compile(r"\(C\)\s*\(N?ED\)", re.IGNORECASE),
    re.compile(r"^\**\s*[\d.]+\s*$"),  # bare numeric table-cell fragment
)


def is_plausible_risk_text(text: str) -> bool:
    """True if *text* survives the cleanly-classifiable-garbage filter.

    Not a claim that everything passing this is a genuine risk factor —
    see the module-level caveat above. Only removes what's confidently
    identifiable as boilerplate/table noise, never a subjective content
    judgment about what counts as "risky enough".
    """
    stripped = text.strip()
    if len(stripped) < _MIN_RISK_TEXT_LENGTH:
        return False
    return not any(p.search(stripped) for p in _BOILERPLATE_PATTERNS)


RISK_RELIABILITY_CAVEAT = (
    "RISK_FACTOR extraction from annual reports has a known, pre-existing reliability "
    "limitation (out of scope for this report generator to fix): it can match board-"
    "governance boilerplate, table fragments, or OCR noise instead of genuine risk "
    "disclosure. Entries below have been filtered for the most obvious cases but are "
    "not guaranteed clean — verify against the source Annual Report before relying on this list."
)

# Split into unambiguous ("strong") vs. common-in-any-financial-writing
# ("weak") risk vocabulary. Found necessary during validation: a first cut
# using "impact"/"may"/"could" etc. as equally-weighted single-word
# matches let a plain financial-commentary sentence ("the impact of the
# one-time employee reward on cash flow") pass as "risk vocabulary" purely
# because it contained the word "impact" — a word that appears constantly
# in ordinary financial writing having nothing to do with risk. A strong
# term alone is a real signal; a weak term needs a second, distinct weak
# term alongside it before counting (reduces false positives from one
# common word appearing incidentally).
_STRONG_RISK_TERMS = re.compile(
    r"\b(risk|adverse|litigation|non-compliance|penalt|vulnerab|threat)\w*",
    re.IGNORECASE,
)
_WEAK_RISK_TERMS = re.compile(
    r"\b(may|could|uncertain|impact|competit|regulat|disrupt|volatil|exposure|challeng)\w*",
    re.IGNORECASE,
)


def is_high_confidence_risk(text: str, recurrence: int) -> bool:
    """True if *text* is trustworthy enough to headline as THE risk callout
    (The Call), not just plausible enough to appear in the full list.

    recurrence >= 2 alone is sufficient (two separate documents producing
    the same text is hard for OCR/extraction noise to coincidentally
    repeat verbatim). Vocabulary alone requires either one strong term or
    two distinct weak terms — see the module comment for why a single weak
    term isn't enough on its own.
    """
    if recurrence >= 2:
        return True
    if _STRONG_RISK_TERMS.search(text):
        return True
    return len(set(m.lower() for m in _WEAK_RISK_TERMS.findall(text))) >= 2


def group_risks_by_text(profile: CompanyProfile) -> dict[str, list[RiskEntry]]:
    """Every plausible-risk RiskEntry grouped by exact-match (lowercased,
    stripped) text — see is_plausible_risk_text() for what's excluded and why.

    Undeduplicated input (profile.governance.risk_factors carries one entry
    per annual report that mentioned it) — the caller decides whether it
    wants the full group (to count recurrence) or just the latest entry
    per group (to list current risks once).
    """
    by_text: dict[str, list[RiskEntry]] = {}
    for r in profile.governance.risk_factors:
        if not is_plausible_risk_text(r.text):
            continue
        by_text.setdefault(r.text.lower().strip(), []).append(r)
    return by_text


def collect_dated_events(profile: CompanyProfile) -> list[tuple[datetime, str, str, list[str]]]:
    """Every capital-event and governance event as (date, category,
    description, evidence_ids), unsorted and deduplicated.

    Mirrors the shape engine.summary()'s "Recent Capital Events" section
    builds internally (deliberately not refactored to share that exact
    code — summary() is stable, tested, and truncates to 5; this collects
    the FULL history for timeline.py, a different consumer with different
    needs). Duplicating the shape rather than the truncation logic is the
    considered trade-off, not an oversight.

    Deduplicates on (date, category, description): the same real-world
    event routinely gets recorded twice in CompanyProfile — once per filing
    type that announced it (a dividend named in both a Board Outcome and a
    Financial Results filing, e.g.) — correctly, at that layer, since both
    are real independent evidence. Rendering it twice in a timeline reads
    as two different events, so duplicates are merged into one entry
    carrying every contributing evidence_id, not one arbitrarily chosen.
    """
    raw: list[tuple[datetime, str, str, str]] = []
    ce = profile.capital_events

    for e in ce.dividends:
        raw.append((e.source_date, "Dividend", f"{e.dividend_type} {e.per_share:.2f}/share", e.evidence_id))
    for e in ce.buybacks:
        amt = f" ({e.amount:,.0f} cr)" if e.amount else ""
        raw.append((e.source_date, "Buyback", f"{e.sub_type}{amt}", e.evidence_id))
    for e in ce.acquisitions:
        raw.append((e.source_date, "Acquisition", " ".join(e.target_name.split()), e.evidence_id))
    for e in ce.investments:
        raw.append((e.source_date, "Investment", " ".join(e.target_name.split()), e.evidence_id))
    for e in ce.fundraises:
        raw.append((e.source_date, "Fundraise", e.fundraise_type, e.evidence_id))
    for r in (profile.credit_history.debt_ratings + profile.credit_history.esg_ratings):
        desc = f"{r.agency}: {r.action or 'rating'} {r.rating or ''}".strip()
        raw.append((r.source_date, "Rating Action", desc, r.evidence_id))
    for d in profile.governance.director_changes:
        raw.append((d.source_date, "Board Change", f"{d.change_type} — {' '.join(d.name.split())}", d.evidence_id))
    for s in profile.strategy.entries:
        if s.kind == "guidance":
            raw.append((s.source_date, "Guidance", s.text, s.evidence_id))
        elif s.kind == "aspiration":
            raw.append((s.source_date, "Aspiration", s.text, s.evidence_id))

    # Key on calendar date, not the full datetime — the two filings
    # announcing the same real event are timestamped minutes apart on the
    # same day (different submission times to BSE), not at the identical
    # instant, so deduping on full datetime equality silently failed to
    # catch this in an earlier version of this function. The displayed
    # date (_fmt_source_date) already drops time-of-day, so this matches
    # what a reader actually sees.
    merged: dict[tuple[str, str, str], list[str]] = {}
    order: list[tuple[str, str, str]] = []
    representative_date: dict[tuple[str, str, str], datetime] = {}
    for date, category, desc, eid in raw:
        key = (date.date().isoformat(), category, desc)
        if key not in merged:
            merged[key] = []
            order.append(key)
            representative_date[key] = date
        else:
            representative_date[key] = min(representative_date[key], date)
        if eid and eid not in merged[key]:
            merged[key].append(eid)

    return [(representative_date[key], key[1], key[2], merged[key]) for key in order]


def drop_empty_rows(table: TableSection, value_columns: slice = slice(1, None)) -> TableSection:
    """Drop any row whose value columns are entirely "-".

    Found necessary during validation: engine.revenue()/leverage() build one
    row per annual snapshot regardless of whether that snapshot has P&L
    facts — real for TCS, where several years' snapshots exist only because
    an investor deck's 5-year ROE/FCF reference table touched that period,
    with no revenue/PAT ever extracted for it. A row of all "-" (bar the
    period label and a derived "-" change column) adds no information and
    reads as broken; every other value in value_columns being exactly "-"
    is a reliable, general signal that the row is genuinely empty, not
    reflective of a real embedded zero (a real 0 renders as "0", never "-").
    """
    kept_rows = [
        row for row in table.rows
        if any(cell != "-" for cell in row[value_columns])
    ]
    return TableSection(heading=table.heading, columns=table.columns, rows=kept_rows)


# A number or number-range, optionally followed by a short unit token —
# deliberately narrow to the shape a re-affirmed target actually takes
# ("26-28%", "35-40 MTPA", "<2 tCO2e", "4x", "11,500 crores"), not a
# general number matcher that would flag every date or page reference.
_NUMERIC_TARGET_PATTERN = re.compile(
    r"(?:<\s*)?\d[\d,]*(?:\.\d+)?(?:\s*-\s*\d[\d,]*(?:\.\d+)?)?\s*(?:%|x\b|mtpa|tco2e?|crores?|cr\b)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class RepeatedTarget:
    """One numeric target found repeated across 2+ dated guidance entries."""

    pattern: str
    occurrences: list[tuple[datetime, str]]  # (source_date, evidence_id)


def detect_repeated_targets(profile: CompanyProfile) -> list[RepeatedTarget]:
    """Numeric targets (percentages, ranges, ratios) that recur verbatim
    across two or more distinct guidance/aspiration filing dates.

    Deterministic pattern matching, not NLP — a literal, normalized
    substring match on a narrow numeric-target shape. Whether a repeated
    target reflects consistent commitment or a stale, un-updated line is a
    judgment left to the reader (both dates are shown); this only surfaces
    the deterministic fact of repetition itself.
    """
    by_pattern: dict[str, list[tuple[datetime, str]]] = {}
    for e in profile.strategy.entries:
        if e.kind not in ("guidance", "aspiration"):
            continue
        seen_in_entry: set[str] = set()
        for m in _NUMERIC_TARGET_PATTERN.finditer(e.text):
            norm = re.sub(r"\s+", " ", m.group(0).strip().lower())
            if norm in seen_in_entry:
                continue  # count each entry once per pattern, not once per mention
            seen_in_entry.add(norm)
            by_pattern.setdefault(norm, []).append((e.source_date, e.evidence_id))

    results = []
    for pattern, occurrences in by_pattern.items():
        distinct_dates = {d.date() for d, _ in occurrences}
        if len(distinct_dates) >= 2:
            results.append(RepeatedTarget(pattern=pattern, occurrences=sorted(occurrences)))
    return sorted(results, key=lambda r: len(r.occurrences), reverse=True)


def dedupe_identical_rows(table: TableSection) -> TableSection:
    """Collapse rows that are cell-for-cell identical to one.

    Found necessary during validation: the same real-world dividend gets
    reported through two separate document types (a Board Outcome filing
    and a Financial Results filing both announcing the same declaration on
    the same date) and company/builder.py records both as distinct ledger
    entries — correct at that layer (both are real, independent evidence),
    but rendering the identical row twice in a report reads as if two
    different dividends were declared. Safe because it only ever removes a
    row whose every displayed cell exactly matches an earlier row — two
    genuinely different events could never collide here (they'd differ in
    at least the date or amount column).
    """
    seen: set[tuple[str, ...]] = set()
    kept_rows = []
    for row in table.rows:
        key = tuple(row)
        if key in seen:
            continue
        seen.add(key)
        kept_rows.append(row)
    return TableSection(heading=table.heading, columns=table.columns, rows=kept_rows)
