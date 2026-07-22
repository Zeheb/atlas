"""Deterministic staleness checking for recalled views (M2.4 commit 4).

Answers a mechanical question -- "has the evidence behind this view changed?"
-- as distinct from the reasoning question t34 actually asks: "does that
change matter?" Whether evidence changed is a pure function of the
repository; whether it matters requires judgment, which is what
``contradicts_thesis``/``counter_case`` (populated in commit 6) exist for.
This module answers only the first question, and answers it without an LLM.

Advisory, not blocking (ADR-0004's Phase-1 precedent): a stale view is still
usable. ``StalenessReport`` is printed alongside an answer, not a gate that
refuses one.

VALIDATION ONLY -- no persistence. This module never imports
``research.memory``, and that omission is load-bearing, not incidental: a
staleness checker with no path back to ``ThesisStore`` cannot accidentally
grow into a stateful cache, and the store can change its persistence format
without this module's tests noticing. Enforced by
``test_staleness_never_imports_memory`` (an AST scan of module-level
imports). ``sweep_staleness`` is the one function that composes both, and it
imports ``ThesisStore`` LOCALLY, inside its own body -- the same deferred-
import convention ``cli.py`` already uses for every command's dependencies --
so the module-level boundary holds while the composition point still exists.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from atlas.knowledge.base import KnowledgeBase
from atlas.acquisition.repository import Repository
from atlas.reasoning.contracts import RecalledView


@dataclass(frozen=True)
class StalenessPolicy:
    """Configuration for :func:`check_staleness`.

    Deliberately empty of speculative knobs. The one real extension point --
    which evidence kinds count toward ``new_evidence_since`` -- defaults to
    "all kinds", since M2.4 has no basis yet for treating one kind as more
    staleness-relevant than another. ``StalenessPolicy()`` with no arguments
    is the only configuration any caller needs today.
    """

    kinds: tuple[str, ...] | None = None


_DEFAULT_POLICY = StalenessPolicy()


@dataclass(frozen=True)
class StalenessReport:
    """The mechanical verdict on one RecalledView's currency.

    ``hard_stale`` -- a cited evidence id no longer resolves in the
    KnowledgeBase at all (re-parsed away, evidence_id changed, document
    removed). This is the only field a caller should treat as a real
    warning; the rest is informational.

    ``missing_evidence`` -- which cited ids triggered hard_stale.

    ``new_evidence_since`` -- evidence ids acquired after the view's
    ``as_of``, regardless of whether they relate to the view's claims. A
    count, not a judgment: more documents existing is not itself a problem,
    but zero is the only value that lets a reader skip reading further.
    """

    view_id: str
    hard_stale: bool
    missing_evidence: tuple[str, ...]
    new_evidence_since: tuple[str, ...]


def check_staleness(
    view: RecalledView, repo_root: Path, policy: StalenessPolicy = _DEFAULT_POLICY,
) -> StalenessReport:
    """Check one recalled view against the current state of its repository.

    Pure with respect to the view: reads ``repo_root``'s KnowledgeBase and
    Repository, never the view's own store. No LLM call, no network.
    """
    cited_ids = frozenset(eid for claim in view.claims for eid in claim.evidence_ids)

    known = frozenset()
    if (repo_root / "knowledge.db").exists():
        known = KnowledgeBase(repo_root).known_ids()
    missing = tuple(sorted(cited_ids - known)) if cited_ids else ()

    new_ids: tuple[str, ...] = ()
    if (repo_root / "catalog.json").exists():
        since = datetime.fromisoformat(view.as_of)
        entries = Repository(repo_root).list_evidence(kinds=None, since=since)
        if policy.kinds is not None:
            entries = [e for e in entries if e.kind in policy.kinds]
        new_ids = tuple(e.evidence_id for e in entries)

    return StalenessReport(
        view_id=view.view_id,
        hard_stale=bool(missing),
        missing_evidence=missing,
        new_evidence_since=new_ids,
    )


def sweep_staleness(
    repo_base: Path, subject: str, policy: StalenessPolicy = _DEFAULT_POLICY,
) -> tuple[StalenessReport, ...]:
    """Check every stored view for one subject.

    The composition point between this module and ``research.memory`` --
    see the module docstring for why the import is local to this function
    rather than module-level.
    """
    from atlas.research.memory import ThesisStore

    repo_root = repo_base / subject
    store = ThesisStore(repo_root / "theses.json", subject)
    return tuple(
        check_staleness(thesis.to_view(), repo_root, policy)
        for thesis in store.list()
    )
