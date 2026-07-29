"""Build fingerprint — which code produced a given artifact.

Atlas keeps every layer above evidence rebuildable, which is only a useful
guarantee if a stored artifact can say what produced it. Five version
constants live in five different modules; on their own they answer nothing,
because no consumer can compare "the versions I was built with" against "the
versions in the tree right now" without first collecting them into one value.

BuildFingerprint is that value.

What is hashed, and what is not
-------------------------------
``digest()`` covers the five declared version components. It deliberately
excludes ``code_rev``: a fingerprint that changed on every commit would
invalidate every cached artifact on every commit, which is indistinguishable
from having no cache at all. Only a declared version bump means "the output
may differ" -- that is what declaring a version is for.

``code_rev`` is still recorded, because when a digest does move the first
question is always which commits are involved, and answering it from the
artifact beats reconstructing it from timestamps.

Completeness
------------
A component missing here is worse than no fingerprint, because the digest
would assert coverage it does not have and callers would trust it. That is
why ``analyzer_versions()`` derives from the registry rather than a parallel
table, and why ``shared_parser_version`` exists at all -- the parsing helpers
seven analyzers share can change extracted values without moving any
ANALYZER_VERSION.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from atlas.analysis.base import ONTOLOGY_VERSION
from atlas.analysis.patterns import SHARED_PARSER_VERSION
from atlas.analysis.registry import analyzer_versions
from atlas.company.builder import BUILDER_VERSION
from atlas.knowledge.base import PARSER_VERSION

_CODE_REV_COMMAND = ("git", "describe", "--always", "--dirty")
_CODE_REV_TIMEOUT_SECONDS = 5


@dataclass(frozen=True)
class BuildFingerprint:
    """The declared versions of every stage that can shape an artifact.

    ontology_version:      FactKind vocabulary (atlas.analysis.base).
    parser_version:        Document text extraction (atlas.knowledge.base).
    shared_parser_version: Shared analyzer helpers (atlas.analysis.patterns).
    analyzer_versions:     Evidence kind -> ANALYZER_VERSION, all registered
                           analyzers. Sorted by key, so already canonical.
    builder_version:       Profile assembly (atlas.company.builder).
    code_rev:              ``git describe`` output, or None outside a
                           checkout. Recorded for forensics; NOT hashed.
    """

    ontology_version: str
    parser_version: str
    shared_parser_version: str
    analyzer_versions: Mapping[str, str]
    builder_version: str
    code_rev: str | None

    def digest(self) -> str:
        """Return a stable sha256 over the declared version components.

        Stable across processes and machines: canonical JSON with sorted
        keys, no timestamps, no absolute paths, no iteration-order
        dependence. Two runs of the same code always agree.
        """
        payload = {
            "ontology_version": self.ontology_version,
            "parser_version": self.parser_version,
            "shared_parser_version": self.shared_parser_version,
            "builder_version": self.builder_version,
            "analyzer_versions": dict(sorted(self.analyzer_versions.items())),
        }
        canonical = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _repo_root() -> Path:
    """Return the repository root: src/atlas/provenance.py -> two levels up."""
    return Path(__file__).resolve().parents[2]


def detect_code_rev() -> str | None:
    """Return ``git describe --always --dirty``, or None if unavailable.

    None is a normal answer, not an error: Atlas may run from an installed
    wheel, a container without git, or an exported tree. Since code_rev is
    excluded from the digest, its absence weakens forensics but never
    changes cache behaviour.
    """
    try:
        completed = subprocess.run(
            _CODE_REV_COMMAND,
            cwd=_repo_root(),
            capture_output=True,
            text=True,
            timeout=_CODE_REV_TIMEOUT_SECONDS,
            check=True,
        )
    except OSError, subprocess.SubprocessError:
        return None
    rev = completed.stdout.strip()
    return rev or None


def current_fingerprint() -> BuildFingerprint:
    """Return the fingerprint of the code in this process."""
    return BuildFingerprint(
        ontology_version=ONTOLOGY_VERSION,
        parser_version=PARSER_VERSION,
        shared_parser_version=SHARED_PARSER_VERSION,
        analyzer_versions=analyzer_versions(),
        builder_version=BUILDER_VERSION,
        code_rev=detect_code_rev(),
    )
