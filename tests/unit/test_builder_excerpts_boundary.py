"""The builder must never read ``AnalysisResult.excerpts``.

This is a tripwire, not a feature test. The assertion store does not hold
section bodies -- they are hundreds to thousands of characters each and
nothing consumes them -- so a result reconstructed from the store arrives with
``excerpts={}``. That is safe exactly as long as the builder ignores the field.

The day someone adds a section that reads it, profiles built from Tier 1 would
quietly differ from profiles built from analyzers: no exception, no missing
key, just a section that comes out empty. Nothing downstream could attribute
that to the store. This test fails loudly on the commit that introduces the
dependency, which is the only cheap moment to catch it.

It passes today. It is written before anything depends on the assumption, so
the assumption is checked rather than remembered.
"""

from __future__ import annotations

import ast
from pathlib import Path

_BUILDER = Path(__file__).parents[2] / "src" / "atlas" / "company" / "builder.py"


def _excerpt_references(source: str) -> list[tuple[int, str]]:
    """Return (line, description) for every way *source* reaches excerpts.

    Parsed rather than grepped: a match on the bare word would fire on a
    docstring that merely explains why the field is unused, and a test that
    cries wolf gets deleted.
    """
    tree = ast.parse(source)
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "excerpts":
            found.append((node.lineno, "attribute access .excerpts"))
        elif isinstance(node, ast.Subscript):
            index = node.slice
            if isinstance(index, ast.Constant) and index.value == "excerpts":
                found.append((node.lineno, 'subscript ["excerpts"]'))
        elif isinstance(node, ast.Name) and node.id == "excerpts":
            found.append((node.lineno, "name excerpts"))
    return found


def test_builder_never_reads_excerpts() -> None:
    references = _excerpt_references(_BUILDER.read_text(encoding="utf-8"))

    assert not references, (
        "builder.py now reads excerpts at "
        + ", ".join(f"line {line} ({how})" for line, how in references)
        + ". Results reconstructed from the assertion store carry excerpts={}, "
        "so this makes Tier 1 profiles differ from analyzer profiles with no "
        "error anywhere. Either store the section bodies or drop the "
        "dependency."
    )


def test_the_detector_finds_a_reference_when_there_is_one() -> None:
    """A detector that cannot fail is not protecting anything."""
    references = _excerpt_references(
        "def f(result):\n"
        "    a = result.excerpts\n"
        "    b = payload['excerpts']\n"
        "    return a, b\n"
    )

    assert len(references) == 2
