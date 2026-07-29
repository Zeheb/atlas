"""The equivalence gate over the golden corpus — the confidence variant.

Same invariant as ``tests/unit/test_rebuild_equivalence.py``: full ==
incremental == shuffled == reversed, byte-identical after canonicalisation.
Real analyzer output over real documents rather than constructed results.

Marked ``integration`` (D1): CI has no acquired PDFs, so the CI gate is the
synthetic variant and this is the pre-merge confidence check.
"""

from __future__ import annotations

import json
import random
from collections.abc import Generator
from pathlib import Path

import pytest

from atlas.acquisition.repository import Repository
from atlas.analysis.base import AnalysisResult
from atlas.analysis.registry import analyze
from atlas.company.builder import build_profile
from atlas.company.store import CompanyStore, StaleResultError, load_profile_payload
from atlas.knowledge.base import KnowledgeBase
from atlas.rebuild import explain_difference

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


@pytest.fixture(scope="module")
def results(kb: KnowledgeBase) -> list[AnalysisResult]:
    analysed = [
        analyze(evidence_id, kb)
        for evidence_id in _EVIDENCE_IDS
        if kb.get(evidence_id) is not None
        and kb.get(evidence_id).status == "ok"  # type: ignore[union-attr]
        and kb.get_content(evidence_id)
    ]
    if not analysed:
        pytest.skip("no corpus document is parsed in this checkout")
    return analysed


def _full(results: list[AnalysisResult], path: Path) -> dict:
    CompanyStore(path, _COMPANY).save(build_profile(_COMPANY, results), results)
    return load_profile_payload(path)


def _incremental(results: list[AnalysisResult], path: Path) -> dict:
    store = CompanyStore(path, _COMPANY)
    store.save(build_profile(_COMPANY, results[:1]), results[:1])
    for result in results[1:]:
        try:
            store.merge(result)
        except StaleResultError:
            pytest.skip("corpus holds one evidence_id under two analyzer versions")
    return load_profile_payload(path)


def _assert_same(candidate: dict, reference: dict, *, label: str) -> None:
    differences = explain_difference(reference, candidate)
    assert not differences, (
        f"{label} differs from the full build "
        f"({len(differences)} field difference(s)):\n  " + "\n  ".join(differences[:20])
    )


def test_full_build_is_idempotent(
    tmp_path: Path, results: list[AnalysisResult]
) -> None:
    reference = _full(results, tmp_path / "full.json")

    _assert_same(_full(results, tmp_path / "again.json"), reference, label="a rebuild")


def test_incremental_equals_full(tmp_path: Path, results: list[AnalysisResult]) -> None:
    reference = _full(results, tmp_path / "full.json")

    _assert_same(
        _incremental(results, tmp_path / "incremental.json"),
        reference,
        label="the incremental build",
    )


def test_reversed_order_equals_full(
    tmp_path: Path, results: list[AnalysisResult]
) -> None:
    reference = _full(results, tmp_path / "full.json")

    _assert_same(
        _full(list(reversed(results)), tmp_path / "reversed.json"),
        reference,
        label="the reverse-order build",
    )


def test_shuffled_order_equals_full(
    tmp_path: Path, results: list[AnalysisResult]
) -> None:
    """Seeded, so a failure is reproducible rather than a rumour."""
    reference = _full(results, tmp_path / "full.json")
    shuffled = list(results)
    random.Random(20260729).shuffle(shuffled)

    _assert_same(
        _full(shuffled, tmp_path / "shuffled.json"),
        reference,
        label="the shuffled-order build",
    )
