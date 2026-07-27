"""Golden corpus regression tests.

Parametrized over every JSON file in tests/corpus/expectations/.
Each JSON file defines:
  evidence_id      the document to analyze
  analyzer         documentation only — dispatch is by evidence kind via registry
  min_confidence   result-level confidence threshold
  max_warnings     maximum acceptable warnings
  expected_facts   list of ExpectedFact criterion dicts

Adding a new document to the regression suite:
  1. Put the raw document in the appropriate repositories/ directory.
  2. Add a catalog entry.
  3. Write an expectations JSON file.
  No code changes required.

Run with: pytest tests/corpus/ -m integration -v
"""

from __future__ import annotations

import json
from collections.abc import Generator
from pathlib import Path

import pytest

from .framework import EvalResult, evaluate, load_expected_facts

pytestmark = pytest.mark.integration

_PROJECT_ROOT = Path(__file__).parents[2]
_EXPECTATIONS_DIR = Path(__file__).parent / "expectations"
_TCS_REPO = _PROJECT_ROOT / "repositories" / "TCS"


# ---------------------------------------------------------------------------
# Parametrize — one test case per expectations file
# ---------------------------------------------------------------------------


def _load_cases() -> list[dict]:
    cases = []
    for path in sorted(_EXPECTATIONS_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        data["_path"] = str(path.name)
        cases.append(data)
    return cases


_CASES = _load_cases()
_CASE_IDS = [c["_path"].replace(".json", "") for c in _CASES]


@pytest.fixture(scope="module")
def tcs_repo(isolated_repo_factory) -> Path:
    if not _TCS_REPO.exists():
        pytest.skip("TCS repository not found")
    return isolated_repo_factory(
        _TCS_REPO, evidence_ids=[case["evidence_id"] for case in _CASES]
    )


@pytest.fixture(scope="module")
def kb(tcs_repo: Path) -> Generator:
    from atlas.acquisition.repository import Repository
    from atlas.knowledge.base import KnowledgeBase

    instance = KnowledgeBase(tcs_repo)
    repo = Repository(tcs_repo)

    # Pre-parse all documents referenced by corpus expectations
    for case in _CASES:
        eid = case["evidence_id"]
        entry = repo.get(eid)
        if entry is not None:
            instance.parse(entry)

    yield instance


@pytest.mark.parametrize("case", _CASES, ids=_CASE_IDS)
class TestCorpus:
    @pytest.fixture
    def result(self, case: dict, kb):
        from atlas.analysis.registry import analyze as registry_analyze

        eid = case["evidence_id"]
        entry = kb.get(eid)
        if entry is None or entry.status != "ok":
            pytest.skip(f"{eid[:16]}... not parsed — add to repository first")
        return registry_analyze(eid, kb)

    @pytest.fixture
    def eval_result(self, case: dict, result) -> EvalResult:
        expected = load_expected_facts(case["expected_facts"])
        return evaluate(expected, result, max_warnings=case.get("max_warnings", 0))

    def test_confidence(self, case: dict, result):
        min_conf = case.get("min_confidence", "medium")
        order = {"high": 2, "medium": 1, "low": 0}
        assert (
            order[result.confidence] >= order[min_conf]
        ), f"confidence={result.confidence!r} below minimum {min_conf!r}"

    def test_no_missing_facts(self, eval_result: EvalResult, case: dict):
        assert eval_result.missing == 0, (
            f"{case['_path']}: {eval_result.missing} expected fact(s) not found\n"
            f"  recall={eval_result.recall:.2f}"
        )

    def test_no_warning_issues(self, eval_result: EvalResult, case: dict):
        assert not eval_result.warning_issues, f"{case['_path']}: " + "; ".join(
            eval_result.warning_issues
        )
