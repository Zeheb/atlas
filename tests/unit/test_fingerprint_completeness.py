"""Every analysis module that can shape an extracted fact is fingerprinted.

The build fingerprint is only trustworthy if it is complete. A module that
influences extraction but contributes no component lets its behaviour change
while the digest stays put -- callers then trust a fingerprint that no longer
describes the code that produced their data. Silent staleness, and the digest
is what made it silent.

This is not hypothetical: atlas.analysis.patterns held the parsing helpers
seven analyzers share for the whole of the project before it carried a
version at all.

So the rule enforced here: every atlas.analysis.* module imported by a
registered analyzer must contribute a fingerprint component. Adding a new
shared helper module fails this test until it is versioned and wired in.

Deliberately NOT a component: atlas.analysis.shareholding_trend. Its entry
point is analyze_trend(Sequence[AnalysisResult]) -> TrendResult -- it
consumes analyzer output and emits no AnalysisFact, and it is absent from
_REGISTRY. It is a Tier 2 consumer, structurally a sibling of
atlas.query.engine rather than of the analyzers. Versioning it would pin a
view, not an extraction. It is excluded by not being imported by any
analyzer, so this test never sees it; the exclusion is recorded here so the
reasoning survives.

Uses ast.walk rather than tree.body, so a deferred import inside a function
trips this exactly like a module-level one.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

from atlas.analysis.registry import _REGISTRY, analyzer_versions
from atlas.provenance import current_fingerprint

_ANALYSIS_PREFIX = "atlas.analysis."

# Shared analysis modules that are not themselves analyzers, mapped to the
# constant each contributes to the fingerprint.
_VERSIONED_SHARED_MODULES = {
    "atlas.analysis.base": "ONTOLOGY_VERSION",
    "atlas.analysis.patterns": "SHARED_PARSER_VERSION",
}


def _analyzer_module_names() -> list[str]:
    """Module names of every registered analyzer, from the registry itself."""
    return sorted({fn.__module__ for fn in _REGISTRY.values()})


def _module_path(module_name: str) -> Path:
    module = importlib.import_module(module_name)
    assert module.__file__ is not None, module_name
    return Path(module.__file__)


def _imported_analysis_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(
                alias.name
                for alias in node.names
                if alias.name.startswith(_ANALYSIS_PREFIX)
            )
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module.startswith(_ANALYSIS_PREFIX):
                names.add(node.module)
    return names


@pytest.mark.parametrize("module_name", _analyzer_module_names())
def test_analyzer_imports_only_fingerprinted_analysis_modules(
    module_name: str,
) -> None:
    """Every atlas.analysis.* module an analyzer imports is versioned."""
    analyzer_modules = set(_analyzer_module_names())
    allowed = analyzer_modules | set(_VERSIONED_SHARED_MODULES)

    imported = _imported_analysis_modules(_module_path(module_name))
    unversioned = sorted(imported - allowed)

    assert not unversioned, (
        f"{module_name} imports {unversioned}, which contribute no build "
        "fingerprint component. A change there could alter extracted facts "
        "while the digest stays identical. Give each module a version "
        "constant, add it to BuildFingerprint, and register it in "
        "_VERSIONED_SHARED_MODULES here."
    )


@pytest.mark.parametrize(
    ("module_name", "constant"), sorted(_VERSIONED_SHARED_MODULES.items())
)
def test_shared_module_declares_its_version_constant(
    module_name: str, constant: str
) -> None:
    module = importlib.import_module(module_name)
    value = getattr(module, constant, None)
    assert isinstance(value, str) and value, (
        f"{module_name} must declare {constant} as a non-empty string; "
        "the fingerprint reads it."
    )


def test_shared_module_versions_reach_the_fingerprint() -> None:
    """Declaring a constant is not enough -- it must be wired in.

    A module could carry a version that nothing reads, which looks correct
    in review and fingerprints nothing.
    """
    fingerprint = current_fingerprint()
    base = importlib.import_module("atlas.analysis.base")
    patterns = importlib.import_module("atlas.analysis.patterns")

    assert fingerprint.ontology_version == base.ONTOLOGY_VERSION
    assert fingerprint.shared_parser_version == patterns.SHARED_PARSER_VERSION


def test_analyzer_versions_reach_the_fingerprint() -> None:
    assert current_fingerprint().analyzer_versions == analyzer_versions()


def test_at_least_one_analyzer_was_actually_checked() -> None:
    """A parametrization collecting zero cases would make every assertion
    above vacuously true. Guard against this test going dark if the
    registry is ever restructured."""
    assert len(_analyzer_module_names()) >= 11
