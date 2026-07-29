"""SHARED_PARSER_VERSION is present and usable as a fingerprint component.

atlas.analysis.patterns holds the parsing helpers seven of the eleven
registered analyzers import. A change there can alter what all seven extract
without moving any ANALYZER_VERSION, so the shared module needs a version of
its own for the build fingerprint to be complete.

The stronger guarantee -- that every extraction-affecting module contributes
a fingerprint component -- is enforced separately by the M0 guard test.
"""

from atlas.analysis.patterns import SHARED_PARSER_VERSION


def test_shared_parser_version_is_a_nonempty_string() -> None:
    assert isinstance(SHARED_PARSER_VERSION, str)
    assert SHARED_PARSER_VERSION.strip() == SHARED_PARSER_VERSION
    assert SHARED_PARSER_VERSION != ""
