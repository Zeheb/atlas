"""JudgmentStore: append-only persistence for one subject's judgments.

One JSON file per subject, ``store_version = "1"``, path supplied by the
caller — the same file convention as ``research/memory.py``'s ``ThesisStore``
(``repo_root / "theses.json"`` becomes ``repo_root / "judgments.json"``).
The conventions are shared; the semantics are not, in three places:

Duplicates raise, they do not no-op
-----------------------------------
``ThesisStore.save`` is idempotent on ``view_id``: re-saving an unchanged
synthesis is a no-op, because a thesis is derived and re-deriving it is
routine. A judgment is not derived. Writing the same judgment twice means
the caller believes it is recording something new and is wrong, and
swallowing that hides the bug at the only layer that could still catch it.
So ``append`` raises ``DuplicateJudgmentError``.

Nothing is ever removed
-----------------------
There is no update and no overwrite. A revision is a new judgment carrying
``supersedes``, and the superseded judgment stays exactly where it was.
Deletion is a separate, explicitly forced operation and does not live here.

``supersedes`` must resolve
---------------------------
Appending a judgment that supersedes an id this store has never seen is
rejected. A dangling link would make ``chain`` return a truncated history
that looks complete, which is worse than a write that failed loudly. The
same walk rejects cycles: A superseding B while B supersedes A cannot be
built through ``Judgment.create`` — ``supersedes`` is inside the content
hash, so it would require knowing B's id before computing it — but it can
arrive from a hand-edited file, and a chain walk that trusted the file
would loop forever.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from atlas.judgment.model import Judgment
from atlas.reasoning.contracts import SubjectRef

STORE_VERSION = "1"


class JudgmentNotFoundError(KeyError):
    """No stored judgment matches the requested judgment_id."""


class DuplicateJudgmentError(ValueError):
    """A judgment with this id is already stored; the store is append-only."""


class SupersedeCycleError(ValueError):
    """A supersedes chain loops back on itself."""


class IncompatibleStoreVersionError(ValueError):
    """The store file was written by an incompatible JudgmentStore version."""


def _serialize_subject(subject: SubjectRef) -> dict[str, Any]:
    return {
        "subject_id": subject.subject_id,
        "display": subject.display,
        "subject_type": subject.subject_type,
        "aliases": list(subject.aliases),
    }


def _deserialize_subject(d: dict[str, Any]) -> SubjectRef:
    return SubjectRef(
        subject_id=d["subject_id"],
        display=d["display"],
        subject_type=d.get("subject_type", "company"),
        aliases=tuple(d.get("aliases", ())),
    )


def _serialize_judgment(judgment: Judgment) -> dict[str, Any]:
    return {
        "judgment_id": judgment.judgment_id,
        "subject": _serialize_subject(judgment.subject),
        "statement": judgment.statement,
        "rationale": judgment.rationale,
        "evidence_ids": list(judgment.evidence_ids),
        "asserted_at": judgment.asserted_at.isoformat(),
        "fingerprint": judgment.fingerprint,
        "supersedes": judgment.supersedes,
    }


def _deserialize_judgment(d: dict[str, Any]) -> Judgment:
    return Judgment(
        judgment_id=d["judgment_id"],
        subject=_deserialize_subject(d["subject"]),
        statement=d["statement"],
        rationale=d["rationale"],
        evidence_ids=tuple(d["evidence_ids"]),
        asserted_at=datetime.fromisoformat(d["asserted_at"]),
        fingerprint=d["fingerprint"],
        supersedes=d.get("supersedes"),
    )


class JudgmentStore:
    """Append-only store for one subject's judgments.

    Typical workflow::

        store = JudgmentStore(Path("repositories/TCS/judgments.json"), "TCS")
        store.append(judgment)
        revision = Judgment.create(..., supersedes=judgment.judgment_id)
        store.append(revision)
        history = store.chain(revision.judgment_id)   # revision, then judgment
    """

    def __init__(self, path: Path, subject: str) -> None:
        self._path = Path(path)
        self._subject = subject

    def exists(self) -> bool:
        return self._path.exists()

    def append(self, judgment: Judgment) -> None:
        """Store *judgment*, which must be new and must not dangle.

        Raises ``ValueError`` if the subject does not match this store,
        ``DuplicateJudgmentError`` if the id is already stored,
        ``JudgmentNotFoundError`` if ``supersedes`` names an unknown
        judgment, and ``SupersedeCycleError`` if the resulting chain loops.
        Nothing is written unless every check passes.
        """
        if judgment.subject.subject_id != self._subject:
            raise ValueError(
                f"Judgment subject {judgment.subject.subject_id!r} does not "
                f"match store subject {self._subject!r}"
            )
        envelope = self._load_raw() if self.exists() else self._empty_envelope()
        stored = {raw["judgment_id"]: raw for raw in envelope["judgments"]}
        if judgment.judgment_id in stored:
            raise DuplicateJudgmentError(
                f"Judgment {judgment.judgment_id!r} is already stored; the "
                f"judgment store is append-only. Record a revision with "
                f"supersedes={judgment.judgment_id!r} instead."
            )
        self._walk_supersedes(judgment.judgment_id, judgment.supersedes, stored)
        envelope["judgments"].append(_serialize_judgment(judgment))
        self._write(envelope)

    def get(self, judgment_id: str) -> Judgment:
        """Load one stored judgment by id.

        Raises ``JudgmentNotFoundError`` if no judgment with that id is
        stored.
        """
        for raw in self._raw_judgments():
            if raw["judgment_id"] == judgment_id:
                return _deserialize_judgment(raw)
        raise JudgmentNotFoundError(judgment_id)

    def list(self) -> tuple[Judgment, ...]:
        """Every stored judgment for this subject, oldest first.

        Empty if the store file does not exist, matching ``ThesisStore.list``
        and ``CompanyStore.get_ingested_ids``: a store that has never been
        written holds nothing, which is not an error.
        """
        return tuple(_deserialize_judgment(raw) for raw in self._raw_judgments())

    def chain(self, judgment_id: str) -> tuple[Judgment, ...]:
        """Return *judgment_id* and everything it supersedes, newest first.

        The full revision history of one conclusion. A judgment that
        supersedes nothing yields a one-element chain.
        """
        by_id = {raw["judgment_id"]: raw for raw in self._raw_judgments()}
        if judgment_id not in by_id:
            raise JudgmentNotFoundError(judgment_id)
        history: list[Judgment] = []
        seen: set[str] = set()
        current: str | None = judgment_id
        while current is not None:
            if current in seen:
                raise SupersedeCycleError(
                    f"supersedes chain from {judgment_id!r} revisits " f"{current!r}"
                )
            seen.add(current)
            raw = by_id.get(current)
            if raw is None:
                raise JudgmentNotFoundError(current)
            history.append(_deserialize_judgment(raw))
            current = raw.get("supersedes")
        return tuple(history)

    def _walk_supersedes(
        self,
        judgment_id: str,
        supersedes: str | None,
        stored: dict[str, dict[str, Any]],
    ) -> None:
        """Check that the chain below *supersedes* resolves and terminates."""
        seen = {judgment_id}
        current = supersedes
        while current is not None:
            if current in seen:
                raise SupersedeCycleError(
                    f"supersedes chain from {judgment_id!r} revisits " f"{current!r}"
                )
            seen.add(current)
            prior = stored.get(current)
            if prior is None:
                raise JudgmentNotFoundError(
                    f"supersedes {current!r}, which is not stored for subject "
                    f"{self._subject!r}"
                )
            current = prior.get("supersedes")

    def _raw_judgments(self) -> tuple[dict[str, Any], ...]:
        """The stored records, undecoded, in file order.

        Returns a tuple rather than a list because ``list`` is a method on
        this class, and inside the class body an annotation naming ``list``
        resolves to that method rather than to the builtin.
        """
        if not self.exists():
            return ()
        raw: Sequence[dict[str, Any]] = self._load_raw()["judgments"]
        return tuple(raw)

    def _empty_envelope(self) -> dict[str, Any]:
        return {
            "store_version": STORE_VERSION,
            "subject": self._subject,
            "judgments": [],
        }

    def _load_raw(self) -> dict[str, Any]:
        data: dict[str, Any] = json.loads(self._path.read_text(encoding="utf-8"))
        version = data.get("store_version")
        if version != STORE_VERSION:
            raise IncompatibleStoreVersionError(
                f"Unsupported store_version {version!r} in {self._path}. "
                f"Expected {STORE_VERSION!r}."
            )
        return data

    def _write(self, envelope: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(envelope, indent=2, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
