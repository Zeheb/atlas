"""The query renderer prints the build that answered — #52.

A pinned ``QueryResult`` whose pin never reaches the screen is pinned only in
principle: the person comparing two revenue figures across a week is reading
rendered text, not a dataclass.

The prefix comes from ``citation.build_pin``, shared with the answer footer,
so the two surfaces cannot drift into naming the same build differently.
"""

from __future__ import annotations

from atlas.citation import build_pin
from atlas.provenance import current_fingerprint
from atlas.query.engine import QueryResult, TableSection
from atlas.query.render import render_result

_COMPANY = "TCS"


def _result(*, rows: list[list[str]] | None = None, **kwargs: object) -> QueryResult:
    return QueryResult(
        query="revenue",
        company_id=_COMPANY,
        title="Revenue Evolution",
        sections=[
            TableSection(
                heading="Consolidated",
                columns=["Period", "Revenue"],
                rows=rows if rows is not None else [["Mar 2026", "64,988 cr"]],
            )
        ],
        **kwargs,  # type: ignore[arg-type]
    )


def test_the_footer_names_the_running_build() -> None:
    rendered = render_result(_result())

    assert rendered.endswith(f"Atlas {current_fingerprint().digest()}")


def test_the_footer_is_last() -> None:
    """After the notes: the number is what someone came for."""
    result = _result()
    result.notes = ["one qualifying note"]

    lines = [line for line in render_result(result).splitlines() if line.strip()]

    assert lines[-1] == build_pin(result.fingerprint)
    assert "one qualifying note" in lines[-2]


def test_an_empty_result_is_pinned_too() -> None:
    """ "This build found nothing" is a different claim from "nothing ran"."""
    rendered = render_result(_result(rows=[]))

    assert "(no data)" in rendered
    assert rendered.endswith(f"Atlas {current_fingerprint().digest()}")


def test_a_blank_fingerprint_renders_no_footer() -> None:
    """Rather than a footer naming nothing."""
    rendered = render_result(_result(fingerprint=""))

    assert "Atlas" not in rendered


def test_the_digest_is_printed_whole() -> None:
    """Not abbreviated. A prefix collision is unlikely; a wrong match is silent.

    The other half of this invariant -- that the answer footer spells the
    prefix the same way -- lives beside the footer's own tests, where the
    ``ReasoningResult`` factory already is.
    """
    digest = current_fingerprint().digest()

    assert digest in render_result(_result())
    assert len(digest) == 64
