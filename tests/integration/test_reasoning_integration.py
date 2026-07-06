"""Real-API reasoning check (M0 commit 6). Marked 'integration' — deselected by
default; skipped without a key or the TCS profile. Hitting the live model, the
one invariant that must always hold is closed-world grounding (G1/G10).
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from atlas.company.store import CompanyStore
from atlas.config.settings import Settings
from atlas.reasoning.ask import ask
from atlas.reasoning.context import build_context
from atlas.reasoning.contracts import Question, SubjectRef
from atlas.reasoning.llm import build_llm_client

pytestmark = pytest.mark.integration


@pytest.mark.skipif(
    not os.getenv("ATLAS_ANTHROPIC_API_KEY"), reason="requires ATLAS_ANTHROPIC_API_KEY"
)
def test_ask_real_api_stays_within_closed_world() -> None:
    profile_path = Path("repositories/TCS/profile.json")
    if not profile_path.exists():
        pytest.skip("no TCS profile on disk")
    profile = CompanyStore(profile_path, "TCS").load()
    subject = SubjectRef(subject_id="TCS", display="Tata Consultancy Services")
    context = build_context(profile, subject)
    client = build_llm_client(Settings(), role="reasoning")

    result = ask(
        Question(raw_text="How consistent has ROE been over the available history?",
                 subject_ref=subject),
        context, client,
    )
    # Whatever the model says, every surviving citation is in the closed world.
    assert result.citations <= context.evidence_index
    if not result.refused:
        assert result.findings
