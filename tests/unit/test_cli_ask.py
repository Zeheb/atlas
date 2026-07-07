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
from atlas.reasoning.llm import FakeLLMClient


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
    monkeypatch.setenv("ATLAS_ANTHROPIC_API_KEY", "sk-test")  # build_llm_client needs a key
    # Patch the factory (the actual seam cli.py depends on), not a specific
    # adapter's classmethod — robust to which provider is configured.
    monkeypatch.setattr(
        "atlas.reasoning.llm.build_llm_client",
        lambda settings, *, role: FakeLLMClient(response=response),
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


# --- Ollama transport: friendly build/connection errors (real factory) --------
def test_ask_with_ollama_missing_model_exits_cleanly(monkeypatch, tmp_path) -> None:
    # No build_llm_client patch: the real factory builds a real OllamaClient,
    # which fails clearly because ATLAS_OLLAMA_MODEL is unset.
    monkeypatch.setenv("ATLAS_REPOSITORY_BASE_PATH", str(tmp_path))
    monkeypatch.setenv("ATLAS_LLM_PROVIDER", "ollama")
    monkeypatch.delenv("ATLAS_OLLAMA_MODEL", raising=False)
    _seed_profile(tmp_path)
    result = CliRunner().invoke(cli, ["ask", "TCS", "How are margins?"])
    assert result.exit_code == 1
    assert "ATLAS_OLLAMA_MODEL" in result.output  # actionable, not a traceback
    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_ask_with_ollama_server_down_exits_cleanly(monkeypatch, tmp_path) -> None:
    import requests

    monkeypatch.setenv("ATLAS_REPOSITORY_BASE_PATH", str(tmp_path))
    monkeypatch.setenv("ATLAS_LLM_PROVIDER", "ollama")
    monkeypatch.setenv("ATLAS_OLLAMA_MODEL", "qwen3:8b")

    def _connection_refused(url, *, json, timeout):  # noqa: ANN001, ANN202 - test double
        raise requests.exceptions.ConnectionError("refused")

    monkeypatch.setattr("atlas.reasoning.llm.ollama.requests.post", _connection_refused)
    _seed_profile(tmp_path)
    result = CliRunner().invoke(cli, ["ask", "TCS", "How are margins?"])
    assert result.exit_code == 1
    assert "Is Ollama running?" in result.output  # friendly, not a traceback
    assert result.exception is None or isinstance(result.exception, SystemExit)
