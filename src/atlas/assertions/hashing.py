"""Canonical form for hashing and comparison.

Every content address and every equivalence check in this project has the
same problem: some fields record when something happened, and those fields
differ between two runs that are otherwise identical. ``analyzed_at``
defaults to ``datetime.now`` (``analysis/base.py``), ``built_at`` is stamped
at each store write, ``created_at`` at each row insert. Hash them and no
assertion id is ever stable; compare them and no two builds ever match.

The exclusion list therefore has to exist. What matters is that it exists
*once*. Three separate callers need it -- the assertion id function, the
build fingerprint, and the rebuild comparison helper -- and three copies
would drift, with the symptom being an id that changes for no reason or a
comparison that quietly ignores a field it should have caught.

Excluded fields are dropped, not blanked. A blanked field still occupies a
key, which invites the mistake of treating "recorded but ignored" and
"absent" as different when they are not.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

#: Wall-clock fields: recorded on the artifact, never hashed, never compared.
EXCLUDED_FROM_HASH = frozenset(
    {
        "analyzed_at",
        "built_at",
        "created_at",
    }
)


def strip_volatile(payload: Any) -> Any:
    """Return *payload* with every excluded key removed, at any depth.

    Recursive because the fields appear at several levels: ``built_at`` sits
    on a store envelope, ``analyzed_at`` inside each ingested-result record.
    A top-level-only strip would miss the nested ones and reintroduce exactly
    the instability this module exists to remove.
    """
    if isinstance(payload, Mapping):
        return {
            key: strip_volatile(value)
            for key, value in payload.items()
            if key not in EXCLUDED_FROM_HASH
        }
    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes)):
        return [strip_volatile(item) for item in payload]
    return payload


def canonical_for_hash(payload: Any) -> str:
    """Return canonical JSON for *payload*, wall-clock fields removed.

    Canonical means: excluded keys dropped, remaining keys sorted, no
    incidental whitespace. Two structures that differ only in key insertion
    order or in a timestamp produce the same string, so hashing it or
    comparing it gives a stable answer across processes and machines.
    """
    return json.dumps(
        strip_volatile(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    )
