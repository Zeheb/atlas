"""CompanyStore — persist and incrementally update a CompanyProfile.

File layout (one JSON file per company)
----------------------------------------
::

    {
        "store_version": "1",
        "builder_version": "1.0",
        "company_id": "TCS",
        "built_at": "2026-07-01T10:00:00+00:00",
        "ingested_results": [
            {
                "evidence_id": "bse-news-...",
                "kind": "financial_results",
                "analyzer_version": "2.0",
                "source_date": "2026-04-09T10:30:30+00:00",
                "analyzed_at": "2026-07-01T09:00:00+00:00"
            }
        ],
        "profile": { ... }
    }

The ``profile`` object is a serialised CompanyProfile.  FactKind enum keys in
``facts`` dicts are stored as their string values (e.g. ``"financial_revenue"``).
FactUnit enum values are stored as strings (e.g. ``"crore_inr"``) or ``null``.
All ``datetime`` fields are stored as ISO-8601 strings.

Incremental update
------------------
:meth:`CompanyStore.merge` applies one new AnalysisResult to the stored
profile without rebuilding from all historical results.  It is idempotent: if
the evidence_id is already tracked **with the same analyzer_version**, the
stored profile is returned unchanged.

If the evidence_id is already tracked but the analyzer_version has changed,
:class:`StaleResultError` is raised.  The caller should rebuild from scratch::

    profile = build_profile(company_id, all_results)
    store.save(profile, all_results)

Reproducibility
---------------
The ``ingested_results`` list carries enough metadata to rerun the identical
pipeline: ``evidence_id``, ``kind``, ``analyzer_version``, ``source_date``,
``analyzed_at``.  ``builder_version`` records which version of the assembly
algorithm produced the stored profile.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from atlas.analysis.base import AnalysisResult, FactKind, FactUnit
from atlas.company.builder import BUILDER_VERSION, merge_result
from atlas.company.model import (
    AGMResolution,
    AcquisitionEvent,
    AuditorEntry,
    RelatedPartyEntry,
    BuybackEvent,
    CSATEntry,
    CapitalEventLedger,
    CompanyProfile,
    CreditHistory,
    CreditRatingEntry,
    DirectorChange,
    DirectorIdentity,
    DividendEvent,
    ESGSnapshot,
    ESGTimeSeries,
    FinancialSnapshot,
    FinancialTimeSeries,
    FundraisingEvent,
    GovernanceProfile,
    NamedShareholder,
    ParticipantAppearance,
    InvestmentEvent,
    OwnershipSnapshot,
    OwnershipTimeSeries,
    RiskEntry,
    SegmentEntry,
    SegmentTimeSeries,
    StrategyEntry,
    StrategyProfile,
)

STORE_VERSION = "1"


class StaleResultError(Exception):
    """Raised when merge() encounters an evidence_id that is already tracked
    but with a different analyzer_version.

    Recovery: rebuild from scratch with ``build_profile() + store.save()``.
    """


# ---------------------------------------------------------------------------
# Serialisation — profile → JSON-safe dict
# ---------------------------------------------------------------------------


def _dt(dt: datetime) -> str:
    return dt.isoformat()


def _unit(u: FactUnit | None) -> str | None:
    return u.value if u is not None else None


def _facts_out(facts: dict[FactKind, float]) -> dict[str, float]:
    return {fk.value: fv for fk, fv in facts.items()}


def _serialize_profile(profile: CompanyProfile) -> dict[str, Any]:
    ce = profile.capital_events
    ch = profile.credit_history

    def _credit(e: CreditRatingEntry) -> dict[str, Any]:
        return {
            "source_date": _dt(e.source_date),
            "agency": e.agency,
            "instrument": e.instrument,
            "rating": e.rating,
            "outlook": e.outlook,
            "action": e.action,
            "amount": e.amount,
            "evidence_id": e.evidence_id,
        }

    return {
        "company_id": profile.company_id,
        "financial": {
            "snapshots": [
                {
                    "period": s.period,
                    "period_type": s.period_type,
                    "basis": s.basis,
                    "facts": _facts_out(s.facts),
                    "sources": s.sources,
                }
                for s in profile.financial.snapshots
            ]
        },
        "esg": {
            "snapshots": [
                {
                    "period": s.period,
                    "facts": _facts_out(s.facts),
                    "sources": s.sources,
                }
                for s in profile.esg.snapshots
            ]
        },
        "capital_events": {
            "dividends": [
                {
                    "source_date": _dt(e.source_date),
                    "per_share": e.per_share,
                    "dividend_type": e.dividend_type,
                    "record_date": e.record_date,
                    "payment_date": e.payment_date,
                    "evidence_id": e.evidence_id,
                }
                for e in ce.dividends
            ],
            "buybacks": [
                {
                    "source_date": _dt(e.source_date),
                    "sub_type": e.sub_type,
                    "amount": e.amount,
                    "price_per_share": e.price_per_share,
                    "shares_offered": e.shares_offered,
                    "shares_bought": e.shares_bought,
                    "record_date": e.record_date,
                    "evidence_id": e.evidence_id,
                }
                for e in ce.buybacks
            ],
            "acquisitions": [
                {
                    "source_date": _dt(e.source_date),
                    "target_name": e.target_name,
                    "consideration_type": e.consideration_type,
                    "enterprise_value": e.enterprise_value,
                    "enterprise_value_unit": _unit(e.enterprise_value_unit),
                    "stake_pct": e.stake_pct,
                    "expected_completion": e.expected_completion,
                    "evidence_id": e.evidence_id,
                }
                for e in ce.acquisitions
            ],
            "investments": [
                {
                    "source_date": _dt(e.source_date),
                    "target_name": e.target_name,
                    "amount": e.amount,
                    "amount_unit": _unit(e.amount_unit),
                    "evidence_id": e.evidence_id,
                }
                for e in ce.investments
            ],
            "fundraises": [
                {
                    "source_date": _dt(e.source_date),
                    "fundraise_type": e.fundraise_type,
                    "amount": e.amount,
                    "evidence_id": e.evidence_id,
                }
                for e in ce.fundraises
            ],
        },
        "credit_history": {
            "debt_ratings": [_credit(e) for e in ch.debt_ratings],
            "esg_ratings": [_credit(e) for e in ch.esg_ratings],
        },
        "ownership": {
            "snapshots": [
                {
                    "period": s.period,
                    "facts": _facts_out(s.facts),
                    "sources": s.sources,
                }
                for s in profile.ownership.snapshots
            ]
        },
        "segments": {
            "entries": [
                {
                    "period": e.period,
                    "name": e.name,
                    "revenue": e.revenue,
                    "ebit": e.ebit,
                    "growth_pct": e.growth_pct,
                    "evidence_id": e.evidence_id,
                }
                for e in profile.segments.entries
            ]
        },
        "strategy": {
            "entries": [
                {
                    "source_date": _dt(e.source_date),
                    "kind": e.kind,
                    "text": e.text,
                    "evidence_id": e.evidence_id,
                }
                for e in profile.strategy.entries
            ],
            "csat": [
                {
                    "period": c.period,
                    "score": c.score,
                    "evidence_id": c.evidence_id,
                }
                for c in profile.strategy.csat
            ],
        },
        "governance": {
            "resolutions": [
                {
                    "source_date": _dt(r.source_date),
                    "period": r.period,
                    "title": r.title,
                    "resolution_type": r.resolution_type,
                    "outcome": r.outcome,
                    "pct_for": r.pct_for,
                    "pct_against": r.pct_against,
                    "evidence_id": r.evidence_id,
                }
                for r in profile.governance.resolutions
            ],
            "director_changes": [
                {
                    "source_date": _dt(d.source_date),
                    "change_type": d.change_type,
                    "name": d.name,
                    "role": d.role,
                    "evidence_id": d.evidence_id,
                }
                for d in profile.governance.director_changes
            ],
            "audit_kams": list(profile.governance.audit_kams),
            "risk_factors": [
                {
                    "period": r.period,
                    "text": r.text,
                    "evidence_id": r.evidence_id,
                }
                for r in profile.governance.risk_factors
            ],
            "auditor_history": [
                {
                    "source_date": _dt(a.source_date),
                    "firm": a.firm,
                    "opinion": a.opinion,
                    "evidence_id": a.evidence_id,
                }
                for a in profile.governance.auditor_history
            ],
            "related_parties": [
                {
                    "period": rp.period,
                    "kind": rp.kind,
                    "category": rp.category,
                    "amount": rp.amount,
                    "counterparty": rp.counterparty,
                    "evidence_id": rp.evidence_id,
                }
                for rp in profile.governance.related_parties
            ],
        },
        "participants": [
            {
                "entity_id": p.entity_id,
                "canonical_name": p.canonical_name,
                "role": p.role,
                "affiliation": p.affiliation,
                "evidence_id": p.evidence_id,
                "source_date": p.source_date,
                "question_text": p.question_text,
            }
            for p in profile.participants
        ],
        "named_shareholders": [
            {
                "entity_id": h.entity_id,
                "canonical_name": h.canonical_name,
                "kind": h.kind,
                "category": h.category,
                "evidence_id": h.evidence_id,
                "source_date": h.source_date,
            }
            for h in profile.named_shareholders
        ],
        "directors": [
            {
                "entity_id": d.entity_id,
                "canonical_name": d.canonical_name,
                "din": d.din,
                "evidence_id": d.evidence_id,
                "source_date": d.source_date,
            }
            for d in profile.directors
        ],
    }


# ---------------------------------------------------------------------------
# Deserialisation — JSON dict → profile
# ---------------------------------------------------------------------------


def _parse_dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


def _parse_unit(s: str | None) -> FactUnit | None:
    return FactUnit(s) if s is not None else None


def _facts_in(d: dict[str, Any]) -> dict[FactKind, float]:
    return {FactKind(k): float(v) for k, v in d.items()}


def _deserialize_profile(data: dict[str, Any]) -> CompanyProfile:
    fin = data.get("financial", {})
    esg = data.get("esg", {})
    ce = data.get("capital_events", {})
    ch = data.get("credit_history", {})
    own = data.get("ownership", {})
    seg = data.get("segments", {})
    strat = data.get("strategy", {})
    gov = data.get("governance", {})

    def _credit(d: dict[str, Any]) -> CreditRatingEntry:
        return CreditRatingEntry(
            source_date=_parse_dt(d["source_date"]),
            agency=d["agency"],
            instrument=d.get("instrument"),
            rating=d.get("rating"),
            outlook=d.get("outlook"),
            action=d.get("action"),
            amount=float(d["amount"]) if d.get("amount") is not None else None,
            evidence_id=d.get("evidence_id", ""),
        )

    return CompanyProfile(
        company_id=data["company_id"],
        financial=FinancialTimeSeries(
            snapshots=[
                FinancialSnapshot(
                    period=s["period"],
                    period_type=s["period_type"],
                    basis=s["basis"],
                    facts=_facts_in(s.get("facts", {})),
                    sources=list(s.get("sources", [])),
                )
                for s in fin.get("snapshots", [])
            ]
        ),
        esg=ESGTimeSeries(
            snapshots=[
                ESGSnapshot(
                    period=s["period"],
                    facts=_facts_in(s.get("facts", {})),
                    sources=list(s.get("sources", [])),
                )
                for s in esg.get("snapshots", [])
            ]
        ),
        capital_events=CapitalEventLedger(
            dividends=[
                DividendEvent(
                    source_date=_parse_dt(e["source_date"]),
                    per_share=float(e["per_share"]),
                    dividend_type=e.get("dividend_type", ""),
                    record_date=e.get("record_date"),
                    payment_date=e.get("payment_date"),
                    evidence_id=e.get("evidence_id", ""),
                )
                for e in ce.get("dividends", [])
            ],
            buybacks=[
                BuybackEvent(
                    source_date=_parse_dt(e["source_date"]),
                    sub_type=e["sub_type"],
                    amount=float(e["amount"]) if e.get("amount") is not None else None,
                    price_per_share=(
                        float(e["price_per_share"])
                        if e.get("price_per_share") is not None
                        else None
                    ),
                    shares_offered=(
                        int(e["shares_offered"])
                        if e.get("shares_offered") is not None
                        else None
                    ),
                    shares_bought=(
                        int(e["shares_bought"])
                        if e.get("shares_bought") is not None
                        else None
                    ),
                    record_date=e.get("record_date"),
                    evidence_id=e.get("evidence_id", ""),
                )
                for e in ce.get("buybacks", [])
            ],
            acquisitions=[
                AcquisitionEvent(
                    source_date=_parse_dt(e["source_date"]),
                    target_name=e["target_name"],
                    consideration_type=e.get("consideration_type"),
                    enterprise_value=(
                        float(e["enterprise_value"])
                        if e.get("enterprise_value") is not None
                        else None
                    ),
                    enterprise_value_unit=_parse_unit(e.get("enterprise_value_unit")),
                    stake_pct=(
                        float(e["stake_pct"])
                        if e.get("stake_pct") is not None
                        else None
                    ),
                    expected_completion=e.get("expected_completion"),
                    evidence_id=e.get("evidence_id", ""),
                )
                for e in ce.get("acquisitions", [])
            ],
            investments=[
                InvestmentEvent(
                    source_date=_parse_dt(e["source_date"]),
                    target_name=e["target_name"],
                    amount=float(e["amount"]) if e.get("amount") is not None else None,
                    amount_unit=_parse_unit(e.get("amount_unit")),
                    evidence_id=e.get("evidence_id", ""),
                )
                for e in ce.get("investments", [])
            ],
            fundraises=[
                FundraisingEvent(
                    source_date=_parse_dt(e["source_date"]),
                    fundraise_type=e["fundraise_type"],
                    amount=float(e["amount"]) if e.get("amount") is not None else None,
                    evidence_id=e.get("evidence_id", ""),
                )
                for e in ce.get("fundraises", [])
            ],
        ),
        credit_history=CreditHistory(
            debt_ratings=[_credit(e) for e in ch.get("debt_ratings", [])],
            esg_ratings=[_credit(e) for e in ch.get("esg_ratings", [])],
        ),
        ownership=OwnershipTimeSeries(
            snapshots=[
                OwnershipSnapshot(
                    period=s["period"],
                    facts=_facts_in(s.get("facts", {})),
                    sources=list(s.get("sources", [])),
                )
                for s in own.get("snapshots", [])
            ]
        ),
        segments=SegmentTimeSeries(
            entries=[
                SegmentEntry(
                    period=e["period"],
                    name=e["name"],
                    revenue=(
                        float(e["revenue"]) if e.get("revenue") is not None else None
                    ),
                    ebit=float(e["ebit"]) if e.get("ebit") is not None else None,
                    growth_pct=(
                        float(e["growth_pct"])
                        if e.get("growth_pct") is not None
                        else None
                    ),
                    evidence_id=e.get("evidence_id", ""),
                )
                for e in seg.get("entries", [])
            ]
        ),
        strategy=StrategyProfile(
            entries=[
                StrategyEntry(
                    source_date=_parse_dt(e["source_date"]),
                    kind=e["kind"],
                    text=e["text"],
                    evidence_id=e.get("evidence_id", ""),
                )
                for e in strat.get("entries", [])
            ],
            csat=[
                CSATEntry(
                    period=c["period"],
                    score=float(c["score"]),
                    evidence_id=c.get("evidence_id", ""),
                )
                for c in strat.get("csat", [])
            ],
        ),
        governance=GovernanceProfile(
            resolutions=[
                AGMResolution(
                    source_date=_parse_dt(r["source_date"]),
                    period=r.get("period"),
                    title=r["title"],
                    resolution_type=r.get("resolution_type", ""),
                    outcome=r.get("outcome"),
                    pct_for=(
                        float(r["pct_for"]) if r.get("pct_for") is not None else None
                    ),
                    pct_against=(
                        float(r["pct_against"])
                        if r.get("pct_against") is not None
                        else None
                    ),
                    evidence_id=r.get("evidence_id", ""),
                )
                for r in gov.get("resolutions", [])
            ],
            director_changes=[
                DirectorChange(
                    source_date=_parse_dt(d["source_date"]),
                    change_type=d["change_type"],
                    name=d["name"],
                    role=d.get("role"),
                    evidence_id=d.get("evidence_id", ""),
                )
                for d in gov.get("director_changes", [])
            ],
            audit_kams=list(gov.get("audit_kams", [])),
            risk_factors=[
                RiskEntry(
                    period=r["period"],
                    text=r["text"],
                    evidence_id=r.get("evidence_id", ""),
                )
                for r in gov.get("risk_factors", [])
            ],
            auditor_history=[
                AuditorEntry(
                    source_date=_parse_dt(a["source_date"]),
                    firm=a.get("firm"),
                    opinion=a.get("opinion"),
                    evidence_id=a.get("evidence_id", ""),
                )
                for a in gov.get("auditor_history", [])
            ],
            related_parties=[
                RelatedPartyEntry(
                    period=rp["period"],
                    kind=rp["kind"],
                    category=rp["category"],
                    amount=rp["amount"],
                    counterparty=rp.get("counterparty"),
                    evidence_id=rp.get("evidence_id", ""),
                )
                for rp in gov.get("related_parties", [])
            ],
        ),
        participants=[
            ParticipantAppearance(
                entity_id=p["entity_id"],
                canonical_name=p["canonical_name"],
                role=p.get("role"),
                affiliation=p.get("affiliation"),
                evidence_id=p.get("evidence_id", ""),
                source_date=p.get("source_date", ""),
                question_text=p.get("question_text"),
            )
            for p in data.get("participants", [])
        ],
        named_shareholders=[
            NamedShareholder(
                entity_id=h["entity_id"],
                canonical_name=h["canonical_name"],
                kind=h["kind"],
                category=h["category"],
                evidence_id=h.get("evidence_id", ""),
                source_date=h.get("source_date", ""),
            )
            for h in data.get("named_shareholders", [])
        ],
        directors=[
            DirectorIdentity(
                entity_id=d["entity_id"],
                canonical_name=d["canonical_name"],
                din=d["din"],
                evidence_id=d.get("evidence_id", ""),
                source_date=d.get("source_date", ""),
            )
            for d in data.get("directors", [])
        ],
    )


# ---------------------------------------------------------------------------
# Ingested result record
# ---------------------------------------------------------------------------


@dataclass
class _ResultRecord:
    """Lightweight summary of one AnalysisResult stored for provenance."""

    evidence_id: str
    kind: str
    analyzer_version: str
    source_date: str
    analyzed_at: str

    def to_dict(self) -> dict[str, str]:
        return {
            "evidence_id": self.evidence_id,
            "kind": self.kind,
            "analyzer_version": self.analyzer_version,
            "source_date": self.source_date,
            "analyzed_at": self.analyzed_at,
        }

    @classmethod
    def from_result(cls, result: AnalysisResult) -> "_ResultRecord":
        return cls(
            evidence_id=result.evidence_id,
            kind=result.kind,
            analyzer_version=result.analyzer_version,
            source_date=result.source_date.isoformat(),
            analyzed_at=result.analyzed_at.isoformat(),
        )


# ---------------------------------------------------------------------------
# CompanyStore
# ---------------------------------------------------------------------------


class CompanyStore:
    """Persistent store for a single company's CompanyProfile.

    Parameters
    ----------
    path:       Path to the JSON file (parent directory is created on first
                write; file need not exist yet).
    company_id: Stable identifier for the company (e.g. ``"TCS"``).

    Typical workflow
    ----------------
    Initial population from a full batch of results::

        profile = build_profile("TCS", all_results)
        store = CompanyStore(Path("profiles/TCS.json"), "TCS")
        store.save(profile, all_results)

    Incremental update when a new filing arrives::

        new_result = analyze(evidence_id, kb)
        profile = store.merge(new_result)

    Loading the profile at any later time::

        profile = store.load()
    """

    def __init__(self, path: Path, company_id: str) -> None:
        self._path = Path(path)
        self._company_id = company_id

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def exists(self) -> bool:
        """Return ``True`` if the store file exists on disk."""
        return self._path.exists()

    def save(
        self,
        profile: CompanyProfile,
        results: Sequence[AnalysisResult] = (),
    ) -> None:
        """Write *profile* and the provenance metadata of *results* to disk.

        *results* should be the complete set of AnalysisResult objects that
        were used to build *profile*.  Their evidence_ids are recorded so that
        :meth:`merge` can skip them on future calls.

        Raises ``ValueError`` if ``profile.company_id`` does not match the
        ``company_id`` this store was initialised with.
        """
        if profile.company_id != self._company_id:
            raise ValueError(
                f"Profile company_id {profile.company_id!r} does not match "
                f"store company_id {self._company_id!r}"
            )
        records = [_ResultRecord.from_result(r) for r in results]
        envelope = {
            "store_version": STORE_VERSION,
            "builder_version": BUILDER_VERSION,
            "company_id": self._company_id,
            "built_at": datetime.now(timezone.utc).isoformat(),
            "ingested_results": [rec.to_dict() for rec in records],
            "profile": _serialize_profile(profile),
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(envelope, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def load(self) -> CompanyProfile:
        """Deserialise and return the stored CompanyProfile.

        Raises ``FileNotFoundError`` if the store file does not exist.
        Raises ``ValueError`` if the store file was written by an incompatible
        version.
        """
        raw = self._load_raw()
        return _deserialize_profile(raw["profile"])

    def merge(self, result: AnalysisResult) -> CompanyProfile:
        """Apply *result* incrementally to the stored profile and save.

        Returns the updated CompanyProfile.

        Behaviour
        ---------
        - **Idempotent**: if *result.evidence_id* is already tracked with the
          same ``analyzer_version``, the stored profile is returned unchanged.
        - **StaleResultError**: if the evidence_id is already tracked but with
          a different ``analyzer_version``.  Rebuild from scratch in that case.
        - **Bootstrap**: if the store does not yet exist, a new profile is
          created from this single result and saved.

        The same update semantics as :func:`build_profile` apply — see
        :func:`atlas.company.builder.merge_result`.
        """
        if not self.exists():
            from atlas.company.builder import build_profile

            profile = build_profile(self._company_id, [result])
            self.save(profile, [result])
            return profile

        raw = self._load_raw()
        ingested: dict[str, str] = {
            r["evidence_id"]: r["analyzer_version"]
            for r in raw.get("ingested_results", [])
        }

        if result.evidence_id in ingested:
            stored_ver = ingested[result.evidence_id]
            if stored_ver == result.analyzer_version:
                return _deserialize_profile(raw["profile"])
            raise StaleResultError(
                f"evidence_id {result.evidence_id!r} already ingested with "
                f"analyzer_version {stored_ver!r} but new result has "
                f"{result.analyzer_version!r}. "
                f"Rebuild from scratch with build_profile() + save()."
            )

        profile = _deserialize_profile(raw["profile"])
        merge_result(result, profile)

        raw["profile"] = _serialize_profile(profile)
        raw["built_at"] = datetime.now(timezone.utc).isoformat()
        raw["ingested_results"].append(_ResultRecord.from_result(result).to_dict())

        self._path.write_text(
            json.dumps(raw, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return profile

    def get_ingested_ids(self) -> set[str]:
        """Return the set of evidence_ids already incorporated into the profile.

        Returns an empty set if the store file does not exist.
        """
        if not self.exists():
            return set()
        raw = self._load_raw()
        return {r["evidence_id"] for r in raw.get("ingested_results", [])}

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load_raw(self) -> dict[str, Any]:
        text = self._path.read_text(encoding="utf-8")
        data: dict[str, Any] = json.loads(text)
        version = data.get("store_version")
        if version != STORE_VERSION:
            raise ValueError(
                f"Unsupported store_version {version!r}. "
                f"Expected {STORE_VERSION!r}. "
                f"Rebuild from scratch with build_profile() + save()."
            )
        return data
