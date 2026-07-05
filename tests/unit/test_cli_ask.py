"""End-to-end `atlas ask` CLI wiring (M0 commit 6).

Exercises the full slice — profile load -> context -> ask -> render -> print —
with a FakeLLMClient injected in place of the Anthropic client, so no network
or API key is needed. This is the walking skeleton of §8.2 W3.
"""
from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from atlas.analysis.base import FactKind
from atlas.cli import cli
from atlas.company.model import (
    CompanyProfile,
    FinancialSnapshot,
    FinancialTimeSeries,
)
from atlas.company.store import CompanyStore
from atlas.reasoning.client import FakeLLMClient


def _seed_profile(base: Path, ticker: str = "TCS") -> None:
    profile = CompanyProfile(
        company_id=ticker,
        financial=FinancialTimeSeries(snapshots=[
            FinancialSnapshot(
                period="2026-03-31", period_type="annual", basis="consolidated",
                facts={FactKind.FINANCIAL_OPERATING_MARGIN: 24.2},
                sources=["ev-1"],
            )
        ]),
    )
    CompanyStore(base / ticker / "profile.json", ticker).save(profile)


def _run(monkeypatch, tmp_path, response: str, args: list[str]):
    monkeypatch.setenv("ATLAS_REPOSITORY_BASE_PATH", str(tmp_path))
    monkeypatch.setenv("ATLAS_ANTHROPIC_API_KEY", "sk-test")  # from_settings needs a key
    monkeypatch.setattr(
        "atlas.reasoning.client.AnthropicClient.from_settings",
        classmethod(lambda cls, settings: FakeLLMClient(response=response)),
    )
    _seed_profile(tmp_path)
    return CliRunner().invoke(cli, args)


def test_ask_end_to_end_grounded_answer(monkeypatch, tmp_path) -> None:
    response = json.dumps({
        "refused": False, "overall_confidence": "high",
        "findings": [{
            "statement": "Operating margin has held near 24%.",
            "assertability": "judgment", "confidence": "high",
            "supporting_evidence_ids": ["ev-1"], "known_unknowns": [],
        }],
    })
    result = _run(monkeypatch, tmp_path, response, ["ask", "TCS", "How are margins?"])
    assert result.exit_code == 0, result.output
    assert "JUDGMENT" in result.output
    assert "ev-1" in result.output


def test_ask_refuses_out_of_scope(monkeypatch, tmp_path) -> None:
    response = json.dumps({
        "refused": True, "refusal_reason": "No market price data in Atlas.",
        "overall_confidence": "low", "findings": [],
    })
    result = _run(monkeypatch, tmp_path, response, ["ask", "TCS", "What is it worth?"])
    assert result.exit_code == 0, result.output
    assert "cannot answer" in result.output.lower()


def test_ask_errors_when_profile_missing(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ATLAS_REPOSITORY_BASE_PATH", str(tmp_path))
    monkeypatch.setenv("ATLAS_ANTHROPIC_API_KEY", "sk-test")
    result = CliRunner().invoke(cli, ["ask", "NOPE", "anything?"])
    assert result.exit_code == 1
    assert "No profile" in result.output
