"""Real-API evaluation smoke (eval commit 5). Marked 'integration'; skipped
without a key or the TCS profile. Runs the deterministic dimensions of the real
suite (no judge) against TCS and asserts a well-formed report is produced with
grounding scored — the harness works end to end on the live system.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from atlas.config.settings import Settings
from atlas.eval.cases import load_cases
from atlas.eval.runner import LiveReasoningRunner, run_suite
from atlas.reasoning.client import AnthropicClient

pytestmark = pytest.mark.integration


@pytest.mark.skipif(
    not os.getenv("ATLAS_ANTHROPIC_API_KEY"), reason="requires ATLAS_ANTHROPIC_API_KEY"
)
def test_eval_suite_runs_against_real_tcs() -> None:
    if not Path("repositories/TCS/profile.json").exists():
        pytest.skip("no TCS profile on disk")
    settings = Settings()
    client = AnthropicClient.from_settings(settings)
    # Only the always-available single-name cases; no judge (deterministic dims).
    cases = [c for c in load_cases() if c.is_available(frozenset({"single_name"}))]
    report = run_suite(
        cases[:3], LiveReasoningRunner(settings, client), None, {"single_name"},
        milestone="integration", model=settings.reasoning_model,
    )
    agg = report.to_dict()["aggregates"]
    assert agg["active_cases"] == 3
    assert agg["grounding_pass_rate"] is not None  # grounding was scored
