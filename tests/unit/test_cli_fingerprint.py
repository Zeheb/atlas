"""`atlas fingerprint show`.

A digest is opaque by design -- it says two builds differ, never which
component differs. This command is how that question gets answered, so the
central claim is that it prints every component, not just the digest.
"""

from __future__ import annotations

from click.testing import CliRunner

from atlas.analysis.registry import analyzer_versions
from atlas.cli import cli
from atlas.provenance import current_fingerprint


def test_show_prints_the_digest() -> None:
    result = CliRunner().invoke(cli, ["fingerprint", "show"])
    assert result.exit_code == 0
    assert current_fingerprint().digest() in result.output


def test_show_prints_every_hashed_component() -> None:
    """The reason the command exists: locate which component moved."""
    result = CliRunner().invoke(cli, ["fingerprint", "show"])
    assert result.exit_code == 0
    for name in (
        "ontology_version",
        "parser_version",
        "shared_parser_version",
        "builder_version",
    ):
        assert name in result.output


def test_show_lists_every_registered_analyzer() -> None:
    result = CliRunner().invoke(cli, ["fingerprint", "show"])
    assert result.exit_code == 0
    versions = analyzer_versions()
    assert f"analyzer_versions ({len(versions)})" in result.output
    for kind in versions:
        assert kind in result.output


def test_explain_names_the_source_module_of_each_component() -> None:
    result = CliRunner().invoke(cli, ["fingerprint", "show", "--explain"])
    assert result.exit_code == 0
    assert "atlas.analysis.base.ONTOLOGY_VERSION" in result.output
    assert "atlas.analysis.patterns.SHARED_PARSER_VERSION" in result.output
    assert "atlas.knowledge.base.PARSER_VERSION" in result.output
    assert "atlas.company.builder.BUILDER_VERSION" in result.output


def test_explain_states_that_code_rev_is_not_hashed() -> None:
    """Someone reading a moved digest needs to know code_rev is excluded,
    or they will chase the wrong difference."""
    result = CliRunner().invoke(cli, ["fingerprint", "show", "--explain"])
    assert result.exit_code == 0
    assert "NOT hashed" in result.output
