"""Profile equivalence over the golden corpus — the confidence variant.

Same claim as ``tests/unit/test_profile_source_equivalence.py`` and the same
comparison helper, against real analyzer output over real acquired documents.
Marked ``integration``: CI has no acquired PDFs, which is why the marker is
deselected there, and why the CI gate is the synthetic variant (D1).

What this adds is the part synthetic inputs cannot claim. The synthetic
corpus contains the shapes the store was built to survive because they were
put there; this shows the two paths agree on whatever the eleven analyzers
actually emit, including every fact kind and section name nobody thought to
construct by hand.
"""

from __future__ import annotations

import json
from collections.abc import Generator
from pathlib import Path

import pytest

from atlas.acquisition.repository import Repository
from atlas.analysis.registry import analyze
from atlas.assertions.store import AssertionStore
from atlas.assertions.writer import write_result
from atlas.company.builder import build_profile
from atlas.company.store import CompanyStore, load_profile_payload
from atlas.knowledge.base import KnowledgeBase
from atlas.provenance import current_fingerprint
from tests.support.equivalence import assert_profiles_identical

pytestmark = pytest.mark.integration

_PROJECT_ROOT = Path(__file__).parents[2]
_EXPECTATIONS_DIR = _PROJECT_ROOT / "tests" / "corpus" / "expectations"
_TCS_REPO = _PROJECT_ROOT / "repositories" / "TCS"
_COMPANY = "TCS"


def _corpus_evidence_ids() -> list[str]:
    return [
        json.loads(path.read_text(encoding="utf-8"))["evidence_id"]
        for path in sorted(_EXPECTATIONS_DIR.glob("*.json"))
    ]


_EVIDENCE_IDS = _corpus_evidence_ids()


@pytest.fixture(scope="module")
def tcs_repo(isolated_repo_factory) -> Path:  # type: ignore[no-untyped-def]
    if not _TCS_REPO.exists():
        pytest.skip("TCS repository not found")
    return isolated_repo_factory(_TCS_REPO, evidence_ids=_EVIDENCE_IDS)


@pytest.fixture(scope="module")
def kb(tcs_repo: Path) -> Generator[KnowledgeBase, None, None]:
    instance = KnowledgeBase(tcs_repo)
    repo = Repository(tcs_repo)
    for evidence_id in _EVIDENCE_IDS:
        entry = repo.get(evidence_id)
        if entry is not None:
            instance.parse(entry)
    yield instance


def _analyzable(kb: KnowledgeBase, evidence_id: str) -> bool:
    document = kb.get(evidence_id)
    if document is None or document.status != "ok":
        return False
    return bool(kb.get_content(evidence_id))


def test_analyzer_and_assertion_profiles_are_identical(
    tmp_path: Path, kb: KnowledgeBase
) -> None:
    fingerprint = current_fingerprint()
    store_root = tmp_path / "store"
    store = AssertionStore(store_root)

    from_analyzers = []
    for evidence_id in _EVIDENCE_IDS:
        if not _analyzable(kb, evidence_id):
            continue
        result = analyze(evidence_id, kb)
        from_analyzers.append(result)
        write_result(store, result, fingerprint=fingerprint)

    if not from_analyzers:
        pytest.skip("no corpus document is parsed in this checkout")

    from atlas.assertions.reader import results_for

    from_assertions = results_for(store_root, fingerprint=fingerprint.digest())
    assert len(from_assertions) == len(from_analyzers)

    left_path = tmp_path / "analyzers.json"
    right_path = tmp_path / "assertions.json"
    CompanyStore(left_path, _COMPANY).save(
        build_profile(_COMPANY, from_analyzers), from_analyzers
    )
    CompanyStore(right_path, _COMPANY).save(
        build_profile(_COMPANY, from_assertions), from_assertions
    )

    assert_profiles_identical(
        load_profile_payload(left_path),
        load_profile_payload(right_path),
        left_label="analyzer-sourced",
        right_label="assertion-sourced",
    )


def test_the_corpus_profile_is_not_empty(tmp_path: Path, kb: KnowledgeBase) -> None:
    """Guards the test above from passing on two empty profiles."""
    results = [
        analyze(evidence_id, kb)
        for evidence_id in _EVIDENCE_IDS
        if _analyzable(kb, evidence_id)
    ]
    if not results:
        pytest.skip("no corpus document is parsed in this checkout")

    path = tmp_path / "profile.json"
    CompanyStore(path, _COMPANY).save(build_profile(_COMPANY, results), results)
    payload = load_profile_payload(path)

    populated = {
        key
        for key, value in payload.items()
        if key != "company_id" and value not in ({}, [], None)
    }
    print(f"corpus profile sections with content: {sorted(populated)}")
    assert populated, "the corpus produced an empty profile; equivalence is vacuous"
