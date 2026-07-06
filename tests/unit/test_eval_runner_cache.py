"""LiveReasoningRunner + EvalCache (harness redesign, free-tier operation).

An unchanged case never re-invokes the LLM across separate runner
constructions sharing one EvalCache — the exact scenario two separate
`atlas eval run` invocations would produce. Reasoning itself (ask.py,
prompt.py, context.py) is untouched; only LiveReasoningRunner's optional
`cache` parameter is exercised.
"""
from __future__ import annotations

import json
from pathlib import Path

from atlas.analysis.base import FactKind
from atlas.company.model import CompanyProfile, FinancialSnapshot, FinancialTimeSeries
from atlas.company.store import CompanyStore
from atlas.config.settings import Settings
from atlas.eval.cache import EvalCache
from atlas.eval.cases import EvalCase
from atlas.eval.runner import LiveReasoningRunner
from atlas.reasoning.llm import FakeLLMClient


def _seed(base: Path) -> None:
    profile = CompanyProfile(
        company_id="TCS",
        financial=FinancialTimeSeries(snapshots=[FinancialSnapshot(
            period="2026-03-31", period_type="annual", basis="consolidated",
            facts={FactKind.FINANCIAL_OPERATING_MARGIN: 24.2}, sources=["ev-1"],
        )]),
    )
    CompanyStore(base / "TCS" / "profile.json", "TCS").save(profile)


def _case() -> EvalCase:
    return EvalCase(id="t01", category="A", question="How stable are margins?",
                    subject="TCS", expected_behavior="answer", rubric="synthesize")


def _fake_client() -> FakeLLMClient:
    return FakeLLMClient(response=json.dumps({
        "refused": False, "overall_confidence": "high",
        "findings": [{
            "statement": "Operating margin has held near 24%.",
            "assertability": "judgment", "confidence": "high",
            "supporting_evidence_ids": ["ev-1"], "known_unknowns": [],
        }],
    }))


def test_second_run_of_unchanged_case_does_not_call_the_llm(tmp_path: Path) -> None:
    _seed(tmp_path)
    settings = Settings(_env_file=None, repository_base_path=tmp_path)
    cache = EvalCache(tmp_path / "cache.json")

    client1 = _fake_client()
    runner1 = LiveReasoningRunner(settings, client1, cache=cache)
    result1, answer1, _ctx1 = runner1.run(_case())
    assert len(client1.calls) == 1

    # A fresh runner + fresh client, sharing the SAME cache — mirrors a
    # second `atlas eval run` invocation for an unchanged case.
    client2 = _fake_client()
    runner2 = LiveReasoningRunner(settings, client2, cache=cache)
    result2, answer2, _ctx2 = runner2.run(_case())

    assert len(client2.calls) == 0  # cache hit: the LLM was never touched
    assert answer2.prose == answer1.prose
    assert result2.findings == result1.findings
    assert cache.hits == 1
    assert cache.misses == 1


def test_without_cache_every_run_calls_the_llm(tmp_path: Path) -> None:
    _seed(tmp_path)
    settings = Settings(_env_file=None, repository_base_path=tmp_path)

    client1 = _fake_client()
    LiveReasoningRunner(settings, client1).run(_case())  # cache=None (default)
    client2 = _fake_client()
    LiveReasoningRunner(settings, client2).run(_case())

    assert len(client1.calls) == 1
    assert len(client2.calls) == 1  # no cache shared, no memoization


def test_cache_persists_to_disk_across_process_boundaries(tmp_path: Path) -> None:
    _seed(tmp_path)
    settings = Settings(_env_file=None, repository_base_path=tmp_path)
    path = tmp_path / "cache.json"

    cache1 = EvalCache(path)
    client1 = _fake_client()
    LiveReasoningRunner(settings, client1, cache=cache1).run(_case())
    cache1.save()

    # New EvalCache instance from the same path — simulates a brand-new
    # `atlas eval run` process reading a cache written by a prior one.
    cache2 = EvalCache(path)
    client2 = _fake_client()
    LiveReasoningRunner(settings, client2, cache=cache2).run(_case())

    assert len(client2.calls) == 0
    assert cache2.hits == 1
