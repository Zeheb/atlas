"""Package-level import boundary: reasoning never imports research (M2.4.1
item 7).

ADR-0010's falsification pass claimed this boundary is "enforced by the same
AST import-boundary mechanism ADR-0007 already uses for planners" -- but no
test actually checked it; the property held only by convention. This is the
enforcement the ADR already claimed to have.

Directional by design: research importing reasoning is correct and is how
the C6 projection flows (research.Thesis.to_view() -> RecalledView). The
violation this guards against is the other direction -- a reasoning module
reaching into research-layer vocabulary (dimensions, dispositions, run
fingerprints), which is exactly what ADR-0009's corollary forbids.

Scoped to a different concern than test_reasoning_planner.py's own
_FORBIDDEN_IMPORT_PREFIXES (no-KB/no-LLM/no-network, and only for
plan.py/planner.py) -- extending that list would conflate two unrelated
rules under one name.

Uses ast.walk (not tree.body-only): the boundary is meant to be absolute, so
a deferred import inside a function body should trip this test exactly like
a module-level one would. staleness.py's local `from atlas.research.memory
import ThesisStore` inside sweep_staleness is the one KNOWN, deliberate
exception to "no research import" in this codebase -- but staleness.py lives
in atlas.research, not atlas.reasoning, so it is out of this test's scope
entirely and untouched by it.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_REASONING_ROOT = Path(__file__).resolve().parents[2] / "src" / "atlas" / "reasoning"


def _reasoning_modules() -> list[Path]:
    return sorted(_REASONING_ROOT.rglob("*.py"))


def _imported_module_names(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


@pytest.mark.parametrize("path", _reasoning_modules(), ids=lambda p: p.name)
def test_reasoning_module_never_imports_research(path: Path) -> None:
    imports = _imported_module_names(path)
    for imported in imports:
        assert not imported.startswith("atlas.research"), (
            f"{path.relative_to(_REASONING_ROOT)} imports {imported!r} -- "
            "reasoning must never import research (ADR-0009's corollary: "
            "research-layer vocabulary must not reach a consumer-agnostic "
            "contract package). The projection flows the other way, via "
            "research.Thesis.to_view()."
        )


def test_at_least_one_reasoning_module_was_actually_checked() -> None:
    """A parametrization that silently collected zero cases would make every
    test above vacuously true -- guard against the boundary test itself
    going dark if the package is ever restructured."""
    assert len(_reasoning_modules()) >= 10
