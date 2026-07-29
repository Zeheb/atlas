"""Comparing two profiles that must be identical.

Byte-identity is the standard for fresh-vs-fresh: two profiles built by the
same builder from the same facts, one via the analyzers and one via the
assertion store. Anything weaker -- comparing a few fields, or comparing
lengths -- passes on the failure that matters, which is a section that comes
out subtly reordered or one entry short.

Wall-clock fields are dropped first, through the same ``canonical_for_hash``
the assertion ids use, because ``built_at`` differs between two builds by
construction and would make every comparison fail for the one reason nobody
cares about.

A failing comparison reports *where*, not just that. A red boolean on a
document this size sends someone reading two thousand lines of JSON by hand.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from atlas.assertions.hashing import canonical_for_hash
from atlas.company.builder import build_profile
from atlas.company.store import CompanyStore, diff_profiles, load_profile_payload
from atlas.company.store import load_results as load_profile_results


def build_and_serialize(
    root: Path, company_id: str, *, source: str, out: Path
) -> dict[str, Any]:
    """Build a profile from *source* and return its serialised payload.

    Goes through ``CompanyStore.save`` rather than serialising in the test, so
    what is compared is what would actually be written to disk.
    """
    report = load_profile_results(root, source=source)  # type: ignore[arg-type]
    profile = build_profile(company_id, report.results)
    CompanyStore(out, company_id).save(profile, report.results)
    return load_profile_payload(out)


def assert_profiles_identical(
    left: dict[str, Any], right: dict[str, Any], *, left_label: str, right_label: str
) -> None:
    """Assert two serialised profiles are byte-identical once canonicalised."""
    if canonical_for_hash(left) == canonical_for_hash(right):
        return

    differences = diff_profiles(left, right)
    detail = "\n  ".join(differences[:20]) or "(canonical forms differ, no field diff)"
    raise AssertionError(
        f"{left_label} and {right_label} profiles differ "
        f"({len(differences)} field difference(s)):\n  {detail}"
    )
