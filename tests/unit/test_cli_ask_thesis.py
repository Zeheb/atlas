"""`atlas ask --thesis <view_id>` (M2.4.1 item 1).

The production entry point C6 lacked: before this, the only code paths that
populated GroundingContext.thesis were eval/runner.py and tests, so a user
could remember a view but never reason against one.

The load-bearing test is the closed-world one. This is the first path where a
REAL stored view meets a REAL context, so it is the first place the
"reference only, never evidence" guarantee could actually leak in production
-- the recalled view's evidence ids must not reach evidence_index, and
therefore must not be citable.
"""

from __future__ import annotations

import json
from pathlib import Path

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

VIEW_EVIDENCE = "ev-OLD"
CURRENT_EVIDENCE = "ev-1"


def _seed_profile(base: Path, ticker: str = "TCS") -> None:
    profile = CompanyProfile(
        company_id=ticker,
        financial=FinancialTimeSeries(
            snapshots=[
                FinancialSnapshot(
                    period="2026-03-31",
                    period_type="annual",
                    basis="consolidated",
                    facts={FactKind.FINANCIAL_OPERATING_MARGIN: 24.2},
                    sources=[CURRENT_EVIDENCE],
                )
            ]
        ),
    )
    CompanyStore(base / ticker / "profile.json", ticker).save(profile)


def _remember(
    base: Path, ticker: str = "TCS", evidence_id: str = VIEW_EVIDENCE
) -> Thesis:
    """Persist a view citing evidence that is NOT in the current profile, so
    the closed-world test has something real to catch."""
    subject = SubjectRef(subject_id=ticker, display=ticker)
    claim = Claim(
        subject_ref=subject,
        statement="Margins were declining.",
        assertability="judgment",
        confidence="medium",
        evidence=(EvidenceReference(evidence_id=evidence_id),),
    )
    result = ReasoningResult(
        question=Question(raw_text="Should I invest in TCS?", subject_ref=subject),
        findings=(
            Finding(
                statement="Margins were declining.",
                assertability="judgment",
                confidence="medium",
                supporting_claims=(claim,),
            ),
        ),
        overall_confidence="medium",
        citations=frozenset({evidence_id}),
        refused=False,
    )
    fingerprint = "fp-1"
    thesis = Thesis(
        question="Should I invest in TCS?",
        subjects=(ticker,),
        run_fingerprint=fingerprint,
        view_id=compute_view_id(fingerprint, "Should I invest in TCS?"),
        as_of="2026-01-01T00:00:00+00:00",
        result=result,
    )
    ThesisStore(base / ticker / "theses.json", ticker).save(thesis)
    return thesis


class _CapturingFake:
    """Records the rendered user prompt so the test can inspect what the model
    was actually shown, not merely what the CLI printed."""

    def __init__(self) -> None:
        self.user_prompts: list[str] = []

    def complete(self, *, system: str, user: str) -> str:
        self.user_prompts.append(user)
        return json.dumps(
            {
                "refused": False,
                "overall_confidence": "medium",
                "findings": [
                    {
                        "statement": "Margins improved to 24.2%.",
                        "assertability": "judgment",
                        "confidence": "medium",
                        "supporting_evidence_ids": [CURRENT_EVIDENCE],
                        "known_unknowns": [],
                        "contradicts_thesis": True,
                        "counter_case": "The recalled view said margins were declining.",
                    }
                ],
            }
        )


class _FabricatingFake:
    """Cites the recalled view's evidence id, which is NOT in the current
    closed world. Graded "judgment" deliberately: G3/G4 drops an ungrounded
    judgment outright, so if ev-OLD were citable the finding would survive,
    and if it is not the finding disappears and ask() refuses. That makes the
    closed-world outcome unambiguous rather than a string search over prose."""

    def complete(self, *, system: str, user: str) -> str:
        return json.dumps(
            {
                "refused": False,
                "overall_confidence": "medium",
                "findings": [
                    {
                        "statement": "Margins were declining, as previously concluded.",
                        "assertability": "judgment",
                        "confidence": "high",
                        "supporting_evidence_ids": [VIEW_EVIDENCE],
                        "known_unknowns": [],
                    }
                ],
            }
        )


def _env(monkeypatch, tmp_path: Path, client) -> None:
    monkeypatch.setenv("ATLAS_REPOSITORY_BASE_PATH", str(tmp_path))
    monkeypatch.setenv("ATLAS_ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(
        "atlas.reasoning.llm.build_llm_client",
        lambda settings, *, role: client,
    )


# --- The closed world, at the CLI boundary ------------------------------------------
def test_recalled_view_evidence_is_never_citable(monkeypatch, tmp_path) -> None:
    """THE test. The model cites the recalled view's ev-OLD; ev-OLD is not in
    the current context, so the citation is dropped -- and with the judgment's
    only support gone, nothing survives grounding and ask() refuses rather
    than asserting a conclusion the current evidence cannot support."""
    _env(monkeypatch, tmp_path, _FabricatingFake())
    _seed_profile(tmp_path)
    thesis = _remember(tmp_path)

    result = CliRunner().invoke(
        cli,
        ["ask", "TCS", "What about margins?", "--thesis", thesis.view_id],
    )
    assert result.exit_code == 0, result.output
    assert "No finding could be grounded" in result.output
    # The claim itself never reached the reader.
    assert "as previously concluded" not in result.output


def test_valid_evidence_ids_never_include_the_recalled_views_evidence(
    monkeypatch,
    tmp_path,
) -> None:
    """Inspect the actual prompt: ev-OLD may appear in the RECALLED VIEW block
    (labelled not citable) but must never reach VALID EVIDENCE IDS."""
    client = _CapturingFake()
    _env(monkeypatch, tmp_path, client)
    _seed_profile(tmp_path)
    thesis = _remember(tmp_path)

    CliRunner().invoke(
        cli, ["ask", "TCS", "What about margins?", "--thesis", thesis.view_id]
    )

    prompt = client.user_prompts[0]
    valid_line = next(
        l for l in prompt.splitlines() if l.startswith("VALID EVIDENCE IDS")
    )
    assert VIEW_EVIDENCE not in valid_line
    assert CURRENT_EVIDENCE in valid_line


# --- The view actually reaches the model ---------------------------------------------
def test_recalled_view_block_reaches_the_prompt(monkeypatch, tmp_path) -> None:
    client = _CapturingFake()
    _env(monkeypatch, tmp_path, client)
    _seed_profile(tmp_path)
    thesis = _remember(tmp_path)

    CliRunner().invoke(
        cli, ["ask", "TCS", "What about margins?", "--thesis", thesis.view_id]
    )

    prompt = client.user_prompts[0]
    assert "RECALLED VIEW" in prompt
    assert "Margins were declining." in prompt


def test_advisory_staleness_line_is_printed(monkeypatch, tmp_path) -> None:
    """No knowledge.db exists, so the view's cited id cannot resolve -- the
    advisory line must say so rather than staying silent."""
    _env(monkeypatch, tmp_path, _CapturingFake())
    _seed_profile(tmp_path)
    thesis = _remember(tmp_path)

    result = CliRunner().invoke(
        cli,
        ["ask", "TCS", "What about margins?", "--thesis", thesis.view_id],
    )
    assert "Recalled view" in result.output
    assert "STALE" in result.output


def test_staleness_is_advisory_not_blocking(monkeypatch, tmp_path) -> None:
    """A stale view still answers -- ADR-0010 §5. Exit 0, answer rendered."""
    _env(monkeypatch, tmp_path, _CapturingFake())
    _seed_profile(tmp_path)
    thesis = _remember(tmp_path)

    result = CliRunner().invoke(
        cli,
        ["ask", "TCS", "What about margins?", "--thesis", thesis.view_id],
    )
    assert result.exit_code == 0, result.output
    assert "Margins improved" in result.output


# --- Failure modes exit cleanly ------------------------------------------------------
def test_unknown_view_id_exits_one(monkeypatch, tmp_path) -> None:
    _env(monkeypatch, tmp_path, _CapturingFake())
    _seed_profile(tmp_path)
    _remember(tmp_path)

    result = CliRunner().invoke(
        cli,
        ["ask", "TCS", "What about margins?", "--thesis", "no-such-view"],
    )
    assert result.exit_code == 1
    assert "No remembered view" in result.output
    assert "atlas memory list" in result.output


def test_no_store_at_all_exits_one(monkeypatch, tmp_path) -> None:
    _env(monkeypatch, tmp_path, _CapturingFake())
    _seed_profile(tmp_path)  # profile but never remembered anything

    result = CliRunner().invoke(
        cli,
        ["ask", "TCS", "What about margins?", "--thesis", "anything"],
    )
    assert result.exit_code == 1
    assert "No remembered view" in result.output


def test_incompatible_store_exits_one_without_a_traceback(
    monkeypatch, tmp_path
) -> None:
    _env(monkeypatch, tmp_path, _CapturingFake())
    _seed_profile(tmp_path)
    (tmp_path / "TCS" / "theses.json").write_text(
        json.dumps({"store_version": "99", "subject": "TCS", "theses": []}),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        cli,
        ["ask", "TCS", "What about margins?", "--thesis", "anything"],
    )
    assert result.exit_code == 1
    assert "Unsupported store_version" in result.output
    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_bad_view_id_fails_before_building_an_llm_client(monkeypatch, tmp_path) -> None:
    """A user error should not cost an API-key check -- the same
    fail-before-spending-anything shape as --dry-run/--retrieval-only."""
    monkeypatch.setenv("ATLAS_REPOSITORY_BASE_PATH", str(tmp_path))

    def _boom(settings, *, role):
        raise AssertionError("build_llm_client must not run when --thesis is invalid")

    monkeypatch.setattr("atlas.reasoning.llm.build_llm_client", _boom)
    _seed_profile(tmp_path)

    result = CliRunner().invoke(
        cli,
        ["ask", "TCS", "What about margins?", "--thesis", "no-such-view"],
    )
    assert result.exit_code == 1


# --- Absent: unchanged from today ----------------------------------------------------
def test_without_thesis_flag_no_view_is_loaded(monkeypatch, tmp_path) -> None:
    client = _CapturingFake()
    _env(monkeypatch, tmp_path, client)
    _seed_profile(tmp_path)
    _remember(tmp_path)  # a view EXISTS but was not asked for

    result = CliRunner().invoke(cli, ["ask", "TCS", "What about margins?"])
    assert result.exit_code == 0, result.output
    assert "RECALLED VIEW" not in client.user_prompts[0]
    assert "Recalled view" not in result.output


def test_contradicts_thesis_survives_to_the_result(monkeypatch, tmp_path) -> None:
    """End-to-end: the C7 field M2.4 revived is populated on a real ask path,
    not only in eval."""
    _env(monkeypatch, tmp_path, _CapturingFake())
    _seed_profile(tmp_path)
    thesis = _remember(tmp_path)

    result = CliRunner().invoke(
        cli,
        ["ask", "TCS", "What about margins?", "--thesis", thesis.view_id],
    )
    assert result.exit_code == 0, result.output
