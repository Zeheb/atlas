"""Tier 0 survives a rebuild, and the rebuild path cannot reach it.

Two halves of one guarantee. The first is behavioural: rebuild a company
from evidence and from assertions, and the judgment file comes back byte
for byte. The second is structural: ``atlas.rebuild``'s transitive import
closure contains no ``atlas.judgment`` module, so no future edit can reach
the store to touch it in the first place.

The behavioural half alone would be satisfied by a rebuild that opens the
judgment store, reads it, and happens to write back what it read. That is
one refactor away from data loss and no test would notice. The structural
half is the one that keeps holding.
"""

from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path

import pytest

from atlas.analysis.base import AnalysisResult, FactKind, FactUnit
from atlas.company.store import LoadReport
from atlas.judgment.model import Judgment
from atlas.judgment.store import JudgmentStore
from atlas.reasoning.contracts import SubjectRef
from atlas.rebuild import rebuild
from tests.support.roundtrip import make_fact, make_result

_COMPANY = "TCS"
_SRC = Path(__file__).parents[2] / "src"


# ---------------------------------------------------------------------------
# #40 — a judgment survives a full rebuild
# ---------------------------------------------------------------------------


def _result(evidence_id: str = "ev-1", *, revenue: int = 64988) -> AnalysisResult:
    result = make_result(
        "financial_results",
        facts=[
            make_fact(
                FactKind.FINANCIAL_REVENUE,
                revenue,
                unit=FactUnit.CRORE_INR,
                period="2026-03-31",
                section="consolidated_p_and_l",
            )
        ],
    )
    result.evidence_id = evidence_id
    result.source_date = datetime(2026, 4, 9, tzinfo=timezone.utc)
    return result


@pytest.fixture
def analyzer_output(monkeypatch: pytest.MonkeyPatch) -> list[AnalysisResult]:
    """Stand in for parse+analyze, matching test_rebuild_orchestration."""
    results = [_result()]

    def _load(root: Path, *, source: object = None, on_error: object = None):
        if source == "assertions":
            from atlas.assertions.reader import results_for

            return LoadReport(results=results_for(root), source="assertions")
        return LoadReport(
            results=list(results), source="analyzers", parsed=len(results)
        )

    monkeypatch.setattr("atlas.rebuild.load_results", _load)
    return results


@pytest.fixture
def judged_repo(tmp_path: Path) -> Path:
    """A repository holding one recorded judgment."""
    store = JudgmentStore(tmp_path / "judgments.json", _COMPANY)
    store.append(
        Judgment.create(
            subject=SubjectRef(subject_id=_COMPANY, display=_COMPANY),
            statement="Margin compression is structural.",
            rationale="Four consecutive quarters of wage inflation.",
            evidence_ids=("ev-1",),
            asserted_at=datetime(2026, 3, 31, 12, 0, tzinfo=timezone.utc),
            fingerprint="fingerprint-at-the-time",
        )
    )
    return tmp_path


def test_judgment_bytes_survive_a_rebuild_from_evidence(
    judged_repo: Path, analyzer_output: list[AnalysisResult]
) -> None:
    path = judged_repo / "judgments.json"
    before = path.read_bytes()

    rebuild(judged_repo, _COMPANY, source="evidence")

    assert path.read_bytes() == before


def test_judgment_bytes_survive_a_rebuild_from_assertions(
    judged_repo: Path, analyzer_output: list[AnalysisResult]
) -> None:
    path = judged_repo / "judgments.json"
    rebuild(judged_repo, _COMPANY, source="evidence")
    before = path.read_bytes()

    rebuild(judged_repo, _COMPANY, source="assertions")

    assert path.read_bytes() == before


def test_judgment_bytes_survive_repeated_rebuilds(
    judged_repo: Path, analyzer_output: list[AnalysisResult]
) -> None:
    path = judged_repo / "judgments.json"
    before = path.read_bytes()

    for _ in range(3):
        rebuild(judged_repo, _COMPANY, source="evidence")

    assert path.read_bytes() == before


def test_the_judgment_still_reads_back_after_a_rebuild(
    judged_repo: Path, analyzer_output: list[AnalysisResult]
) -> None:
    """Byte-identity is the strong claim; this is the one anyone will notice."""
    store = JudgmentStore(judged_repo / "judgments.json", _COMPANY)
    before = store.list()

    rebuild(judged_repo, _COMPANY, source="evidence")

    assert store.list() == before


def test_the_rebuild_did_run(
    judged_repo: Path, analyzer_output: list[AnalysisResult]
) -> None:
    """A rebuild that silently did nothing would pass every test above."""
    outcome = rebuild(judged_repo, _COMPANY, source="evidence")

    assert outcome.written_to is not None
    assert outcome.written_to.exists()
    assert outcome.documents == 1


# ---------------------------------------------------------------------------
# #41 — the rebuild path never imports judgment/
# ---------------------------------------------------------------------------


def _module_file(module: str) -> Path | None:
    """Return the file backing *module*, or None if it is not ours."""
    relative = Path(*module.split("."))
    for candidate in (
        _SRC / relative.with_suffix(".py"),
        _SRC / relative / "__init__.py",
    ):
        if candidate.exists():
            return candidate
    return None


def _ancestors(module: str) -> set[str]:
    """Every package importing *module* also executes, e.g. atlas.judgment."""
    parts = module.split(".")
    return {".".join(parts[:i]) for i in range(1, len(parts) + 1)}


def _direct_imports(source: str) -> set[str]:
    """Every ``atlas.*`` module *source* imports, at any nesting depth.

    Walks the tree rather than the top level: half the rebuild path's
    imports are inside function bodies, and a top-level-only scan would
    declare the boundary clean while missing every one of them. Imports
    under ``if TYPE_CHECKING`` count too — a boundary that a type annotation
    may cross is a boundary someone will cross.
    """
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("atlas"):
                    found |= _ancestors(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level or not node.module or not node.module.startswith("atlas"):
                continue
            found |= _ancestors(node.module)
            # `from atlas.pkg import mod` imports a submodule, not a symbol,
            # whenever atlas/pkg/mod.py exists.
            for alias in node.names:
                submodule = f"{node.module}.{alias.name}"
                if _module_file(submodule) is not None:
                    found |= _ancestors(submodule)
    return found


def _import_closure(root: str) -> set[str]:
    """Every ``atlas`` module reachable from *root* by import."""
    seen: set[str] = set()
    pending = [root]
    while pending:
        module = pending.pop()
        if module in seen:
            continue
        seen.add(module)
        path = _module_file(module)
        if path is None:
            continue
        pending.extend(_direct_imports(path.read_text(encoding="utf-8")) - seen)
    return seen


def test_the_rebuild_path_never_imports_the_judgment_store() -> None:
    reachable = sorted(
        module
        for module in _import_closure("atlas.rebuild")
        if module.startswith("atlas.judgment")
    )

    assert not reachable, (
        "atlas.rebuild can now reach "
        + ", ".join(reachable)
        + ". Judgments are Tier 0: a rebuild regenerates Tier 1 and Tier 2 and "
        "must not be able to touch them at all. Drop the import; if the "
        "rebuild genuinely needs to read a judgment, that is an architecture "
        "decision, not a refactor."
    )


def test_the_closure_reaches_real_modules() -> None:
    """A closure that came back nearly empty would pass the test above."""
    closure = _import_closure("atlas.rebuild")

    assert "atlas.assertions.store" in closure
    assert "atlas.company.builder" in closure
    assert "atlas.analysis.registry" in closure


def test_the_detector_finds_judgment_imports_where_they_exist() -> None:
    """atlas.cli imports the store deliberately; the CLI is outside the boundary."""
    closure = _import_closure("atlas.cli")

    assert "atlas.judgment.store" in closure


def test_function_local_and_type_checking_imports_are_both_seen() -> None:
    """The two shapes a boundary violation would most plausibly take."""
    found = _direct_imports(
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    from atlas.judgment.store import JudgmentStore\n"
        "def f():\n"
        "    import atlas.judgment.model\n"
    )

    assert "atlas.judgment.store" in found
    assert "atlas.judgment.model" in found
