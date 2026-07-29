"""Round trip over the golden corpus — the confidence variant.

Same invariant as ``tests/unit/test_assertion_roundtrip.py``, same assertion
helper, different input: real analyzer output over real acquired documents.
Marked ``integration``, so it runs locally and pre-merge rather than in CI
(per D1 -- CI has no acquired PDFs, which is why the marker is deselected
there in the first place).

What this adds over the synthetic variant is not a stronger check of the
store. It is evidence that the shapes the store is built to survive --
duplicate facts, absent char offsets, mixed value types -- are shapes the
real analyzers actually emit.
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
from atlas.knowledge.base import KnowledgeBase
from tests.support.roundtrip import FINGERPRINT, assert_round_trip, fact_key

pytestmark = pytest.mark.integration

_PROJECT_ROOT = Path(__file__).parents[2]
_EXPECTATIONS_DIR = _PROJECT_ROOT / "tests" / "corpus" / "expectations"
_TCS_REPO = _PROJECT_ROOT / "repositories" / "TCS"


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
    """Whether this document can be analyzed in *this* checkout.

    Same guard the existing corpus suite uses (``test_corpus.py:88``), plus a
    content check: a document can parse to status "ok" and still yield no
    text, and the analyzers raise on that rather than returning an empty
    result. Neither case is a store defect, so neither should fail this test.
    """
    document = kb.get(evidence_id)
    if document is None or document.status != "ok":
        return False
    return bool(kb.get_content(evidence_id))


@pytest.mark.parametrize("evidence_id", _EVIDENCE_IDS)
def test_corpus_document_round_trips(
    tmp_path: Path, kb: KnowledgeBase, evidence_id: str
) -> None:
    if not _analyzable(kb, evidence_id):
        pytest.skip(f"{evidence_id[:16]}... not parsed — add to repository first")

    assert_round_trip(tmp_path, analyze(evidence_id, kb))


def test_corpus_exercises_the_shapes_the_store_is_built_for(
    kb: KnowledgeBase,
) -> None:
    """The claim the synthetic variant cannot make on its own.

    If no real document ever produced a duplicate fact key or an absent char
    offset, ``ordinal`` and the nullable columns would be insurance against
    nothing, and this would be the place to find that out.
    """
    seen_keys: list[tuple[str, ...]] = []
    offsetless = 0
    for evidence_id in _EVIDENCE_IDS:
        if not _analyzable(kb, evidence_id):
            continue
        for fact in analyze(evidence_id, kb).facts:
            seen_keys.append(fact_key(fact))
            if fact.provenance.char_offset is None:
                offsetless += 1

    if not seen_keys:
        pytest.skip("no corpus document is parsed in this checkout")
    duplicates = len(seen_keys) - len(set(seen_keys))
    # Reported, not required: a corpus that happens to contain no duplicate
    # today must not fail the suite, but the number belongs in the record.
    print(
        f"corpus facts={len(seen_keys)} duplicate-keys={duplicates} "
        f"offsetless={offsetless}"
    )


def test_full_corpus_store_size_and_row_count(
    tmp_path: Path, kb: KnowledgeBase
) -> None:
    """#17: the number goes in the PR body, and the bound goes here.

    A store whose size nobody tracked is how "rebuildable cache" turns into
    "the thing that filled the disk".
    """
    import sqlite3

    store = AssertionStore(tmp_path)
    documents = 0
    for evidence_id in _EVIDENCE_IDS:
        if not _analyzable(kb, evidence_id):
            continue
        write_result(store, analyze(evidence_id, kb), fingerprint=FINGERPRINT)
        documents += 1
    if documents == 0:
        pytest.skip("no corpus document is parsed in this checkout")

    connection = sqlite3.connect(str(store.path))
    try:
        runs = connection.execute("SELECT COUNT(*) FROM assertion_runs").fetchone()[0]
        facts = connection.execute("SELECT COUNT(*) FROM assertions").fetchone()[0]
    finally:
        connection.close()
    size_bytes = store.path.stat().st_size

    print(
        f"assertion store: documents={documents} runs={runs} assertions={facts} "
        f"size={size_bytes} bytes"
    )
    assert runs == documents
    assert facts > 0
    # Generous: one corpus document's facts are kilobytes, not megabytes. The
    # bound catches an order-of-magnitude regression, not normal growth.
    assert size_bytes < 20_000_000
