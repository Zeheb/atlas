"""BuildFingerprint digest behaviour.

Three properties matter, and each has a distinct failure mode:

Stability      -- an unstable digest invalidates every cache on every run,
                  which is the same as having no cache.
Sensitivity    -- a digest blind to a component lets that component change
                  while callers believe nothing did. Silent staleness.
code_rev free  -- a digest that moved with every commit would invalidate
                  everything on every commit, for no correctness gain.
"""

from __future__ import annotations

import dataclasses
import os
import subprocess
import sys
from pathlib import Path

import pytest

from atlas.provenance import (
    BuildFingerprint,
    current_fingerprint,
    detect_code_rev,
)

_SRC = Path(__file__).resolve().parents[2] / "src"

_HASHED_STRING_FIELDS = (
    "ontology_version",
    "parser_version",
    "shared_parser_version",
    "builder_version",
)


def _fingerprint(**overrides: object) -> BuildFingerprint:
    """A fingerprint with fixed values, so tests never depend on real ones."""
    base: dict[str, object] = {
        "ontology_version": "1.0",
        "parser_version": "2.0",
        "shared_parser_version": "1.0",
        "analyzer_versions": {"financial_results": "1.1", "buyback": "1.0"},
        "builder_version": "1.0",
        "code_rev": "abc1234",
    }
    base.update(overrides)
    return BuildFingerprint(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Stability
# ---------------------------------------------------------------------------


def test_digest_is_stable_across_constructions() -> None:
    assert _fingerprint().digest() == _fingerprint().digest()


def test_digest_ignores_analyzer_versions_insertion_order() -> None:
    """Mapping order must not reach the digest, or two equivalent
    fingerprints built in different orders would disagree."""
    forward = _fingerprint(analyzer_versions={"buyback": "1.0", "brsr": "2.0"})
    reverse = _fingerprint(analyzer_versions={"brsr": "2.0", "buyback": "1.0"})
    assert forward.digest() == reverse.digest()


@pytest.mark.parametrize("hashseed", ["0", "1", "12345"])
def test_digest_is_stable_across_processes(hashseed: str) -> None:
    """Run the digest in a fresh interpreter under a different
    PYTHONHASHSEED. Catches any dependence on str hash randomisation, which
    would make the digest differ between machines while looking fine here.
    """
    script = (
        "from atlas.provenance import BuildFingerprint\n"
        "print(BuildFingerprint(\n"
        "    ontology_version='1.0',\n"
        "    parser_version='2.0',\n"
        "    shared_parser_version='1.0',\n"
        "    analyzer_versions={'financial_results': '1.1', 'buyback': '1.0'},\n"
        "    builder_version='1.0',\n"
        "    code_rev='abc1234',\n"
        ").digest())\n"
    )
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = hashseed
    env["PYTHONPATH"] = str(_SRC)
    completed = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        check=True,
    )
    assert completed.stdout.strip() == _fingerprint().digest()


# ---------------------------------------------------------------------------
# Sensitivity
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("field", _HASHED_STRING_FIELDS)
def test_changing_any_hashed_component_changes_the_digest(field: str) -> None:
    """Parametrized over the field list rather than written out, so a
    component added later cannot quietly escape this test."""
    changed = dataclasses.replace(_fingerprint(), **{field: "99.9"})
    assert changed.digest() != _fingerprint().digest()


def test_changing_an_analyzer_version_changes_the_digest() -> None:
    changed = _fingerprint(
        analyzer_versions={"financial_results": "9.9", "buyback": "1.0"}
    )
    assert changed.digest() != _fingerprint().digest()


def test_adding_an_analyzer_changes_the_digest() -> None:
    changed = _fingerprint(
        analyzer_versions={
            "financial_results": "1.1",
            "buyback": "1.0",
            "brsr": "1.0",
        }
    )
    assert changed.digest() != _fingerprint().digest()


def test_every_hashed_field_is_covered_by_the_sensitivity_test() -> None:
    """Guard the guard: if a string component is added to BuildFingerprint
    without being added to _HASHED_STRING_FIELDS, the parametrized test
    above would silently stop covering it."""
    fields = {f.name for f in dataclasses.fields(BuildFingerprint)}
    unchecked = (
        fields
        - set(_HASHED_STRING_FIELDS)
        - {
            "analyzer_versions",
            "code_rev",
        }
    )
    assert unchecked == set(), (
        f"BuildFingerprint fields {sorted(unchecked)} are not covered by a "
        "digest-sensitivity test -- add them to _HASHED_STRING_FIELDS, or to "
        "the deliberate exclusion set if they must not be hashed."
    )


# ---------------------------------------------------------------------------
# code_rev is recorded but never hashed
# ---------------------------------------------------------------------------


def test_code_rev_does_not_affect_the_digest() -> None:
    """Otherwise every commit would invalidate every cached artifact."""
    assert _fingerprint(code_rev="deadbee").digest() == _fingerprint().digest()
    assert _fingerprint(code_rev=None).digest() == _fingerprint().digest()


def test_detect_code_rev_returns_none_when_git_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(*args: object, **kwargs: object) -> object:
        raise FileNotFoundError("git")

    monkeypatch.setattr(subprocess, "run", _boom)
    assert detect_code_rev() is None


def test_detect_code_rev_returns_none_when_git_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(*args: object, **kwargs: object) -> object:
        raise subprocess.CalledProcessError(128, "git")

    monkeypatch.setattr(subprocess, "run", _boom)
    assert detect_code_rev() is None


# ---------------------------------------------------------------------------
# current_fingerprint
# ---------------------------------------------------------------------------


def test_current_fingerprint_populates_every_component() -> None:
    fingerprint = current_fingerprint()
    assert fingerprint.ontology_version
    assert fingerprint.parser_version
    assert fingerprint.shared_parser_version
    assert fingerprint.builder_version
    assert fingerprint.analyzer_versions
    assert len(fingerprint.digest()) == 64


def test_current_fingerprint_is_reproducible_within_a_process() -> None:
    assert current_fingerprint().digest() == current_fingerprint().digest()
