"""Rule-based fact extraction from AGM notice filings (SEBI Reg 44(3) and Reg 30).

Two sub-types are recognised:

  voting_results — Post-AGM filing with the Annexure B/C voting summary table
                   and per-resolution scrutineer report. Filed under Regulation
                   44(3). Extracts resolution descriptions, types, outcomes, and
                   vote percentages (in-favour / against) for each resolution.

  notice         — Pre-meeting AGM notice package (sometimes large, up to 1 MB).
                   Contains the proposed resolutions but no voting outcomes.
                   No structured facts are extracted from notice sub-type.

Resolution linking:
  All facts for the same resolution share provenance.section = "resolution_N"
  (where N is the resolution number as filed). Downstream aggregation can group
  facts by (period, section) to reconstruct the full resolution record.

Vote percentage extraction:
  AGM PDFs use column-major table extraction, producing two layouts:
  - "Total row" format: grand total row appears just before the "Whether
    resolution is Pass" marker; the last two XX.XXXX decimals in that row
    are %_for and %_against.
  - "Column split" format: column (6) % in-favour values appear between
    "Whether...is Pass" and "Yes/No"; the grand total is the last XX.XXXX
    value before the column (7) header, and the grand total % against is the
    last XX.XXXX value before "Yes/No".
  Both formats are tried in order; the first whose pair sums to ~100 is used.
  If neither yields a valid pair, a warning is added and vote % is skipped.
"""
from __future__ import annotations

import re
from datetime import datetime

from atlas.analysis.base import (
    AnalysisResult,
    AnalysisFact,
    FactKind,
    FactUnit,
    Provenance,
    _snip,
)
from atlas.knowledge.base import KnowledgeBase

ANALYZER_VERSION = "1.0"

_MONTH_MAP = {
    "january": "01", "february": "02", "march": "03", "april": "04",
    "may": "05", "june": "06", "july": "07", "august": "08",
    "september": "09", "october": "10", "november": "11", "december": "12",
}

# ---------------------------------------------------------------------------
# Compiled patterns
# ---------------------------------------------------------------------------

_RE_AGM_DATE = re.compile(
    r"(?:Annual\s+General\s+Meeting|AGM)[^.]{0,80}?was\s+held\s+on\s+"
    r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s*"
    r"([A-Z][a-z]+ \d{1,2},?\s*\d{4})",
    re.I,
)

_RE_AGM_DATE_ALT = re.compile(
    r"Date\s+of\s+the\s+AGM\s+(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s*"
    r"([A-Z][a-z]+ \d{1,2},?\s*\d{4})",
    re.I,
)

# Regulation 44(3) indicates post-AGM voting results filing
_RE_REG_44 = re.compile(r"Regulation\s+44\s*\(\s*3\s*\)", re.I)

# "VOTING RESULTS OF THE MEETING" section header (2024/2025 format)
_RE_VOTING_RESULTS_SECTION = re.compile(
    r"VOTING\s+RESULTS\s+(?:OF\s+THE\s+MEETING)?\s*\n",
    re.I,
)

# Proceedings table header (2026 format)
_RE_PROCEEDINGS_RESOLUTIONS = re.compile(
    r"(?:following\s+resolutions|resolutions?\s+set\s+out).{0,60}?"
    r"(?:put\s+to\s+vote|passed\s+by\s+(?:the\s+)?members)",
    re.I | re.DOTALL,
)

# Global outcome: "All the Resolutions were declared as passed"
_RE_ALL_PASSED = re.compile(
    r"All\s+(?:the\s+)?[Rr]esolution\w*\s+were\s+declared\s+as\s+passed",
    re.I,
)

# Per-resolution outcome (in summary table entries)
_RE_PASSED = re.compile(r"Passed\s+with\s+requisite\s+majority", re.I)

# Resolution (N) detailed block header — tolerates OCR garbling e.g. "Resolutio(4)"
_RE_RES_BLOCK = re.compile(r"Resolutio[^\s(]{0,3}\s*\(\s*(\d{1,2})\s*\)", re.I)

# Column (7) header — separates % in-favour from % against columns
_RE_COL7_HEADER = re.compile(r"\(\s*7\s*\)\s*=", re.I)

# Whether-resolution-is-Pass marker
_RE_WHETHER = re.compile(r"Whether\s+resolution\s+[il]s\s+Pass", re.I)

# "Yes" pass/fail — handles OCR variants: "Yes", ""es", "'es"
_RE_YES = re.compile(r"""(?:\bYes\b|["'“‘]es\b)""", re.I)
_RE_NO = re.compile(r"\bNo\b")

# Four-decimal percentage (columns 6 and 7 values)
_RE_PCT4 = re.compile(r"\b(\d{1,3}\.\d{4})\b")

# Page header lines to strip from description text
_HEADER_STRIP = re.compile(
    r"^(?:Sr\.|Agenda|Resolution\s+required|Mode\s+of|Voting\s*$|Remarks\s*$|"
    r"TATA|Tata\s+Consultancy|9th\s+Floor|Tel\s|Register|Corporate\s+Identity|"
    r"Res\.?\s*No\.?|Brief\s+Description|Resolution\s+Type)",
    re.I | re.M,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_date(date_str: str) -> str | None:
    """'June 19, 2025' → '2025-06-19'; returns None on failure."""
    date_str = re.sub(r",", "", date_str.strip())
    parts = date_str.split()
    if len(parts) < 3:
        return None
    month_key = parts[0].lower()
    if month_key not in _MONTH_MAP:
        return None
    try:
        day = int(parts[1])
        year = int(parts[2])
        return f"{year}-{_MONTH_MAP[month_key]}-{day:02d}"
    except (ValueError, IndexError):
        return None


def _pf(
    kind: FactKind,
    value: str | float | int | None,
    unit: FactUnit | None,
    period: str | None,
    section: str,
    offset: int,
    excerpt: str,
    confidence: str = "high",
) -> AnalysisFact:
    """Construct a period-carrying AnalysisFact with Provenance."""
    return AnalysisFact(
        kind=kind,
        value=value,
        unit=unit,
        period=period,
        confidence=confidence,  # type: ignore[arg-type]
        provenance=Provenance(
            section=section,
            char_offset=offset,
            excerpt=excerpt[:120],
        ),
    )


def _clean_description(raw: str) -> str:
    """Normalise multi-line PDF-extracted description text to a single line."""
    lines = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        if _HEADER_STRIP.match(line):
            continue
        if re.match(r"^[\W\d]+$", line):
            continue
        lines.append(line)
    desc = " ".join(lines)
    desc = re.sub(r"\s+", " ", desc).strip()
    # Trim trailing mode-of-voting text that bleeds in
    desc = re.sub(r"\s+Remote\s+e.voting.*$", "", desc, flags=re.I).strip()
    return desc


# ---------------------------------------------------------------------------
# Sub-type detection
# ---------------------------------------------------------------------------

def _detect_subtype(content: str) -> str:
    """'voting_results' if post-AGM outcome filing; else 'notice'."""
    if _RE_VOTING_RESULTS_SECTION.search(content) or _RE_ALL_PASSED.search(content[:8000]):
        return "voting_results"
    return "notice"


# ---------------------------------------------------------------------------
# Resolution summary extraction
# ---------------------------------------------------------------------------

def _extract_format_a(content: str) -> list[tuple[int, str, str, str]]:
    """Format A (2024/2025): numbered entries in 'VOTING RESULTS OF THE MEETING' section.

    Returns list of (res_num, description, res_type, outcome).
    """
    m = _RE_VOTING_RESULTS_SECTION.search(content)
    if not m:
        return []

    # Section ends at the first "Resolution (1)" detailed block
    detail_m = _RE_RES_BLOCK.search(content, m.end())
    end = detail_m.start() if detail_m else len(content)
    section_text = content[m.end():end]

    # Split on numbered resolution markers "N.\n" or "N.  \n"
    parts = re.split(r"\n(\d{1,2})\.\s+\n", section_text)
    # parts layout: [pre, num1, text1, num2, text2, ...]

    results: list[tuple[int, str, str, str]] = []
    for res_num_str, entry_text in zip(parts[1::2], parts[2::2]):
        res_num = int(res_num_str)
        # Take the LAST type-keyword match — description text may contain embedded
        # "special" (e.g., "special dividend") that appears on its own line due to
        # PDF word-wrap, which would cause the first match to misfire.
        type_matches = list(re.finditer(r"\n(Ordinary|Special)\s*\n", entry_text, re.I))
        if not type_matches:
            continue
        type_m = type_matches[-1]

        raw_desc = entry_text[: type_m.start()]
        description = _clean_description(raw_desc)
        if not description:
            continue

        res_type = type_m.group(1).lower()
        remaining = entry_text[type_m.end():]
        outcome = "passed" if _RE_PASSED.search(remaining) else "not_passed"
        results.append((res_num, description, res_type, outcome))

    return results


def _extract_format_b(content: str) -> list[tuple[int, str, str, str]]:
    """Format B (2026): numbered entries in proceedings section; global outcome.

    Triggered when a proceedings resolution list exists but no VOTING RESULTS
    OF THE MEETING table.
    """
    m = _RE_PROCEEDINGS_RESOLUTIONS.search(content)
    if not m:
        return []

    # Section ends at next blank-line block or "Members who attended"
    section_end_m = re.search(r"\nMembers\s+who\s+attended", content[m.end():], re.I)
    end = m.end() + section_end_m.start() if section_end_m else m.end() + 3000
    section_text = content[m.end():end]

    # Global outcome from proceedings paragraph
    global_passed = bool(_RE_ALL_PASSED.search(content[m.end(): m.end() + 5000]))

    # Match numbered entries: single digit or double digit NOT followed by period
    # pattern: "\n1\nTo receive..." — number on its own line before description
    parts = re.split(r"\n(\d{1,2})\s*\n", section_text)

    results: list[tuple[int, str, str, str]] = []
    for res_num_str, entry_text in zip(parts[1::2], parts[2::2]):
        res_num = int(res_num_str)
        type_m = re.search(r"\n(Ordinary|Special)\s*\n?", entry_text, re.I)
        if not type_m:
            continue
        raw_desc = entry_text[: type_m.start()]
        description = _clean_description(raw_desc)
        if not description:
            continue
        res_type = type_m.group(1).lower()
        outcome = "passed" if global_passed else "not_passed"
        results.append((res_num, description, res_type, outcome))

    return results


# ---------------------------------------------------------------------------
# Vote percentage extraction from Resolution (N) detailed blocks
# ---------------------------------------------------------------------------

def _extract_vote_pcts(block_text: str) -> tuple[float | None, float | None]:
    """Return (pct_for, pct_against) grand totals from one resolution's detail block.

    Strategy: all valid formats share one property — the grand total % against is
    the LAST XX.XXXX decimal appearing before the pass/fail 'Yes'/'No' marker.
    Finding % for varies by layout:

      A. Column-split (most 2025 blocks): col (6) values then col (7) header then
         col (7) values; grand total % for = last XX.XXXX before the col (7) header
         in the tail between 'Whether' and 'Yes'.
      A-robust. Same but col (7) header is garbled: compute expected_for = 100 -
         pct_against and find the closest match in the tail's value list.
      B. Total-row (2025 Res(1)): last two XX.XXXX values before 'Whether' sum
         to ~100.
    Returns (None, None) if no layout yields a pair whose sum is within 0.05 of
    100.0.
    """
    whether_m = _RE_WHETHER.search(block_text)
    if not whether_m:
        return None, None

    tail = block_text[whether_m.end():]
    yes_m = _RE_YES.search(tail)

    # ---- Layouts A / A-robust (column-split format, tail contains col 6+7) ----
    if yes_m:
        before_yes = tail[: yes_m.start()]
        tail_pcts = [float(p) for p in _RE_PCT4.findall(before_yes)]

        if tail_pcts:
            pct_against = tail_pcts[-1]

            # Layout A: clean col (7) header separates col 6 from col 7
            col7_m = _RE_COL7_HEADER.search(before_yes)
            if col7_m:
                before_col7_pcts = [float(p) for p in _RE_PCT4.findall(before_yes[: col7_m.start()])]
                if before_col7_pcts:
                    pct_for = before_col7_pcts[-1]
                    if abs(pct_for + pct_against - 100.0) < 0.05:
                        return pct_for, pct_against

            # Layout A-robust: col (7) header garbled or absent; complement search.
            # The grand total % for is the tail value closest to (100 - pct_against).
            expected_for = 100.0 - pct_against
            if 0.0 <= expected_for <= 100.0:
                candidates = tail_pcts[:-1]
                if candidates:
                    closest = min(candidates, key=lambda x: abs(x - expected_for))
                    if abs(closest - expected_for) < 0.02:
                        return closest, pct_against

    # ---- Layout B: Total-row format (grand totals precede 'Whether') -----------
    before_whether = block_text[: whether_m.start()]
    pcts_bw = [float(p) for p in _RE_PCT4.findall(before_whether)]
    if len(pcts_bw) >= 2:
        pct_for     = pcts_bw[-2]
        pct_against = pcts_bw[-1]
        if abs(pct_for + pct_against - 100.0) < 0.05:
            return pct_for, pct_against

    return None, None


# ---------------------------------------------------------------------------
# Main extraction
# ---------------------------------------------------------------------------

def _extract_voting_results(
    content: str,
    result: AnalysisResult,
    agm_date: str,
) -> None:
    """Extract resolution facts from a voting_results document."""

    # 1. Resolution summaries (descriptions, types, outcomes)
    summaries = _extract_format_a(content) or _extract_format_b(content)
    if not summaries:
        result.warnings.append("could not extract resolution summary table")

    summary_map: dict[int, tuple[str, str, str]] = {
        num: (desc, typ, out) for num, desc, typ, out in summaries
    }

    # 2. Find all Resolution (N) detailed blocks for vote percentages
    block_starts = [(int(m.group(1)), m.start()) for m in _RE_RES_BLOCK.finditer(content)]
    vote_pcts: dict[int, tuple[float, float]] = {}

    for idx, (res_num, block_start) in enumerate(block_starts):
        next_start = block_starts[idx + 1][1] if idx + 1 < len(block_starts) else len(content)
        block_text = content[block_start:next_start]
        pct_for, pct_against = _extract_vote_pcts(block_text)
        if pct_for is not None and pct_against is not None:
            vote_pcts[res_num] = (pct_for, pct_against)

    # 3. Emit facts — resolution description, type, outcome, vote percentages
    all_res_nums = sorted(set(list(summary_map.keys()) + list(vote_pcts.keys())))

    for res_num in all_res_nums:
        section = f"resolution_{res_num}"

        if res_num in summary_map:
            desc, res_type, outcome = summary_map[res_num]
            offset = content.find(desc[:30]) if desc else 0

            result.facts.append(_pf(
                FactKind.GOVERNANCE_RESOLUTION_TITLE, desc, None,
                agm_date, section, offset, desc[:80],
            ))
            result.facts.append(_pf(
                FactKind.GOVERNANCE_RESOLUTION_TYPE, res_type, None,
                agm_date, section, offset, res_type,
            ))
            result.facts.append(_pf(
                FactKind.GOVERNANCE_RESOLUTION_OUTCOME, outcome, None,
                agm_date, section, offset, outcome,
            ))

        if res_num in vote_pcts:
            pct_for, pct_against = vote_pcts[res_num]
            block_starts_dict = dict(block_starts)
            vote_offset = block_starts_dict.get(res_num, 0)

            result.facts.append(_pf(
                FactKind.GOVERNANCE_VOTE_PCT_FOR, round(pct_for, 4), FactUnit.PERCENT,
                agm_date, section, vote_offset, f"{pct_for:.4f}%",
                confidence="medium",
            ))
            result.facts.append(_pf(
                FactKind.GOVERNANCE_VOTE_PCT_AGAINST, round(pct_against, 4), FactUnit.PERCENT,
                agm_date, section, vote_offset, f"{pct_against:.4f}%",
                confidence="medium",
            ))

    # 4. Warn if vote percentage extraction yielded nothing
    if block_starts and not vote_pcts:
        result.warnings.append(
            f"found {len(block_starts)} Resolution(N) blocks but could not extract "
            "vote percentages from any of them"
        )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def analyze(evidence_id: str, kb: KnowledgeBase) -> AnalysisResult:
    """Analyze one agm_notice evidence document.

    Extracts:
    - voting_results sub-type: per-resolution title, type, outcome, and vote
      percentages (% in-favour / % against) keyed by AGM date.
    - notice sub-type: no structured facts; sub-type recorded in excerpts.
    """
    entry = kb.get(evidence_id)
    if entry is None:
        raise ValueError(f"evidence_id {evidence_id!r} not found in KnowledgeBase")
    if entry.kind != "agm_notice":
        raise ValueError(
            f"evidence_id {evidence_id!r} has kind {entry.kind!r}; expected 'agm_notice'"
        )

    content = kb.get_content(evidence_id) or ""

    # Catalog stores source_date as an ISO string; unit test fixtures may pass
    # a pre-converted datetime.  Normalise to datetime once here.
    source_dt = (
        entry.source_date
        if isinstance(entry.source_date, datetime)
        else datetime.fromisoformat(entry.source_date)
    )

    result = AnalysisResult(
        evidence_id=evidence_id,
        kind="agm_notice",
        analyzer_version=ANALYZER_VERSION,
        confidence="low",
        source_date=source_dt,
    )

    if not content.strip():
        result.warnings.append("document content is empty")
        return result

    subtype = _detect_subtype(content)
    result.excerpts["subtype"] = subtype

    if subtype == "notice":
        result.confidence = "low"
        result.warnings.append(
            "pre-meeting AGM notice — no voting outcome facts extracted"
        )
        return result

    # --- voting_results sub-type ---

    # AGM date
    agm_date: str | None = None
    date_m = _RE_AGM_DATE.search(content[:6000])
    if not date_m:
        date_m = _RE_AGM_DATE_ALT.search(content[:6000])
    if date_m:
        agm_date = _parse_date(date_m.group(1))
        if agm_date:
            result.excerpts["agm_date"] = agm_date

    if agm_date is None:
        result.warnings.append("could not extract AGM date from cover letter")
        # Fall back to filing date
        agm_date = source_dt.strftime("%Y-%m-%d")

    _extract_voting_results(content, result, agm_date)

    # Confidence: based on how many resolution titles were extracted
    title_count = sum(
        1 for f in result.facts if f.kind == FactKind.GOVERNANCE_RESOLUTION_TITLE
    )
    if title_count >= 3:
        result.confidence = "high"
    elif title_count >= 1:
        result.confidence = "medium"
    else:
        result.confidence = "low"
        result.warnings.append("no resolution titles extracted — check document format")

    return result
