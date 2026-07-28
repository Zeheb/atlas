"""Rule-based fact extraction from investor presentation filings (Reg 30/51).

v2.0 redesign. v1.0 was built and validated against a single TCS Analyst Day
deck and matched literal TCS slide titles ("tcsAI Internal Transformation",
"We will be the world's largest AI-led Technology Services company"). It
produced zero facts on the vast majority of Tata Steel and SBI investor
presentations — confirmed empirically during the OCR validation sprint
(2026-07-03): 118 of 124 OCR-recovered investor_presentation documents across
all three companies yielded 0 facts from either native or OCR text.

This version is built around concepts that recur across sectors — a bank, a
steel manufacturer, and an IT services company all disclose forward guidance,
a return-on-capital metric, and *some* form of operating KPI — even though
the literal wording, headings, and slide order differ completely between
them. Every pattern below was checked against real filings from all three
companies before being written; several v1.0 concepts (ROE, FCF, segment
growth, CSAT) survive with generalized detection, and several new ones are
added because the FactKind ontology already reserved but never populated them
(the banking ratio family) or because real cross-company evidence justified
a new concept (physical production/delivery volume).

Document shapes observed
-------------------------
Investor presentation filings come in three shapes, none of which map neatly
to "one company, one format":
  - Genuine slide decks (TCS Analyst Day, SBI analyst presentations): bullet
    lists, infographic-style value-then-label callouts, and small comparison
    tables.
  - Press-release-style filings (Tata Steel): a SEBI Reg 30/51 cover letter
    followed by a press release with "Highlights:" bullets and a labelled
    "Management Comments:" CEO/CFO quote block.
  - Short administrative filings: IR meeting schedules, analyst-meet
    intimations — carry little beyond a reporting period.

Extraction does not gate on which shape a document is; every pattern below is
independently tried and independently degrades to "not found" (a warning,
not an error) when its anchor is absent. Confidence is derived from how many
distinct fact categories were actually found, not from a pre-classified
sub-type.

Fact vocabulary
----------------
Reused from v1.0 (generalized extraction, same FactKind):
  STRATEGY_ASPIRATION   Vision/mission statement; unit=None
  STRATEGY_PRIORITY     Named strategic priority/pillar; unit=None
  STRATEGY_GUIDANCE     Forward-looking target statement (margin, cost
                        savings, leverage — format varies); unit=None
  STRATEGY_CSAT         Customer satisfaction score; unit=PERCENT
  SEGMENT_NAME / SEGMENT_GROWTH_PCT   Business line + YoY growth; unit=PERCENT
  FINANCIAL_ROE         Return on equity; unit=PERCENT
  FINANCIAL_FCF         Management-defined free cash flow; unit=CRORE_INR
  REPORT_PERIOD_END / REPORT_PERIOD_TYPE

New in v2.0 — banking ratio family (FactKinds already existed in the
ontology, reserved for exactly this disclosure pattern, but no analyzer had
ever populated them; financial_results.py deliberately extracts Net Profit
only for Banking Regulation Act filings):
  FINANCIAL_NET_INTEREST_INCOME, FINANCIAL_NET_INTEREST_MARGIN,
  FINANCIAL_GROSS_NPA_RATIO, FINANCIAL_NET_NPA_RATIO,
  FINANCIAL_PROVISION_COVERAGE_RATIO, FINANCIAL_CREDIT_COST,
  FINANCIAL_CASA_RATIO, FINANCIAL_CAPITAL_ADEQUACY_RATIO,
  FINANCIAL_SLIPPAGE_RATIO

New in v2.0 — physical operating volume (new FactKinds; justified by
Tata Steel disclosing Production/Deliveries in every quarterly and annual
presentation reviewed):
  FINANCIAL_PRODUCTION_VOLUME, FINANCIAL_DELIVERY_VOLUME

Deliberately NOT extracted (duplicates financial_results.py's authoritative
P&L/balance-sheet facts): revenue, PAT, EBITDA, dividend per share, capex,
net debt. These appear routinely in presentation text but financial_results
is the primary source; re-extracting them here would create two competing
values for the same fact with no way to reconcile a discrepancy. See
_EXCLUDE_LABELS.

Excerpts
--------
management_commentary   CEO/CFO named-quote block, when present
aspiration               Text window around the vision/mission statement
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from atlas.analysis.base import (
    AnalysisFact,
    AnalysisResult,
    FactKind,
    FactUnit,
    Provenance,
    _snip,
)
from atlas.analysis.patterns import (
    extract_n_values,
    find_guidance_statements,
    parse_iso_date,
)
from atlas.knowledge.base import KnowledgeBase

ANALYZER_VERSION = "2.0"

# ---------------------------------------------------------------------------
# Period detection (cover letter)
# ---------------------------------------------------------------------------

# "Quarter Ended September 30, 2024" / "quarter and year ended March 31, 2025"
# Group 1 = the cadence keyword actually used ("quarter"/"half year"/"year"),
# needed to distinguish a Q4-and-annual bundled filing ("quarter and
# financial year ended...") from a pure quarterly one — "year" anywhere in
# the matched span means the filing carries annual (full-year) figures.
_RE_PERIOD_TEXTUAL = re.compile(
    r"((?:quarter|half[- ]?year|year)(?:[^.\n]{0,60}?)ended)\s+"
    r"([A-Z][a-z]+\s+\d{1,2},?\s*\d{4})",
    re.IGNORECASE,
)
# SBI-style numeric date: "quarter and half year ended 30.09.2024"
_RE_PERIOD_NUMERIC = re.compile(
    r"((?:quarter|half[- ]?year|year)(?:[^.\n]{0,60}?)ended)\s+"
    r"(\d{1,2})\.(\d{1,2})\.(\d{4})",
    re.IGNORECASE,
)


_RE_HALF_YEAR = re.compile(r"half[- ]?year", re.IGNORECASE)


def _period_type_from_cadence(cadence_phrase: str) -> str:
    """Q4-and-annual filings ('quarter and financial year ended...') carry
    full-year figures — treat as annual, matching financial_results.py's own
    "prefer annual when both quarter and year are mentioned" rule.

    "half year" contains the substring "year" but is not annual — SBI's
    "quarter and half year ended" cadence must not be misdetected as annual.
    """
    stripped = _RE_HALF_YEAR.sub("", cadence_phrase.lower())
    return "annual" if "year" in stripped else "quarterly"


def _detect_period(cover: str) -> tuple[str | None, str | None, int | None]:
    """Return (period_iso, period_type, char_offset), or (None, None, None)."""
    m = _RE_PERIOD_TEXTUAL.search(cover)
    if m:
        iso = parse_iso_date(m.group(2))
        if iso:
            return iso, _period_type_from_cadence(m.group(1)), m.start()
    m = _RE_PERIOD_NUMERIC.search(cover)
    if m:
        day, month, year = m.group(2), m.group(3), m.group(4)
        return (
            f"{year}-{int(month):02d}-{int(day):02d}",
            _period_type_from_cadence(m.group(1)),
            m.start(),
        )
    return None, None, None


# ---------------------------------------------------------------------------
# Shared fact constructor
# ---------------------------------------------------------------------------


def _pf(
    kind: FactKind,
    value: str | float | int,
    unit: FactUnit | None,
    period: str | None,
    section: str,
    offset: int,
    excerpt_text: str,
    confidence: Literal["high", "medium", "low"] = "high",
) -> AnalysisFact:
    return AnalysisFact(
        kind=kind,
        value=value,
        unit=unit,
        period=period,
        confidence=confidence,
        provenance=Provenance(
            section=section,
            char_offset=offset,
            excerpt=_snip(excerpt_text, 0) if excerpt_text else None,
        ),
    )


# ---------------------------------------------------------------------------
# 1. Strategic aspiration / vision statement
# ---------------------------------------------------------------------------

# Common lead-ins observed across sectors. Slide-deck "vision" lines are
# often slide titles with no terminating punctuation at all (unlike a real
# prose sentence), so the span is length-capped rather than punctuation-
# bounded — an unbounded search for the next period can walk straight past
# unrelated slide titles concatenated by the whitespace normalization.
_RE_ASPIRATION = re.compile(
    r"(?:Our\s+vision\s+is\s+to|Our\s+purpose\s+is\s+to|"
    r"We\s+will\s+be|We\s+aspire\s+to\s+be|We\s+intend\s+to\s+be)"
    r"\s+((?:(?!\bOur\s+Aspiration\b)[^.\n]){10,150})",
    re.IGNORECASE,
)


def _extract_aspiration(normalized: str, result: AnalysisResult) -> None:
    m = _RE_ASPIRATION.search(normalized)
    if not m:
        result.warnings.append("Strategic aspiration statement not found")
        return
    span = m.group(0)
    # Trim at the first sentence-ending period within the captured span, when
    # one exists (a real prose sentence); otherwise keep the full capped span
    # (a punctuation-less slide title).
    cut = span.find(".")
    if cut != -1:
        span = span[:cut]
    value = span.strip()
    result.facts.append(
        _pf(
            FactKind.STRATEGY_ASPIRATION,
            value,
            None,
            None,
            "aspiration",
            m.start(),
            value,
        )
    )
    result.excerpts["aspiration"] = normalized[
        max(0, m.start() - 80) : m.start() + len(span) + 100
    ]


# ---------------------------------------------------------------------------
# 2. Strategic priorities / pillars
# ---------------------------------------------------------------------------

# A labelled section heading, followed by a short bulleted or short-line list.
# Requires an explicit heading rather than guessing at any bullet list in the
# document — bullet lists are common and mostly not "priorities".
_RE_PRIORITIES_HEADING = re.compile(
    r"(?:Strategic\s+Priorit(?:y|ies)|Strategic\s+Pillars|Key\s+Priorit(?:y|ies)|"
    r"Transformation\s+Pillars|Focus\s+Areas|Strategic\s+Roadmap)\s*\n",
    re.IGNORECASE,
)
# A bullet-prefixed or short Title Case line, immediately following the heading.
_RE_BULLET_LINE = re.compile(
    r"^[▪●•\-•]?\s*([A-Z][A-Za-z0-9 ,&/()\-']{4,90})\s*$",
    re.MULTILINE,
)
_MAX_PRIORITIES = 8


def _extract_priorities(content: str, result: AnalysisResult) -> None:
    m = _RE_PRIORITIES_HEADING.search(content)
    if not m:
        return  # Not every presentation restates priorities; no warning needed.
    window = content[m.end() : m.end() + 1500]
    seen: set[str] = set()
    count = 0
    for bm in _RE_BULLET_LINE.finditer(window):
        if count >= _MAX_PRIORITIES:
            break
        text = bm.group(1).strip()
        key = text.lower()
        if key in seen or len(text) < 5:
            continue
        seen.add(key)
        count += 1
        result.facts.append(
            _pf(
                FactKind.STRATEGY_PRIORITY,
                text,
                None,
                None,
                "priorities",
                m.end() + bm.start(),
                text,
            )
        )


# ---------------------------------------------------------------------------
# 3. Forward guidance / targets
# ---------------------------------------------------------------------------

# Sentence-based guidance detection lives in patterns.py (find_guidance_
# statements) — shared with earnings_transcript.py, since both a slide deck
# and a CFO's spoken remarks express forward targets the same way.
#
# Fallback for chart-style guidance with no verb at all — a range value sits
# directly under a generic heading like "Margin Levers" / "Margin Guidance" /
# "Outlook" with no sentence around it (common in infographic slide layouts).
# Case-sensitive and closed to specific known headings deliberately: an
# open "Margin\s+\w*" wildcard matches a stray lowercase "margin" inside an
# unrelated sentence (e.g. "...consistent cash conversion, margin Over
# 50%...") long before it reaches the real slide heading, since re.search
# stops at the first match.
_RE_GUIDANCE_HEADING = re.compile(
    r"(?:Margin\s+(?:Levers|Guidance|Outlook|Trajectory)|Guidance|Outlook)\s*\n",
)
_RE_GUIDANCE_RANGE = re.compile(r"(\d{2,3}\s*-\s*\d{2,3})\s*%")
_MAX_GUIDANCE = 3


def _extract_guidance(normalized: str, content: str, result: AnalysisResult) -> None:
    seen: set[str] = set()
    count = 0
    for text, offset in find_guidance_statements(normalized, _MAX_GUIDANCE):
        seen.add(text.lower())
        count += 1
        result.facts.append(
            _pf(
                FactKind.STRATEGY_GUIDANCE,
                text,
                None,
                None,
                "guidance",
                offset,
                text,
            )
        )

    m_heading = _RE_GUIDANCE_HEADING.search(content)
    if m_heading:
        window = content[m_heading.end() : m_heading.end() + 800]
        m_range = _RE_GUIDANCE_RANGE.search(window)
        if m_range:
            text = f"{m_heading.group(0).strip()}: {m_range.group(1)}%"
            key = text.lower()
            if key not in seen:
                count += 1
                result.facts.append(
                    _pf(
                        FactKind.STRATEGY_GUIDANCE,
                        text,
                        None,
                        None,
                        "guidance",
                        m_heading.end() + m_range.start(),
                        text,
                    )
                )

    if count == 0:
        result.warnings.append("No forward guidance statement found")


# ---------------------------------------------------------------------------
# 4. Return on Equity / Free Cash Flow — inline sentence disclosure
# ---------------------------------------------------------------------------

_RE_ROE_INLINE = re.compile(
    r"(?:Return\s+on\s+Equity|\bROE\b)[^.\n]{0,40}?" r"(\d{1,2}(?:\.\d+)?)\s*%",
    re.IGNORECASE,
)
_RE_FCF_INLINE = re.compile(
    r"[Ff]ree\s+cash\s*flows?[^.\n]{0,35}?"
    r"(?:Rs\.?|₹)\s*([\d,]+(?:\.\d+)?)\s{0,2}(?:crores?|cr\.?)",
    re.IGNORECASE,
)
_RE_FY_YEAR = re.compile(r"FY\s?(\d{2,4})\b", re.IGNORECASE)


def _nearest_fy_period(
    content: str, offset: int, source_period: str | None
) -> str | None:
    """Infer a fiscal-year-end period for a value near *offset*.

    Looks for the nearest "FYxx" token within a short window before the
    match; if found, returns the Indian FY end date. The window is kept
    short (60 chars, roughly one clause) deliberately: a wider lookback
    picks up an unrelated forward-looking year mention from a *previous*
    sentence (e.g. a cost-savings target for "FY2027" bleeding into the
    period assigned to a same-paragraph FCF figure that is actually about
    the current reporting period) more often than it correctly attributes
    a genuine nearby year label. Falls back to the document's own detected
    reporting period, which is correct for the common case where the
    surrounding paragraph never restates the year at all.
    """
    window = content[max(0, offset - 60) : offset]
    matches = list(_RE_FY_YEAR.finditer(window))
    if matches:
        raw = matches[-1].group(1)
        year = int(raw) if len(raw) == 4 else 2000 + int(raw)
        return f"{year}-03-31"
    return source_period


# Bar-chart / infographic disclosure: a "Return on Equity" (or "Capital
# Allocation" / "Free Cash Flow") heading followed by a block of FY-year
# labels and a separate block of value labels (the two axes of a bar chart,
# extracted as text in reading order rather than as a table). Years and
# values are paired positionally — both blocks are emitted oldest-first in
# every real filing observed, which is also how PDF text extraction reads a
# left-to-right chart.
_RE_ROE_HEADING = re.compile(r"Return\s+on\s+Equity\s*\n", re.IGNORECASE)
_RE_FCF_HEADING = re.compile(
    r"Capital\s+Allocation\s*\n|Free\s+Cash\s*[Ff]low\s*\n",
    re.IGNORECASE,
)
_RE_PCT_TOKEN = re.compile(r"(?<!\d)(\d{1,3}(?:\.\d+)?)\s*%")
_RE_CRORE_TOKEN = re.compile(r"\b(\d{2,3}),(\d{3})\b")
_BLOCK_WINDOW = 300
_MAX_BLOCK_YEARS = 6
# Real bar-chart text has the value block starting within a few characters of
# the year-label block (both are short, contiguous chart-axis text). A large
# gap means the "years" and "numbers" found nearby are unrelated prose
# mentions scattered through a paragraph, not chart data — reject those.
_MAX_YEAR_TO_VALUE_GAP = 40


def _year_value_pairs(
    window: str,
    year_re: re.Pattern[str],
    value_re: re.Pattern[str],
) -> list[tuple[str, tuple[str, ...]]]:
    """Pair FY-year labels with chart values via greedy FIFO over position order.

    PDF text extraction from a bar chart does not reliably give "all year
    labels, then all values" — some decks extract the first bar's label and
    value adjacent to each other, with only the *remaining* bars' labels and
    values each grouped separately (observed in a real TCS filing). A rigid
    "years block then values block" split mis-pairs every year in that case.

    Instead, walk both matches in document order as one merged stream: each
    year token is queued, and each value token claims the oldest still-queued
    year (FIFO). This handles a clean "labels-block then values-block" chart
    (queue fills, then drains in order) and a "label+value, label+value..."
    chart (queue never grows past 1) identically and correctly. A large gap
    between consecutive tokens ends the scan — it signals the chart is over
    and any further numbers belong to unrelated content.

    The heading itself is ambiguous across companies — the exact same
    heading text ("Capital Allocation") introduces a clean bar chart in one
    company's deck and a bulleted prose section in another's. Requiring the
    first year token to appear within _MAX_YEAR_TO_VALUE_GAP of the window
    start discriminates a chart (year axis label immediately follows the
    heading) from prose (several sentences of unrelated text intervene
    before any "FYxx" token happens to appear).
    """
    years = list(year_re.finditer(window))[:_MAX_BLOCK_YEARS]
    if not years or years[0].start() > _MAX_YEAR_TO_VALUE_GAP:
        return []
    values = list(value_re.finditer(window))[: _MAX_BLOCK_YEARS * 2]

    tokens = sorted(
        [("year", m) for m in years] + [("value", m) for m in values],
        key=lambda t: t[1].start(),
    )
    # Trim to the contiguous run starting at the first year token — a big
    # gap anywhere means we have drifted into unrelated text.
    first_year_idx = next(i for i, (kind, _) in enumerate(tokens) if kind == "year")
    tokens = tokens[first_year_idx:]
    trimmed: list[tuple[str, re.Match[str]]] = []
    prev_end = None
    for kind, m in tokens:
        if prev_end is not None and m.start() - prev_end > _MAX_YEAR_TO_VALUE_GAP:
            break
        trimmed.append((kind, m))
        prev_end = m.end()

    pending: list[re.Match[str]] = []
    pairs: list[tuple[str, tuple[str, ...]]] = []
    for kind, m in trimmed:
        if kind == "year":
            pending.append(m)
        elif pending:
            year_m = pending.pop(0)
            pairs.append((year_m.group(1), m.groups()))
    return pairs


def _extract_roe_fcf_block(content: str, result: AnalysisResult) -> set[str]:
    """Bar-chart multi-year ROE/FCF. Returns the set of periods populated."""
    periods_found: set[str] = set()

    m = _RE_ROE_HEADING.search(content)
    if m:
        window = content[m.end() : m.end() + _BLOCK_WINDOW]
        for year, (pct,) in _year_value_pairs(window, _RE_FY_YEAR, _RE_PCT_TOKEN):
            yr = int(year) if len(year) == 4 else 2000 + int(year)
            period = f"{yr}-03-31"
            result.facts.append(
                _pf(
                    FactKind.FINANCIAL_ROE,
                    float(pct),
                    FactUnit.PERCENT,
                    period,
                    "roe",
                    m.start(),
                    f"FY {year}: {pct}%",
                )
            )
            periods_found.add(period)

    m = _RE_FCF_HEADING.search(content)
    if m:
        window = content[m.end() : m.end() + _BLOCK_WINDOW]
        for year, (thousands, hundreds) in _year_value_pairs(
            window, _RE_FY_YEAR, _RE_CRORE_TOKEN
        ):
            yr = int(year) if len(year) == 4 else 2000 + int(year)
            period = f"{yr}-03-31"
            value = int(thousands + hundreds)
            result.facts.append(
                _pf(
                    FactKind.FINANCIAL_FCF,
                    value,
                    FactUnit.CRORE_INR,
                    period,
                    "fcf",
                    m.start(),
                    f"FY {year}: Rs {value} cr",
                )
            )
            periods_found.add(period)

    return periods_found


def _extract_roe_fcf(
    normalized: str, content: str, result: AnalysisResult, source_period: str | None
) -> None:
    block_periods = _extract_roe_fcf_block(content, result)

    # Dedup key is period alone (not period+value): a presentation can mention
    # ROE/FCF for the same period more than once (whole-bank vs. a subsidiary,
    # or restated later in a detail slide) — keep only the first, consistent
    # with the banking-ratio table's same "first occurrence wins" policy.
    seen_roe: set[str | None] = set()
    for m in _RE_ROE_INLINE.finditer(normalized):
        period = _nearest_fy_period(normalized, m.start(), source_period)
        if period in block_periods or period in seen_roe:
            continue
        seen_roe.add(period)
        result.facts.append(
            _pf(
                FactKind.FINANCIAL_ROE,
                float(m.group(1)),
                FactUnit.PERCENT,
                period,
                "roe",
                m.start(),
                m.group(0),
            )
        )

    seen_fcf: set[str | None] = set()
    for m in _RE_FCF_INLINE.finditer(normalized):
        period = _nearest_fy_period(normalized, m.start(), source_period)
        if period in block_periods or period in seen_fcf:
            continue
        value = float(m.group(1).replace(",", ""))
        seen_fcf.add(period)
        result.facts.append(
            _pf(
                FactKind.FINANCIAL_FCF,
                value,
                FactUnit.CRORE_INR,
                period,
                "fcf",
                m.start(),
                m.group(0),
            )
        )


# ---------------------------------------------------------------------------
# 5. Customer Satisfaction Score (services-sector concept; simply won't fire
#    for companies that don't disclose it)
# ---------------------------------------------------------------------------

_RE_CSAT_MARKER = re.compile(r"Customer\s+Satisfaction", re.IGNORECASE)
_RE_CSAT_VALUE = re.compile(r"(\d{2}\.\d{1,2})\s*%")
_RE_CSAT_PERIOD = re.compile(r"(H[12]\s*FY\d{2})", re.IGNORECASE)


def _half_year_period(label: str) -> str | None:
    """Convert 'H1 FY26' -> '2025-09-30', 'H2 FY23' -> '2023-03-31'."""
    m = re.match(r"H([12])\s*FY(\d{2})", label.strip(), re.IGNORECASE)
    if not m:
        return None
    half = int(m.group(1))
    fy_year = 2000 + int(m.group(2))
    return f"{fy_year - 1}-09-30" if half == 1 else f"{fy_year}-03-31"


def _extract_csat(content: str, result: AnalysisResult) -> None:
    """Extract the most recent half-year CSAT score, when disclosed.

    "Customer Satisfaction" can appear more than once in a deck — a real TCS
    filing mentions it once in an unrelated AI-adoption stat (a bare
    percentage with no period label) before the actual half-year CSAT
    section. Every occurrence is tried in turn until one has a nearby
    period label; a marker without one is not treated as a failure.
    """
    for m_marker in _RE_CSAT_MARKER.finditer(content):
        window = content[max(0, m_marker.start() - 1200) : m_marker.start() + 200]
        vals = _RE_CSAT_VALUE.findall(window)
        periods = _RE_CSAT_PERIOD.findall(window)
        if not periods:
            continue
        # A 1200-char backward window can pick up unrelated stray
        # percentages from an earlier, different slide (segment growth
        # rates etc.) alongside the real CSAT bar-chart values. The real
        # values are always the ones immediately preceding the period
        # labels (closest to the marker) — take the tail of the list, not
        # the head, so a positional zip does not mis-pair noise with the
        # real periods.
        vals = vals[-len(periods) :] if len(vals) >= len(periods) else vals
        pairs = list(zip(vals, periods))
        if not pairs:
            continue
        latest_val, latest_label = pairs[-1]
        period = _half_year_period(latest_label)
        result.facts.append(
            _pf(
                FactKind.STRATEGY_CSAT,
                float(latest_val),
                FactUnit.PERCENT,
                period,
                "csat",
                m_marker.start(),
                f"CSAT {latest_val}% {latest_label}",
            )
        )
        return


# ---------------------------------------------------------------------------
# 6. Banking ratio family — labelled comparison table
# ---------------------------------------------------------------------------

# Bounds the search to a labelled KPI table so that a stray mention of e.g.
# "margin" in prose elsewhere in the document is not mistaken for a table row.
_RE_KPI_TABLE_HEADING = re.compile(
    r"Key\s+(?:Financial\s+)?Indicators|Financial\s+(?:Summary|Highlights)|Key\s+Ratios",
    re.IGNORECASE,
)

# (label pattern, FactKind, FactUnit) — order matters: more specific labels
# (Net Interest Margin) must be tried before their substrings would otherwise
# ambiguously match a shorter pattern.
_BANK_RATIO_ROWS: list[tuple[re.Pattern[str], FactKind, FactUnit]] = [
    (
        re.compile(r"^Net\s+Interest\s+Margin", re.IGNORECASE),
        FactKind.FINANCIAL_NET_INTEREST_MARGIN,
        FactUnit.PERCENT,
    ),
    (
        re.compile(r"^Net\s+Interest\s+Income", re.IGNORECASE),
        FactKind.FINANCIAL_NET_INTEREST_INCOME,
        FactUnit.CRORE_INR,
    ),
    (
        re.compile(r"^Gross\s+NPA", re.IGNORECASE),
        FactKind.FINANCIAL_GROSS_NPA_RATIO,
        FactUnit.PERCENT,
    ),
    (
        re.compile(r"^Net\s+NPA", re.IGNORECASE),
        FactKind.FINANCIAL_NET_NPA_RATIO,
        FactUnit.PERCENT,
    ),
    (
        re.compile(r"^Provision\s+Coverage|^PCR\b", re.IGNORECASE),
        FactKind.FINANCIAL_PROVISION_COVERAGE_RATIO,
        FactUnit.PERCENT,
    ),
    (
        re.compile(r"^Credit\s+Cost", re.IGNORECASE),
        FactKind.FINANCIAL_CREDIT_COST,
        FactUnit.PERCENT,
    ),
    (
        re.compile(r"^CASA\b", re.IGNORECASE),
        FactKind.FINANCIAL_CASA_RATIO,
        FactUnit.PERCENT,
    ),
    (
        re.compile(r"^Capital\s+Adequacy", re.IGNORECASE),
        FactKind.FINANCIAL_CAPITAL_ADEQUACY_RATIO,
        FactUnit.PERCENT,
    ),
    (
        re.compile(r"^Slippage\s+Ratio", re.IGNORECASE),
        FactKind.FINANCIAL_SLIPPAGE_RATIO,
        FactUnit.PERCENT,
    ),
]


def _extract_banking_ratios(
    content: str, result: AnalysisResult, source_period: str | None
) -> None:
    """Populate the banking ratio family from a labelled KPI table, when present.

    Absence of any matching row is expected and unremarkable for the large
    majority of (non-financial-sector) companies — no warning is raised for
    that case, since it is not an extraction failure, just a concept that
    does not apply.
    """
    m_heading = _RE_KPI_TABLE_HEADING.search(content)
    if not m_heading:
        return
    region = content[m_heading.end() : m_heading.end() + 4000]

    # Presentations often restate the same ratio in more than one section
    # (a summary "Key indicators" table, then a detailed "Capital Adequacy"
    # breakdown slide later). Keep only the first occurrence of each ratio —
    # it is consistently the summary-table value in every filing reviewed —
    # rather than emitting conflicting duplicates for the same period.
    seen_kinds: set[FactKind] = set()
    search_from = 0
    for line in region.split("\n"):
        line_start = region.find(line, search_from)
        search_from = line_start + len(line)
        stripped = line.strip()
        if not stripped:
            continue
        for label_re, kind, unit in _BANK_RATIO_ROWS:
            if kind in seen_kinds or not label_re.match(stripped):
                continue
            values = extract_n_values(region, line_start + len(line), n=3)
            numeric = [v for v in values if v is not None]
            if not numeric:
                break
            # Table layout observed: [prior_period, current_period, yoy_delta%].
            # Two-column layout: [prior_period, current_period].
            current = numeric[1] if len(numeric) >= 2 else numeric[0]
            result.facts.append(
                _pf(
                    kind,
                    current,
                    unit,
                    source_period,
                    "kpi_table",
                    m_heading.end() + line_start,
                    stripped,
                )
            )
            seen_kinds.add(kind)
            break


# ---------------------------------------------------------------------------
# 7. Physical production / delivery volume (industrial companies)
# ---------------------------------------------------------------------------

_RE_PRODUCTION_ROW = re.compile(
    r"^Production\s*\(m[n.]?\s*tons?\)",
    re.IGNORECASE | re.MULTILINE,
)
_RE_DELIVERY_ROW = re.compile(
    r"^Deliveries\s*\(m[n.]?\s*tons?\)",
    re.IGNORECASE | re.MULTILINE,
)


def _extract_volume_row(
    content: str,
    pattern: re.Pattern[str],
    kind: FactKind,
    result: AnalysisResult,
    source_period: str | None,
) -> None:
    m = pattern.search(content)
    if not m:
        return
    # Skip to the next newline before scanning for values: a footnote
    # superscript digit is often appended directly to the row label with no
    # separating newline ("Production (mn tons)2 \n6.22 \n..."), and would
    # otherwise be read by extract_n_values as the row's first (and, at
    # n=1, only) value instead of the real production figure.
    line_end = content.find("\n", m.end())
    scan_from = line_end if line_end != -1 else m.end()
    values = extract_n_values(content, scan_from, n=1)
    numeric = [v for v in values if v is not None]
    if not numeric:
        return
    result.facts.append(
        _pf(
            kind,
            numeric[0],
            FactUnit.MILLION_TONNES,
            source_period,
            "operating_volume",
            m.start(),
            m.group(0),
            confidence="medium",  # column position within a multi-scope table is a best-effort guess
        )
    )


# ---------------------------------------------------------------------------
# 8. Segment name + YoY growth — value-then-label infographic callouts
# ---------------------------------------------------------------------------

# One short connector line ("in" / "of" / "for" / "the") is sometimes
# inserted by the PDF's line-wrapping between the growth-label and the real
# name (observed in SBI's "YoY Growth in\nDeposits" callouts) — skip past it
# rather than capturing the connector itself as the segment name.
_RE_SERVICE_GROWTH = re.compile(
    r"([\d.]+)%\s*\n(?:Y-?O-?Y\s*CC|YoY|Y-?o-?Y)[^\n]{0,20}\n"
    r"(?:(?:in|of|for|the)\s*\n)?"
    r"([^\n]{2,60})"
)
_SEGMENT_STOPWORDS = frozenset({"in", "of", "for", "the", "and", "to", "a"})


def _extract_segment_growth(content: str, result: AnalysisResult) -> None:
    seen: set[str] = set()
    for m in _RE_SERVICE_GROWTH.finditer(content):
        seg_name = m.group(2).strip()
        if (
            seg_name.lower() in seen
            or not seg_name
            or seg_name.lower() in _SEGMENT_STOPWORDS
        ):
            continue
        seen.add(seg_name.lower())
        pct_val = float(m.group(1))
        result.facts.append(
            _pf(
                FactKind.SEGMENT_NAME,
                seg_name,
                None,
                None,
                "service_growth",
                m.start(),
                m.group(0),
            )
        )
        result.facts.append(
            _pf(
                FactKind.SEGMENT_GROWTH_PCT,
                pct_val,
                FactUnit.PERCENT,
                None,
                "service_growth",
                m.start(),
                m.group(0),
            )
        )


# ---------------------------------------------------------------------------
# 9. Management commentary — excerpt only, not a fact
# ---------------------------------------------------------------------------

_RE_MGMT_COMMENTARY = re.compile(
    r"Management\s+Comments?\s*:?\s*\n"
    r"((?:Mr\.|Ms\.|Mrs\.|Dr\.)[^\n]{5,80}:.{100,4000}?)"
    r"(?=\n(?:Disclaimer|Mr\.|Ms\.|Mrs\.|Dr\.|About\s)|\Z)",
    re.DOTALL,
)


def _extract_management_commentary(content: str, result: AnalysisResult) -> None:
    m = _RE_MGMT_COMMENTARY.search(content)
    if m:
        result.excerpts["management_commentary"] = m.group(1)[:2000]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def analyze(evidence_id: str, kb: KnowledgeBase) -> AnalysisResult:
    """Extract structured facts from an investor presentation filing.

    Raises ValueError for missing, wrong-kind, or empty-content documents.
    """
    entry = kb.get(evidence_id)
    if entry is None:
        raise ValueError(
            f"cannot analyze evidence_id={evidence_id!r}: not in knowledge base"
        )
    if entry.kind != "investor_presentation":
        raise ValueError(
            f"cannot analyze evidence_id={evidence_id!r}: "
            f"kind={entry.kind!r} is not 'investor_presentation'"
        )

    content = kb.get_content(evidence_id)
    if not content:
        raise ValueError(
            f"cannot analyze evidence_id={evidence_id!r}: document has no content"
        )

    content = content.replace("ﬁ", "fi").replace("ﬂ", "fl")

    result = AnalysisResult(
        evidence_id=evidence_id,
        kind="investor_presentation",
        analyzer_version=ANALYZER_VERSION,
        confidence="low",
        source_date=datetime.fromisoformat(entry.source_date),
    )

    normalized = re.sub(r"[ \t]*\n[ \t]*", " ", content)

    period, period_type, period_offset = _detect_period(normalized[:3000])
    if period:
        result.facts.append(
            _pf(
                FactKind.REPORT_PERIOD_END,
                period,
                FactUnit.ISO_DATE,
                period,
                "cover_letter",
                period_offset or 0,
                period,
            )
        )
        if period_type is not None:
            result.facts.append(
                _pf(
                    FactKind.REPORT_PERIOD_TYPE,
                    period_type,
                    None,
                    period,
                    "cover_letter",
                    period_offset or 0,
                    period_type,
                )
            )
    else:
        result.warnings.append("Could not detect reporting period from cover letter")

    _extract_aspiration(normalized, result)
    _extract_priorities(content, result)
    _extract_guidance(normalized, content, result)
    _extract_roe_fcf(normalized, content, result, period)
    _extract_csat(content, result)
    _extract_banking_ratios(content, result, period)
    _extract_volume_row(
        content,
        _RE_PRODUCTION_ROW,
        FactKind.FINANCIAL_PRODUCTION_VOLUME,
        result,
        period,
    )
    _extract_volume_row(
        content, _RE_DELIVERY_ROW, FactKind.FINANCIAL_DELIVERY_VOLUME, result, period
    )
    _extract_segment_growth(content, result)
    _extract_management_commentary(content, result)

    # Confidence reflects breadth: how many independent fact *categories*
    # were found, not raw fact count (a single category firing 8 times should
    # not outrank three categories firing once each).
    categories_found = len(
        {
            (
                f.kind.name.split("_")[0]
                if not f.kind.name.startswith(("STRATEGY", "SEGMENT", "FINANCIAL"))
                else f.kind.name
            )
            for f in result.facts
            if f.kind not in (FactKind.REPORT_PERIOD_END, FactKind.REPORT_PERIOD_TYPE)
        }
    )
    if categories_found >= 3:
        result.confidence = "high"
    elif categories_found >= 1:
        result.confidence = "medium"
    elif period:
        result.confidence = "medium"

    return result
