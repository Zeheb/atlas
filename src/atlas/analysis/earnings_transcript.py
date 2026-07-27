"""Rule-based fact extraction from earnings call / analyst meet transcripts
(SEBI Reg-30 disclosures filed after quarterly Board of Directors meetings).

v2.0 redesign (2026-07). v1.0 was built and validated exclusively against
TCS: its docstring named TCS's actual speakers as if they were structural
constants, its CFO-section splitter recognized only TCS's two known
quarterly/annual boundary phrasings, and its core "find the CFO's speaker
turn" gate assumed a single named CFO exists at all. A full-transcript
survey across TCS, Tata Steel, and SBI (2026-07) found that assumption
false: SBI has no CEO or CFO — a Chairman plus four Managing Directors each
own a business vertical, and the Chairman delivers all headline financial
commentary directly. Tata Steel's CFO gives one continuous narrative
covering the quarter, the full year, the balance sheet, and per-geography
detail with no clean two-way split at all. A data-catalog bug was also
found and fixed during that survey: SBI's real transcripts (7 documents)
were mis-catalogued as investor_presentation and would have been invisible
to this analyzer regardless of how well it was redesigned.

Design shift from v1.0
-----------------------
v1.0 gated all numeric extraction behind first correctly identifying "the
CFO's speaker turn" — a single point of failure that breaks the moment a
company's speaker structure doesn't match TCS's. v2.0 instead bounds the
search to the *prepared remarks* region (transcript start to the first
Q&A-transition phrase) and searches that whole region for each concept
independently, the same content-anchored, no-hard-gate approach validated
in investor_presentation.py v2.0 this session. Speaker/role detection is
retained only as a best-effort source for excerpts and provenance — it is
no longer a prerequisite for any fact to be extracted.

Fact vocabulary
----------------
No new FactKinds were introduced. A dedicated investment-value audit against
real filings found every genuinely new, high-value concept already has a
home in the existing ontology:

  REPORT_PERIOD_END / REPORT_PERIOD_TYPE   Quarter/year end; from cover
                                            letter or a "QN FYyy" label.
  FINANCIAL_REVENUE          Quarterly revenue (CRORE_INR or USD_BILLION);
                              annual too, for Q4/full-year calls.
  FINANCIAL_OPERATING_MARGIN Operating/EBITDA margin %; PERCENT.
  FINANCIAL_NET_MARGIN       Net income margin %; PERCENT.
  FINANCIAL_TCV              Total Contract Value; USD_BILLION. IT-services
                              specific — simply will not fire elsewhere.
  STRATEGY_GUIDANCE          Forward targets spoken aloud (Tata Steel's
                              FY2027 capex target, SBI's "NIM above 3%"
                              guidance) — reuses the same FactKind and the
                              same shared pattern (patterns.find_guidance_
                              statements) as investor_presentation.py.
  ESG_WORKFORCE_HEADCOUNT,   Reused from BRSR's ontology, not new. BRSR
  ESG_WORKFORCE_FEMALE_PCT   supplies these annually; TCS's CHRO/COO restate
                              them (headcount, % women) every quarter on the
                              earnings call — a materially higher-frequency
                              version of an existing fact, exactly the case
                              Stage 4 of the review was designed to catch.

Explicitly NOT extracted (checked against Stage 4 of the review):
  - Revenue/PAT/margin *actuals* already covered by financial_results —
    kept as supplement-only (setdefault), matching v1.0's policy.
  - Banking ratios (NIM, NPA, PCR, CASA) — already extracted from investor
    decks by investor_presentation.py; the transcript restates the same
    table, not a materially richer version.
  - Client concentration bands ($100M+/$50M+/$1M+ accounts) — real Tier-1
    value with no existing representation, but a single-company (TCS)
    revenue-banding convention observed in this 3-company sample. Adding a
    bespoke FactKind for one company's disclosure convention risks exactly
    the ontology bloat the freeze policy exists to prevent — deferred
    pending evidence it recurs across more companies.
  - Macro/system-level commentary (SBI's IMF/RBI growth and inflation
    outlook) — genuinely present, but not company-specific and trivially
    available from any bank's material or the RBI directly. Extracting it
    would be facts for facts' sake against Atlas's stated objective.
  - Segment/geography/vertical demand color, deal-pipeline narrative —
    real value, but irreducibly qualitative prose (not a single number or
    short categorical value). Captured as excerpts, matching the existing
    precedent for unstructured commentary elsewhere in the codebase, not
    forced into a numeric or enum FactKind.

Section boundaries
-------------------
prepared_remarks   Transcript start (after the Reg-30 cover letter) to the
                    first Q&A-transition phrase ("we will now begin the
                    question-and-answer session", "now invite questions",
                    etc.). All numeric facts are searched here only — an
                    analyst's question or a hypothetical comparison number
                    in the Q&A is far more likely to be misread as a
                    company figure than anything in the scripted remarks.
qa_section          Everything after that boundary. Not currently searched
                    for facts; reserved for future analyst-question-aware
                    extraction (see retrospective).

Period detection
------------------
Two independent strategies, tried in order:
  1. Cover-letter phrase: "quarter ended March 31, 2026" / "quarter and
     year ended ...". Same pattern family as v1.0, widened to a larger
     window since SBI's Analyst Meet cover letter states the filing date
     but not always the quarter-end date in this exact phrasing.
  2. "QN FYyy" label (e.g. "Q4FY26", "4QFY2025") — ubiquitous across all
     three companies' transcripts and title pages — mapped to the Indian
     fiscal quarter-end date. This is the fallback, not the primary path,
     because a label alone cannot distinguish a mid-year call from a
     Q4-bundled-with-annual one; the phrase-based path answers that.

Speaker / role detection
--------------------------
Best-effort only, used for excerpts and provenance — never a prerequisite
for a fact to be extracted (see "Design shift" above). Two independent
sources, since no single one covers all three companies:
  1. An upfront participant directory, when present (Tata Steel's
     "CORPORATE PARTICIPANTS" list; SBI's "MANAGEMENT" list). Parsed
     generically as consecutive (Name, Role) or (Name \n Role) pairs near
     the document start — company-agnostic by construction, since it reads
     whatever the company chose to print rather than assuming a fixed
     format.
  2. A broadened role-alias table (CEO, Chairman, Managing Director,
     Deputy Managing Director (Finance), CFO, Executive Director, COO,
     CHRO/Chief HR Officer) scanned in the moderator's spoken introduction,
     for companies with no printed directory (TCS).

Excerpts
--------
management_commentary   The first substantive prepared-remarks block from
                          whichever senior speaker was identified (CEO- or
                          Chairman-equivalent), for human review.
financial_commentary     The prepared-remarks block containing the revenue/
                          margin figures actually extracted, for provenance.
"""

from __future__ import annotations

import re
from datetime import datetime

from atlas.analysis.base import (
    AnalysisFact,
    AnalysisResult,
    EntityMention,
    FactKind,
    FactUnit,
    Provenance,
    _snip,
)
from atlas.analysis.patterns import find_guidance_statements, parse_iso_date
from atlas.knowledge.base import KnowledgeBase
from atlas.knowledge.entities import EntityResolver

ANALYZER_VERSION = "2.3"

# Q&A analyst self-introduction, via the moderator (M-P1.2, Q13). Calibrated to
# the Chorus-call convention ubiquitous in Indian earnings transcripts:
#   "...from the line of Ravi Menon \nfrom Macquarie. Please go ahead."
# Newlines fall on either side of the inner "from", so `\s+` spans them. The
# name is 1-4 Title-case tokens; the institution runs lazily to the "Please go
# ahead" anchor, which reliably bounds it.
_RE_ANALYST_INTRO = re.compile(
    r"line of\s+"
    r"([A-Z][A-Za-z.'\-]*(?:\s+[A-Z][A-Za-z.'\-]*){0,3})"
    r"\s+from\s+"
    r"([A-Z][A-Za-z0-9.'&\-]*(?:\s+[A-Za-z0-9.'&\-]+){0,4}?)"
    r"\s*\.\s*Please go ahead",
)


# Cap on the bounded question-turn text (M-P2.8), matching the existing
# management-commentary excerpt cap (analyze()'s `senior_section[:3000]`) --
# reusing that precedent's order of magnitude rather than inventing a new one.
_MAX_QUESTION_CHARS = 3000


def _bounded_question_text(
    content: str, analyst_name: str, search_from: int
) -> str | None:
    """Verbatim text of the analyst's own question turn: from their own
    speaker tag (``Name:``) to the NEXT speaker tag, using the SAME
    ``_RE_ANY_SPEAKER`` boundary ``_speaker_section`` already uses for the
    management turn -- no new segmentation heuristic. Capped at
    ``_MAX_QUESTION_CHARS`` for an unbounded/malformed transcript. ``None`` if
    the analyst's own tag is never found (introduced by the moderator but no
    matching in-dialogue tag in the extracted text), or if the bounded text is
    empty after trimming.
    """
    tag_match = re.compile(re.escape(analyst_name) + r"\s*:", re.MULTILINE).search(
        content, search_from
    )
    if tag_match is None:
        return None
    start = tag_match.end()
    limit = min(start + _MAX_QUESTION_CHARS, len(content))
    next_speaker = _RE_ANY_SPEAKER.search(content, start, limit)
    end = next_speaker.start() if next_speaker else limit
    text = content[start:end].strip()
    return text or None


def _extract_analyst_mentions(
    content: str, resolver: EntityResolver
) -> list[EntityMention]:
    """Resolve the analysts who asked questions, one EntityMention per distinct
    analyst (role="analyst", affiliation=their institution, question_text=their
    bounded question turn). De-duplicated within this transcript by resolved
    entity id -- the first turn only, matching the existing dedup behavior."""
    mentions: list[EntityMention] = []
    seen: set[str] = set()
    for m in _RE_ANALYST_INTRO.finditer(content):
        name = re.sub(r"\s+", " ", m.group(1)).strip()
        affiliation = re.sub(r"\s+", " ", m.group(2)).strip()
        entity = resolver.resolve(name, "person")
        if entity.entity_id in seen:
            continue
        seen.add(entity.entity_id)
        question_text = _bounded_question_text(content, name, m.end())
        mentions.append(
            EntityMention(
                entity=entity,
                role="analyst",
                affiliation=affiliation,
                question_text=question_text,
                provenance=Provenance("qa", m.start(), _snip(content, m.start())),
            )
        )
    return mentions


# Management roster (M-P1.5, Q45). Two observed layouts, both bounded to the
# roster block:
#   Tata Steel "CORPORATE PARTICIPANTS": "Name, Title - Company" per line.
#   SBI "MANAGEMENT:": "MR. NAME" line, title on the next line.
# Under-emit: no roster header -> no management participants (TCS has none).
_RE_ROSTER_HEADER = re.compile(r"CORPORATE PARTICIPANTS|MANAGEMENT TEAM|MANAGEMENT:")
_RE_ROSTER_END = re.compile(r"CONFERENCE CALL PARTICIPANTS|\bPARTICIPANTS\b|Moderator")
# "T V Narendran, CEO & MD - Tata Steel Limited" — name before the comma; the
# remainder is title (+ company) and is captured for affiliation. Kept
# dash-independent so a mis-decoded separator does not lose the name.
_RE_MGMT_COMMA = re.compile(
    r"^[ \t]*([A-Z][A-Za-z.'\-]*(?:[ \t]+[A-Z][A-Za-z.'\-]*){1,3}),[ \t]*(.+?)[ \t]*$",
    re.MULTILINE,
)
# "MR. DINESH KUMAR KHARA" (may share the "MANAGEMENT:" header line, hence [ \t]*).
# Intra-line whitespace only ([ \t], never \n) so a name never absorbs the
# title printed on the following line.
_RE_MGMT_HONORIFIC = re.compile(
    r"^[ \t]*(?:MR|MS|MRS|DR)\.?[ \t]+([A-Z][A-Z.'\-]*(?:[ \t]+[A-Z][A-Z.'\-]*){1,3})[ \t]*$",
    re.MULTILINE,
)
# Company sits after the last dash-like separator in the comma-form remainder.
_RE_ROSTER_SEP = re.compile(r"[–—\-�]")


def _extract_management_mentions(
    content: str, resolver: EntityResolver
) -> list[EntityMention]:
    """Resolve the management team named in the transcript's roster block
    (role="management"; affiliation=company when the line states it). One
    EntityMention per distinct person; under-emit where no roster is printed."""
    h = _RE_ROSTER_HEADER.search(content)
    if h is None:
        return []
    # Include the header line's own tail (SBI prints the first name on it).
    tail = content[h.start() :]
    end = _RE_ROSTER_END.search(tail, h.end() - h.start())
    region = tail[: end.start()] if end else tail[:1200]

    mentions: list[EntityMention] = []
    seen: set[str] = set()

    def _add(raw_name: str, affiliation: str | None, offset: int) -> None:
        name = re.sub(r"\s+", " ", raw_name).strip().title()
        entity = resolver.resolve(name, "person")
        if entity.entity_id in seen:
            return
        seen.add(entity.entity_id)
        mentions.append(
            EntityMention(
                entity=entity,
                role="management",
                affiliation=affiliation,
                provenance=Provenance(
                    "roster", h.start() + offset, _snip(region, offset)
                ),
            )
        )

    for m in _RE_MGMT_COMMA.finditer(region):
        parts = _RE_ROSTER_SEP.split(m.group(2))
        company = re.sub(r"\s+", " ", parts[-1]).strip() if len(parts) > 1 else None
        _add(m.group(1), company or None, m.start())
    for m in _RE_MGMT_HONORIFIC.finditer(region):
        _add(m.group(1), None, m.start())
    return mentions


# ---------------------------------------------------------------------------
# Period detection
# ---------------------------------------------------------------------------

# "quarter ended March 31, 2026" / "quarter and year ended ..." / "half-year
# period ended ...". Searched over a wider window than v1.0 (5000 vs 3000
# chars) since some companies restate the period in the opening remarks
# rather than the Reg-30 cover letter alone.
_RE_PERIOD_PHRASE = re.compile(
    r"((?:quarter|half[- ]?year|year)(?:[^.\n]{0,60}?)ended)\s+"
    r"([A-Z][a-z]+\s+\d{1,2},?\s*\d{4})",
    re.IGNORECASE,
)

# "Q4FY26" / "4QFY2025" / "Q2 FY26" — ubiquitous label fallback.
_RE_QUARTER_LABEL = re.compile(
    r"\bQ([1-4])\s*[- ]?\s*FY\s*'?(\d{2,4})\b|\b([1-4])Q\s*FY\s*'?(\d{2,4})\b",
    re.IGNORECASE,
)

_QUARTER_END_MONTH_DAY = {1: (6, 30), 2: (9, 30), 3: (12, 31), 4: (3, 31)}


def _period_type_from_phrase(cadence_phrase: str) -> str:
    """ "half year" contains the substring "year" — must not read as annual.

    Mirrors investor_presentation.py's identical fix for the same bug.
    """
    stripped = re.sub(r"half[- ]?year", "", cadence_phrase, flags=re.IGNORECASE)
    return "annual" if "year" in stripped.lower() else "quarterly"


def _quarter_label_period(label_match: re.Match[str]) -> tuple[str, str] | None:
    """Return (period_iso, period_type) from a 'QN FYyy' label, or None."""
    q = label_match.group(1) or label_match.group(3)
    yr = label_match.group(2) or label_match.group(4)
    if not q or not yr:
        return None
    quarter = int(q)
    year = int(yr) if len(yr) == 4 else 2000 + int(yr)
    month, day = _QUARTER_END_MONTH_DAY[quarter]
    # "FYyy" labels the year the fiscal year *ends* in (FY26 = Apr 2025 -
    # Mar 2026). Only Q4 (Jan-Mar) ends within that same calendar year;
    # Q1 (Apr-Jun), Q2 (Jul-Sep), and Q3 (Oct-Dec) all end in the *previous*
    # calendar year relative to the FYyy label.
    period_year = year if quarter == 4 else year - 1
    return f"{period_year}-{month:02d}-{day:02d}", "quarterly"


def _detect_period(content: str) -> tuple[str | None, str | None, int]:
    """Return (period_iso, period_type, char_offset)."""
    window = content[:5000]
    m = _RE_PERIOD_PHRASE.search(window)
    if m:
        iso = parse_iso_date(m.group(2))
        if iso:
            return iso, _period_type_from_phrase(m.group(1)), m.start()

    m_label = _RE_QUARTER_LABEL.search(window)
    if m_label:
        result = _quarter_label_period(m_label)
        if result:
            return result[0], result[1], m_label.start()

    return None, None, 0


# ---------------------------------------------------------------------------
# Prepared-remarks / Q&A boundary
# ---------------------------------------------------------------------------

# The moderator's (or Chairman's) actual hand-off to Q&A — requires an
# action verb ("begin", "invite", "open", "proceed"), not just the noun
# phrase "question and answer session", which can appear much earlier as
# part of the IR head's description of the call's agenda (observed in TCS's
# real transcript: "followed by a Q&A session" appears in the second
# speaker turn, long before Q&A actually starts).
_RE_QA_TRANSITION = re.compile(
    r"(?:now\s+)?begin\s+(?:the\s+)?question|"
    r"now\s+invite\s+questions|"
    r"open\s+(?:the\s+)?(?:call|floor)\s+(?:up\s+)?for\s+questions|"
    r"proceed\s+with\s+(?:the\s+)?questions?|"
    r"happy\s+to\s+take\s+your\s+questions|"
    r"take\s+any\s+questions\s+you\s+may\s+have",
    re.IGNORECASE,
)


def _prepared_remarks_end(content: str) -> int:
    """Return the char offset where Q&A begins, or a conservative fallback.

    The IR head's opening remarks routinely describe the call's agenda
    ("...followed by a Q&A session", "we will take any questions you may
    have") using the exact same phrasing as the real hand-off, minutes
    later, into actual Q&A — a real Tata Steel filing has both, 3.6% and
    24.4% into the document respectively. Matches before 10% of the
    document are assumed to be an agenda mention, not the real transition
    (calibrated on TCS/Tata Steel/SBI real transcripts: every confirmed
    real transition sits at 15% or later; every confirmed agenda mention
    sits under 4%). Falls back to 60% of the document length when no
    transition phrase is found at all.
    """
    min_offset = len(content) * 0.10
    for m in _RE_QA_TRANSITION.finditer(content):
        if m.start() >= min_offset:
            return m.start()
    return int(len(content) * 0.6)


# ---------------------------------------------------------------------------
# Speaker / role detection (best-effort; excerpts and provenance only)
# ---------------------------------------------------------------------------

_RE_ANY_SPEAKER = re.compile(r"^[A-Z][A-Za-z .]{2,60}:", re.MULTILINE)

# Broadened beyond v1.0's literal "CEO"/"CFO": covers the role vocabulary
# actually observed across TCS (CEO/CFO/COO/Chief HR Officer), Tata Steel
# (CEO & MD / ED & CFO), and SBI (Chairman / Managing Director / Deputy
# Managing Director (Finance) — SBI has no single "CEO" or "CFO" at all).
_RE_SENIOR_ROLE = re.compile(
    r"Chief\s+Executive\s+Officer|Chairman|Managing\s+Director|"
    r"Chief\s+Financial\s+Officer|Deputy\s+Managing\s+Director|"
    r"Executive\s+Director|\bCEO\b|\bCFO\b|\bMD\b",
    re.IGNORECASE,
)

# Participant-directory line shapes:
#   "T V Narendran, CEO & MD - Tata Steel Limited"      (one line, comma)
#   "MR. C S SETTY" / "CHAIRMAN, STATE BANK OF INDIA"   (two lines)
_RE_DIRECTORY_ONE_LINE = re.compile(
    r"^([A-Z][A-Za-z .]{2,40}),\s*([^\n]{3,80})$",
    re.MULTILINE,
)


def _detect_senior_speaker_tag(content: str) -> str | None:
    """Best-effort senior-speaker tag ("Name:"), or None.

    Tries the participant directory first (most reliable when present),
    then falls back to scanning the moderator's spoken introduction for a
    role mention and the name immediately preceding it.
    """
    # 6000 chars, not 4000: a long printed roster (SBI lists 7 people with
    # full titles, ~1700 chars alone) can push the real in-dialogue speaker
    # tag past a tighter window.
    preamble = content[:6000]

    m_dir = _RE_DIRECTORY_ONE_LINE.search(preamble)
    if m_dir and _RE_SENIOR_ROLE.search(m_dir.group(2)):
        name = m_dir.group(1).strip()
        name = re.sub(r"^(?:Mr|Ms|Dr|Mrs|Prof)\.?\s+", "", name, flags=re.IGNORECASE)
        return name + ":"

    role_matches = list(_RE_SENIOR_ROLE.finditer(preamble))
    if not role_matches:
        return None
    # Try matches in reverse: an upfront ALL-CAPS "MANAGEMENT" or "CORPORATE
    # PARTICIPANTS" roster (SBI, Tata Steel) lists every senior role before
    # the real spoken introduction happens — the *last* role mention in the
    # preamble is the one most likely to be the genuine, in-dialogue speaker
    # tag (matching the exact case/punctuation used later in the body),
    # while the roster's own entries tend to be ALL CAPS and often don't
    # recur verbatim as a speaker tag at all.
    for m_role in reversed(role_matches):
        segment = preamble[: m_role.start()]
        # Each "word" is [A-Z][A-Za-z]*\.? — one capital-starting token with
        # an optional trailing period — deliberately permissive: it covers
        # ALL-CAPS roster names ("MR. C S SETTY"), Title Case ("Samir
        # Seksaria"), and space-separated initials ("T. V. Narendran", where
        # each initial is its own whitespace-delimited token) uniformly,
        # rather than a single rigid shape that silently fails on whichever
        # convention it wasn't written for.
        # A name "word" is either a compact dotted-initials cluster ("C.S.",
        # no internal space) or a plain capitalized token with an optional
        # trailing period ("Setty", "T.", "SETTY").
        name_m = re.search(
            r"(?<!\w)((?:(?:[A-Z]\.){1,3}|[A-Z][A-Za-z]*\.?)(?:\s+(?:(?:[A-Z]\.){1,3}|[A-Z][A-Za-z]*\.?)){0,3})"
            r"\s*[,:\-–]?\s*$",
            segment,
        )
        if not name_m:
            continue
        name = re.sub(
            r"^(?:Mr|Ms|Dr|Mrs|Prof)\.?\s*",
            "",
            name_m.group(1).strip(),
            flags=re.IGNORECASE,
        )
        tag = name + ":"
        if tag in content:
            return tag
    return None


def _speaker_section(content: str, tag: str, end: int) -> str:
    """Text of the speaker's first substantive turn, bounded by *end*."""
    first = content.find(tag)
    if first < 0 or first >= end:
        return ""
    second = content.find(tag, first + len(tag))
    start = second if 0 <= second < end else first
    offsets = [
        m.start() for m in _RE_ANY_SPEAKER.finditer(content, start + len(tag), end)
    ]
    section_end = offsets[0] if offsets else min(start + 6000, end)
    return content[start:section_end]


# ---------------------------------------------------------------------------
# Numeric fact patterns — broadened beyond v1.0's TCS-only phrasing
# ---------------------------------------------------------------------------

# v1.0 anchored purely on the "₹" glyph, with no verb requirement at all —
# the first rupee figure in the search window, whatever it was attached to,
# became "revenue". Tata Steel's CFO uses "Rs" (no ₹ glyph) and always
# states revenue with an explicit verb ("revenues stood at Rs X crores").
# Requiring the verb closes a real false-positive gap (a stray capex or
# dividend figure could otherwise be misread as revenue) and the broadened
# currency marker closes a real recall gap.
_RE_REVENUE_INR = re.compile(
    r"revenues?\s+(?:stood\s+at|w(?:as|ere)|of)\s+"
    r"(?:₹|Rs\.?)\s*([\d,]+)(?:\s*(?:crores?|cr\.?))?",
    re.IGNORECASE,
)
_RE_REVENUE_USD = re.compile(
    r"revenue\s+was\s+\$([\d.]+)\s*billion"
    r"|dollar\s+revenues?\s+(?:were|was)\s+(?:at\s+)?\$?([\d.]+)\s*billion",
    re.IGNORECASE,
)

# Generalized beyond v1.0's "operating margin" literal: Tata Steel says just
# "a margin of 16%" (EBITDA margin, no qualifying word). An explicit "net"
# qualifier routes to FINANCIAL_NET_MARGIN; anything else (bare "margin",
# "operating margin", "EBITDA margin") routes to FINANCIAL_OPERATING_MARGIN
# — the closest existing-ontology fit, since no separate EBITDA-margin
# FactKind exists and operating/EBITDA margin are used interchangeably in
# spoken commentary across the filings reviewed.
_RE_MARGIN = re.compile(
    r"(net\s+)?(?:income\s+)?margins?[^\n]{0,20}?\s*(?:of|at|was|were|stood\s+at)\s+"
    r"([\d]+\.?\d*)\s*%",
    re.IGNORECASE,
)

# IT-services specific; simply will not match outside that sector.
_RE_TCV = re.compile(
    r"TCV\s+(?:of\s+)?\$([\d.]+)\s*billion" r"|\$([\d.]+)\s*billion\s+(?:in\s+)?TCV",
    re.IGNORECASE,
)

# CHRO / people commentary — reuses existing ESG_WORKFORCE_* FactKinds
# (BRSR-sourced annually; this analyzer supplies a quarterly refresh).
_RE_HEADCOUNT = re.compile(
    r"headcount\s+stood\s+at\s+([\d,]+)|"
    r"global\s+headcount\s+(?:of|at|was)\s+([\d,]+)",
    re.IGNORECASE,
)
_RE_FEMALE_PCT = re.compile(
    r"([\d]+\.?\d*)\s*%\s+are\s+women|"
    r"women\s+(?:employees\s+)?(?:represent|comprise|are)\s+([\d]+\.?\d*)\s*%",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Fact construction helper
# ---------------------------------------------------------------------------


def _pf(
    kind: FactKind,
    value: str | float | int,
    unit: FactUnit | None,
    period: str | None,
    section: str,
    offset: int,
    excerpt: str,
) -> AnalysisFact:
    return AnalysisFact(
        kind=kind,
        value=value,
        unit=unit,
        period=period,
        confidence="high",
        provenance=Provenance(
            section=section,
            char_offset=offset,
            excerpt=excerpt[:120] if excerpt else None,
        ),
    )


def _parse_inr(s: str) -> float:
    return float(s.replace(",", ""))


def _usd_from_match(m: re.Match[str]) -> float | None:
    raw = m.group(1) or m.group(2)
    try:
        return float(raw) if raw else None
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def analyze(evidence_id: str, kb: KnowledgeBase) -> AnalysisResult:
    """Extract structured facts from an earnings call / analyst meet transcript.

    Raises ValueError for missing, wrong-kind, or empty-content documents.
    """
    entry = kb.get(evidence_id)
    if entry is None:
        raise ValueError(
            f"cannot analyze evidence_id={evidence_id!r}: not in knowledge base"
        )
    if entry.kind != "earnings_transcript":
        raise ValueError(
            f"cannot analyze evidence_id={evidence_id!r}: "
            f"kind={entry.kind!r} is not 'earnings_transcript'"
        )

    content = kb.get_content(evidence_id)
    if not content:
        raise ValueError(
            f"cannot analyze evidence_id={evidence_id!r}: document has no content"
        )

    content = content.replace("ﬁ", "fi").replace("ﬂ", "fl")

    result = AnalysisResult(
        evidence_id=evidence_id,
        kind="earnings_transcript",
        analyzer_version=ANALYZER_VERSION,
        confidence="low",
        source_date=datetime.fromisoformat(entry.source_date),
    )

    # ------------------------------------------------------------------
    # 1. Period detection
    # ------------------------------------------------------------------
    period, period_type, period_offset = _detect_period(content)
    if period is None:
        result.warnings.append(
            "Could not detect reporting period from cover letter or quarter label"
        )
        return result

    result.facts.append(
        _pf(
            FactKind.REPORT_PERIOD_END,
            period,
            FactUnit.ISO_DATE,
            period,
            "cover_letter",
            period_offset,
            period,
        )
    )
    result.facts.append(
        _pf(
            FactKind.REPORT_PERIOD_TYPE,
            period_type,
            None,
            period,
            "cover_letter",
            period_offset,
            period_type or "",
        )
    )
    is_annual = period_type == "annual"

    # ------------------------------------------------------------------
    # 2. Bound the search zone to prepared remarks (excludes Q&A)
    # ------------------------------------------------------------------
    qa_start = _prepared_remarks_end(content)
    remarks = content[:qa_start]
    normalized_remarks = re.sub(r"[ \t]*\n[ \t]*", " ", remarks)

    senior_tag = _detect_senior_speaker_tag(content)
    if senior_tag:
        senior_section = _speaker_section(content, senior_tag, qa_start)
        if senior_section:
            result.excerpts["management_commentary"] = senior_section[:3000].strip()

    # Q&A analysts (M-P1.2, Q13) + management roster (M-P1.5, Q45) -> resolved
    # entity mentions. One per-document resolver; distinct roles ("analyst" /
    # "management") flow through the existing participant ingest unchanged.
    _resolver = EntityResolver()
    result.entities.extend(_extract_analyst_mentions(content, _resolver))
    result.entities.extend(_extract_management_mentions(content, _resolver))

    # ------------------------------------------------------------------
    # 3. Revenue (quarterly always; annual too for Q4/full-year calls)
    # ------------------------------------------------------------------
    financial_offset: int | None = None

    m_inr = _RE_REVENUE_INR.search(remarks)
    if m_inr:
        financial_offset = m_inr.start()
        result.facts.append(
            _pf(
                FactKind.FINANCIAL_REVENUE,
                _parse_inr(m_inr.group(1)),
                FactUnit.CRORE_INR,
                period,
                "quarterly",
                m_inr.start(),
                m_inr.group(0),
            )
        )

    m_usd = _RE_REVENUE_USD.search(remarks)
    if m_usd:
        usd_val = _usd_from_match(m_usd)
        if usd_val is not None:
            financial_offset = financial_offset or m_usd.start()
            result.facts.append(
                _pf(
                    FactKind.FINANCIAL_REVENUE,
                    usd_val,
                    FactUnit.USD_BILLION,
                    period,
                    "quarterly",
                    m_usd.start(),
                    m_usd.group(0),
                )
            )

    if is_annual:
        # The second distinct revenue mention in the CFO's remarks is the
        # full-year figure (the quarterly figure comes first). Compared by
        # match *position*, not object identity — re.finditer yields a new
        # Match object even for a position already found by m_inr.search(),
        # so an identity check never actually skips the quarterly match.
        quarterly_start = m_inr.start() if m_inr else -1
        for m in _RE_REVENUE_INR.finditer(remarks):
            if m.start() != quarterly_start:
                result.facts.append(
                    _pf(
                        FactKind.FINANCIAL_REVENUE,
                        _parse_inr(m.group(1)),
                        FactUnit.CRORE_INR,
                        period,
                        "annual",
                        m.start(),
                        m.group(0),
                    )
                )
                break

    # ------------------------------------------------------------------
    # 4. Margins (operating/EBITDA -> OPERATING_MARGIN; explicit "net" ->
    #    NET_MARGIN). Distinct occurrences of each kind are kept.
    #
    # A company's remarks routinely state more than one margin figure at
    # different scopes — Tata Steel's CFO states an annual India-specific
    # EBITDA margin well before the quarterly consolidated headline margin
    # ("...translating to a margin of 16%") that immediately follows the
    # revenue figure. Prefer whichever margin mention sits closest to (and
    # after) the revenue match — the pairing management itself uses when
    # stating results — falling back to document order when no revenue
    # match exists to anchor against (e.g. a bank with no "revenue" line).
    # ------------------------------------------------------------------
    all_margins = list(_RE_MARGIN.finditer(remarks))
    if financial_offset is not None and all_margins:
        after_revenue = [mm for mm in all_margins if mm.start() >= financial_offset]
        margin_matches = after_revenue if after_revenue else all_margins
    else:
        margin_matches = all_margins

    seen_margin_kinds: set[FactKind] = set()
    for m in margin_matches:
        is_net = bool(m.group(1))
        kind = (
            FactKind.FINANCIAL_NET_MARGIN
            if is_net
            else FactKind.FINANCIAL_OPERATING_MARGIN
        )
        if kind in seen_margin_kinds:
            continue
        seen_margin_kinds.add(kind)
        financial_offset = (
            financial_offset if financial_offset is not None else m.start()
        )
        result.facts.append(
            _pf(
                kind,
                float(m.group(2)),
                FactUnit.PERCENT,
                period,
                "quarterly",
                m.start(),
                m.group(0),
            )
        )

    if financial_offset is not None:
        window_start = max(0, financial_offset - 200)
        result.excerpts["financial_commentary"] = remarks[
            window_start : window_start + 2000
        ].strip()

    # ------------------------------------------------------------------
    # 5. TCV (IT-services specific; searched over prepared remarks only)
    # ------------------------------------------------------------------
    m_tcv = _RE_TCV.search(remarks)
    if m_tcv:
        tcv_raw = m_tcv.group(1) or m_tcv.group(2)
        result.facts.append(
            _pf(
                FactKind.FINANCIAL_TCV,
                float(tcv_raw),
                FactUnit.USD_BILLION,
                period,
                "quarterly",
                m_tcv.start(),
                m_tcv.group(0),
            )
        )

    # ------------------------------------------------------------------
    # 6. Forward guidance (shared pattern with investor_presentation.py)
    # ------------------------------------------------------------------
    for text, offset in find_guidance_statements(normalized_remarks, max_count=3):
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

    # ------------------------------------------------------------------
    # 7. Workforce (reused ESG FactKinds; quarterly refresh of BRSR's
    #    annual figures — sector-conditional, fires mainly for IT services)
    # ------------------------------------------------------------------
    m_headcount = _RE_HEADCOUNT.search(remarks)
    if m_headcount:
        raw = m_headcount.group(1) or m_headcount.group(2)
        result.facts.append(
            _pf(
                FactKind.ESG_WORKFORCE_HEADCOUNT,
                _parse_inr(raw),
                FactUnit.COUNT,
                period,
                "workforce",
                m_headcount.start(),
                m_headcount.group(0),
            )
        )

    m_female = _RE_FEMALE_PCT.search(remarks)
    if m_female:
        raw = m_female.group(1) or m_female.group(2)
        result.facts.append(
            _pf(
                FactKind.ESG_WORKFORCE_FEMALE_PCT,
                float(raw),
                FactUnit.PERCENT,
                period,
                "workforce",
                m_female.start(),
                m_female.group(0),
            )
        )

    # ------------------------------------------------------------------
    # 8. Result-level confidence — breadth of distinct categories found,
    #    not raw fact count (matches investor_presentation.py's model).
    # ------------------------------------------------------------------
    categories = {
        f.kind
        for f in result.facts
        if f.kind not in (FactKind.REPORT_PERIOD_END, FactKind.REPORT_PERIOD_TYPE)
    }
    core = {FactKind.FINANCIAL_REVENUE, FactKind.FINANCIAL_OPERATING_MARGIN}
    if core.issubset(categories):
        result.confidence = "high"
    elif categories:
        result.confidence = "medium"

    return result
