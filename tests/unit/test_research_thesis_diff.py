"""Thesis diff (M-P2.7, Q23).

Presentation-only statement normalization (case/punctuation/whitespace) --
no stemming, synonyms, fuzzy matching, or semantic similarity. Comparison is
refused (returns None) when the two theses answer different questions.
"""
from __future__ import annotations

from atlas.reasoning.contracts import Claim, EvidenceReference, Finding, Question, ReasoningResult, SubjectRef
from atlas.research.thesis import Thesis, compute_view_id
from atlas.research.thesis_diff import diff_theses

_SUBJECT = SubjectRef(subject_id="TCS", display="TCS")


def _claim(statement: str, ev: str) -> Claim:
    return Claim(
        subject_ref=_SUBJECT, statement=statement, assertability="judgment",
        confidence="medium", evidence=(EvidenceReference(evidence_id=ev),),
    )


def _thesis(question: str, fingerprint: str, as_of: str, overall_confidence: str,
            findings: list[tuple[str, str]]) -> Thesis:
    # findings: list of (statement, confidence)
    finding_tuple = tuple(
        Finding(statement=s, assertability="judgment", confidence=c,
                supporting_claims=(_claim(s, "ev-1"),))
        for s, c in findings
    )
    rr = ReasoningResult(
        question=Question(raw_text=question, subject_ref=_SUBJECT),
        findings=finding_tuple,
        overall_confidence=overall_confidence,
        citations=frozenset({"ev-1"}),
        refused=False,
    )
    return Thesis(
        question=question, subjects=("TCS",), run_fingerprint=fingerprint,
        view_id=compute_view_id(fingerprint, question), as_of=as_of,
        result=rr, dispositions=(), unresolved_dimensions=(),
    )


# --- added / removed -----------------------------------------------------------
def test_added_finding_detected() -> None:
    older = _thesis("Is margin durable?", "fp1", "2024-01-01", "medium",
                     [("Margins are stable.", "medium")])
    newer = _thesis("Is margin durable?", "fp2", "2025-01-01", "high",
                     [("Margins are stable.", "medium"), ("New segment is growing fast.", "high")])
    diff = diff_theses(older, newer)
    assert diff is not None
    assert diff.added == ("New segment is growing fast.",)
    assert diff.removed == ()


def test_removed_finding_detected() -> None:
    older = _thesis("Is margin durable?", "fp1", "2024-01-01", "medium",
                     [("Margins are stable.", "medium"), ("Old risk factor.", "low")])
    newer = _thesis("Is margin durable?", "fp2", "2025-01-01", "high",
                     [("Margins are stable.", "medium")])
    diff = diff_theses(older, newer)
    assert diff is not None
    assert diff.removed == ("Old risk factor.",)
    assert diff.added == ()


# --- confidence-only change -----------------------------------------------------
def test_confidence_only_change_detected() -> None:
    older = _thesis("Is margin durable?", "fp1", "2024-01-01", "medium",
                     [("Margins are stable.", "low")])
    newer = _thesis("Is margin durable?", "fp2", "2025-01-01", "high",
                     [("Margins are stable.", "high")])
    diff = diff_theses(older, newer)
    assert diff is not None
    assert len(diff.changed) == 1
    c = diff.changed[0]
    assert c.older_confidence == "low" and c.newer_confidence == "high"
    assert diff.added == () and diff.removed == ()
    assert diff.unchanged_count == 0


# --- identical theses ------------------------------------------------------------
def test_identical_theses_no_differences() -> None:
    findings = [("Margins are stable.", "medium"), ("Debt is manageable.", "high")]
    older = _thesis("Is margin durable?", "fp1", "2024-01-01", "medium", findings)
    newer = _thesis("Is margin durable?", "fp2", "2025-01-01", "medium", findings)
    diff = diff_theses(older, newer)
    assert diff is not None
    assert diff.added == () and diff.removed == () and diff.changed == ()
    assert diff.unchanged_count == 2


# --- question mismatch refusal ---------------------------------------------------
def test_question_mismatch_refuses_comparison() -> None:
    older = _thesis("Is margin durable?", "fp1", "2024-01-01", "medium", [("X", "medium")])
    newer = _thesis("Is the balance sheet safe?", "fp2", "2025-01-01", "medium", [("Y", "medium")])
    assert diff_theses(older, newer) is None


# --- presentation normalization (not semantic) -----------------------------------
def test_statement_matched_across_punctuation_case_whitespace() -> None:
    older = _thesis("Is margin durable?", "fp1", "2024-01-01", "medium",
                     [("Margins ARE stable!!", "medium")])
    newer = _thesis("Is margin durable?", "fp2", "2025-01-01", "medium",
                     [("margins  are   stable", "high")])
    diff = diff_theses(older, newer)
    assert diff is not None
    assert len(diff.changed) == 1  # matched despite case/punctuation/whitespace
    assert diff.added == () and diff.removed == ()


def test_question_normalized_for_matching_too() -> None:
    older = _thesis("Is margin durable?", "fp1", "2024-01-01", "medium", [("X", "medium")])
    newer = _thesis("is margin durable", "fp2", "2025-01-01", "medium", [("X", "medium")])
    assert diff_theses(older, newer) is not None  # same question, punctuation/case differ


def test_no_stemming_synonyms_or_fuzzy_matching() -> None:
    # "stable" vs "stability" -- must NOT be treated as the same statement.
    older = _thesis("Is margin durable?", "fp1", "2024-01-01", "medium",
                     [("Margins are stable.", "medium")])
    newer = _thesis("Is margin durable?", "fp2", "2025-01-01", "medium",
                     [("Margins show stability.", "medium")])
    diff = diff_theses(older, newer)
    assert diff is not None
    assert diff.added == ("Margins show stability.",)
    assert diff.removed == ("Margins are stable.",)
    assert diff.changed == ()


# --- diff directionality (added/removed invert on reversed argument order) -----
def test_diff_directionality_inverts_on_reversed_arguments() -> None:
    t1 = _thesis("Is margin durable?", "fp1", "2024-01-01", "medium", [("Old finding.", "medium")])
    t2 = _thesis("Is margin durable?", "fp2", "2025-01-01", "high", [("New finding.", "high")])

    forward = diff_theses(t1, t2)
    backward = diff_theses(t2, t1)
    assert forward is not None and backward is not None

    assert forward.added == ("New finding.",)
    assert forward.removed == ("Old finding.",)
    assert backward.added == ("Old finding.",)
    assert backward.removed == ("New finding.",)
