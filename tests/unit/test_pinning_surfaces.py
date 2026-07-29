"""Pinning across every answer surface (#46): ask, thesis, investigate, research.

Testing four surfaces one at a time would prove four things and guarantee
nothing about the fifth. So the load-bearing test here is structural:
``ask()`` is the ONLY place in ``src/`` that builds a non-refusal
ReasoningResult, and every path through it is pinned. Any surface that
answers a question therefore answers with a pinned result, including ones
that do not exist yet.

The per-surface tests are then about RENDERING -- whether the footer
reaches the terminal -- which genuinely does differ per surface, because
each command prints its own way.

What the survey found, and why two surfaces have no footer
----------------------------------------------------------
``investigate`` keeps ``semantic_findings`` (C7 Findings) at the
InvestigationResult boundary and drops the ReasoningResult that carried
them, so the per-dimension answer's pinning is not retained anywhere. That
is by construction, not an oversight: the durable artifact of an
investigate-then-synthesize run is the Thesis, and ``synthesize()`` re-asks
through ``ask()``, so the artifact anyone stores IS pinned.

``research`` renders a ReportData, which holds no ReasoningResult at all --
it is assembled from profile queries, not from a reasoning pass.

Both facts are asserted below rather than left implicit, so a future reader
finds a stated design decision instead of a suspected gap.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from atlas.analysis.base import FactKind
from atlas.cli import cli
from atlas.company.model import CompanyProfile, FinancialSnapshot, FinancialTimeSeries
from atlas.company.store import CompanyStore
from atlas.provenance import current_fingerprint
from atlas.reasoning.contracts import (
    Claim,
    EvidenceReference,
    Finding,
    Question,
    ReasoningResult,
    SubjectRef,
)
from atlas.reasoning.llm import FakeLLMClient
from atlas.research.memory import ThesisStore
from atlas.research.thesis import Thesis

_SRC = Path(__file__).parents[2] / "src"
_TICKER = "TCS"
_SUBJECT = SubjectRef(subject_id=_TICKER, display=_TICKER)


# ---------------------------------------------------------------------------
# The structural claim
# ---------------------------------------------------------------------------


def _construction_sites(path: Path) -> list[int]:
    """Line numbers where *path* calls ``ReasoningResult(...)``."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "ReasoningResult"
    ]


def test_only_ask_and_the_thesis_store_build_reasoning_results() -> None:
    """The inventory the structural claim rests on.

    ``ask.py`` produces answers; ``research/memory.py`` reconstructs a stored
    one on load, which is a deserializer and carries whatever was saved. A
    third site would be a new answer path that this milestone never pinned.
    """
    sites = {
        str(path.relative_to(_SRC)).replace("\\", "/"): _construction_sites(path)
        for path in _SRC.rglob("*.py")
        if _construction_sites(path)
    }

    assert sorted(sites) == ["atlas/reasoning/ask.py", "atlas/research/memory.py"], (
        f"A new ReasoningResult construction site appeared: {sorted(sites)}. "
        "Every answer surface must be pinned; pin this one, then add it here."
    )


def test_every_construction_site_in_ask_is_pinned() -> None:
    """Both of them: the answer path and the refusal path."""
    source = (_SRC / "atlas" / "reasoning" / "ask.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "ReasoningResult"
    ]

    assert len(calls) == 2
    for call in calls:
        keywords = {kw.arg for kw in call.keywords}
        assert "fingerprint" in keywords, f"unpinned result at line {call.lineno}"
        assert "consulted_evidence_ids" in keywords


# ---------------------------------------------------------------------------
# Surface: ask
# ---------------------------------------------------------------------------


def _seed_profile(base: Path) -> None:
    profile = CompanyProfile(
        company_id=_TICKER,
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
    CompanyStore(base / _TICKER / "profile.json", _TICKER).save(profile)


def _answer_response() -> str:
    return json.dumps(
        {
            "refused": False,
            "overall_confidence": "high",
            "findings": [
                {
                    "statement": "Operating margin has held near 24%.",
                    "assertability": "fact",
                    "confidence": "high",
                    "supporting_evidence_ids": ["ev-1"],
                }
            ],
        }
    )


def _run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    response: str,
    args: list[str],
) -> Any:
    monkeypatch.setenv("ATLAS_REPOSITORY_BASE_PATH", str(tmp_path))
    monkeypatch.setenv("ATLAS_ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(
        "atlas.reasoning.llm.build_llm_client",
        lambda settings, *, role: FakeLLMClient(response=response),
    )
    _seed_profile(tmp_path)
    return CliRunner().invoke(cli, args)


def test_ask_prints_the_pinning_footer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    result = _run(
        monkeypatch,
        tmp_path,
        _answer_response(),
        ["ask", _TICKER, "How are margins?"],
    )

    assert result.exit_code == 0, result.output
    assert f"Atlas {current_fingerprint().digest()}" in result.output


def test_ask_prints_the_footer_on_a_refusal_too(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    refusal = json.dumps({"refused": True, "refusal_reason": "out of scope"})

    result = _run(monkeypatch, tmp_path, refusal, ["ask", _TICKER, "How are margins?"])

    assert "Atlas cannot answer this question." in result.output
    assert f"Atlas {current_fingerprint().digest()}" in result.output


# ---------------------------------------------------------------------------
# Surface: thesis, via the stored view that `memory show` renders
# ---------------------------------------------------------------------------


def _pinned_result() -> ReasoningResult:
    claim = Claim(
        subject_ref=_SUBJECT,
        statement="Revenue grew.",
        assertability="fact",
        confidence="high",
        evidence=(EvidenceReference(evidence_id="ev-1"),),
    )
    return ReasoningResult(
        question=Question(raw_text="Did revenue grow?", subject_ref=_SUBJECT),
        findings=(
            Finding(
                statement="Revenue grew.",
                assertability="fact",
                confidence="high",
                supporting_claims=(claim,),
            ),
        ),
        overall_confidence="high",
        citations=frozenset({"ev-1"}),
        fingerprint="3f9a1c",
        consulted_evidence_ids=("ev-1", "ev-2"),
    )


def _store_thesis(base: Path, result: ReasoningResult) -> None:
    ThesisStore(base / _TICKER / "theses.json", _TICKER).save(
        Thesis(
            question="Did revenue grow?",
            subjects=(_TICKER,),
            run_fingerprint="run-1",
            view_id="view-1",
            as_of="2026-07-14T10:00:00+00:00",
            result=result,
        )
    )


def test_memory_show_prints_the_pinning_footer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The thesis surface, read back from the store rather than re-synthesized."""
    monkeypatch.setenv("ATLAS_REPOSITORY_BASE_PATH", str(tmp_path))
    monkeypatch.setenv("ATLAS_ANTHROPIC_API_KEY", "sk-test")
    _seed_profile(tmp_path)
    _store_thesis(tmp_path, _pinned_result())

    result = CliRunner().invoke(cli, ["memory", "show", "view-1"])

    assert result.exit_code == 0, result.output
    assert "Atlas 3f9a1c · 2 documents" in result.output


def test_memory_show_of_a_pre_pinning_thesis_prints_no_footer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Views stored before M6 must render exactly as they always did."""
    monkeypatch.setenv("ATLAS_REPOSITORY_BASE_PATH", str(tmp_path))
    monkeypatch.setenv("ATLAS_ANTHROPIC_API_KEY", "sk-test")
    _seed_profile(tmp_path)
    unpinned = ReasoningResult(
        question=_pinned_result().question,
        findings=_pinned_result().findings,
        overall_confidence="high",
        citations=frozenset({"ev-1"}),
    )
    _store_thesis(tmp_path, unpinned)

    result = CliRunner().invoke(cli, ["memory", "show", "view-1"])

    assert result.exit_code == 0, result.output
    assert "Atlas " not in result.output


# ---------------------------------------------------------------------------
# Surfaces with no footer, and why
# ---------------------------------------------------------------------------


def test_investigate_drops_the_reasoning_result_at_its_boundary() -> None:
    """Stated, so the missing footer reads as a decision rather than a gap.

    InvestigationResult keeps the C7 Findings and not the envelope that
    carried the fingerprint. The durable artifact of a run is the Thesis,
    and synthesize() re-asks through ask(), so what gets stored is pinned.
    """
    from atlas.research.investigate import InvestigationResult

    fields = set(InvestigationResult.__dataclass_fields__)

    assert "semantic_findings" in fields
    assert "fingerprint" not in fields
    assert not any(
        f.type == "ReasoningResult"
        for f in InvestigationResult.__dataclass_fields__.values()
    )


def test_the_research_report_holds_no_reasoning_result() -> None:
    """ReportData is assembled from profile queries, not from a reasoning pass."""
    from atlas.research.model import ReportData

    assert "result" not in ReportData.__dataclass_fields__
    assert not _construction_sites(_SRC / "atlas" / "research" / "report.py")
