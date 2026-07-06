"""Content-based document classification — a check on BSE/NSE's own kind
label, run after parsing (not at raw download time, since the signals it
needs — extracted text, page count — don't exist until KnowledgeBase has
parsed the file).

Why this exists
----------------
The evidence coverage audit found BSE's own classification is trusted too
literally. Three confirmed real cases, all in the TCS repository:

  - 49 of 50 "Investor Presentation" entries are Reg-30 cover letters or
    meeting-schedule notices, not decks — BSE files both under the same
    subcategory ("Analyst / Investor Meet").
  - 3 of 5 "Financial Results" entries are Regulation 23(9) related-party
    transaction disclosures, not financial results — BSE's own "Financial
    Results" announcement subcategory captures both.
  - Several "Annual Report" entries are AGM-notice forwarding letters, not
    the report itself.

These are not analyzer failures — financial_results.py's own "No P&L table
found" warning already detects the third case correctly, after the fact.
This module catches it earlier and more cheaply, before an analyzer runs at
all, and catches the other two cases analyzers have no way to detect
(there's nothing wrong with extracting 2 facts from a 2-page schedule
notice — the analyzer did its job; the document just isn't what its label
claims).

Signal: the "Sub:" line
-------------------------
Every BSE Reg-30/Reg-34/Reg-23(9) cover letter states its own purpose in a
"Sub: <purpose>" line within the first ~3000 characters — the filer's own
words, not an inference. A schedule notice says "Sub: Schedule of Analyst
/ Institutional Investor Meetings"; a real deck submission says "Sub:
Submission of presentation..."; a related-party disclosure says "Sub:
Disclosure of Related Party Transactions pursuant to Regulation 23(9)...".
This is read directly, not pattern-matched against a title string that
could vary — the same anti-fragile-parsing principle used throughout Atlas
(e.g. citation.py resolving period from CompanyProfile back-links instead
of re-parsing titles).

Page count is used as a second, independent signal (a "cover letter" is
essentially never more than a few pages; a real deck/transcript/annual
report almost never is that short) — calibrated against real TCS data:
investor_presentation stubs were 2-3 pages against a 55-page real deck;
the misclassified financial_results docs ranged 3-25 pages (not reliably
short on its own, which is why the Sub-line check exists for that case
specifically rather than relying on page count alone).

No LLM. No ML. Every rule here is a literal substring/regex match against
already-extracted text, deterministic and independently testable.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import Path

from atlas.acquisition.catalog import RepositoryCatalog
from atlas.knowledge.base import KnowledgeBase

_RE_SUB_LINE = re.compile(r"Sub\s*[:\-]\s*([^\n]{0,200})", re.IGNORECASE)

# Kinds this classifier has rules for. Anything else passes through
# unexamined — this module makes claims only where it has calibrated
# evidence, not a blanket "guess for every kind" heuristic.
_SUBSTANTIVE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "investor_presentation": ("presentation", "analyst day", "investor meet", "investor day"),
    "earnings_transcript": ("transcript",),
    "annual_report": ("annual report",),
    "brsr": ("business responsibility", "brsr", "sustainability"),
}

# Sub-line phrases that mark an administrative notice *about* a document,
# not the document itself — checked only when the substantive-keyword
# check above already failed, so a Sub line that happens to mention both
# ("Notice convening the AGM and Integrated Annual Report...") still
# passes as substantive.
_NON_SUBSTANTIVE_MARKERS = (
    "schedule of",
    "intimation of schedule",
    "intimation under regulation",
    "intimation regarding",
)

# A document this short, for a kind that should be substantial, is a cover
# letter/notice regardless of what its Sub line says — calibrated against
# real TCS filings (see module docstring).
_MIN_SUBSTANTIVE_PAGES: dict[str, int] = {
    "investor_presentation": 5,
    "earnings_transcript": 5,
    "annual_report": 10,
    "brsr": 5,
}

# Sub-line phrases that mark a genuine cross-kind misclassification, not
# just a thin/administrative version of the claimed kind. Maps the marker
# to the corrected EvidenceKind value.
_REGULATORY_RECLASSIFICATION: dict[str, tuple[str, ...]] = {
    "regulatory_filing": ("related party transaction", "regulation 23(9)", "reg. 23(9)", "reg 23(9)"),
}

# Regex fallback for the same reclassification, matched against the same
# Sub-line text: older scanned filings can come back from OCR with prose
# corrupted character-by-character ("Regulation" -> "Resulation",
# "pursuant" -> "nursuant" — a real example found in a 2019 TCS filing)
# while a short digit/punctuation citation like "23(9)" survives intact,
# since OCR confuses visually similar letters far more than digits. Kept
# separate from the plain-substring table above rather than trying to
# fuzzy-match prose, which would trade precision for recall in a way that's
# hard to reason about; this is a narrow, deliberate exception for exactly
# the one citation pattern observed to survive.
_RE_REG_23_9 = re.compile(r"\b23\s*\(\s*9\s*\)")


@dataclass(frozen=True)
class ClassificationResult:
    """The classifier's verdict for one document.

    original_kind:  the kind BSE/NSE's own metadata assigned.
    resolved_kind:  original_kind, unless a cross-kind correction applies.
    is_substantive: False for a cover letter / schedule notice that carries
                    the right kind but isn't the real document — still
                    correctly the *kind* the catalog assigned, just thin.
    reason:         human-readable justification, always citing the actual
                    Sub line or page count that triggered the verdict.
    """

    original_kind: str
    resolved_kind: str
    is_substantive: bool
    reason: str

    @property
    def was_reclassified(self) -> bool:
        return self.resolved_kind != self.original_kind


def _extract_sub_line(text: str) -> str | None:
    match = _RE_SUB_LINE.search(text[:3000])
    return match.group(1).strip() if match else None


def classify(kind: str, text: str, page_count: int | None) -> ClassificationResult:
    """Classify one parsed document against the kind its source assigned.

    text is the full extracted content (only the first ~3000 chars are
    actually inspected — the Sub line always appears in the cover-letter
    preamble). page_count may be None for older parsed_documents rows that
    predate page_count being persisted; page-based checks are skipped in
    that case, not treated as a failure.
    """
    sub_line = _extract_sub_line(text)
    haystack = sub_line.lower() if sub_line else ""

    for corrected_kind, markers in _REGULATORY_RECLASSIFICATION.items():
        matched = any(m in haystack for m in markers) or (sub_line is not None and _RE_REG_23_9.search(sub_line))
        if kind != corrected_kind and matched:
            return ClassificationResult(
                original_kind=kind,
                resolved_kind=corrected_kind,
                is_substantive=True,
                reason=f"Sub line indicates a {corrected_kind.replace('_', ' ')}, not {kind.replace('_', ' ')}: {sub_line!r}",
            )

    required_keywords = _SUBSTANTIVE_KEYWORDS.get(kind)
    if required_keywords and sub_line is not None:
        has_substantive_keyword = any(kw in haystack for kw in required_keywords)
        has_non_substantive_marker = any(m in haystack for m in _NON_SUBSTANTIVE_MARKERS)
        if not has_substantive_keyword and has_non_substantive_marker:
            return ClassificationResult(
                original_kind=kind,
                resolved_kind=kind,
                is_substantive=False,
                reason=f"Sub line indicates an administrative notice, not the {kind.replace('_', ' ')} itself: {sub_line!r}",
            )

    min_pages = _MIN_SUBSTANTIVE_PAGES.get(kind)
    if min_pages is not None and page_count is not None and page_count < min_pages:
        return ClassificationResult(
            original_kind=kind,
            resolved_kind=kind,
            is_substantive=False,
            reason=f"only {page_count} page(s), below the {min_pages}-page floor for a real {kind.replace('_', ' ')}",
        )

    return ClassificationResult(
        original_kind=kind,
        resolved_kind=kind,
        is_substantive=True,
        reason="passed all classification checks for this kind",
    )


# ---------------------------------------------------------------------------
# Repository-level orchestration — apply classification to a real catalog
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReclassificationRecord:
    """One document's classification outcome from a repository-wide pass."""

    evidence_id: str
    result: ClassificationResult


def reclassify_repository(repo_root: Path) -> list[ReclassificationRecord]:
    """Run classify() over every catalog entry with calibrated rules, and
    write back any cross-kind correction (financial_results -> regulatory_
    filing) to catalog.json and knowledge.db.

    "Use the classified type rather than blindly trusting BSE/NSE metadata"
    means the *kind* correction is what the rest of the pipeline (analyzer
    dispatch, downstream Repository.list_evidence() filters) actually needs
    to act on — that's what gets persisted here. is_substantive is
    diagnostic only (nothing downstream currently filters on it; every
    analyzer already degrades gracefully on a thin document, as designed)
    and is returned in the report but not written anywhere.

    Only examines evidence_ids whose kind has calibrated rules in this
    module (_SUBSTANTIVE_KEYWORDS / _MIN_SUBSTANTIVE_PAGES / "financial_
    results", the one source kind for the regulatory_filing correction) and
    whose parse status is "ok" — a document with no extracted text has
    nothing for this classifier to read.
    """
    calibrated_kinds = set(_SUBSTANTIVE_KEYWORDS) | set(_MIN_SUBSTANTIVE_PAGES) | {"financial_results"}

    catalog = RepositoryCatalog(repo_root)
    kb = KnowledgeBase(repo_root)
    records: list[ReclassificationRecord] = []

    for entry in catalog.all_entries():
        if entry.kind not in calibrated_kinds:
            continue
        doc = kb.get(entry.evidence_id)
        if doc is None or doc.status != "ok":
            continue
        text = kb.get_content(entry.evidence_id) or ""
        result = classify(entry.kind, text, doc.page_count)
        records.append(ReclassificationRecord(entry.evidence_id, result))

        if result.was_reclassified:
            reclassified_entry = replace(entry, kind=result.resolved_kind)
            catalog.add(reclassified_entry)
            kb.parse(reclassified_entry)

    catalog.save()
    return records
