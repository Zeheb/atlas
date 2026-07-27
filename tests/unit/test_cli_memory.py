"""`atlas memory list/show/check` (M2.4 commit 8).

No portfolio-wide index exists -- these commands sweep discover_companies()
the same way `atlas screen` does, plus one ThesisStore per subject. The
central claims: list/show read what --remember actually wrote (round-trip,
not a stub), and check's hard_stale flag actually reflects a cited id that no
longer resolves in the KnowledgeBase.
"""

from __future__ import annotations

from click.testing import CliRunner

from atlas.analysis.base import FactKind
from atlas.cli import cli
from atlas.company.model import CompanyProfile, FinancialSnapshot, FinancialTimeSeries
from atlas.company.store import CompanyStore
from atlas.reasoning.contracts import (
    Claim,
    EvidenceReference,
    Finding,
    Question,
    ReasoningResult,
    SubjectRef,
)
from atlas.research.memory import ThesisStore
from atlas.research.thesis import Thesis, compute_view_id


def _seed_profile(base, ticker: str = "TCS") -> None:
    profile = CompanyProfile(
        company_id=ticker,
        financial=FinancialTimeSeries(
            snapshots=[
                FinancialSnapshot(
                    period="2026-03-31",
                    period_type="annual",
                    basis="consolidated",
                    facts={FactKind.FINANCIAL_OPERATING_MARGIN: 24.2},
                    sources=["ev-1"],
                )
            ]
        ),
    )
    CompanyStore(base / ticker / "profile.json", ticker).save(profile)


def _thesis(ticker: str, question: str, evidence_id: str = "ev-1") -> Thesis:
    subject = SubjectRef(subject_id=ticker, display=ticker)
    result = ReasoningResult(
        question=Question(raw_text=question, subject_ref=subject),
        findings=(
            Finding(
                statement="Margins are durable at ~24%.",
                assertability="judgment",
                confidence="medium",
                supporting_claims=(_claim(subject, evidence_id),),
            ),
        ),
        overall_confidence="medium",
        citations=frozenset({evidence_id}),
        refused=False,
    )
    fingerprint = f"fp-{ticker}"
    return Thesis(
        question=question,
        subjects=(ticker,),
        run_fingerprint=fingerprint,
        view_id=compute_view_id(fingerprint, question),
        as_of="2026-01-01T00:00:00+00:00",
        result=result,
        dispositions=(),
        unresolved_dimensions=(),
    )


def _claim(subject, evidence_id: str):
    from atlas.reasoning.contracts import Claim

    return Claim(
        subject_ref=subject,
        statement="Margins are durable at ~24%.",
        assertability="judgment",
        confidence="medium",
        evidence=(EvidenceReference(evidence_id=evidence_id),),
    )


def _env(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ATLAS_REPOSITORY_BASE_PATH", str(tmp_path))


# --- list --------------------------------------------------------------------------------
def test_list_reports_no_profiles_when_portfolio_is_empty(
    monkeypatch, tmp_path
) -> None:
    _env(monkeypatch, tmp_path)
    result = CliRunner().invoke(cli, ["memory", "list"])
    assert result.exit_code == 1
    assert "No company profiles found" in result.output


def test_list_reports_no_views_when_none_remembered(monkeypatch, tmp_path) -> None:
    _env(monkeypatch, tmp_path)
    _seed_profile(tmp_path)
    result = CliRunner().invoke(cli, ["memory", "list"])
    assert result.exit_code == 0, result.output
    assert "No remembered views yet" in result.output


def test_list_shows_a_remembered_view(monkeypatch, tmp_path) -> None:
    _env(monkeypatch, tmp_path)
    _seed_profile(tmp_path)
    thesis = _thesis("TCS", "Should I invest in TCS?")
    ThesisStore(tmp_path / "TCS" / "theses.json", "TCS").save(thesis)

    result = CliRunner().invoke(cli, ["memory", "list"])
    assert result.exit_code == 0, result.output
    assert "TCS" in result.output
    assert thesis.view_id in result.output
    assert "Should I invest in TCS?" in result.output


# --- show --------------------------------------------------------------------------------
def test_show_prints_claims_confidence_and_evidence(monkeypatch, tmp_path) -> None:
    _env(monkeypatch, tmp_path)
    _seed_profile(tmp_path)
    thesis = _thesis("TCS", "Should I invest in TCS?")
    ThesisStore(tmp_path / "TCS" / "theses.json", "TCS").save(thesis)

    result = CliRunner().invoke(cli, ["memory", "show", thesis.view_id])
    assert result.exit_code == 0, result.output
    assert "Margins are durable" in result.output
    assert "evidence: ev-1" in result.output
    assert "confidence: medium" in result.output


def test_show_unknown_view_id_fails_cleanly(monkeypatch, tmp_path) -> None:
    _env(monkeypatch, tmp_path)
    _seed_profile(tmp_path)
    result = CliRunner().invoke(cli, ["memory", "show", "no-such-view"])
    assert result.exit_code == 1
    assert "No remembered view" in result.output


# --- check -------------------------------------------------------------------------------
def test_check_flags_hard_stale_when_evidence_no_longer_resolves(
    monkeypatch, tmp_path
) -> None:
    """The view cites 'ev-1', but no knowledge.db exists for TCS at all -- so
    the cited id cannot resolve, and hard_stale must be true."""
    _env(monkeypatch, tmp_path)
    _seed_profile(tmp_path)
    thesis = _thesis("TCS", "Should I invest in TCS?", evidence_id="ev-does-not-exist")
    ThesisStore(tmp_path / "TCS" / "theses.json", "TCS").save(thesis)

    result = CliRunner().invoke(cli, ["memory", "check"])
    assert result.exit_code == 0, result.output
    assert "STALE" in result.output
    assert "ev-does-not-exist" in result.output


def test_check_reports_current_when_no_knowledge_base_exists(
    monkeypatch, tmp_path
) -> None:
    """No knowledge.db at all means check_staleness has nothing to compare
    against -- known ids are empty, so any cited id is reported missing."""
    _env(monkeypatch, tmp_path)
    _seed_profile(tmp_path)
    thesis = _thesis("TCS", "Should I invest in TCS?", evidence_id="ev-1")
    ThesisStore(tmp_path / "TCS" / "theses.json", "TCS").save(thesis)

    result = CliRunner().invoke(cli, ["memory", "check"])
    assert result.exit_code == 0, result.output
    assert thesis.view_id in result.output


def test_check_reports_no_views_when_none_remembered(monkeypatch, tmp_path) -> None:
    _env(monkeypatch, tmp_path)
    _seed_profile(tmp_path)
    result = CliRunner().invoke(cli, ["memory", "check"])
    assert result.exit_code == 0, result.output
    assert "No remembered views to check" in result.output


# --- Incompatible store handling (M2.4.1 item 6) ----------------------------------------
# Before this fix, a store this build cannot read (e.g. a future
# store_version) crashed the whole command with a raw traceback -- one bad
# subject blocked the entire portfolio view for list/show/check alike.
def _write_incompatible_store(base, ticker: str) -> None:
    import json

    (base / ticker / "theses.json").write_text(
        json.dumps({"store_version": "999", "subject": ticker, "theses": []}),
        encoding="utf-8",
    )


def test_list_warns_and_continues_past_an_incompatible_store(
    monkeypatch, tmp_path
) -> None:
    _env(monkeypatch, tmp_path)
    _seed_profile(tmp_path, "TCS")
    _write_incompatible_store(tmp_path, "TCS")

    result = CliRunner().invoke(cli, ["memory", "list"])
    assert result.exit_code == 0, result.output
    assert "Warning" in result.output
    assert "TCS" in result.output


def test_list_still_shows_a_good_subject_alongside_a_bad_one(
    monkeypatch, tmp_path
) -> None:
    _env(monkeypatch, tmp_path)
    _seed_profile(tmp_path, "TCS")
    _write_incompatible_store(tmp_path, "TCS")
    _seed_profile(tmp_path, "SBIN")
    thesis = _thesis("SBIN", "Should I invest in SBIN?")
    ThesisStore(tmp_path / "SBIN" / "theses.json", "SBIN").save(thesis)

    result = CliRunner().invoke(cli, ["memory", "list"])
    assert result.exit_code == 0, result.output
    assert "SBIN" in result.output
    assert thesis.view_id in result.output


def test_show_warns_and_continues_past_an_incompatible_store(
    monkeypatch, tmp_path
) -> None:
    _env(monkeypatch, tmp_path)
    _seed_profile(tmp_path, "TCS")
    _write_incompatible_store(tmp_path, "TCS")
    _seed_profile(tmp_path, "SBIN")
    thesis = _thesis("SBIN", "Should I invest in SBIN?")
    ThesisStore(tmp_path / "SBIN" / "theses.json", "SBIN").save(thesis)

    result = CliRunner().invoke(cli, ["memory", "show", thesis.view_id])
    assert result.exit_code == 0, result.output
    assert "Margins are durable" in result.output


def test_check_warns_and_continues_past_an_incompatible_store(
    monkeypatch, tmp_path
) -> None:
    _env(monkeypatch, tmp_path)
    _seed_profile(tmp_path, "TCS")
    _write_incompatible_store(tmp_path, "TCS")
    _seed_profile(tmp_path, "SBIN")
    thesis = _thesis("SBIN", "Should I invest in SBIN?")
    ThesisStore(tmp_path / "SBIN" / "theses.json", "SBIN").save(thesis)

    result = CliRunner().invoke(cli, ["memory", "check"])
    assert result.exit_code == 0, result.output
    assert "Warning" in result.output
    assert "SBIN" in result.output
    assert thesis.view_id in result.output


# --- diff --------------------------------------------------------------------------------
def _thesis_v(
    ticker: str,
    question: str,
    fingerprint: str,
    as_of: str,
    statement: str,
    confidence: str,
) -> Thesis:
    subject = SubjectRef(subject_id=ticker, display=ticker)
    result = ReasoningResult(
        question=Question(raw_text=question, subject_ref=subject),
        findings=(
            Finding(
                statement=statement,
                assertability="judgment",
                confidence=confidence,
                supporting_claims=(
                    Claim(
                        subject_ref=subject,
                        statement=statement,
                        assertability="judgment",
                        confidence=confidence,
                        evidence=(EvidenceReference(evidence_id="ev-1"),),
                    ),
                ),
            ),
        ),
        overall_confidence=confidence,
        citations=frozenset({"ev-1"}),
        refused=False,
    )
    return Thesis(
        question=question,
        subjects=(ticker,),
        run_fingerprint=fingerprint,
        view_id=compute_view_id(fingerprint, question),
        as_of=as_of,
        result=result,
        dispositions=(),
        unresolved_dimensions=(),
    )


def test_diff_shows_confidence_change(monkeypatch, tmp_path) -> None:
    _env(monkeypatch, tmp_path)
    _seed_profile(tmp_path, "TCS")
    older = _thesis_v(
        "TCS", "Is margin durable?", "fp1", "2024-01-01", "Margins are durable.", "low"
    )
    newer = _thesis_v(
        "TCS", "Is margin durable?", "fp2", "2025-01-01", "Margins are durable.", "high"
    )
    store = ThesisStore(tmp_path / "TCS" / "theses.json", "TCS")
    store.save(older)
    store.save(newer)

    result = CliRunner().invoke(cli, ["memory", "diff", older.view_id, newer.view_id])
    assert result.exit_code == 0, result.output
    assert "low -> high" in result.output


def test_diff_question_mismatch_refuses(monkeypatch, tmp_path) -> None:
    _env(monkeypatch, tmp_path)
    _seed_profile(tmp_path, "TCS")
    a = _thesis_v("TCS", "Is margin durable?", "fp1", "2024-01-01", "X", "medium")
    b = _thesis_v(
        "TCS", "Is the balance sheet safe?", "fp2", "2025-01-01", "Y", "medium"
    )
    store = ThesisStore(tmp_path / "TCS" / "theses.json", "TCS")
    store.save(a)
    store.save(b)

    result = CliRunner().invoke(cli, ["memory", "diff", a.view_id, b.view_id])
    assert result.exit_code == 1
    assert "different questions" in result.output.lower()


def test_diff_missing_view_id_a(monkeypatch, tmp_path) -> None:
    _env(monkeypatch, tmp_path)
    _seed_profile(tmp_path, "TCS")
    b = _thesis_v("TCS", "Is margin durable?", "fp2", "2025-01-01", "Y", "medium")
    ThesisStore(tmp_path / "TCS" / "theses.json", "TCS").save(b)

    result = CliRunner().invoke(cli, ["memory", "diff", "nonexistent-id", b.view_id])
    assert result.exit_code == 1
    assert "nonexistent-id" in result.output


def test_diff_missing_view_id_b(monkeypatch, tmp_path) -> None:
    _env(monkeypatch, tmp_path)
    _seed_profile(tmp_path, "TCS")
    a = _thesis_v("TCS", "Is margin durable?", "fp1", "2024-01-01", "X", "medium")
    ThesisStore(tmp_path / "TCS" / "theses.json", "TCS").save(a)

    result = CliRunner().invoke(cli, ["memory", "diff", a.view_id, "nonexistent-id"])
    assert result.exit_code == 1
    assert "nonexistent-id" in result.output


def test_diff_identical_theses_reports_no_differences(monkeypatch, tmp_path) -> None:
    _env(monkeypatch, tmp_path)
    _seed_profile(tmp_path, "TCS")
    a = _thesis_v("TCS", "Is margin durable?", "fp1", "2024-01-01", "Stable.", "medium")
    b = _thesis_v("TCS", "Is margin durable?", "fp2", "2025-01-01", "Stable.", "medium")
    store = ThesisStore(tmp_path / "TCS" / "theses.json", "TCS")
    store.save(a)
    store.save(b)

    result = CliRunner().invoke(cli, ["memory", "diff", a.view_id, b.view_id])
    assert result.exit_code == 0, result.output
    assert "No differences" in result.output


def test_diff_finds_view_across_different_subjects(monkeypatch, tmp_path) -> None:
    # CLI lookup must sweep the whole portfolio, same convention as `memory show`.
    _env(monkeypatch, tmp_path)
    _seed_profile(tmp_path, "TCS")
    _seed_profile(tmp_path, "SBIN")
    a = _thesis_v("TCS", "Is margin durable?", "fp1", "2024-01-01", "X", "medium")
    b = _thesis_v("SBIN", "Is margin durable?", "fp2", "2025-01-01", "Y", "medium")
    ThesisStore(tmp_path / "TCS" / "theses.json", "TCS").save(a)
    ThesisStore(tmp_path / "SBIN" / "theses.json", "SBIN").save(b)

    result = CliRunner().invoke(cli, ["memory", "diff", a.view_id, b.view_id])
    assert result.exit_code == 0, result.output
    assert "+ Y" in result.output
    assert "- X" in result.output
