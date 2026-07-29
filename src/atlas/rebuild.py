"""Comparing two builds of the same thing.

Everything downstream of this project asks one question in different words:
did rebuilding change anything? A full rebuild against an incremental one, a
shuffled corpus against a sorted one, today's build against yesterday's. The
answer has to be a single unambiguous bit, and when the bit is "yes" it has to
be followed by *where*.

The comparison is byte-identity of a canonical form, not field sampling. A
section that comes back one entry short, or in a different order, is exactly
what a partial comparison waves through -- and it is the failure mode this
project exists to eliminate, so the check cannot be the weaker one.

One exclusion list
------------------
Wall-clock fields have to be dropped before comparing: ``built_at`` differs
between two builds by construction, so a raw comparison fails for the one
reason nobody cares about. That list already exists -- ``canonical_for_hash``
owns it, and the assertion ids and the fingerprint already use it. This module
calls it rather than restating it. Two lists would drift, and the symptom
would be a rebuild that reports a difference in a field that was never meant
to be compared, which teaches everyone to ignore the check.
"""

from __future__ import annotations

import hashlib
from typing import Any

from atlas.assertions.hashing import canonical_for_hash
from atlas.company.store import diff_profiles


def canonical_profile(payload: Any) -> str:
    """Return the canonical string form of a serialised profile."""
    return canonical_for_hash(payload)


def profile_digest(payload: Any) -> str:
    """Return a stable digest of *payload*'s canonical form.

    For recording in a log or a store-status line, where carrying the whole
    canonical document would be absurd but "did this move" still needs an
    answer that survives a process boundary.
    """
    return hashlib.sha256(canonical_profile(payload).encode("utf-8")).hexdigest()


def profiles_match(left: Any, right: Any) -> bool:
    """Whether two serialised profiles are identical once canonicalised."""
    return canonical_profile(left) == canonical_profile(right)


def explain_difference(left: Any, right: Any) -> list[str]:
    """Return human-readable differences between two serialised profiles.

    Empty when they match. Delegates to ``diff_profiles`` so the rebuild
    check and ``atlas profile diff`` describe a difference the same way --
    someone debugging a red gate should not have to learn a second format.
    """
    if profiles_match(left, right):
        return []
    return diff_profiles(left, right)
