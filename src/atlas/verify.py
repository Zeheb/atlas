"""Is this repository's storage usable by the code that is running?

``store status`` reports what the tiers hold. This answers the different
question an operator actually has before trusting a number: would a rebuild
work right now, and if not, which step fixes it.

The checks are ordered by what has to be true for the next one to mean
anything -- a missing store makes "are any rows stale" unanswerable rather
than false -- and each one names its own remedy, because a verifier that says
"failed" and stops has moved the diagnosis onto the person least likely to
have the context.

Read-only, including on a repository with no store at all. That is not a
convention here but a constraint: ``AssertionStore`` creates its database on
open, so a verifier that opened one first would report success at having
built the very thing it was asked to find missing.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from atlas.assertions.store import DB_FILENAME, STORE_VERSION, AssertionStore


@dataclass(frozen=True)
class Check:
    """One named question, its answer, and what to do when the answer is no.

    ``remedy`` is empty on a passing check. It is not a log line: it is the
    command the operator runs next, and every failing check has one or it is
    not actionable enough to be worth reporting.
    """

    name: str
    passed: bool
    detail: str
    remedy: str = ""


@dataclass(frozen=True)
class VerifyReport:
    """Every check that ran, in the order they ran.

    Checks stop at the first failure. A store that does not exist makes every
    later question unanswerable rather than false, and reporting three
    confident failures that all restate the first one buries the one that
    matters.
    """

    company_id: str
    checks: tuple[Check, ...]

    @property
    def ok(self) -> bool:
        return all(check.passed for check in self.checks)

    @property
    def failure(self) -> Check | None:
        """The check that stopped the run, or None if everything passed."""
        return next((check for check in self.checks if not check.passed), None)


def verify_store(root: Path, company_id: str) -> VerifyReport:
    """Run every storage check against *root*, stopping at the first failure."""
    checks: list[Check] = []

    store_path = root / DB_FILENAME
    if not store_path.exists():
        checks.append(
            Check(
                name="store exists",
                passed=False,
                detail=f"no {DB_FILENAME} in {root}",
                remedy=f"atlas migrate assertions --company {company_id}",
            )
        )
        return VerifyReport(company_id=company_id, checks=tuple(checks))
    checks.append(
        Check(name="store exists", passed=True, detail=str(store_path)),
    )

    store = AssertionStore(root)
    version = store.schema_version()
    if version != STORE_VERSION:
        checks.append(
            Check(
                name="schema current",
                passed=False,
                detail=f"schema is at version {version}, code expects {STORE_VERSION}",
                remedy="upgrade Atlas, or re-open the store to run pending migrations",
            )
        )
        return VerifyReport(company_id=company_id, checks=tuple(checks))
    checks.append(
        Check(
            name="schema current",
            passed=True,
            detail=f"version {version}",
        )
    )

    stale = store.stale_evidence_ids()
    if stale:
        checks.append(
            Check(
                name="rows readable",
                passed=False,
                detail=(
                    f"{len(stale)} document(s) this build cannot serve: "
                    f"{', '.join(stale[:5])}" + (" ..." if len(stale) > 5 else "")
                ),
                remedy=(
                    f"atlas rebuild --company {company_id} "
                    "--from evidence --stale-only"
                ),
            )
        )
        return VerifyReport(company_id=company_id, checks=tuple(checks))
    checks.append(
        Check(
            name="rows readable",
            passed=True,
            detail=f"{store.stats().runs} run(s), all from this build",
        )
    )

    checks.append(_profile_check(root, company_id))
    return VerifyReport(company_id=company_id, checks=tuple(checks))


def _profile_check(root: Path, company_id: str) -> Check:
    """Whether the stored profile is what the store would rebuild today.

    The deep check, and the only one that reads both tiers. The three before
    it can all pass on a repository whose profile was written by code that no
    longer produces it -- every row current, every row readable, and the
    number on screen still not the number the store implies.

    Compared with ``rebuild.profiles_match``, the canonical helper: it already
    excludes the wall-clock fields that differ between any two builds, and a
    second comparison here would drift from the one ``rebuild --verify`` uses.
    Nothing is written -- the candidate profile is built in memory and
    serialised into a temporary directory outside the repository.
    """
    import tempfile

    from atlas.assertions.reader import results_for
    from atlas.company.builder import build_profile
    from atlas.company.store import CompanyStore, load_profile_payload
    from atlas.rebuild import PROFILE_FILENAME, explain_difference, profiles_match

    stored_path = root / PROFILE_FILENAME
    if not stored_path.exists():
        return Check(
            name="profile current",
            passed=True,
            detail="no stored profile to compare against",
        )

    results = results_for(root)
    with tempfile.TemporaryDirectory() as scratch:
        candidate_path = Path(scratch) / PROFILE_FILENAME
        CompanyStore(candidate_path, company_id).save(
            build_profile(company_id, results), results
        )
        candidate = load_profile_payload(candidate_path)

    stored = load_profile_payload(stored_path)
    if profiles_match(stored, candidate):
        return Check(
            name="profile current",
            passed=True,
            detail=f"matches a rebuild from {len(results)} document(s)",
        )
    differences = explain_difference(stored, candidate)
    return Check(
        name="profile current",
        passed=False,
        detail=f"{len(differences)} difference(s): {differences[0]}",
        remedy=f"atlas rebuild --company {company_id}",
    )
