"""ThesisStore: persistence for synthesized views (M2.4 commit 3).

PERSISTENCE ONLY. Whether a stored view is still current is a different
question, asked by a different module (``staleness.py``) that never imports
this one -- the store does not know what "stale" means, and the staleness
checker does not know how to save or load anything. That independence is
what lets the two evolve separately, and it is enforced by import-boundary
test, not just by convention.

One JSON file per subject, matching ``CompanyStore``'s convention -- but a
different lifecycle. A ``CompanyProfile`` is DERIVED from evidence and freely
rebuildable; a ``Thesis`` is a JUDGMENT made at a time by a specific model and
is not reproducible. Rebuilding a profile from scratch is routine; rebuilding
a thesis from scratch discards a conclusion. They cannot share a store.

Reconstruction is observable-field-faithful, not byte-identical
------------------------------------------------------------------
``ReasoningResult``/``Claim`` (C7/C8/C3) are §10 contract types built fresh by
one reasoning pass; they were never designed to be serialized, and nothing
downstream of a stored Thesis reads Claim-level granularity -- only each
Finding's aggregate ``evidence_ids``, ``statement``, ``assertability`` and
``confidence`` (``Thesis.to_view()`` reads exactly these four). So the store
persists those four fields per finding, plus ``known_unknowns``, and
reconstructs ON LOAD one synthetic ``Claim`` per finding carrying all of that
finding's evidence ids as bare ``EvidenceReference``s. The original claim
boundaries within a finding (which evidence backed which fragment of the
statement) are not preserved, because nothing reads them. This is a
deliberate, bounded simplification, not an oversight -- it is faithful to
every field anything in this codebase actually consumes.

``Thesis.result.refused`` is always ``False`` for a persisted Thesis --
enforced by ``Thesis.__post_init__`` before it ever reaches ``save()``.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from atlas.reasoning.contracts import (
    Claim,
    ConfidenceLevel,
    EvidenceReference,
    Finding,
    Question,
    ReasoningResult,
    SubjectRef,
)
from atlas.research.thesis import Disposition, Thesis

STORE_VERSION = "1"


class ThesisNotFoundError(KeyError):
    """No stored thesis matches the requested view_id."""


class IncompatibleStoreVersionError(ValueError):
    """The store file was written by an incompatible ThesisStore version."""


def _serialize_finding(finding: Finding) -> dict[str, Any]:
    return {
        "statement": finding.statement,
        "assertability": finding.assertability,
        "confidence": finding.confidence,
        "evidence_ids": sorted(finding.evidence_ids),
        "salience_rank": finding.salience_rank,
        "contradicts_thesis": finding.contradicts_thesis,
        "counter_case": finding.counter_case,
        "known_unknowns": list(finding.known_unknowns),
    }


def _deserialize_finding(d: dict[str, Any], subject_ref: SubjectRef) -> Finding:
    evidence_ids: list[str] = d.get("evidence_ids", [])
    # One synthetic Claim carrying every evidence id -- see module docstring.
    # A Claim requires >=1 EvidenceReference (G10); a finding with zero
    # evidence_ids (never produced by synthesize(), but not structurally
    # forbidden by Finding itself) gets zero supporting_claims instead of a
    # Claim that would violate its own invariant.
    supporting_claims: tuple[Claim, ...] = ()
    if evidence_ids:
        supporting_claims = (
            Claim(
                subject_ref=subject_ref,
                statement=d["statement"],
                assertability=d["assertability"],
                confidence=d["confidence"],
                evidence=tuple(
                    EvidenceReference(evidence_id=eid) for eid in evidence_ids
                ),
            ),
        )
    return Finding(
        statement=d["statement"],
        assertability=d["assertability"],
        confidence=d["confidence"],
        supporting_claims=supporting_claims,
        salience_rank=d.get("salience_rank"),
        contradicts_thesis=d.get("contradicts_thesis", False),
        counter_case=d.get("counter_case"),
        known_unknowns=tuple(d.get("known_unknowns", ())),
    )


def _serialize_thesis(thesis: Thesis) -> dict[str, Any]:
    result = thesis.result
    return {
        "question": thesis.question,
        "subjects": list(thesis.subjects),
        "run_fingerprint": thesis.run_fingerprint,
        "view_id": thesis.view_id,
        "as_of": thesis.as_of,
        "synthesizer_version": thesis.synthesizer_version,
        "result": {
            "question_raw_text": result.question.raw_text,
            "overall_confidence": result.overall_confidence,
            "citations": sorted(result.citations),
            "trace": list(result.trace),
            "known_unknowns": list(result.known_unknowns),
            "findings": [_serialize_finding(f) for f in result.findings],
        },
        "dispositions": [
            {
                "dimension": d.dimension,
                "materiality": d.materiality,
                "rationale": d.rationale,
            }
            for d in thesis.dispositions
        ],
        "unresolved_dimensions": list(thesis.unresolved_dimensions),
    }


def _deserialize_thesis(d: dict[str, Any]) -> Thesis:
    subjects = tuple(d["subjects"])
    subject_ref = SubjectRef(subject_id=subjects[0], display=subjects[0])
    r = d["result"]
    findings = tuple(_deserialize_finding(f, subject_ref) for f in r["findings"])
    result = ReasoningResult(
        question=Question(raw_text=r["question_raw_text"], subject_ref=subject_ref),
        findings=findings,
        overall_confidence=r["overall_confidence"],
        citations=frozenset(r["citations"]),
        refused=False,
        trace=tuple(r.get("trace", ())),
        known_unknowns=tuple(r.get("known_unknowns", ())),
    )
    return Thesis(
        question=d["question"],
        subjects=subjects,
        run_fingerprint=d["run_fingerprint"],
        view_id=d["view_id"],
        as_of=d["as_of"],
        result=result,
        dispositions=tuple(
            Disposition(
                dimension=disp["dimension"],
                materiality=disp["materiality"],
                rationale=disp.get("rationale", ""),
            )
            for disp in d.get("dispositions", ())
        ),
        unresolved_dimensions=tuple(d.get("unresolved_dimensions", ())),
        synthesizer_version=d.get("synthesizer_version", "unknown"),
    )


class ThesisStore:
    """Persistent store for one subject's synthesized views.

    Typical workflow::

        store = ThesisStore(Path("repositories/TCS/theses.json"), "TCS")
        store.save(thesis)                  # idempotent on view_id
        view = store.load(thesis.view_id)
        every_view = store.list()
    """

    def __init__(self, path: Path, subject: str) -> None:
        self._path = Path(path)
        self._subject = subject

    def exists(self) -> bool:
        return self._path.exists()

    def save(self, thesis: Thesis) -> None:
        """Append *thesis*, or do nothing if its view_id is already stored.

        Idempotent by view_id, matching ``CompanyStore.merge``'s idempotency
        convention: since view_id is deterministic (``compute_view_id``),
        re-saving an unchanged synthesis is a no-op rather than a duplicate.
        """
        if thesis.subjects[0] != self._subject:
            raise ValueError(
                f"Thesis subject {thesis.subjects[0]!r} does not match store "
                f"subject {self._subject!r}"
            )
        envelope = self._load_raw() if self.exists() else self._empty_envelope()
        existing_ids = {t["view_id"] for t in envelope["theses"]}
        if thesis.view_id in existing_ids:
            return
        envelope["theses"].append(_serialize_thesis(thesis))
        self._write(envelope)

    def load(self, view_id: str) -> Thesis:
        """Load one stored thesis by its view_id.

        Raises ``ThesisNotFoundError`` if no thesis with that id is stored.
        """
        if not self.exists():
            raise ThesisNotFoundError(view_id)
        envelope = self._load_raw()
        for raw in envelope["theses"]:
            if raw["view_id"] == view_id:
                return _deserialize_thesis(raw)
        raise ThesisNotFoundError(view_id)

    def list(self) -> tuple[Thesis, ...]:
        """Every stored thesis for this subject, oldest first.

        Empty if the store file does not exist -- matching
        ``CompanyStore.get_ingested_ids``'s "missing store = nothing yet"
        convention rather than raising.
        """
        if not self.exists():
            return ()
        envelope = self._load_raw()
        return tuple(_deserialize_thesis(raw) for raw in envelope["theses"])

    def _empty_envelope(self) -> dict[str, Any]:
        return {"store_version": STORE_VERSION, "subject": self._subject, "theses": []}

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
            json.dumps(envelope, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
