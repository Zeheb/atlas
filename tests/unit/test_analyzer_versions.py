"""analyzer_versions() pins every registered analyzer, and cannot drift.

The build fingerprint records which code produced a set of extracted facts.
If a registered analyzer were missing from that record, a version bump there
would leave the fingerprint unchanged and anything keyed by it stale with no
signal -- so the mapping is derived from _REGISTRY itself rather than from a
parallel table that could fall behind.
"""

from collections.abc import Callable

import pytest

from atlas.analysis import registry
from atlas.analysis.base import AnalysisResult
from atlas.analysis.registry import analyzer_versions, supported_kinds
from atlas.knowledge.base import KnowledgeBase


def test_covers_exactly_the_registered_kinds() -> None:
    assert sorted(analyzer_versions()) == supported_kinds()


def test_every_version_is_a_nonempty_string() -> None:
    for kind, version in analyzer_versions().items():
        assert isinstance(version, str), kind
        assert version.strip() == version, kind
        assert version != "", kind


def test_keys_are_sorted_so_the_mapping_is_canonical() -> None:
    """Canonical ordering keeps the fingerprint digest stable across runs."""
    keys = list(analyzer_versions())
    assert keys == sorted(keys)


def test_raises_when_a_registered_analyzer_declares_no_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An analyzer registered without ANALYZER_VERSION must fail loudly.

    Silently skipping it would let the fingerprint claim coverage it does
    not have -- the exact failure this function exists to prevent.
    """

    def _unversioned(evidence_id: str, kb: KnowledgeBase) -> AnalysisResult:
        raise AssertionError("never called")

    # This test module declares no ANALYZER_VERSION, so a function defined
    # here stands in for an analyzer whose module forgot the constant.
    fn: Callable[[str, KnowledgeBase], AnalysisResult] = _unversioned
    monkeypatch.setitem(registry._REGISTRY, "unversioned_kind", fn)

    with pytest.raises(RuntimeError, match="declares no ANALYZER_VERSION"):
        analyzer_versions()
